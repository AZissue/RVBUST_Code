# -*- coding: utf-8 -*-
"""
功能二：单相机移动链式拼接视图（MobileChainView）。

UI 布局：
  - 左侧：机位时间线（竖排，每机位显示标记数/重合度/误差/质量色标）
  - 中央上部：实时取景（当前相机 2D 预览 + 编码圆检测叠加）
  - 中央下部：实时 3D 拼接视图（增量刷新，按机位分色）
  - 右侧：评估面板（当前步共视标记/内点率/RMS/建议动作）

所有业务动作通过信号发给主窗口。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QGroupBox, QFormLayout,
)

from ..icons import icon_text, apply_icon, make_group_box, apply_group_icon


class StationTimelineWidget(QListWidget):
    """机位时间线（竖排列表）。"""

    station_selected = Signal(str)      # 选中机位
    station_rejected = Signal(str)      # 重拍机位

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(200)

    def add_station(self, station_id: str, n_markers: int,
                    cum_rms_mm: float, quality: str = "good"):
        """添加机位节点。"""
        text = f"{station_id}\n标记:{n_markers} 误差:{cum_rms_mm:.2f}mm"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, station_id)
        # 质量色标
        if quality == "good":
            item.setBackground(Qt.darkGreen)
        elif quality == "ok":
            item.setBackground(Qt.darkYellow)
        else:
            item.setBackground(Qt.darkRed)
        self.addItem(item)

    def update_station(self, station_id: str, n_markers: int,
                       cum_rms_mm: float, quality: str = "good"):
        """更新机位节点。"""
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) == station_id:
                text = f"{station_id}\n标记:{n_markers} 误差:{cum_rms_mm:.2f}mm"
                item.setText(text)
                if quality == "good":
                    item.setBackground(Qt.darkGreen)
                elif quality == "ok":
                    item.setBackground(Qt.darkYellow)
                else:
                    item.setBackground(Qt.darkRed)
                return


class EvaluationPanel(QWidget):
    """评估面板（当前步质量显示）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QFormLayout(self)
        lo.setSpacing(4)

        self.lbl_station = QLabel("-")
        self.lbl_markers = QLabel("-")
        self.lbl_inlier = QLabel("-")
        self.lbl_rms = QLabel("-")
        self.lbl_cum_rms = QLabel("-")
        self.lbl_suggestion = QLabel("-")
        self.lbl_suggestion.setWordWrap(True)

        lo.addRow("当前机位:", self.lbl_station)
        lo.addRow("共视标记:", self.lbl_markers)
        lo.addRow("内点率:", self.lbl_inlier)
        lo.addRow("单步 RMS:", self.lbl_rms)
        lo.addRow("累计误差:", self.lbl_cum_rms)
        lo.addRow("建议:", self.lbl_suggestion)

    def set_evaluation(self, evaluation: Dict[str, Any]):
        """更新评估结果。"""
        self.lbl_station.setText(evaluation.get('station_id', '-'))
        self.lbl_markers.setText(str(evaluation.get('common_markers', '-')))
        self.lbl_inlier.setText(f"{evaluation.get('inlier_ratio', 0):.1%}")
        self.lbl_rms.setText(f"{evaluation.get('rms_mm', 0):.3f} mm")
        self.lbl_cum_rms.setText(f"{evaluation.get('cum_rms_mm', 0):.3f} mm")
        self.lbl_suggestion.setText(evaluation.get('suggestion', '-'))
        # 质量色标
        if evaluation.get('success'):
            self.lbl_suggestion.setStyleSheet("color: #43a047;")
        else:
            self.lbl_suggestion.setStyleSheet("color: #e53935;")


class MobileChainView(QWidget):
    """单相机移动链式拼接视图。"""

    capture_station_requested = Signal()
    undo_station_requested = Signal()
    optimize_global_requested = Signal()
    save_session_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(6)

        # 左：机位时间线
        self.grp_timeline = make_group_box("station", "📍 机位时间线")
        tl_lo = QVBoxLayout(self.grp_timeline)
        apply_group_icon(self.grp_timeline)
        self.timeline = StationTimelineWidget()
        tl_lo.addWidget(self.timeline)
        lo.addWidget(self.grp_timeline)

        # 中：实时取景 + 3D 拼接
        center_lo = QVBoxLayout()
        center_lo.setSpacing(6)

        # 实时取景
        self.grp_preview = make_group_box("camera", "📷 实时取景")
        pv_lo = QVBoxLayout(self.grp_preview)
        apply_group_icon(self.grp_preview)
        self.lbl_preview = QLabel("未连接相机")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(200)
        self.lbl_preview.setStyleSheet("background-color: #1A1A20; color: #8B8D98;")
        pv_lo.addWidget(self.lbl_preview)
        center_lo.addWidget(self.grp_preview)

        # 3D 拼接视图
        self.grp_3d = make_group_box("view_3d", "🧊 实时拼接")
        v3_lo = QVBoxLayout(self.grp_3d)
        apply_group_icon(self.grp_3d)
        self.lbl_3d = QLabel("未加载点云")
        self.lbl_3d.setAlignment(Qt.AlignCenter)
        self.lbl_3d.setMinimumHeight(200)
        self.lbl_3d.setStyleSheet("background-color: #1A1A20; color: #8B8D98;")
        v3_lo.addWidget(self.lbl_3d)
        center_lo.addWidget(self.grp_3d, 1)

        lo.addLayout(center_lo, 1)

        # 右：评估面板 + 操作按钮
        right_lo = QVBoxLayout()
        right_lo.setSpacing(6)

        self.grp_eval = make_group_box("chart", "📊 配准评估")
        eval_lo = QVBoxLayout(self.grp_eval)
        apply_group_icon(self.grp_eval)
        self.eval_panel = EvaluationPanel()
        eval_lo.addWidget(self.eval_panel)
        right_lo.addWidget(self.grp_eval)

        # 操作按钮
        self.grp_actions = make_group_box("process", "🎬 操作")
        act_lo = QVBoxLayout(self.grp_actions)
        apply_group_icon(self.grp_actions)

        self.btn_capture = QPushButton(icon_text("capture", "📸 拍摄机位"))
        self.btn_capture.setObjectName("primaryButton")
        self.btn_capture.setMinimumHeight(44)
        self.btn_capture.clicked.connect(self.capture_station_requested.emit)
        apply_icon(self.btn_capture, "capture")
        act_lo.addWidget(self.btn_capture)

        self.btn_undo = QPushButton(icon_text("clear", "↩ 撤销上一机位"))
        self.btn_undo.clicked.connect(self.undo_station_requested.emit)
        apply_icon(self.btn_undo, "clear")
        act_lo.addWidget(self.btn_undo)

        self.btn_optimize = QPushButton(icon_text("calibrate", "🌐 全局优化"))
        self.btn_optimize.clicked.connect(self.optimize_global_requested.emit)
        apply_icon(self.btn_optimize, "calibrate")
        act_lo.addWidget(self.btn_optimize)

        self.btn_save = QPushButton(icon_text("save", "💾 保存会话"))
        self.btn_save.setObjectName("successButton")
        self.btn_save.clicked.connect(self.save_session_requested.emit)
        apply_icon(self.btn_save, "save")
        act_lo.addWidget(self.btn_save)

        right_lo.addWidget(self.grp_actions)
        right_lo.addStretch(1)

        lo.addLayout(right_lo)

    # ------------------------------------------------------------------
    # 公共接口（主窗口调用）
    # ------------------------------------------------------------------
    def add_station_to_timeline(self, station_id: str, n_markers: int,
                                cum_rms_mm: float, quality: str = "good"):
        """添加机位到时间线。"""
        self.timeline.add_station(station_id, n_markers, cum_rms_mm, quality)

    def update_evaluation(self, evaluation: Dict[str, Any]):
        """更新评估面板。"""
        self.eval_panel.set_evaluation(evaluation)

    def set_preview_text(self, text: str):
        """设置实时取景显示文本。"""
        self.lbl_preview.setText(text)

    def set_3d_text(self, text: str):
        """设置 3D 拼接显示文本。"""
        self.lbl_3d.setText(text)
