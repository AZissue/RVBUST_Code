# -*- coding: utf-8 -*-
"""
主窗口（MainWindow）—— 三栏装配 + 信号转发 + 业务逻辑。

布局（参考 DualCameraFusion，泛化为 N 相机）：
  - 左：CameraPanel（固定宽度 ~350px）
  - 中：相机预览卡片网格（QGridLayout 动态行列）+ 底部可折叠 3D 查看器
  - 右：QTabWidget（CalibrationPanel / StitchPanel）
  - 底：可折叠日志面板（CollapsibleLogPanel，与主区域垂直 QSplitter 分隔，高度可拖动）

信号流：面板信号 → 主窗口槽函数 → core 模块 → 更新 UI。
"""

from __future__ import annotations

import os
import time
import hashlib
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QTabWidget, QScrollArea, QTextEdit,
    QMessageBox, QFileDialog, QSplitter, QSizePolicy,
)

from core.camera_manager import CameraManager, SingleCameraController
from core.calibration_engine import CalibrationEngine
from core.marker_detector import MarkerDetector, MARKER_TYPE_CODED_CIRCLE, MARKER_TYPE_ASYMMETRIC_GRID
from core.stitch_engine import StitchEngine
from core.point_cloud_processor import PointCloudProcessor
from core.frame_data import FrameData
from core.offline_session import OfflineSession
from core.station_manager import StationManager
from core.utils import logger

from .camera_card import CameraPreviewCard
from .viewer_3d import EmbeddedPointCloudViewer
from .icons import get_icon, has_icon, icon_text, apply_icon
from .panels.camera_panel import CameraPanel
from .panels.calibration_panel import CalibrationPanel
from .panels.stitch_panel import StitchPanel
from .panels.station_panel import StationPanel, station_label

# RANSAC 内点阈值：检测的 3D 坐标来自 SaveWithImage(Millimeter)，单位 mm
RANSAC_THRESHOLD_MM = 2.0


# =========================================================================
# 可折叠日志面板（从 DualCameraFusion/src/app.py:43-176 抽取，提示语泛化）
# =========================================================================
class CollapsibleLogPanel(QWidget):
    """现代可折叠日志面板，带彩色级别前缀和自动滚动。

    toggled(bool)：折叠状态变化信号（True=展开，False=折叠），
    主窗口用它调整垂直 Splitter——折叠时只保留标题栏高度（最小化到底部栏）。
    """

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._tips_visible = True      # 提示区可见状态（btn_tips 切换）
        self._tips_sizes = None        # 收起前的 splitter 尺寸（展开时恢复）
        self._setup_ui()

    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # 顶部工具条（28px）
        self.header = QWidget()
        self.header.setFixedHeight(28)
        self.header.setStyleSheet("background-color: #1A1A20; border-top: 1px solid #2A2A34;")
        header_lo = QHBoxLayout(self.header)
        header_lo.setContentsMargins(8, 2, 8, 2)
        header_lo.setSpacing(8)

        # 日志图标（有 log.png 时显示 16px 图标，无文件隐藏保持纯文字兜底）
        self.lbl_log_icon = QLabel()
        self.lbl_log_icon.setFixedSize(16, 16)
        self.lbl_log_icon.setStyleSheet("background: transparent; border: none;")
        if has_icon("log"):
            self.lbl_log_icon.setPixmap(get_icon("log").pixmap(16, 16))
        else:
            self.lbl_log_icon.hide()
        header_lo.addWidget(self.lbl_log_icon)

        self.btn_toggle = QPushButton("▼ 日志")
        self.btn_toggle.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #8B8D98; "
            "font-size: 9pt; font-weight: bold; padding: 2px 4px; }"
            "QPushButton:hover { color: #F0F0F5; }"
        )
        self.btn_toggle.setMaximumWidth(60)
        self.btn_toggle.clicked.connect(self._toggle)
        header_lo.addWidget(self.btn_toggle)

        # 提示区收起 / 展开按钮（样式与 btn_toggle 一致）
        self.btn_tips = QPushButton("◀ 提示")
        self.btn_tips.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #8B8D98; "
            "font-size: 9pt; font-weight: bold; padding: 2px 4px; }"
            "QPushButton:hover { color: #F0F0F5; }"
        )
        self.btn_tips.setMaximumWidth(60)
        self.btn_tips.clicked.connect(self._toggle_tips)
        header_lo.addWidget(self.btn_tips)

        self.lbl_status = QLabel("就绪 | 请先查找并添加设备")
        self.lbl_status.setStyleSheet("color: #aaaaaa; font-size: 9pt;")
        header_lo.addWidget(self.lbl_status, 1)

        self.btn_clear = QPushButton(icon_text("clear", "🗑 清空"))
        self.btn_clear.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #aaaaaa; "
            "font-size: 8pt; padding: 2px 6px; }"
            "QPushButton:hover { color: #e53935; }"
        )
        self.btn_clear.setMaximumHeight(22)
        self.btn_clear.clicked.connect(self.clear)
        apply_icon(self.btn_clear, "clear")
        header_lo.addWidget(self.btn_clear)
        lo.addWidget(self.header)

        # 内容区：左 操作提示 | 右 日志（水平 QSplitter，宽度可拖动）
        self.content = QWidget()
        content_lo = QVBoxLayout(self.content)
        content_lo.setContentsMargins(0, 0, 0, 0)
        content_lo.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)

        self.tips_edit = QTextEdit()
        self.tips_edit.setReadOnly(True)
        self.tips_edit.setMinimumWidth(0)
        self.tips_edit.setStyleSheet(
            "background-color: #0F0F13; color: #8B8D98; "
            "border: none; border-right: 1px solid #2A2A34; "
            "font-size: 8pt; font-family: 'Geist', 'Inter', 'Microsoft YaHei', 'Segoe UI', system-ui, sans-serif;"
            "padding: 6px;"
        )
        self.tips_edit.setText(
            "操作流程：\n"
            "多相机：查找设备→添加→摆放标定板→\n"
            "  拍摄→检测标记→标定 pair→拼接\n"
            "站位：连接相机→逐站位移动拍摄→\n"
            "  检测→标定(默认参考站位1)→拼接\n"
            "提高精度：移动标定板换姿态，拍多轮\n"
            "  后「累积当前帧」→「多帧标定」\n"
            "后处理：参数过激会滤光点云，点\n"
            "  「✨自动设置参数」按数据估计\n"
            "离线：拍摄→存会话→加载→批量\n"
            "  检测/标定/拼接"
        )
        self.splitter.addWidget(self.tips_edit)

        self.log_content = QTextEdit()
        self.log_content.setReadOnly(True)
        self.log_content.setObjectName("logEdit")
        self.log_content.setStyleSheet(
            "background-color: #1a1a1a; color: #ffffff; "
            "font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 9pt; "
            "border: none; padding: 6px;"
        )
        self.splitter.addWidget(self.log_content)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([240, 760])
        content_lo.addWidget(self.splitter)
        lo.addWidget(self.content, 1)

    def _toggle(self):
        self._expanded = not self._expanded
        self.content.setVisible(self._expanded)
        self.btn_toggle.setText("▼ 日志" if self._expanded else "▶ 日志")
        self.toggled.emit(self._expanded)

    def _toggle_tips(self):
        """收起 / 展开操作提示区：收起后日志占满全宽，展开恢复之前的位置。"""
        self._tips_visible = not self._tips_visible
        if not self._tips_visible:
            self._tips_sizes = self.splitter.sizes()
            self.tips_edit.hide()
        else:
            self.tips_edit.show()
            if self._tips_sizes and len(self._tips_sizes) == 2 and self._tips_sizes[0] > 0:
                self.splitter.setSizes(self._tips_sizes)
        self.btn_tips.setText("◀ 提示" if self._tips_visible else "▶ 提示")

    def append(self, text: str):
        """追加日志，自动识别级别并着色前缀。"""
        import re
        colors = {
            "ERROR": "#e53935", "错误": "#e53935", "失败": "#e53935",
            "WARN": "#FF9800", "WARNING": "#FF9800", "警告": "#FF9800",
            "INFO": "#aaaaaa", "信息": "#aaaaaa",
            "SUCCESS": "#43a047", "成功": "#43a047",
            "DEBUG": "#888888",
        }
        colored = text
        for level, color in colors.items():
            pattern = rf"(\[{level}\]|{level}:|\b{level}\b)"
            if re.search(pattern, text, re.IGNORECASE):
                colored = re.sub(
                    pattern,
                    lambda m: f'<span style="color:{color};font-weight:bold;">{m.group(1)}</span>',
                    text, flags=re.IGNORECASE, count=1,
                )
                break
        colored = re.sub(
            r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
            r'<span style="color:#888888;">\1</span>',
            colored,
        )
        self.log_content.append(colored)
        scrollbar = self.log_content.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear(self):
        self.log_content.clear()

    def set_status(self, text: str):
        self.lbl_status.setText(text)


# =========================================================================
# Foundation 设计系统 — 深色主题（utilitarian modernism）
# =========================================================================
STYLESHEET = """
QMainWindow { background-color: #0F0F13; }
QWidget { background-color: #1A1A20; color: #F0F0F5; font-family: "Geist", "Inter", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif; font-size: 9pt; }

QGroupBox {
    background-color: #1A1A20;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    margin-top: 4px;
    font-weight: bold;
    padding: 6px;
    font-size: 9pt;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #2979FF;
    font-size: 9pt;
}

QPushButton {
    background-color: #24242C;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    padding: 6px 12px;
    color: #F0F0F5;
    font-weight: 500;
    font-size: 9pt;
    min-height: 28px;
}
QPushButton:hover { background-color: #2E2E38; border-color: #3E3E4C; }
QPushButton:pressed { background-color: #3E3E4C; }
QPushButton:disabled { background-color: #1A1A20; color: #5C5E6A; border-color: #2A2A34; }
QPushButton#primaryButton { background-color: #2979FF; border-color: #1565C0; }
QPushButton#primaryButton:hover { background-color: #1565C0; }
QPushButton#dangerButton { background-color: #DC2626; border-color: #B91C1C; }
QPushButton#dangerButton:hover { background-color: #B91C1C; }
QPushButton#successButton { background-color: #16A34A; border-color: #15803D; }
QPushButton#successButton:hover { background-color: #15803D; }

QLineEdit {
    background-color: #1A1A20;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    padding: 4px;
    color: #F0F0F5;
    font-size: 9pt;
    min-height: 20px;
}
QLineEdit:focus {
    border: 1px solid #2979FF;
}
QTextEdit {
    background-color: #1A1A20;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    padding: 6px;
    color: #F0F0F5;
    font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace;
    font-size: 8pt;
}
QLabel { color: #F0F0F5; font-size: 9pt; }
QLabel#infoLabel { font-size: 8pt; color: #8B8D98; padding: 2px 4px; }

QStatusBar { background-color: #0F0F13; color: #8B8D98; font-size: 8pt; }

QTableWidget {
    background-color: #1A1A20;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    gridline-color: #2A2A34;
    font-size: 8pt;
}
QHeaderView::section {
    background-color: #24242C;
    padding: 4px;
    border: 1px solid #2A2A34;
    font-weight: bold;
    font-size: 8pt;
}
QTableWidget::item { padding: 2px 4px; }

QSpinBox, QDoubleSpinBox {
    background-color: #24242C;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    padding: 2px 4px;
    color: #F0F0F5;
    font-size: 9pt;
    min-height: 20px;
}

QComboBox {
    background-color: #24242C;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    padding: 2px 4px;
    color: #F0F0F5;
    font-size: 9pt;
    min-height: 20px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #24242C;
    color: #F0F0F5;
    selection-background-color: #2979FF;
}

QListWidget {
    background-color: #1A1A20;
    border: 1px solid #2A2A34;
    border-radius: 6px;
    font-size: 9pt;
}
QListWidget::item { padding: 4px; }
QListWidget::item:selected { background-color: #2979FF; }

QTabWidget::pane { border: 1px solid #2A2A34; border-radius: 6px; }
QTabBar::tab {
    background-color: #1A1A20;
    border: 1px solid #2A2A34;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 14px;
    color: #8B8D98;
}
QTabBar::tab:selected { background-color: #24242C; color: #2979FF; }

QSplitter::handle { background-color: #2A2A34; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }

QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical {
    background-color: #1A1A20;
    width: 10px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background-color: #2A2A34;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background-color: #3E3E4C; }
QScrollBar:horizontal {
    background-color: #1A1A20;
    height: 10px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background-color: #2A2A34;
    border-radius: 6px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background-color: #3E3E4C; }
"""


# =========================================================================
# 主窗口
# =========================================================================
class MainWindow(QMainWindow):
    """多相机标定与拼接主窗口。"""

    # 站位模式下物理相机的固定 ID（Phase 5）
    PHYSICAL_ID = "physical"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MultiCameraCalibration — 多相机外参标定与点云拼接")
        self.setMinimumSize(1500, 900)
        self.resize(1800, 1050)

        # ---- core 模块 ----
        self.camera_manager = CameraManager()
        self.calibration_engine = CalibrationEngine()
        self.marker_detector = MarkerDetector()
        self.stitch_engine = StitchEngine()
        self.offline_session = OfflineSession()
        self.station_manager = StationManager(self.camera_manager)

        # ---- 状态 ----
        self.frames: Dict[str, FrameData] = {}      # camera_id/station_id → 最新帧
        self.cards: Dict[str, CameraPreviewCard] = {}  # camera_id/station_id → 预览卡片
        self._physical_frame: Optional[FrameData] = None  # 物理相机取景帧（不参与标定）
        self._device_descs: List[str] = []
        self._cam_seq = 0                            # 相机 ID 序号
        self._session_capture_seq = 0                # 会话内拍摄序号（跨相机统一帧号）
        self._process_params: dict = {}            # 拼接后处理参数（面板信号更新）
        self._last_merged_pcd = None               # 最近一次拼接结果（自动参数数据源）
        self._last_stitch_input_points = 0         # 最近一次在线拼接的原始点数（过滤保护）
        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._on_capture_all)
        # 当前相机（取景）持续 2D 预览定时器
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._on_preview_tick)
        self._preview_camera_id: Optional[str] = None

        self._setup_ui()
        self._connect_signals()

        # 初始化 RVC 系统（无 SDK 环境优雅降级）
        ok, msg = self.camera_manager.initialize()
        self._log(f"[INFO] {msg}" if ok else f"[WARN] {msg}（离线模式）")
        self._update_capture_enabled()

    # ------------------------------------------------------------------
    # UI 装配
    # ------------------------------------------------------------------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_lo = QVBoxLayout(central)
        root_lo.setContentsMargins(4, 4, 4, 0)
        root_lo.setSpacing(4)

        # 主三栏（水平分割）
        main_splitter = QSplitter(Qt.Horizontal)

        # 左：相机面板（Tab1 多相机 / Tab2 单相机站位）
        # Tab1 内容较高（minimumSizeHint ~920px），套 QScrollArea 压低最小高度，
        # 否则底部日志的垂直 QSplitter 会把 minimumSizeHint 当硬下限而无法拖动
        self.left_tabs = QTabWidget()
        self.camera_panel = CameraPanel()
        self.station_panel = StationPanel()
        cam_scroll = QScrollArea()
        cam_scroll.setWidgetResizable(True)
        cam_scroll.setWidget(self.camera_panel)
        self.left_tabs.addTab(cam_scroll, icon_text("multicam", "🎥 多相机"))
        self.left_tabs.addTab(self.station_panel, icon_text("station", "📍 单相机站位"))
        if has_icon("multicam"):
            self.left_tabs.setTabIcon(0, get_icon("multicam"))
        if has_icon("station"):
            self.left_tabs.setTabIcon(1, get_icon("station"))
        self.left_tabs.setFixedWidth(350)
        main_splitter.addWidget(self.left_tabs)

        # 中：卡片网格 + 3D 查看器（垂直分割，折叠/最大化由查看器工具栏控制）
        self.center_splitter = QSplitter(Qt.Vertical)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setSpacing(6)
        self.grid_scroll.setWidget(self.grid_container)
        self.center_splitter.addWidget(self.grid_scroll)

        # 3D 查看器（顶部工具栏含折叠 / 着色 / 视角 / 最大化等）
        self.viewer_3d = EmbeddedPointCloudViewer()
        self.center_splitter.addWidget(self.viewer_3d)
        # 默认 3D 区占大头（卡片仅作取景/标记确认，3D 才是主要观察区）
        self.center_splitter.setSizes([350, 650])
        main_splitter.addWidget(self.center_splitter)

        # 3D 折叠 = 最小化到工具栏：释放空间给卡片区，展开恢复原高度
        self._viewer_expanded_sizes = None
        self.viewer_3d.collapse_toggled.connect(self._on_viewer_collapse_toggled)

        # 右：标定 / 拼接 Tab
        self.right_tabs = QTabWidget()
        self.calibration_panel = CalibrationPanel()
        self.stitch_panel = StitchPanel()
        self.right_tabs.addTab(self.calibration_panel, icon_text("calibrate", "📐 标定"))
        self.right_tabs.addTab(self.stitch_panel, icon_text("link", "🔗 拼接"))
        if has_icon("calibrate"):
            self.right_tabs.setTabIcon(0, get_icon("calibrate"))
        if has_icon("link"):
            self.right_tabs.setTabIcon(1, get_icon("link"))
        self.right_tabs.setMinimumWidth(380)
        main_splitter.addWidget(self.right_tabs)

        # 左 350 / 中 1100（中央加宽，3D 区更大）/ 右 400
        main_splitter.setSizes([350, 1100, 400])
        main_splitter.setCollapsible(0, False)

        # 底部：可折叠日志面板（与主三栏垂直 QSplitter，高度可拖动，无硬上限）
        self.log_panel = CollapsibleLogPanel()
        self.log_panel.setMinimumHeight(30)

        self.outer_splitter = QSplitter(Qt.Vertical)
        self.outer_splitter.addWidget(main_splitter)
        self.outer_splitter.addWidget(self.log_panel)
        self.outer_splitter.setSizes([780, 160])
        root_lo.addWidget(self.outer_splitter)

        # 日志折叠 = 最小化到底部标题栏：释放空间给主内容区，展开时恢复原高度
        self._log_expanded_sizes = None
        self.log_panel.toggled.connect(self._on_log_toggled)

        self.statusBar().showMessage("就绪")

    def _on_log_toggled(self, expanded: bool):
        """日志折叠时把垂直 Splitter 压到只剩标题栏（最小化到底部栏），
        展开时恢复折叠前的高度分配。"""
        header_h = self.log_panel.header.sizeHint().height() + 4
        if not expanded:
            # 记录当前高度分配，折叠为标题栏高度
            self._log_expanded_sizes = self.outer_splitter.sizes()
            self.log_panel.setMaximumHeight(header_h)
            total = sum(self._log_expanded_sizes)
            self.outer_splitter.setSizes([total - header_h, header_h])
        else:
            # 解除高度限制并恢复
            self.log_panel.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
            if self._log_expanded_sizes:
                self.outer_splitter.setSizes(self._log_expanded_sizes)

    def _on_viewer_collapse_toggled(self, expanded: bool):
        """3D 查看器折叠时把中央垂直 Splitter 压到只剩工具栏（最小化），
        空间让给相机卡片区；展开时恢复折叠前的高度分配。"""
        bar_h = self.viewer_3d.sizeHint().height() + 4   # 容器已隐藏，sizeHint 只剩工具栏
        if not expanded:
            self._viewer_expanded_sizes = self.center_splitter.sizes()
            self.viewer_3d.setMaximumHeight(bar_h)
            total = sum(self._viewer_expanded_sizes)
            self.center_splitter.setSizes([total - bar_h, bar_h])
        else:
            self.viewer_3d.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
            if self._viewer_expanded_sizes:
                self.center_splitter.setSizes(self._viewer_expanded_sizes)

    def _on_viewer_maximized(self, on: bool):
        """查看器最大化：隐藏相机卡片区与左右面板，查看器占满中央；再按恢复。"""
        self.grid_scroll.setVisible(not on)
        self.left_tabs.setVisible(not on)
        self.right_tabs.setVisible(not on)

    # ------------------------------------------------------------------
    # 信号连接（面板信号 → 主窗口槽函数）
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # 左侧 Tab 切换同步标定面板
        self.left_tabs.currentChanged.connect(self._on_left_tab_changed)

        p = self.camera_panel
        p.refresh_devices_requested.connect(self._on_refresh_devices)
        p.cameras_added.connect(self._on_add_cameras)
        p.camera_remove_requested.connect(self._on_remove_camera)
        p.capture_all_requested.connect(self._on_capture_all)
        p.continuous_capture_toggled.connect(self._on_continuous_toggled)
        p.capture_params_changed.connect(self._on_capture_params)
        p.save_frame_to_session_requested.connect(self._on_save_frame_to_session)
        p.save_session_requested.connect(self._on_save_session)
        p.load_session_requested.connect(self._on_load_session)
        p.batch_detect_requested.connect(self._on_batch_detect)
        p.batch_calibrate_requested.connect(self._on_batch_calibrate)

        st = self.station_panel
        st.refresh_devices_requested.connect(self._on_station_refresh_devices)
        st.connect_requested.connect(self._on_station_connect)
        st.disconnect_requested.connect(self._on_station_disconnect)
        st.capture_station_requested.connect(self._on_capture_station)
        st.station_removed.connect(self._on_remove_station)
        st.stations_cleared.connect(self._on_clear_stations)
        st.new_session_requested.connect(self._on_new_station_session)

        c = self.calibration_panel
        c.detect_requested.connect(self._on_detect_markers)
        c.calibrate_pair_requested.connect(self._on_calibrate_pair)
        c.add_frame_requested.connect(self._on_add_frame)
        c.calibrate_multi_requested.connect(self._on_calibrate_multi)
        c.clear_frames_requested.connect(self._on_clear_frames)
        c.save_calibration_requested.connect(self._on_save_calibration)
        c.load_calibration_requested.connect(self._on_load_calibration)
        c.reference_changed.connect(self._on_reference_changed)
        c.pair_selected.connect(self._on_pair_selected)
        c.marker_type_changed.connect(self._on_marker_type_changed)

        s = self.stitch_panel
        s.stitch_requested.connect(self._on_stitch)
        s.stitch_save_requested.connect(self._on_stitch_save)
        s.stitch_session_requested.connect(self._on_stitch_session)
        s.process_params_changed.connect(self._on_process_params)
        s.auto_params_requested.connect(self._on_auto_params)
        self._process_params = s.get_process_params()

        self.viewer_3d.status_changed.connect(self._log)
        self.viewer_3d.maximize_toggled.connect(self._on_viewer_maximized)

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _log(self, text: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_panel.append(f"{ts} {text}")
        logger.info(text)

    # ==================================================================
    # 相机管理
    # ==================================================================
    def _enumerate_devices(self) -> List[str]:
        """枚举 RVC 设备，返回描述字符串列表（无 SDK / 无设备返回空表）。"""
        probe = SingleCameraController("probe")
        devices = probe.find_devices()
        descs = []
        for dev in devices:
            try:
                ret, info = dev.GetDeviceInfo()
                descs.append(f"{info.name} (SN: {info.sn})" if ret else "未知设备")
            except Exception:
                descs.append("未知设备")
        return descs

    def _on_refresh_devices(self):
        """枚举设备并填充左面板设备列表。"""
        try:
            descs = self._enumerate_devices()
            self._device_descs = descs
            self.camera_panel.set_devices(descs)
            if descs:
                self._log(f"[INFO] 查找到 {len(descs)} 台设备: {'; '.join(descs)}")
                self.log_panel.set_status(f"查找到 {len(descs)} 台设备，可多选添加")
            else:
                self._log("[WARN] 未找到任何设备（检查连接或 SDK）")
                self.log_panel.set_status("未找到设备")
        except Exception as e:
            self._log(f"[ERROR] 查找设备失败: {e}")

    def _on_add_cameras(self, device_indices: List[int]):
        """添加选中设备为新相机：注册 + 连接 + 生成预览卡片。"""
        for idx in device_indices:
            # 预检：同一物理设备不能重复添加（索引级快速检查）
            holder = self.camera_manager.is_device_index_connected(idx)
            if holder is not None:
                self._log(f"[WARN] 设备 [{idx}] 已被相机 {holder} 连接，"
                          "同一台物理相机不能重复添加，已跳过")
                continue

            camera_id = self._next_camera_id()
            if not self.camera_manager.add_camera(camera_id):
                continue

            # 创建卡片（无论连接成功与否，便于离线查看 / 重试）
            card = CameraPreviewCard(camera_id)
            card.capture_requested.connect(self._on_capture_single)
            card.disconnect_requested.connect(self._on_remove_camera)
            self.cards[camera_id] = card

            # 尝试连接
            ok, msg = self.camera_manager.connect(camera_id, idx)
            if ok:
                card.set_connected(True)
                self._log(f"[SUCCESS] 相机 {camera_id} 已连接: {msg}")
                self.camera_panel.add_camera_entry(camera_id, msg)
            else:
                card.set_connected(False)
                self._log(f"[WARN] 相机 {camera_id} 连接失败: {msg}")
                self.camera_panel.add_camera_entry(camera_id, f"连接失败({msg})")

        self._relayout_grid()
        self._sync_camera_lists()
        self._update_capture_enabled()

    def _next_camera_id(self) -> str:
        while True:
            cid = f"cam{self._cam_seq}"
            self._cam_seq += 1
            if cid not in self.cards:
                return cid

    def _on_remove_camera(self, camera_id: str):
        """断开并移除相机：销毁卡片、清理帧与点云。"""
        self.camera_manager.remove_camera(camera_id)
        frame = self.frames.pop(camera_id, None)
        if frame is not None:
            frame.release()
        card = self.cards.pop(camera_id, None)
        if card is not None:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.camera_panel.remove_camera_entry(camera_id)
        self.viewer_3d.remove_camera(camera_id)
        self._relayout_grid()
        self._sync_camera_lists()
        self._update_capture_enabled()
        self._log(f"[INFO] 相机 {camera_id} 已移除")

    def _relayout_grid(self):
        """相机卡片网格重排：N≤2 用 1 行，N≤4 用 2×2，N≤9 用 3×3，更多按 4 列。
        站位模式下物理相机卡片（当前相机）固定第一位。"""
        # 先全部从布局移除
        for card in self.cards.values():
            self.grid_layout.removeWidget(card)
        n = len(self.cards)
        if n == 0:
            return
        if n <= 2:
            cols = n
        elif n <= 4:
            cols = 2
        elif n <= 9:
            cols = 3
        else:
            cols = 4
        # 物理相机卡片固定网格第一位（稳定排序，其余保持插入顺序）
        cards = sorted(self.cards.values(),
                       key=lambda c: 0 if c.camera_id == self.PHYSICAL_ID else 1)
        for i, card in enumerate(cards):
            self.grid_layout.addWidget(card, i // cols, i % cols)

    def _station_mode_active(self) -> bool:
        """当前是否处于「单相机站位」Tab。"""
        return self.left_tabs.currentIndex() == 1

    def _on_left_tab_changed(self, index: int):
        """左侧 Tab 切换时同步标定面板相机列表与拍摄按钮状态。"""
        self._sync_camera_lists()
        self._update_capture_enabled()

    def _sync_camera_lists(self):
        """相机集合变化后同步：标定面板参考相机下拉。
        站位模式下喂站位 ID 集合（默认参考 station_1），否则喂相机 ID 集合。"""
        if self._station_mode_active():
            ids = self.station_manager.get_station_ids()
        else:
            ids = [cid for cid in self.cards.keys() if cid != self.PHYSICAL_ID]
        self.calibration_panel.set_camera_ids(ids)

    def _update_capture_enabled(self):
        has_connected = len(self.camera_manager.get_connected_ids()) > 0
        self.camera_panel.set_capture_enabled(has_connected)
        self.station_panel.set_capture_enabled(
            self.camera_manager.is_connected(self.PHYSICAL_ID))
        if not has_connected:
            self.camera_panel.stop_continuous()
            self._capture_timer.stop()

    # ==================================================================
    # 采集
    # ==================================================================
    def _on_capture_all(self):
        """拍摄所有已连接相机（软触发同步）。"""
        frames = self.camera_manager.capture_all(sync=True)
        if not frames:
            self._log("[WARN] 拍摄失败：无已连接相机或全部拍摄失败")
            return
        for cid, frame in frames.items():
            self._store_frame(cid, frame)
        self._log(f"[INFO] 拍摄完成: {len(frames)} 台相机 "
                  f"(帧号 {frames[next(iter(frames))].frame_id})")

    def _on_preview_toggled(self, camera_id: str, active: bool):
        """当前相机卡片「预览/停止预览」按钮切换：启动或停止持续 2D 预览定时器。"""
        if active:
            self._preview_camera_id = camera_id
            self._preview_timer.start(150)  # 约 6~7 fps，流畅且不过载
            self._log(f"[INFO] 相机 {camera_id} 持续 2D 预览已启动")
        else:
            self._stop_physical_preview()

    def _on_preview_tick(self):
        """持续 2D 预览定时器：每 150ms 刷新一次当前相机画面。"""
        if self._preview_camera_id is None:
            return
        self._on_preview_physical(self._preview_camera_id)

    def _stop_physical_preview(self):
        """停止当前相机的持续 2D 预览（3D 拍摄前应先调用，避免冲突）。"""
        if self._preview_timer.isActive():
            self._preview_timer.stop()
            self._log("[INFO] 持续 2D 预览已暂停")
        card = self.cards.get(self.PHYSICAL_ID)
        if card is not None and card.is_preview_active():
            card.stop_preview()
        self._preview_camera_id = None

    def _on_preview_physical(self, camera_id: str):
        """当前相机（取景）的 2D 预览：只调用 Capture2D 更新画面，不保存为站位。"""
        frame = self.camera_manager.capture_2d_preview(camera_id)
        if frame is None:
            self._log(f"[WARN] 相机 {camera_id} 2D 预览失败（未连接？）")
            return
        # 物理相机预览帧只更新画面，不进入 self.frames，不递增拍摄计数
        old = self._physical_frame
        if old is not None:
            old.release()
        self._physical_frame = frame
        card = self.cards.get(camera_id)
        if card is not None:
            card.update_frame(frame, frame.markers)
        # 持续预览模式下减少日志刷屏，只在首次/失败时打印
        if not self._preview_timer.isActive():
            self._log(f"[INFO] 相机 {camera_id} 2D 预览已刷新")

    def _on_capture_single(self, camera_id: str):
        """单拍指定相机。"""
        frame = self.camera_manager.capture(camera_id)
        if frame is None:
            self._log(f"[WARN] 相机 {camera_id} 拍摄失败（未连接？）")
            return
        self._store_frame(camera_id, frame)
        self._log(f"[INFO] 相机 {camera_id} 拍摄成功")

    def _store_frame(self, camera_id: str, frame: FrameData):
        """保存帧并更新卡片预览（释放旧帧资源）。
        物理相机（站位模式取景）的帧只更新预览、不进 self.frames，
        保证站位模式下检测 / 标定 / 拼接只作用于站位帧集合。"""
        if camera_id == self.PHYSICAL_ID:
            old = self._physical_frame
            if old is not None:
                old.release()
            self._physical_frame = frame
            card = self.cards.get(camera_id)
            if card is not None:
                card.update_captured(frame, frame.markers)
            return
        old = self.frames.get(camera_id)
        if old is not None:
            old.release()
        self.frames[camera_id] = frame
        card = self.cards.get(camera_id)
        if card is not None:
            card.update_captured(frame, frame.markers)
        self.camera_panel.set_save_frame_enabled(True)

    def _on_continuous_toggled(self, checked: bool, interval_ms: int):
        if checked:
            if not self.camera_manager.get_connected_ids():
                self._log("[WARN] 无已连接相机，无法连续拍摄")
                self.camera_panel.stop_continuous()
                return
            self._capture_timer.start(interval_ms)
            self._log(f"[INFO] 连续拍摄已启动（间隔 {interval_ms} ms）")
        else:
            self._capture_timer.stop()
            self._log("[INFO] 连续拍摄已停止")

    def _on_capture_params(self, params: dict):
        """应用拍摄参数到所有已连接相机。"""
        connected = self.camera_manager.get_connected_ids()
        if not connected:
            self._log("[WARN] 无已连接相机，参数未应用")
            return
        ok_all = True
        for cid in connected:
            try:
                controller = self.camera_manager._cameras.get(cid)
                opts = controller.build_options(
                    params['exposure_time_2d'], params['exposure_time_3d'],
                    params['gain_2d'], params['gain_3d'], params['brightness'])
                ok_all = self.camera_manager.set_options(cid, opts) and ok_all
            except Exception as e:
                self._log(f"[WARN] 相机 {cid} 参数设置失败: {e}")
                ok_all = False
        self._log("[SUCCESS] 拍摄参数已应用到所有相机" if ok_all
                  else "[WARN] 部分相机参数设置失败")

    # ==================================================================
    # 标定
    # ==================================================================
    def _on_detect_markers(self):
        """对所有相机当前帧做标记物 2D+3D 检测，并在卡片上叠加标记。"""
        if not self.frames:
            self._log("[WARN] 无帧数据，请先拍摄")
            return
        total = 0
        board_mode = getattr(self.marker_detector, 'is_board_mode', lambda: False)()
        for cid, frame in self.frames.items():
            markers = self.marker_detector.detect_3d(
                frame.image_np,
                pointmap=frame.pointmap,
                rvc_image=frame.rvc_image,
                offline_ply_path=frame.offline_pointmap_path,
            )
            frame.markers = markers
            # 标定板模式：缓存位姿与规格到 FrameData
            if board_mode:
                br = self.marker_detector.last_board_result
                if br is not None and br.get('success'):
                    frame.board_pose = br.get('T_board_in_cam')
                    frame.board_pattern = br.get('pattern_size')
                    frame.board_pattern_name = br.get('pattern_name')
                    frame.board_rms_mm = float(br.get('rms_mm', 0.0))
                else:
                    frame.board_pose = None
                    frame.board_pattern = None
                    frame.board_pattern_name = None
                    frame.board_rms_mm = 0.0
            total += len(markers)
            card = self.cards.get(cid)
            if card is not None:
                card.update_frame(frame, markers)
            if board_mode:
                if frame.board_pattern_name:
                    self._log(f"[INFO] 相机 {cid}: 检测到 {frame.board_pattern_name} 标定板，"
                              f"{len(markers)} 个圆心")
                else:
                    br = self.marker_detector.last_board_result
                    reason = br.get('message') if br else "未知原因"
                    self._log(f"[WARN] 相机 {cid}: 标定板检测失败（{reason}）")
            else:
                self._log(f"[INFO] 相机 {cid}: 检测到 {len(markers)} 个编码圆（含 3D）")
        self.log_panel.set_status(f"标记检测完成，共 {total} 个")

    def _on_calibrate_pair(self, ref_id: str, cam_id: str):
        """单帧标定一对相机（cam→ref），根据当前标记物类型自动分发。"""
        frame_ref = self.frames.get(ref_id)
        frame_cam = self.frames.get(cam_id)
        if frame_ref is None or frame_cam is None:
            self._log(f"[WARN] 标定 {cam_id}→{ref_id}: 缺少帧数据，请先拍摄")
            return

        if getattr(self.marker_detector, 'is_board_mode', lambda: False)():
            self._on_calibrate_pair_board_pose(ref_id, cam_id, frame_ref, frame_cam)
            return

        if not frame_ref.markers or not frame_cam.markers:
            self._log(f"[WARN] 标定 {cam_id}→{ref_id}: 缺少标记数据，请先检测标记")
            return
        result = self.calibration_engine.calibrate_pair(
            ref_id, cam_id, frame_ref.markers, frame_cam.markers,
            ransac_threshold=RANSAC_THRESHOLD_MM)
        if result.get('success'):
            self._log(f"[SUCCESS] 标定 {cam_id}→{ref_id}: "
                      f"RMS {result['rms_mm']:.4f} mm, "
                      f"内点 {result['inlier_count']}/{result['total_pairs']}")
        else:
            self._log(f"[ERROR] 标定 {cam_id}→{ref_id} 失败: {result.get('message')}")
        self.calibration_panel.update_results(self.calibration_engine.pair_results)

    def _on_calibrate_pair_board_pose(self, ref_id: str, cam_id: str,
                                      frame_ref: 'FrameData', frame_cam: 'FrameData'):
        """标定板位姿法：双视角拍同一块固定标定板求 cam→ref 外参。"""
        if frame_ref.board_pose is None or frame_cam.board_pose is None:
            self._log(f"[WARN] 标定 {cam_id}→{ref_id}: 缺少标定板位姿，请先检测标记")
            return
        if frame_ref.board_pattern_name != frame_cam.board_pattern_name:
            self._log(f"[WARN] 标定 {cam_id}→{ref_id}: 两个视角识别到的标定板规格不一致 "
                      f"({frame_ref.board_pattern_name} vs {frame_cam.board_pattern_name})")
            return
        result = self.calibration_engine.calibrate_pair_by_board_pose(
            ref_id, cam_id,
            frame_ref.board_pose, frame_cam.board_pose,
            pattern_name=frame_ref.board_pattern_name or "unknown",
            inlier_count=frame_ref.marker_count,
            total_pairs=frame_ref.marker_count,
            rms_ref_mm=frame_ref.board_rms_mm,
            rms_cam_mm=frame_cam.board_rms_mm,
        )
        if result.get('success'):
            self._log(f"[SUCCESS] 标定板位姿法 {cam_id}→{ref_id}: "
                      f"规格 {result.get('board_pattern_name')}, "
                      f"RMS {result['rms_mm']:.4f} mm")
        else:
            self._log(f"[ERROR] 标定 {cam_id}→{ref_id} 失败: {result.get('message')}")
        self.calibration_panel.update_results(self.calibration_engine.pair_results)

    def _on_pair_selected(self, ref_id: str, cam_id: str):
        """结果表选中某对 pair：有离群标记时在日志提示其 code（便于排查坏标记）。"""
        res = self.calibration_engine.pair_results.get((ref_id, cam_id))
        if not res or not res.get('success'):
            return
        codes = res.get('outlier_codes') or []
        if codes:
            self._log(f"[INFO] {cam_id}→{ref_id}: 离群标记已排除: "
                      f"code {', '.join(str(c) for c in codes)}")

    @staticmethod
    def _markers_fingerprint(markers: list):
        """标记数据快速指纹：排序后的 code 元组 + 坐标数组 bytes hash。

        用于判断两组编码圆检测结果是否完全相同（站位模式静态数据重复累积防护）。
        """
        ordered = sorted(markers, key=lambda m: m['code'])
        codes = tuple(m['code'] for m in ordered)
        coords = np.array([[m['x_3d'], m['y_3d'], m['z_3d']] for m in ordered],
                          dtype=np.float64)
        return codes, hashlib.md5(coords.tobytes()).hexdigest()

    def _on_add_frame(self):
        """把当前帧标记累积到多帧缓存（每个非参考相机一组）。

        重复累积防护：某 pair 的标记与缓存中最后一组完全相同时跳过
        （站位模式静态数据无需重复累积）；移动标定板后新数据指纹不同，正常累积。
        """
        if getattr(self.marker_detector, 'is_board_mode', lambda: False)():
            self._log("[INFO] 标定板位姿法为单帧标定，无需累积多帧")
            return
        ref_id = self.calibration_panel.get_reference()
        if not ref_id:
            self._log("[WARN] 请先选择参考相机")
            return
        added = 0
        skipped = 0
        for cid, frame in self.frames.items():
            if cid == ref_id:
                continue
            frame_ref = self.frames.get(ref_id)
            if frame_ref is None or not frame_ref.markers or not frame.markers:
                continue
            # 与缓存中最后一组比较指纹，完全相同则跳过
            cache = self.calibration_engine._multi_frame_data.get((ref_id, cid), [])
            if cache:
                last_ref, last_cam = cache[-1]
                if (self._markers_fingerprint(last_ref) == self._markers_fingerprint(frame_ref.markers)
                        and self._markers_fingerprint(last_cam) == self._markers_fingerprint(frame.markers)):
                    skipped += 1
                    continue
            self.calibration_engine.add_frame_data(
                ref_id, cid, frame_ref.markers, frame.markers)
            added += 1
        n = self._accumulated_count(ref_id)
        self.calibration_panel.set_accumulated_frames(n)
        if added:
            self._log(f"[INFO] 已累积当前帧到 {added} 个 pair 的多帧缓存（当前 {n} 帧）")
        if skipped:
            self._log("[INFO] 当前帧数据与上次累积相同，已跳过"
                      "（站位模式静态数据无需重复累积；如需多帧平均请移动标定板后重新拍摄累积）")

    def _accumulated_count(self, ref_id: str) -> int:
        """多帧缓存中参考相机相关 pair 的最大累积帧数。"""
        counts = [len(v) for (r, _c), v in
                  self.calibration_engine._multi_frame_data.items() if r == ref_id]
        return max(counts) if counts else 0

    def _on_calibrate_multi(self):
        """多帧平均标定（所有非参考相机）。"""
        if getattr(self.marker_detector, 'is_board_mode', lambda: False)():
            self._log("[INFO] 标定板位姿法为单帧标定，请使用【标定所有 pair（标定板位姿）】")
            return
        ref_id = self.calibration_panel.get_reference()
        if not ref_id:
            self._log("[WARN] 请先选择参考相机")
            return
        n_ok = 0
        for cid in self.calibration_panel.other_camera_ids():
            result = self.calibration_engine.calibrate_multi_frame(
                ref_id, cid, ransac_threshold=RANSAC_THRESHOLD_MM)
            if result.get('success'):
                n_ok += 1
                self._log(f"[SUCCESS] 多帧标定 {cid}→{ref_id}: "
                          f"RMS {result['rms_mm']:.4f} mm "
                          f"({result.get('valid_frames', 1)} 帧)")
            else:
                self._log(f"[ERROR] 多帧标定 {cid}→{ref_id} 失败: {result.get('message')}")
        if n_ok:
            self.calibration_panel.update_results(self.calibration_engine.pair_results)

    def _on_clear_frames(self):
        self.calibration_engine.clear_frame_data()
        self.calibration_panel.set_accumulated_frames(0)
        self._log("[INFO] 多帧缓存已清空")

    def _on_reference_changed(self, ref_id: str):
        self.calibration_engine.set_reference(ref_id)
        self.viewer_3d.set_reference(ref_id)
        self._log(f"[INFO] 参考相机: {ref_id}")

    def _on_marker_type_changed(self, marker_type: str):
        """标记物类型切换：同步检测器、清空已有结果并提示用户。"""
        self.marker_detector.set_marker_type(marker_type)
        self.calibration_engine.pair_results.clear()
        self.calibration_engine._multi_frame_data.clear()
        self.calibration_panel.clear_results()
        for frame in self.frames.values():
            frame.markers = []
            frame.board_pose = None
            frame.board_pattern = None
            frame.board_pattern_name = None
        self.viewer_3d.clear_all()
        if marker_type == MARKER_TYPE_ASYMMETRIC_GRID:
            self._log("[INFO] 标记物类型切换为：非对称黑底白圆标定板；"
                      "请确保两个视角拍摄同一块固定标定板")
        else:
            self._log("[INFO] 标记物类型切换为：旋转编码圆")
        self._log("[INFO] 已清空当前标定结果与多帧缓存；"
                  "如有已保存的标定文件（.json），请确认与当前标记物类型兼容后再加载")

    def _on_save_calibration(self):
        if not self.calibration_engine.pair_results:
            self._log("[WARN] 无标定结果可保存")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存标定结果", "calibration.json", "JSON 文件 (*.json)")
        if not path:
            return
        if self.calibration_engine.save_calibration(path):
            self._log(f"[SUCCESS] 标定结果已保存: {path}")
        else:
            self._log(f"[ERROR] 保存失败: {path}")

    def _on_load_calibration(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载标定结果", "", "JSON 文件 (*.json)")
        if not path:
            return
        if self.calibration_engine.load_calibration(path):
            ref = self.calibration_engine.reference_id
            if ref:
                self.calibration_panel.set_reference(ref)
                self.viewer_3d.set_reference(ref)
            self.calibration_panel.update_results(self.calibration_engine.pair_results)
            self._log(f"[SUCCESS] 标定结果已加载: {path} "
                      f"({len(self.calibration_engine.pair_results)} 对)")
        else:
            self._log(f"[ERROR] 加载失败: {path}")

    # ==================================================================
    # 拼接
    # ==================================================================
    def _on_process_params(self, params: dict):
        self._process_params = params

    def _build_processor(self) -> PointCloudProcessor:
        processor = PointCloudProcessor()
        for key, value in self._process_params.items():
            if hasattr(processor, key):
                setattr(processor, key, value)
        return processor

    def _do_stitch(self):
        """执行拼接，返回 (merged_pcd, elapsed_ms) 或 (None, 0)。"""
        if not self.frames:
            self._log("[WARN] 无帧数据，请先拍摄")
            return None, 0.0
        ref_id = (self.calibration_engine.reference_id
                  or self.calibration_panel.get_reference())
        if not ref_id:
            self._log("[WARN] 请先选择参考相机")
            return None, 0.0
        t0 = time.perf_counter()
        merged, msg = self.stitch_engine.stitch(
            self.frames, self.calibration_engine, ref_id,
            processor=self._build_processor())
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        for line in msg.splitlines():
            self._log(f"[INFO] {line}")
        self._last_stitch_input_points = self._parse_input_points(msg)
        if merged is None:
            self._log("[ERROR] 拼接失败（是否已完成标定？）")
            return None, elapsed_ms
        return merged, elapsed_ms

    @staticmethod
    def _parse_input_points(msg: str) -> int:
        """从拼接日志消息中解析后处理前的原始点数（用于过滤保护）。"""
        import re
        m = re.search(r"(?:原始点数|总点数)[:：]\s*([\d,]+)", msg)
        return int(m.group(1).replace(',', '')) if m else 0

    def _check_over_filtering(self, result_points: int, input_points: int):
        """后处理过滤保护：结果为 0 或 < 输入 5% 时告警并标红结果区。"""
        over = (input_points > 0
                and (result_points == 0 or result_points < input_points * 0.05))
        if over:
            pct = 100.0 * (1.0 - result_points / max(1, input_points))
            self._log(f"[WARNING] 后处理滤除了 {pct:.1f}% 的点云"
                      f"（剩余 {result_points:,} 点），参数可能过激，"
                      f"建议点击「自动设置参数」")
        self.stitch_panel.set_points_alert(over)

    def _on_auto_params(self):
        """自动设置后处理参数：基于最近拼接结果（否则当前帧临时合并）估计。"""
        pcd = self._last_merged_pcd
        source = "最近一次拼接结果"
        if pcd is None or len(pcd.points) == 0:
            # 无拼接结果：当前各帧临时合并（无标定时简单合并，不做变换）
            if not self.frames:
                self._log("[WARN] 请先拍摄或拼接点云，再使用「自动设置参数」")
                return
            import open3d as o3d
            pcd = o3d.geometry.PointCloud()
            n_loaded = 0
            for cid, frame in self.frames.items():
                try:
                    sub = frame.load_pointcloud_o3d()
                except Exception:
                    sub = None
                if sub is not None and len(sub.points) > 0:
                    pcd += sub
                    n_loaded += 1
            if n_loaded == 0:
                self._log("[WARN] 当前帧无可用点云，请先拍摄或拼接点云")
                return
            source = f"当前 {n_loaded} 台相机帧临时合并（未变换）"
        self._log(f"[INFO] 自动设置参数：基于{source}"
                  f"（{len(pcd.points):,} 点），正在估计…")
        try:
            params = PointCloudProcessor().auto_tune(pcd)
        except Exception as e:
            self._log(f"[ERROR] 自动参数估计失败: {e}")
            return
        self.stitch_panel.set_process_params(params)
        self.stitch_panel.set_auto_notes(params.get('notes', []))
        voxel_txt = (f"{params['voxel_size']:.2f}mm"
                     if params['enable_voxel_downsample'] else "关闭")
        self._log(f"[SUCCESS] 自动参数已应用: 单位={params['unit']}, "
                  f"点距≈{params['avg_spacing_mm']:.3f}mm, "
                  f"裁切={params['crop_mode']}(比例 {params['crop_ratio']:.2f}), "
                  f"体素={voxel_txt}, "
                  f"离群点 std={params['outlier_std_ratio']}, "
                  f"预估点数 {params['estimated_points']:,}")

    def _on_stitch(self):
        merged, elapsed_ms = self._do_stitch()
        if merged is None:
            return
        # 各路点云 → 3D 查看器（叠加模式可对比）
        for cid, frame in self.frames.items():
            try:
                pcd = frame.load_pointcloud_o3d()
                if pcd is not None and len(pcd.points) > 0:
                    self.viewer_3d.set_pointcloud(cid, pcd)
            except Exception as e:
                self._log(f"[WARN] 相机 {cid} 点云加载失败: {e}")
        self.viewer_3d.set_pointcloud_merged(merged)
        self._last_merged_pcd = merged
        self.stitch_panel.set_result(len(merged.points), elapsed_ms)
        self._check_over_filtering(len(merged.points),
                                   self._last_stitch_input_points)
        self._log(f"[SUCCESS] 拼接完成: {len(merged.points):,} 点, 耗时 {elapsed_ms:.1f} ms")

    def _on_stitch_save(self):
        merged, elapsed_ms = self._do_stitch()
        if merged is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存拼接点云", "stitched.ply", "PLY 文件 (*.ply)")
        if not path:
            return
        try:
            import open3d as o3d
            if o3d.io.write_point_cloud(path, merged):
                self.viewer_3d.set_pointcloud_merged(merged)
                self._last_merged_pcd = merged
                self.stitch_panel.set_result(len(merged.points), elapsed_ms, path)
                self._check_over_filtering(len(merged.points),
                                           self._last_stitch_input_points)
                self._log(f"[SUCCESS] 拼接点云已保存: {path} ({len(merged.points):,} 点)")
            else:
                self._log(f"[ERROR] PLY 写入失败: {path}")
        except Exception as e:
            self._log(f"[ERROR] 保存 PLY 异常: {e}")

    # ==================================================================
    # 离线会话
    # ==================================================================
    def _ensure_card(self, camera_id: str, desc: str = "") -> CameraPreviewCard:
        """确保预览卡片存在（离线相机无真实设备，仅建卡片用于预览/管理）。"""
        card = self.cards.get(camera_id)
        if card is None:
            card = CameraPreviewCard(camera_id)
            card.capture_requested.connect(self._on_capture_single)
            card.disconnect_requested.connect(self._on_remove_camera)
            self.cards[camera_id] = card
            self.camera_panel.add_camera_entry(camera_id, desc)
            self._relayout_grid()
            self._sync_camera_lists()
        return card

    def _on_save_frame_to_session(self):
        """把当前各相机帧保存到离线会话（无会话则先创建）。"""
        if not self.frames:
            self._log("[WARN] 无帧数据，请先拍摄")
            return
        if not self.offline_session.session_dir:
            path = self.offline_session.create_new("offline_data")
            self._session_capture_seq = 0
            self._log(f"[INFO] 离线会话已创建: {path}")
        # 跨相机统一帧号（在线各相机 frame_id 各自计数，无法直接对齐）
        self._session_capture_seq += 1
        for cid, frame in self.frames.items():
            frame.frame_id = self._session_capture_seq
            self.offline_session.add_frame(cid, frame)
        self.camera_panel.set_session_path(self.offline_session.session_dir)
        self.camera_panel.set_batch_enabled(True)
        self._log(f"[SUCCESS] 第 {self._session_capture_seq} 拍已保存到会话 "
                  f"({len(self.frames)} 台相机)")

    def _on_save_session(self):
        """保存会话（刷新所有帧 meta，含最新检测结果）。"""
        if not self.offline_session.session_dir:
            self._log("[WARN] 会话未创建，请先「保存当前帧到会话」或「加载会话」")
            return
        path = self.offline_session.save_all()
        self.camera_panel.set_session_path(path)
        self._log(f"[SUCCESS] 会话已保存: {path}")

    def _on_load_session(self):
        """选择会话目录并加载。"""
        base = "offline_data" if os.path.isdir("offline_data") else ""
        path = QFileDialog.getExistingDirectory(self, "加载离线会话", base)
        if not path:
            return
        self._load_session_from(path)

    def _load_session_from(self, path: str) -> bool:
        """加载会话目录：帧数据 → 内存，最新帧 → 卡片预览与当前帧。"""
        frames_map = self.offline_session.load_session(path)
        if not frames_map:
            self._log(f"[WARN] 会话为空或加载失败: {path}")
            return False
        # 释放当前帧，替换为会话最新帧
        for old in self.frames.values():
            try:
                old.release()
            except Exception:
                pass
        self.frames = {}
        for cid, frame in self.offline_session.latest_frames().items():
            card = self._ensure_card(cid, "（离线会话）")
            self.frames[cid] = frame
            try:
                card.update_frame(frame, frame.markers)
            except Exception as e:
                self._log(f"[WARN] 相机 {cid} 预览更新失败: {e}")
        self._sync_camera_lists()
        self.camera_panel.set_session_path(self.offline_session.session_dir)
        self.camera_panel.set_batch_enabled(True)
        n = sum(len(v) for v in frames_map.values())
        self._log(f"[SUCCESS] 会话已加载: {path} "
                  f"({len(frames_map)} 台相机, {n} 帧)")
        self._log("[INFO] 接下来可依次：批量检测标记 → 批量标定会话 → 批量拼接会话")
        return True

    def _on_batch_detect(self):
        """批量检测会话中所有帧的编码圆。"""
        if not self.offline_session.frames:
            self._log("[WARN] 无会话帧数据，请先加载会话")
            return
        results = self.offline_session.detect_all(self.marker_detector)
        total = sum(len(m) for per_cam in results.values() for m in per_cam)
        for cid, per_cam in results.items():
            self._log(f"[INFO] 批量检测 {cid}: {[len(m) for m in per_cam]} 个/帧")
        # 最新帧检测结果同步到卡片
        for cid, frame in self.offline_session.latest_frames().items():
            card = self.cards.get(cid)
            if card is not None:
                try:
                    card.update_frame(frame, frame.markers)
                except Exception:
                    pass
            if cid in self.frames:
                self.frames[cid].markers = frame.markers
        self.log_panel.set_status(f"批量检测完成，共 {total} 个标记")
        self._log(f"[SUCCESS] 批量检测完成: {total} 个标记")

    def _on_batch_calibrate(self):
        """批量标定：会话全部帧累积 + 多帧平均（所有非参考相机）。"""
        if getattr(self.marker_detector, 'is_board_mode', lambda: False)():
            self._log("[INFO] 标定板位姿法为单帧标定，请加载会话后在当前帧界面使用"
                      "【标定所有 pair（标定板位姿）】（离线批量多帧平均后续扩展）")
            return
        ref_id = self.calibration_panel.get_reference()
        if not ref_id:
            self._log("[WARN] 请先在标定 Tab 选择参考相机")
            return
        if not self.offline_session.frames:
            self._log("[WARN] 无会话帧数据，请先加载会话")
            return
        results = self.offline_session.calibrate_multi(
            self.calibration_engine, ref_id, ransac_threshold=RANSAC_THRESHOLD_MM)
        n_ok = 0
        for cid, res in results.items():
            if res.get('success'):
                n_ok += 1
                self._log(f"[SUCCESS] 批量标定 {cid}→{ref_id}: "
                          f"RMS {res['rms_mm']:.4f} mm "
                          f"({res.get('valid_frames', 1)} 帧)")
            else:
                self._log(f"[ERROR] 批量标定 {cid}→{ref_id} 失败: {res.get('message')}")
        if n_ok:
            self.calibration_engine.set_reference(ref_id)
            self.viewer_3d.set_reference(ref_id)
            self.calibration_panel.update_results(self.calibration_engine.pair_results)
            self.log_panel.set_status(f"批量标定完成: {n_ok}/{len(results)} 对成功")

    def _on_stitch_session(self):
        """批量拼接离线会话（全部帧对合并到参考坐标系）。"""
        if not self.offline_session.frames:
            self._log("[WARN] 无会话帧数据，请先加载会话")
            return
        ref_id = (self.calibration_engine.reference_id
                  or self.calibration_panel.get_reference())
        if not ref_id:
            self._log("[WARN] 请先选择参考相机")
            return
        t0 = time.perf_counter()
        merged, msg = self.offline_session.stitch_all(
            self.stitch_engine, self.calibration_engine, ref_id,
            processor=self._build_processor())
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        for line in msg.splitlines():
            self._log(f"[INFO] {line}")
        if merged is None:
            self._log("[ERROR] 批量拼接失败（是否已完成批量标定？）")
            return
        self.viewer_3d.set_pointcloud_merged(merged)
        self._last_merged_pcd = merged
        self.stitch_panel.set_result(len(merged.points), elapsed_ms)
        self._check_over_filtering(len(merged.points),
                                   self._parse_input_points(msg))
        self._log(f"[SUCCESS] 批量拼接完成: {len(merged.points):,} 点, "
                  f"耗时 {elapsed_ms:.1f} ms")

    # ==================================================================
    # 单相机多站位模式（Phase 5）
    # ==================================================================
    def _on_station_refresh_devices(self):
        """站位模式：枚举设备并填充站位面板设备列表。"""
        try:
            descs = self._enumerate_devices()
            self.station_panel.set_devices(descs)
            if descs:
                self._log(f"[INFO] 查找到 {len(descs)} 台设备: {'; '.join(descs)}")
            else:
                self._log("[WARN] 未找到任何设备（检查连接或 SDK）")
        except Exception as e:
            self._log(f"[ERROR] 查找设备失败: {e}")

    def _on_station_connect(self, device_index: int):
        """站位模式：连接物理相机 + 生成「当前相机（取景）」卡片（固定网格第一位）。"""
        self.camera_manager.add_camera(self.PHYSICAL_ID)  # 已存在则忽略
        card = self.cards.get(self.PHYSICAL_ID)
        if card is None:
            card = CameraPreviewCard(self.PHYSICAL_ID)
            card.set_title("📷 当前相机（取景）", "camera")
            # 当前相机按钮只做 2D 预览（Capture2D），不拍摄点云，便于调整站位
            card.set_capture_button_text("👁 预览", "preview")
            card.capture_requested.connect(self._on_preview_physical)
            card.preview_toggled.connect(self._on_preview_toggled)
            card.disconnect_requested.connect(self._on_station_disconnect)
            self.cards[self.PHYSICAL_ID] = card
        # 每次连接都确保当前相机卡片是预览模式
        card.set_preview_mode(True, icon_name="preview")

        ok, msg = self.camera_manager.connect(self.PHYSICAL_ID, device_index)
        card.set_connected(ok)
        self.station_panel.set_connected(ok, msg)
        if ok:
            self._log(f"[SUCCESS] 物理相机已连接: {msg}")
            self.log_panel.set_status("物理相机已连接，移动站位后点击「拍摄站位」")
        else:
            self._log(f"[WARN] 物理相机连接失败: {msg}")
        self._relayout_grid()
        self._update_capture_enabled()

    def _on_station_disconnect(self):
        """站位模式：断开物理相机并移除取景卡片（站位卡片与帧保留）。"""
        self._stop_physical_preview()
        self.camera_manager.remove_camera(self.PHYSICAL_ID)
        if self._physical_frame is not None:
            try:
                self._physical_frame.release()
            except Exception:
                pass
            self._physical_frame = None
        card = self.cards.pop(self.PHYSICAL_ID, None)
        if card is not None:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.station_panel.set_connected(False)
        self._relayout_grid()
        self._update_capture_enabled()
        self._log("[INFO] 物理相机已断开")

    def _on_capture_station(self):
        """站位模式：拍摄站位 → 立即存盘 → 中央网格新增站位卡片。"""
        # 3D 拍摄前暂停持续 2D 预览，避免 Capture2D / Capture 冲突
        self._stop_physical_preview()
        station_id, msg = self.station_manager.capture_station(self.PHYSICAL_ID)
        if station_id is None:
            self._log(f"[WARN] 站位拍摄失败: {msg}")
            return
        frame = self.station_manager.get_frame(station_id)

        # 物理相机卡片同步显示刚拍的取景画面
        pcard = self.cards.get(self.PHYSICAL_ID)
        if pcard is not None:
            pcard.update_captured(frame, frame.markers)

        # 站位卡片：显示保存的帧，标题"站位 N"，无拍摄/断开按钮
        card = self._ensure_station_card(station_id)
        self.frames[station_id] = frame
        card.update_captured(frame, frame.markers)

        self.station_panel.add_station(
            station_id, self.station_manager.capture_time(station_id))
        self.station_panel.set_session_path(self.station_manager.session_dir)
        self._relayout_grid()
        self._sync_camera_lists()
        self._log(f"[SUCCESS] {msg}（{self.station_manager.session_dir}）")
        self.log_panel.set_status(
            f"已拍 {self.station_manager.station_count()} 个站位，"
            "可继续移动拍摄，或到标定 Tab 检测/标定")

    def _ensure_station_card(self, station_id: str) -> CameraPreviewCard:
        """确保站位卡片存在（复用 CameraPreviewCard，隐藏拍摄/断开按钮）。"""
        card = self.cards.get(station_id)
        if card is None:
            card = CameraPreviewCard(station_id)
            card.set_title(f"📍 {station_label(station_id)}", "station")
            card.btn_capture.hide()
            card.btn_disconnect.hide()
            card.set_connected(True)  # 绿点表示帧有效
            card.lbl_status.setText("已存盘")
            self.cards[station_id] = card
        return card

    def _on_remove_station(self, station_id: str):
        """删除站位：移除卡片 / 帧 / 磁盘数据，并清理相关标定结果。"""
        if not self.station_manager.remove_station(station_id):
            self._log(f"[WARN] 站位 {station_id} 不存在")
            return
        self.frames.pop(station_id, None)
        card = self.cards.pop(station_id, None)
        if card is not None:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.station_panel.remove_station(station_id)
        self.viewer_3d.remove_camera(station_id)
        self._purge_station_from_calibration(station_id)
        self._relayout_grid()
        self._sync_camera_lists()
        self._log(f"[INFO] {station_label(station_id)} 已删除"
                  f"（剩余 {self.station_manager.station_count()} 个站位）")

    def _purge_station_from_calibration(self, station_id: str):
        """清理涉及指定站位的标定结果与多帧缓存，并刷新标定面板。"""
        engine = self.calibration_engine
        keys = [k for k in engine.pair_results if station_id in k]
        for k in keys:
            del engine.pair_results[k]
        for k in [k for k in engine._multi_frame_data if station_id in k]:
            del engine._multi_frame_data[k]
        if engine.reference_id == station_id:
            engine.reference_id = None
            self._log("[WARN] 参考站位已删除，请以新的参考站位重新标定")
        if keys:
            self.calibration_panel.update_results(engine.pair_results)
            self._log(f"[INFO] 已清理 {len(keys)} 条涉及 "
                      f"{station_label(station_id)} 的标定结果")

    def _clear_station_ui(self):
        """清空站位相关 UI 状态（卡片 / 帧 / 列表 / 标定结果），物理相机保留。
        站位集合从卡片 / 帧键推导（站位 ID 前缀 station_），
        与 StationManager 的清空顺序无关。"""
        prefix = StationManager.STATION_PREFIX
        station_ids = sorted({sid for sid in list(self.cards.keys()) + list(self.frames.keys())
                              if sid.startswith(prefix)})
        for station_id in station_ids:
            self.frames.pop(station_id, None)
            card = self.cards.pop(station_id, None)
            if card is not None:
                self.grid_layout.removeWidget(card)
                card.deleteLater()
            self.viewer_3d.remove_camera(station_id)
            self._purge_station_from_calibration(station_id)
        self.station_panel.clear_stations()
        self._relayout_grid()
        self._sync_camera_lists()

    def _on_clear_stations(self):
        """清空所有站位（保留会话目录，可继续拍摄新站位）。"""
        self.station_manager.clear()
        self._clear_station_ui()
        self._log("[INFO] 站位已清空")

    def _on_new_station_session(self):
        """新会话：归档旧会话目录，清空站位重新开始。"""
        self.station_manager.clear()       # 清内存站位（旧会话目录归档保留）
        self._clear_station_ui()
        path = self.station_manager.new_session()
        self.station_panel.set_session_path(path)
        self._log(f"[SUCCESS] 站位新会话已创建: {path}")

    # ==================================================================
    # 关闭
    # ==================================================================
    def closeEvent(self, event):
        self._capture_timer.stop()
        for frame in self.frames.values():
            try:
                frame.release()
            except Exception:
                pass
        if self._physical_frame is not None:
            try:
                self._physical_frame.release()
            except Exception:
                pass
        self.camera_manager.shutdown()
        super().closeEvent(event)
