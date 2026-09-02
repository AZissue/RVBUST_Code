# -*- coding: utf-8 -*-
"""
后处理测试工具 —— 独立原型（ui_v2 风格）。

布局参考 CloudCompare：
  - 左侧：DB 树 + 属性页，顶部为 DB 树，底部显示选中点云属性；
  - 中间：完整 3D 点云查看器（复用 src/ui_v2/widgets/viewer_panel.py）；
  - 右侧：后处理参数面板（下采样、离群点去除、AABB/球/OBB 裁切）；
  - 底部：日志栏，输出加载/处理/保存信息。

显示控制由左侧 DB 树统一负责：勾选的点云自动叠加显示，取消勾选则隐藏。
为解决大数据量（数千万点）卡顿，引入"显示预算"机制：仅对显示副本进行自适应
均匀降采样，原始 open3d 点云对象保留给后处理与保存。

运行方式：
    python prototypes/postprocess_test/app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np
import open3d as o3d

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDockWidget, QFileDialog,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QProgressDialog, QPushButton, QSizePolicy, QSpinBox, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

# 让原型能引用 src/ 下的模块
SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.point_cloud_processor import PointCloudProcessor
from ui_v2.theme import (
    ACCENT, BG_CARD, BG_INPUT, BG_PANEL, BG_WINDOW, BORDER, GLOBAL_QSS,
    STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_MUTED, TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from ui_v2 import icons as ui_icons
from ui_v2.widgets import LogPanel, ViewerPanel


# DB 树中多路点云的默认配色（与主程序 3D 查看器保持一致）
COLOR_PALETTE = [
    (0.20, 0.80, 1.00),   # 青
    (1.00, 0.60, 0.20),   # 橙
    (0.40, 1.00, 0.40),   # 绿
    (1.00, 0.40, 0.70),   # 品红
    (1.00, 1.00, 0.30),   # 黄
    (0.70, 0.50, 1.00),   # 紫
    (0.40, 0.90, 0.80),   # 蓝绿
    (0.95, 0.50, 0.50),   # 红
]


def _to_qcolor(color: tuple) -> QColor:
    """将归一化 RGB 三元组转为 QColor。"""
    r = max(0, min(255, int(color[0] * 255)))
    g = max(0, min(255, int(color[1] * 255)))
    b = max(0, min(255, int(color[2] * 255)))
    return QColor(r, g, b)


class LoadPointCloudWorker(QThread):
    """后台加载 PLY/PCD/XYZ 点云文件。"""

    progress = Signal(int, int, str)
    loaded = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self.files = files

    def run(self):
        total = len(self.files)
        for i, path in enumerate(self.files, start=1):
            try:
                self.progress.emit(i - 1, total, path)
                pcd = o3d.io.read_point_cloud(path)
                if len(pcd.points) == 0:
                    self.error.emit(f"文件为空或无法解析：{path}")
                else:
                    self.loaded.emit({"path": path, "pcd": pcd})
            except Exception as e:
                self.error.emit(f"加载失败 {path}：{e}")
        self.finished.emit()


class DBTreeItem(QTreeWidgetItem):
    """DB 树节点：携带点云对象、原始点云、渲染缓存与显示名称。"""

    def __init__(self, name: str, pcd: Optional[o3d.geometry.PointCloud] = None,
                 parent=None):
        super().__init__(parent)
        self.setText(0, name)
        self.setFlags(self.flags() | Qt.ItemIsUserCheckable)
        self.setCheckState(0, Qt.Checked)
        self.pcd = pcd
        self.original_pcd = pcd
        self.file_key: Optional[str] = None
        self.color = (0.7, 0.7, 0.7)
        self.point_size = 1
        # 原始点云渲染缓存（完整分辨率，用于后处理/保存/生成显示副本）
        self._render_points: Optional[np.ndarray] = None
        self._render_colors: Optional[np.ndarray] = None
        # 显示级降采样缓存（实际上传到 GPU）
        self._display_points: Optional[np.ndarray] = None
        self._display_colors: Optional[np.ndarray] = None
        # 显示副本相对原始点云的步长（uniform 下采样每 k 点取 1）
        self._display_step: int = 1


class PostProcessTestWindow(QMainWindow):
    """后处理测试主窗口（ui_v2 风格）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("后处理测试工具")
        self.resize(1500, 950)

        self._processor = PointCloudProcessor()
        self._loaded_pcds: Dict[str, o3d.geometry.PointCloud] = {}
        self._current_item: Optional[DBTreeItem] = None
        self._batch_loading = False
        self._viewer_cloud_keys: Set[str] = set()
        # 显示预算：所有可见点云上传到 GPU 的总点数上限
        self._render_budget = 5_000_000

        self._setup_ui()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # 底部日志栏（先创建）
        self._log_panel = LogPanel(self)
        self._log_panel.setFixedHeight(140)
        self._log_panel.setStyleSheet(
            f"QWidget {{ background-color: {BG_PANEL}; border-top: 1px solid {BORDER}; }}")

        # 顶部工具栏
        toolbar = self._build_toolbar()
        root.addWidget(toolbar)

        # 主体：左右 dock + 中间 3D
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        # 左侧 DB 树 + 属性页
        self._dock_db = QDockWidget("DB 树", self)
        self._dock_db.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self._dock_db.setTitleBarWidget(QWidget())
        self._dock_db.setWidget(self._build_db_panel())
        self.addDockWidget(Qt.LeftDockWidgetArea, self._dock_db)

        # 右侧后处理面板
        self._dock_process = QDockWidget("后处理", self)
        self._dock_process.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self._dock_process.setTitleBarWidget(QWidget())
        self._dock_process.setWidget(self._build_process_panel())
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_process)

        # 中间 3D 查看器
        self._viewer_panel = ViewerPanel("3D 点云预览")
        self._viewer_panel.setStyleSheet(
            f"QFrame {{ background-color: {BG_WINDOW}; border: none; }}")
        # 后处理子功能使用极简 3D 工具栏，控制项放到左右面板
        self._viewer_panel.viewer().set_toolbar_minimal(True)
        self._viewer_panel.viewer().set_show_axes(False)
        self._viewer_panel.viewer().set_show_grid(True)

        body.addWidget(self._viewer_panel, 1)

        root.addLayout(body, 1)
        root.addWidget(self._log_panel)

        self._log("后处理测试工具已启动", "info")

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            f"background-color: {BG_PANEL}; border-bottom: 1px solid {BORDER};")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(8)

        lbl_title = QLabel("后处理测试工具")
        lbl_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700;")
        lo.addWidget(lbl_title)

        lo.addSpacing(20)

        btn_open = QPushButton("打开点云文件")
        btn_open.setToolTip("加载一个或多个 PLY/PCD/XYZ 文件")
        ui_icons.apply(btn_open, "folder_open", TEXT_SECONDARY, 15)
        btn_open.clicked.connect(self._on_open_files)
        lo.addWidget(btn_open)

        btn_folder = QPushButton("打开点云文件夹")
        btn_folder.setToolTip("递归加载文件夹内所有点云文件")
        ui_icons.apply(btn_folder, "layers", TEXT_SECONDARY, 15)
        btn_folder.clicked.connect(self._on_open_folder)
        lo.addWidget(btn_folder)

        btn_save = QPushButton("保存当前点云")
        btn_save.setToolTip("保存当前选中的处理后点云")
        ui_icons.apply(btn_save, "save", TEXT_SECONDARY, 15)
        btn_save.clicked.connect(self._on_save_current)
        lo.addWidget(btn_save)

        btn_delete = QPushButton("删除选中")
        btn_delete.setToolTip("删除 DB 树中选中的点云")
        ui_icons.apply(btn_delete, "trash", TEXT_SECONDARY, 15)
        btn_delete.clicked.connect(self._on_delete_selected)
        lo.addWidget(btn_delete)

        lo.addStretch(1)

        # 显示预算控制
        lbl_budget = QLabel("显示预算:")
        lbl_budget.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        lo.addWidget(lbl_budget)
        self._spin_budget = QSpinBox()
        self._spin_budget.setRange(50, 10000)  # 单位：万点
        self._spin_budget.setValue(self._render_budget // 10000)
        self._spin_budget.setSuffix(" 万点")
        self._spin_budget.setToolTip(
            "所有可见点云上传到 GPU 的总点数上限；超过时按比例均匀降采样显示")
        self._spin_budget.valueChanged.connect(self._on_budget_changed)
        lo.addWidget(self._spin_budget)

        btn_clear_log = QPushButton("清空日志")
        ui_icons.apply(btn_clear_log, "trash", TEXT_SECONDARY, 15)
        btn_clear_log.clicked.connect(self._log_panel.clear)
        lo.addWidget(btn_clear_log)

        return bar

    def _build_db_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(f"background-color: {BG_PANEL}; border: none;")
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(10)

        splitter = QSplitter(Qt.Vertical)

        # ---- DB 树 ----
        tree_container = QWidget()
        tree_lo = QVBoxLayout(tree_container)
        tree_lo.setContentsMargins(0, 0, 0, 0)
        tree_lo.setSpacing(6)

        lbl = QLabel("DB 树")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        tree_lo.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        # 选中项红色高亮，去掉虚线焦点框
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: 6px;
                color: {TEXT_PRIMARY};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 4px 2px;
                border: none;
            }}
            QTreeWidget::item:selected {{
                background-color: #d32f2f;
                color: #FFFFFF;
            }}
            QTreeWidget::item:selected:!active {{
                background-color: #b71c1c;
                color: #FFFFFF;
            }}
            QTreeWidget:focus {{ outline: none; }}
        """)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.itemChanged.connect(self._on_tree_item_changed)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        tree_lo.addWidget(self._tree, 1)
        splitter.addWidget(tree_container)

        # ---- 属性页 ----
        prop_container = self._build_property_panel()
        splitter.addWidget(prop_container)
        splitter.setSizes([480, 280])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        lo.addWidget(splitter, 1)
        return panel

    def _build_property_panel(self) -> QWidget:
        """底部属性页：显示/编辑选中点云属性。"""
        panel = QWidget()
        panel.setStyleSheet(f"background-color: {BG_PANEL}; border: none;")
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(6)

        lbl = QLabel("属性")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        lo.addWidget(lbl)

        group = QGroupBox("选中点云")
        group.setStyleSheet(
            f"QGroupBox {{ color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; "
            f"margin-top: 8px; padding-top: 8px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 6px; }}")
        form = QVBoxLayout(group)
        form.setSpacing(8)

        # 名称
        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("名称:"))
        self._prop_name = QLineEdit()
        self._prop_name.setReadOnly(True)
        self._prop_name.setStyleSheet(
            f"QLineEdit {{ background-color: {BG_INPUT}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; padding: 4px; }}")
        row_name.addWidget(self._prop_name, 1)
        form.addLayout(row_name)

        # 点数
        row_pts = QHBoxLayout()
        row_pts.addWidget(QLabel("原始点数:"))
        self._prop_raw_pts = QLabel("-")
        self._prop_raw_pts.setStyleSheet(f"color: {TEXT_MUTED};")
        row_pts.addWidget(self._prop_raw_pts)
        row_pts.addSpacing(12)
        row_pts.addWidget(QLabel("显示点数:"))
        self._prop_disp_pts = QLabel("-")
        self._prop_disp_pts.setStyleSheet(f"color: {TEXT_MUTED};")
        row_pts.addWidget(self._prop_disp_pts)
        row_pts.addStretch(1)
        form.addLayout(row_pts)

        # 可见
        row_vis = QHBoxLayout()
        self._prop_visible = QCheckBox("可见")
        self._prop_visible.stateChanged.connect(self._on_prop_visible_changed)
        row_vis.addWidget(self._prop_visible)
        row_vis.addStretch(1)
        form.addLayout(row_vis)

        # 点大小
        row_size = QHBoxLayout()
        row_size.addWidget(QLabel("点大小:"))
        self._prop_size = QSpinBox()
        self._prop_size.setRange(1, 10)
        self._prop_size.setValue(1)
        self._prop_size.valueChanged.connect(self._on_prop_size_changed)
        row_size.addWidget(self._prop_size)
        row_size.addStretch(1)
        form.addLayout(row_size)

        # 颜色
        row_color = QHBoxLayout()
        row_color.addWidget(QLabel("显示颜色:"))
        self._prop_color = QPushButton()
        self._prop_color.setFixedSize(28, 22)
        self._prop_color.setToolTip("点击选择颜色")
        self._prop_color.clicked.connect(self._on_prop_color_clicked)
        row_color.addWidget(self._prop_color)
        btn_reset_color = QPushButton("恢复默认")
        btn_reset_color.setToolTip("恢复为默认配色")
        btn_reset_color.clicked.connect(self._on_prop_color_reset)
        row_color.addWidget(btn_reset_color)
        row_color.addStretch(1)
        form.addLayout(row_color)

        # 显示包围盒
        row_bbox = QHBoxLayout()
        self._prop_bbox = QCheckBox("显示包围盒")
        self._prop_bbox.setChecked(True)
        self._prop_bbox.stateChanged.connect(self._on_prop_bbox_changed)
        row_bbox.addWidget(self._prop_bbox)
        row_bbox.addStretch(1)
        form.addLayout(row_bbox)

        # 显示旋转中心
        row_pivot = QHBoxLayout()
        self._prop_pivot = QCheckBox("显示旋转中心")
        self._prop_pivot.setChecked(False)
        self._prop_pivot.stateChanged.connect(self._on_prop_pivot_changed)
        row_pivot.addWidget(self._prop_pivot)
        row_pivot.addStretch(1)
        form.addLayout(row_pivot)

        form.addStretch(1)
        lo.addWidget(group)
        return panel

    def _selected_cloud_items(self) -> List[DBTreeItem]:
        """返回当前选中的所有点云节点（若选中文件节点则取其第一个子点云）。"""
        items = []
        for item in self._tree.selectedItems():
            if not isinstance(item, DBTreeItem):
                continue
            if item.pcd is not None:
                items.append(item)
            elif item.childCount() > 0:
                child = item.child(0)
                if isinstance(child, DBTreeItem) and child.pcd is not None:
                    items.append(child)
        return items

    def _update_property_panel(self):
        """根据当前选中项刷新属性页。"""
        items = self._selected_cloud_items()
        if not items:
            self._prop_name.setText("未选择点云")
            self._prop_raw_pts.setText("-")
            self._prop_disp_pts.setText("-")
            self._prop_visible.setChecked(False)
            self._prop_visible.setEnabled(False)
            self._prop_size.setEnabled(False)
            self._prop_color.setEnabled(False)
            self._prop_color.setStyleSheet("background-color: transparent;")
            return

        self._prop_visible.setEnabled(True)
        self._prop_size.setEnabled(True)
        self._prop_color.setEnabled(True)

        if len(items) == 1:
            item = items[0]
            self._prop_name.setText(item.text(0))
            raw_n = len(item.pcd.points) if item.pcd else 0
            disp_n = len(item._display_points) if item._display_points is not None else raw_n
            self._prop_raw_pts.setText(f"{raw_n:,}")
            self._prop_disp_pts.setText(f"{disp_n:,}")
            self._prop_visible.setChecked(item.checkState(0) == Qt.Checked)
            self._prop_size.setValue(item.point_size)
            self._set_color_button(item.color)
        else:
            total_raw = sum(len(it.pcd.points) for it in items if it.pcd)
            total_disp = sum(
                len(it._display_points) if it._display_points is not None
                else (len(it.pcd.points) if it.pcd else 0)
                for it in items
            )
            self._prop_name.setText(f"已选择 {len(items)} 个点云")
            self._prop_raw_pts.setText(f"{total_raw:,}")
            self._prop_disp_pts.setText(f"{total_disp:,}")
            # 可见性：全部勾选才勾选
            all_checked = all(it.checkState(0) == Qt.Checked for it in items)
            self._prop_visible.setChecked(all_checked)
            # 点大小：全部相同才显示，否则清空
            sizes = {it.point_size for it in items}
            self._prop_size.setValue(next(iter(sizes)) if len(sizes) == 1 else 1)
            # 颜色：不显示多选颜色
            self._set_color_button((0.7, 0.7, 0.7))

    def _set_color_button(self, color: tuple):
        qc = _to_qcolor(color)
        self._prop_color.setStyleSheet(
            f"QPushButton {{ background-color: {qc.name()}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; }}"
        )

    def _on_prop_visible_changed(self, state: int):
        items = self._selected_cloud_items()
        checked = state == Qt.Checked
        for item in items:
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        # tree itemChanged 会触发刷新

    def _on_prop_size_changed(self, value: int):
        items = self._selected_cloud_items()
        if not items:
            return
        for item in items:
            item.point_size = value
            key = item.file_key or item.text(0)
            self._viewer_cloud_keys.discard(key)
        self._rebuild_display_caches()
        self._refresh_viewer()

    def _on_prop_color_clicked(self):
        items = self._selected_cloud_items()
        if not items:
            return
        init_color = _to_qcolor(items[0].color)
        color = QColorDialog.getColor(init_color, self, "选择点云颜色")
        if not color.isValid():
            return
        rgb = (color.redF(), color.greenF(), color.blueF())
        for item in items:
            item.color = rgb
            key = item.file_key or item.text(0)
            self._viewer_cloud_keys.discard(key)
        self._rebuild_display_caches()
        self._refresh_viewer()
        self._update_property_panel()

    def _on_prop_color_reset(self):
        items = self._selected_cloud_items()
        if not items:
            return
        # 根据文件在树中的索引恢复默认配色
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if child in items:
                    child.color = self._color_for_index(i)
                    key = child.file_key or child.text(0)
                    self._viewer_cloud_keys.discard(key)
        self._rebuild_display_caches()
        self._refresh_viewer()
        self._update_property_panel()

    def _on_prop_bbox_changed(self, state: int):
        self._update_selection_bbox()

    def _on_prop_pivot_changed(self, state: int):
        visible = state == Qt.Checked
        gl_viewer = self._viewer_panel.viewer()
        gl_viewer.set_pivot_visible(visible)
        if visible:
            gl_viewer.viewer().set_pivot_position(gl_viewer.viewer().camera.target)

    def _update_selection_bbox(self):
        """根据 DB 树选中项更新 3D 视图中的包围盒线框。"""
        gl_viewer = self._viewer_panel.viewer()
        if not self._prop_bbox.isChecked():
            gl_viewer.set_selection_bbox([])
            return
        items = self._selected_cloud_items()
        bounds = []
        for item in items:
            if item.pcd is None or len(item.pcd.points) == 0:
                continue
            pts = np.asarray(item.pcd.points)
            mask = np.isfinite(pts).all(axis=1)
            if not mask.any():
                continue
            pts = pts[mask]
            bounds.append((pts.min(axis=0).tolist(), pts.max(axis=0).tolist()))
        gl_viewer.set_selection_bbox(bounds)

    # ------------------------------------------------------------------ 视图控制
    def _on_view_preset(self, preset: str):
        self._viewer_panel.viewer().set_view_preset(preset)

    def _on_reset_view(self):
        self._viewer_panel.viewer().reset_view()

    def _on_view_axes_changed(self, state: int):
        self._viewer_panel.viewer().set_show_axes(state == Qt.Checked)

    def _on_view_grid_changed(self, state: int):
        self._viewer_panel.viewer().set_show_grid(state == Qt.Checked)

    def _on_view_bg_changed(self, state: int):
        self._viewer_panel.viewer().set_background(dark=state == Qt.Checked)

    # ------------------------------------------------------------------ ROI
    def _on_roi_start(self):
        checked = self._btn_roi_start.isChecked()
        self._viewer_panel.viewer().set_roi_mode(checked)
        if checked:
            self._lbl_roi_status.setText("ROI 模式：在 3D 视图中按住左键拖拽框选")
            self._start_roi_timer()
        else:
            self._lbl_roi_status.setText("未框选")
            self._stop_roi_timer()

    def _on_roi_cancel(self):
        self._viewer_panel.viewer().clear_roi_selection()
        self._btn_roi_start.setChecked(False)
        self._lbl_roi_status.setText("未框选")
        self._btn_segment_in.setEnabled(False)
        self._btn_segment_out.setEnabled(False)
        self._stop_roi_timer()

    def _start_roi_timer(self):
        from PySide6.QtCore import QTimer
        self._roi_timer = QTimer(self)
        self._roi_timer.timeout.connect(self._check_roi_selection)
        self._roi_timer.start(200)

    def _stop_roi_timer(self):
        if getattr(self, "_roi_timer", None) is not None:
            self._roi_timer.stop()
            self._roi_timer = None

    def _check_roi_selection(self):
        selection = self._viewer_panel.viewer().get_roi_selection()
        total = sum(len(v) for v in selection.values())
        if total > 0:
            self._lbl_roi_status.setText(f"已选中 {total:,} 个点")
            self._btn_segment_in.setEnabled(True)
            self._btn_segment_out.setEnabled(True)
        else:
            self._lbl_roi_status.setText("ROI 模式：在 3D 视图中按住左键拖拽框选")
            self._btn_segment_in.setEnabled(False)
            self._btn_segment_out.setEnabled(False)

    def _on_segment_in(self):
        self._apply_roi_segment(True)

    def _on_segment_out(self):
        self._apply_roi_segment(False)

    def _apply_roi_segment(self, segment_in: bool):
        selection = self._viewer_panel.viewer().get_roi_selection()
        if not selection:
            self._log("ROI 未选中任何点", "warn")
            return
        created = []
        for cloud_id, indices in selection.items():
            item = self._find_item_by_key(cloud_id)
            if item is None or item.pcd is None:
                continue
            pcd = item.pcd
            pts = np.asarray(pcd.points)
            if len(pts) == 0:
                continue
            # 将显示级索引映射回原始点云索引
            step = getattr(item, "_display_step", 1)
            orig_indices = (indices.astype(np.int64) * step)
            orig_indices = np.clip(orig_indices, 0, len(pts) - 1)
            mask = np.zeros(len(pts), dtype=bool)
            mask[orig_indices] = True
            if not segment_in:
                mask = ~mask
            if not mask.any():
                continue
            new_pcd = o3d.geometry.PointCloud()
            new_pcd.points = o3d.utility.Vector3dVector(pts[mask])
            if pcd.has_colors():
                cols = np.asarray(pcd.colors)
                new_pcd.colors = o3d.utility.Vector3dVector(cols[mask])
            if pcd.has_normals():
                norms = np.asarray(pcd.normals)
                new_pcd.normals = o3d.utility.Vector3dVector(norms[mask])
            suffix = "_in" if segment_in else "_out"
            base = item.file_key or item.text(0)
            new_name = f"{base}{suffix}"
            # 重名处理
            counter = 1
            unique_name = new_name
            while unique_name in self._loaded_pcds:
                counter += 1
                unique_name = f"{new_name}_{counter}"
            self._add_pcd_to_tree(unique_name, new_pcd, parent_key=base)
            created.append(unique_name)
        self._viewer_panel.viewer().clear_roi_selection()
        self._btn_roi_start.setChecked(False)
        self._lbl_roi_status.setText(f"已生成：{', '.join(created)}")
        self._btn_segment_in.setEnabled(False)
        self._btn_segment_out.setEnabled(False)
        self._stop_roi_timer()
        self._log(f"ROI {'保留' if segment_in else '剔除'} 结果：{', '.join(created)}", "success")

    def _find_item_by_key(self, key: str):
        """根据 file_key 找到 DB 树中对应的点云节点。"""
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            if getattr(file_item, "file_key", None) == key:
                if file_item.childCount() > 0:
                    child = file_item.child(0)
                    if isinstance(child, DBTreeItem):
                        return child
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if isinstance(child, DBTreeItem) and getattr(child, "file_key", None) == key:
                    return child
        return None

    def _add_pcd_to_tree(self, name: str, pcd: o3d.geometry.PointCloud,
                         parent_key: Optional[str] = None):
        """将点云加入 DB 树并刷新显示。"""
        self._loaded_pcds[name] = pcd
        # 若指定父节点则作为子节点插入，否则作为新文件节点
        parent_item = None
        if parent_key is not None:
            for i in range(self._tree.topLevelItemCount()):
                fi = self._tree.topLevelItem(i)
                if getattr(fi, "file_key", None) == parent_key:
                    parent_item = fi
                    break
        color = self._color_for_index(self._tree.topLevelItemCount())
        if parent_item is not None:
            cloud_item = DBTreeItem(name, pcd=pcd, parent=parent_item)
            cloud_item.file_key = name
            cloud_item.color = color
            parent_item.setExpanded(True)
        else:
            file_item = DBTreeItem(name, pcd=None)
            file_item.file_key = name
            file_item.color = color
            cloud_item = DBTreeItem(f"{name} - Cloud", pcd=pcd, parent=file_item)
            cloud_item.file_key = name
            cloud_item.color = color
            file_item.setExpanded(True)
            self._tree.addTopLevelItem(file_item)
        self._cache_render_arrays(cloud_item)
        self._rebuild_display_caches()
        self._refresh_viewer()

    def _build_process_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(f"background-color: {BG_PANEL}; border: none;")
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(12)

        lbl = QLabel("后处理")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        lo.addWidget(lbl)

        # 视图控制
        view_group = QGroupBox("视图")
        view_group.setStyleSheet(
            f"QGroupBox {{ color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; "
            f"margin-top: 8px; padding-top: 8px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 6px; }}")
        view_lo = QVBoxLayout(view_group)
        row_presets = QHBoxLayout()
        for text, preset in (("顶", "top"), ("前", "front"),
                             ("侧", "side"), ("等轴", "iso")):
            btn = QPushButton(text)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _=False, p=preset: self._on_view_preset(p))
            row_presets.addWidget(btn)
        btn_reset = QPushButton("重置")
        btn_reset.setFixedHeight(28)
        btn_reset.clicked.connect(self._on_reset_view)
        row_presets.addWidget(btn_reset)
        view_lo.addLayout(row_presets)
        row_toggles = QHBoxLayout()
        self._chk_axes = QCheckBox("坐标轴")
        self._chk_axes.setChecked(False)
        self._chk_axes.stateChanged.connect(self._on_view_axes_changed)
        row_toggles.addWidget(self._chk_axes)
        self._chk_grid = QCheckBox("网格")
        self._chk_grid.setChecked(True)
        self._chk_grid.stateChanged.connect(self._on_view_grid_changed)
        row_toggles.addWidget(self._chk_grid)
        self._chk_bg = QCheckBox("深色背景")
        self._chk_bg.setChecked(True)
        self._chk_bg.stateChanged.connect(self._on_view_bg_changed)
        row_toggles.addWidget(self._chk_bg)
        view_lo.addLayout(row_toggles)
        lo.addWidget(view_group)

        # ROI 裁剪
        roi_group = QGroupBox("ROI 裁剪")
        roi_group.setStyleSheet(view_group.styleSheet())
        roi_lo = QVBoxLayout(roi_group)
        self._btn_roi_start = QPushButton("开始框选")
        self._btn_roi_start.setCheckable(True)
        self._btn_roi_start.setToolTip("在 3D 视图中拖拽矩形选择区域")
        self._btn_roi_start.clicked.connect(self._on_roi_start)
        roi_lo.addWidget(self._btn_roi_start)
        self._lbl_roi_status = QLabel("未框选")
        self._lbl_roi_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._lbl_roi_status.setWordWrap(True)
        roi_lo.addWidget(self._lbl_roi_status)
        row_roi = QHBoxLayout()
        self._btn_segment_in = QPushButton("保留选中")
        self._btn_segment_in.setToolTip("将框选区域内的点保存为新点云")
        self._btn_segment_in.setEnabled(False)
        self._btn_segment_in.clicked.connect(self._on_segment_in)
        row_roi.addWidget(self._btn_segment_in)
        self._btn_segment_out = QPushButton("剔除选中")
        self._btn_segment_out.setToolTip("将框选区域外的点保存为新点云")
        self._btn_segment_out.setEnabled(False)
        self._btn_segment_out.clicked.connect(self._on_segment_out)
        row_roi.addWidget(self._btn_segment_out)
        roi_lo.addLayout(row_roi)
        btn_roi_cancel = QPushButton("取消")
        btn_roi_cancel.clicked.connect(self._on_roi_cancel)
        roi_lo.addWidget(btn_roi_cancel)
        lo.addWidget(roi_group)

        # 当前选中信息
        info_group = QGroupBox("当前选中")
        info_group.setStyleSheet(
            f"QGroupBox {{ color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; "
            f"margin-top: 8px; padding-top: 8px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 6px; }}")
        info_lo = QVBoxLayout(info_group)
        self._lbl_info = QLabel("未选择点云")
        self._lbl_info.setWordWrap(True)
        self._lbl_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        info_lo.addWidget(self._lbl_info)
        lo.addWidget(info_group)

        # 体素下采样
        voxel_group = QGroupBox("体素下采样")
        voxel_group.setStyleSheet(info_group.styleSheet())
        voxel_lo = QVBoxLayout(voxel_group)
        chk_down = QCheckBox("启用下采样")
        chk_down.setChecked(self._processor.enable_voxel_downsample)
        chk_down.stateChanged.connect(
            lambda s: setattr(self._processor, "enable_voxel_downsample", s == Qt.Checked))
        voxel_lo.addWidget(chk_down)
        row_voxel = QHBoxLayout()
        row_voxel.addWidget(QLabel("体素大小(mm):"))
        spin_voxel = QSpinBox()
        spin_voxel.setRange(1, 50)
        spin_voxel.setValue(int(self._processor.voxel_size))
        spin_voxel.valueChanged.connect(
            lambda v: setattr(self._processor, "voxel_size", float(v)))
        row_voxel.addWidget(spin_voxel)
        voxel_lo.addLayout(row_voxel)
        lo.addWidget(voxel_group)

        # 离群点去除
        outlier_group = QGroupBox("统计离群点去除")
        outlier_group.setStyleSheet(info_group.styleSheet())
        outlier_lo = QVBoxLayout(outlier_group)
        chk_out = QCheckBox("启用离群点去除")
        chk_out.setChecked(self._processor.enable_outlier_removal)
        chk_out.stateChanged.connect(
            lambda s: setattr(self._processor, "enable_outlier_removal", s == Qt.Checked))
        outlier_lo.addWidget(chk_out)
        row_nb = QHBoxLayout()
        row_nb.addWidget(QLabel("邻域点数:"))
        spin_nb = QSpinBox()
        spin_nb.setRange(2, 100)
        spin_nb.setValue(self._processor.outlier_nb_neighbors)
        spin_nb.valueChanged.connect(
            lambda v: setattr(self._processor, "outlier_nb_neighbors", v))
        row_nb.addWidget(spin_nb)
        outlier_lo.addLayout(row_nb)
        row_std = QHBoxLayout()
        row_std.addWidget(QLabel("标准差倍数:"))
        spin_std = QSpinBox()
        spin_std.setRange(1, 10)
        spin_std.setValue(int(self._processor.outlier_std_ratio))
        spin_std.valueChanged.connect(
            lambda v: setattr(self._processor, "outlier_std_ratio", float(v)))
        row_std.addWidget(spin_std)
        outlier_lo.addLayout(row_std)
        lo.addWidget(outlier_group)

        # 裁切
        crop_group = QGroupBox("裁切")
        crop_group.setStyleSheet(info_group.styleSheet())
        crop_lo = QVBoxLayout(crop_group)
        self._combo_crop = QComboBox()
        self._combo_crop.addItem("不裁切", "none")
        self._combo_crop.addItem("AABB 中心比例", "aabb")
        self._combo_crop.addItem("中心球", "sphere")
        self._combo_crop.addItem("OBB 主轴", "obb")
        self._combo_crop.currentIndexChanged.connect(self._on_crop_mode_changed)
        crop_lo.addWidget(self._combo_crop)
        row_ratio = QHBoxLayout()
        row_ratio.addWidget(QLabel("比例/半径:"))
        self._line_crop_param = QLineEdit(str(self._processor.crop_ratio))
        self._line_crop_param.setPlaceholderText("AABB/OBB 填 0~1；球填半径 mm")
        row_ratio.addWidget(self._line_crop_param)
        crop_lo.addLayout(row_ratio)

        self._chk_crop_preview = QCheckBox("预览裁切范围")
        self._chk_crop_preview.setToolTip("在 3D 视图中以红色线框显示当前裁切范围")
        self._chk_crop_preview.stateChanged.connect(
            lambda s: self._refresh_viewer() if s == Qt.Checked else self._refresh_viewer())
        crop_lo.addWidget(self._chk_crop_preview)

        lo.addWidget(crop_group)

        btn_apply = QPushButton("应用到当前选中")
        btn_apply.setObjectName("primary")
        btn_apply.setMinimumHeight(36)
        btn_apply.clicked.connect(self._on_apply_process)
        lo.addWidget(btn_apply)

        btn_reset = QPushButton("重置为原始点云")
        btn_reset.clicked.connect(self._on_reset_current)
        lo.addWidget(btn_reset)

        lo.addStretch(1)
        return panel

    # ------------------------------------------------------------------ 事件
    @staticmethod
    def _color_for_index(idx: int):
        return COLOR_PALETTE[idx % len(COLOR_PALETTE)]

    def _cache_render_arrays(self, item: DBTreeItem):
        """从点云对象生成原始渲染缓存（完整分辨率，用于后处理/保存）。"""
        pcd = item.pcd
        if pcd is None or len(pcd.points) == 0:
            item._render_points = None
            item._render_colors = None
            item._display_points = None
            item._display_colors = None
            return
        points = np.asarray(pcd.points, dtype=np.float32)
        if pcd.has_colors():
            colors = np.asarray(pcd.colors, dtype=np.float32)
            if colors.size and colors.max() > 1.0:
                colors = colors / 255.0
        else:
            colors = np.tile(np.array(item.color, dtype=np.float32), (len(points), 1))
        item._render_points = points
        item._render_colors = colors
        # 显示副本会在 _rebuild_display_caches 中按需生成
        item._display_points = None
        item._display_colors = None

    def _rebuild_display_caches(self):
        """按当前显示预算为所有可见点云生成显示级降采样副本。"""
        try:
            self._do_rebuild_display_caches()
        except Exception as e:
            self._log(f"重建显示缓存失败：{e}", "error")
            import traceback
            traceback.print_exc()

    def _do_rebuild_display_caches(self):
        """_rebuild_display_caches 的实际实现。"""
        visible_items = []
        total_raw = 0
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            if file_item.checkState(0) != Qt.Checked:
                continue
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if not isinstance(child, DBTreeItem):
                    continue
                if child.checkState(0) == Qt.Checked and child.pcd is not None:
                    if child._render_points is None:
                        self._cache_render_arrays(child)
                    if child._render_points is not None:
                        visible_items.append(child)
                        total_raw += len(child._render_points)

        # 非可见点云清空显示缓存以释放内存
        visible_set = {id(it) for it in visible_items}
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if isinstance(child, DBTreeItem) and id(child) not in visible_set:
                    child._display_points = None
                    child._display_colors = None

        if total_raw <= self._render_budget or not visible_items:
            for item in visible_items:
                item._display_points = item._render_points.copy()
                item._display_colors = item._render_colors.copy()
                item._display_step = 1
            return

        # 按比例分配预算，每朵云至少保留 1% 预算（避免小点云消失）
        min_pts = max(1000, self._render_budget // (len(visible_items) * 100))
        for item in visible_items:
            n = len(item._render_points)
            target = max(min_pts, int(self._render_budget * n / total_raw))
            if target >= n:
                item._display_points = item._render_points.copy()
                item._display_colors = item._render_colors.copy()
                item._display_step = 1
            else:
                k = max(1, int(np.ceil(n / target)))
                idx = np.arange(0, n, k)
                item._display_points = item._render_points[idx].copy()
                item._display_colors = item._render_colors[idx].copy()
                item._display_step = k

    def _on_budget_changed(self, value: int):
        """显示预算改变时重新生成显示副本并刷新。"""
        self._render_budget = value * 10000
        self._log(f"显示预算调整为 {self._render_budget:,} 点", "info")
        self._rebuild_display_caches()
        self._refresh_viewer()

    def _on_crop_mode_changed(self, idx: int):
        mode = self._combo_crop.itemData(idx)
        self._processor.crop_mode = mode
        if mode == "sphere":
            self._line_crop_param.setText(str(self._processor.crop_radius))
        else:
            self._line_crop_param.setText(str(self._processor.crop_ratio))
        if self._chk_crop_preview.isChecked():
            self._rebuild_display_caches()
            self._refresh_viewer()

    def _on_open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择点云文件", "",
            "点云文件 (*.ply *.pcd *.xyz);;所有文件 (*)")
        if not files:
            return
        self._run_load_worker(files)

    def _on_open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择点云文件夹")
        if not folder:
            return
        files = []
        for ext in (".ply", ".pcd", ".xyz"):
            files.extend([str(p) for p in Path(folder).glob(f"*{ext}")])
        if not files:
            self._log("文件夹中没有找到点云文件", "warn")
            return
        self._run_load_worker(files)

    def _run_load_worker(self, files: list):
        """启动后台加载线程并显示进度对话框。"""
        if not files:
            return
        self._load_count_before = len(self._loaded_pcds)
        self._batch_loading = True
        self._tree.blockSignals(True)

        self._progress = QProgressDialog("正在加载点云...", None, 0, len(files), self)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setCancelButton(None)
        self._progress.setValue(0)
        self._progress.show()

        self._worker = LoadPointCloudWorker(files, self)
        self._worker.progress.connect(self._on_load_progress)
        self._worker.loaded.connect(self._on_file_loaded)
        self._worker.error.connect(self._on_load_error)
        self._worker.finished.connect(self._on_load_finished)
        self._worker.start()

    def _on_load_progress(self, current: int, total: int, filename: str):
        if getattr(self, "_progress", None) is not None:
            self._progress.setMaximum(total)
            self._progress.setValue(current)
            self._progress.setLabelText(f"正在加载: {Path(filename).name}")

    def _on_file_loaded(self, data: dict):
        path = data["path"]
        pcd = data["pcd"]
        self._load_file(path, pcd=pcd)
        if getattr(self, "_progress", None) is not None:
            self._progress.setValue(self._progress.value() + 1)

    def _on_load_error(self, msg: str):
        self._log(msg, "error")

    def _on_load_finished(self):
        if getattr(self, "_progress", None) is not None:
            self._progress.close()
            self._progress = None
        self._tree.blockSignals(False)
        self._batch_loading = False
        loaded = len(self._loaded_pcds) - getattr(self, "_load_count_before", 0)
        self._log(f"批量加载完成，新增 {loaded} 个点云", "success")
        # 延迟刷新：等进度对话框关闭、事件循环清空后再重建/渲染，
        # 避免在模态对话框状态尚未完全释放时访问 GL 上下文
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._finalize_batch_load)

    def _finalize_batch_load(self):
        """批量加载完成后在主线程事件循环下一轮重建显示缓存并刷新 3D 视图。"""
        try:
            self._rebuild_display_caches()
            self._refresh_viewer()
        except Exception as e:
            self._log(f"批量加载后刷新视图失败：{e}", "error")
            import traceback
            traceback.print_exc()

    def _load_file(self, path: str,
                   pcd: Optional[o3d.geometry.PointCloud] = None):
        try:
            if pcd is None:
                pcd = o3d.io.read_point_cloud(path)
            n_points = len(pcd.points)
            if n_points == 0:
                self._log(f"文件为空或无法解析：{path}", "warn")
                if not self._batch_loading:
                    QMessageBox.warning(self, "加载失败", f"文件为空或无法解析：\n{path}")
                return

            name = Path(path).name
            base = name
            suffix = 1
            while base in self._loaded_pcds:
                suffix += 1
                base = f"{name}_{suffix}"
            self._loaded_pcds[base] = pcd

            color = self._color_for_index(self._tree.topLevelItemCount())
            file_item = DBTreeItem(base, pcd=None)
            file_item.file_key = base
            file_item.color = color
            cloud_item = DBTreeItem(f"{base} - Cloud", pcd=pcd, parent=file_item)
            cloud_item.file_key = base
            cloud_item.color = color
            self._cache_render_arrays(cloud_item)
            file_item.setExpanded(True)
            self._tree.addTopLevelItem(file_item)

            self._log(
                f"加载 {base}：原始点数 {n_points:,}，路径 {path}", "info")
            if not self._batch_loading:
                self._rebuild_display_caches()
                self._refresh_viewer()
        except Exception as e:
            self._log(f"加载失败 {path}：{e}", "error")
            if not self._batch_loading:
                QMessageBox.critical(self, "加载失败", f"无法加载 {path}：\n{e}")

    def _on_tree_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {BG_CARD}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; padding: 4px; }}"
            f"QMenu::item:selected {{ background-color: {ACCENT}; }}"
            f"QMenu::item {{ padding: 6px 16px; }}"
        )
        act = QAction("删除选中点云", self)
        act.triggered.connect(self._on_delete_selected)
        menu.addAction(act)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_delete_selected(self):
        items = self._tree.selectedItems()
        if not items:
            self._log("请先选择要删除的点云", "warn")
            QMessageBox.information(self, "提示", "请先在 DB 树中选择要删除的点云。")
            return
        removed_names = []
        for item in items:
            if not isinstance(item, DBTreeItem):
                continue
            # 统一以父节点（文件）为删除单位
            file_item = item if item.parent() is None else item.parent()
            key = getattr(file_item, "file_key", file_item.text(0))
            if key in self._loaded_pcds:
                self._loaded_pcds.pop(key, None)
            if self._current_item is not None:
                cur_key = getattr(self._current_item, "file_key", None)
                if cur_key == key:
                    self._current_item = None
            idx = self._tree.indexOfTopLevelItem(file_item)
            if idx >= 0:
                removed_names.append(file_item.text(0))
                self._tree.takeTopLevelItem(idx)
        if removed_names:
            self._log(f"已删除点云：{', '.join(removed_names)}", "info")
            self._rebuild_display_caches()
            self._refresh_viewer()
            self._on_tree_selection_changed()

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0:
            return
        self._update_property_panel()
        self._rebuild_display_caches()
        self._refresh_viewer()

    def _on_tree_selection_changed(self):
        self._update_property_panel()
        self._update_selection_bbox()
        selected = self._tree.selectedItems()
        if not selected:
            self._current_item = None
            self._lbl_info.setText("未选择点云")
            if self._chk_crop_preview.isChecked():
                self._rebuild_display_caches()
                self._refresh_viewer()
            return
        item = selected[0]
        if isinstance(item, DBTreeItem) and item.pcd is not None:
            cloud_item = item
        elif isinstance(item, DBTreeItem) and item.childCount() > 0:
            cloud_item = item.child(0)
            if not isinstance(cloud_item, DBTreeItem) or cloud_item.pcd is None:
                self._current_item = None
                self._lbl_info.setText("未选择点云")
                return
        else:
            self._current_item = None
            self._lbl_info.setText("未选择点云")
            return
        self._current_item = cloud_item
        pcd = cloud_item.pcd
        raw_n = len(pcd.points)
        disp_n = len(cloud_item._display_points) if cloud_item._display_points is not None else raw_n
        info = (
            f"名称: {cloud_item.text(0)}\n"
            f"原始点数: {raw_n:,}\n"
            f"显示点数: {disp_n:,}"
        )
        self._lbl_info.setText(info)
        self._log(f"选中 {cloud_item.text(0)}，原始 {raw_n:,} / 显示 {disp_n:,} 点", "info")
        if self._chk_crop_preview.isChecked():
            self._rebuild_display_caches()
            self._refresh_viewer()

    @staticmethod
    def _bbox_info(pcd: o3d.geometry.PointCloud) -> str:
        pts = np.asarray(pcd.points)
        if len(pts) == 0:
            return "范围: —"
        mins = pts.min(axis=0)
        maxs = pts.max(axis=0)
        return (
            f"范围:\n"
            f"  X[{mins[0]:.1f}, {maxs[0]:.1f}]\n"
            f"  Y[{mins[1]:.1f}, {maxs[1]:.1f}]\n"
            f"  Z[{mins[2]:.1f}, {maxs[2]:.1f}]"
        )

    def _crop_preview_arrays(self, item: DBTreeItem):
        """生成当前裁切范围的红色线框点云，用于 3D 预览。"""
        if item is None or self._processor.crop_mode == "none":
            return None, None
        pcd = item.original_pcd if item.original_pcd is not None else item.pcd
        if pcd is None or len(pcd.points) == 0:
            return None, None
        bbox = self._processor.get_crop_bbox(pcd)
        if bbox is None:
            return None, None
        try:
            if isinstance(bbox, o3d.geometry.OrientedBoundingBox):
                ls = o3d.geometry.LineSet.create_from_oriented_bounding_box(bbox)
            else:
                ls = o3d.geometry.LineSet.create_from_axis_aligned_bounding_box(bbox)
        except Exception:
            return None, None
        lines = np.asarray(ls.lines)
        pts = np.asarray(ls.points, dtype=np.float32)
        if len(lines) == 0 or len(pts) == 0:
            return None, None
        edge_points = []
        for i, j in lines:
            edge_points.append(np.linspace(pts[i], pts[j], 50))
        preview_pts = np.concatenate(edge_points, axis=0)
        preview_colors = np.tile(
            np.array([[1.0, 0.2, 0.2]], dtype=np.float32), (len(preview_pts), 1))
        return preview_pts, preview_colors

    def _refresh_viewer(self):
        """根据 DB 树勾选状态刷新 3D 视图（多 VBO 缓存，避免重复上传）。"""
        try:
            self._do_refresh_viewer()
        except Exception as e:
            self._log(f"刷新 3D 视图失败：{e}", "error")
            import traceback
            traceback.print_exc()

    def _do_refresh_viewer(self):
        """_refresh_viewer 的实际实现。"""
        gl_viewer = self._viewer_panel.viewer().viewer()
        if gl_viewer is None:
            return

        # 清理遗留单路点云，避免多路与单路同时绘制
        gl_viewer.clear()

        visible_keys = set()
        visible_items = []
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            if file_item.checkState(0) != Qt.Checked:
                continue
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if not isinstance(child, DBTreeItem):
                    continue
                if child.checkState(0) == Qt.Checked and child.pcd is not None:
                    key = child.file_key or child.text(0)
                    visible_keys.add(key)
                    visible_items.append((key, child))

        # 上传新可见点云，已缓存的仅切换可见性
        for key, item in visible_items:
            pts = item._display_points
            cols = item._display_colors
            if pts is None or cols is None:
                continue
            if key not in self._viewer_cloud_keys:
                gl_viewer.set_pointcloud(
                    key, pts, cols, visible=True, point_size=item.point_size)
                self._viewer_cloud_keys.add(key)
            else:
                gl_viewer.set_pointcloud_visible(key, True)

        # 取消勾选：隐藏但保留 VBO
        for key in self._viewer_cloud_keys:
            if key not in visible_keys and key != "__crop_preview__":
                gl_viewer.set_pointcloud_visible(key, False)

        # 从 DB 树删除后彻底移除 VBO
        loaded_keys = set(self._loaded_pcds.keys())
        for key in list(self._viewer_cloud_keys):
            if key not in loaded_keys and key != "__crop_preview__":
                gl_viewer.set_pointcloud(key, None)
                self._viewer_cloud_keys.discard(key)

        # 裁切范围预览（特殊 cloud id）
        if self._chk_crop_preview.isChecked() and self._current_item is not None:
            preview_pts, preview_cols = self._crop_preview_arrays(self._current_item)
            if preview_pts is not None:
                gl_viewer.set_pointcloud("__crop_preview__", preview_pts, preview_cols, visible=True)
                self._viewer_cloud_keys.add("__crop_preview__")
            else:
                if "__crop_preview__" in self._viewer_cloud_keys:
                    gl_viewer.set_pointcloud("__crop_preview__", None)
                    self._viewer_cloud_keys.discard("__crop_preview__")
        else:
            if "__crop_preview__" in self._viewer_cloud_keys:
                gl_viewer.set_pointcloud("__crop_preview__", None)
                self._viewer_cloud_keys.discard("__crop_preview__")

        # 刷新叠加层文字
        visible_data_keys = visible_keys - {"__crop_preview__"}
        if not visible_data_keys:
            gl_viewer.set_overlay_text("未加载点云")
        else:
            total = 0
            for key in visible_data_keys:
                cloud = gl_viewer._clouds.get(key)
                if cloud is not None:
                    total += cloud["point_count"]
            gl_viewer.set_overlay_text(
                f"可见点云 {len(visible_data_keys)} 个 | 显示总点数 {total:,}"
                f" / 预算 {self._render_budget:,}")

    def _on_apply_process(self):
        if self._current_item is None or self._current_item.pcd is None:
            self._log("请先选择要点云对象", "warn")
            QMessageBox.information(self, "提示", "请先在 DB 树中选择一个点云对象。")
            return
        try:
            value = float(self._line_crop_param.text())
            if self._processor.crop_mode == "sphere":
                self._processor.crop_radius = value
            else:
                self._processor.crop_ratio = value

            self._log(
                f"开始对 {self._current_item.text(0)} 执行后处理："
                f"下采样={self._processor.enable_voxel_downsample}, "
                f"去噪={self._processor.enable_outlier_removal}, "
                f"裁切={self._processor.crop_mode}",
                "info")

            result, stats = self._processor.process(self._current_item.pcd)
            self._current_item.pcd = result
            self._cache_render_arrays(self._current_item)
            key = self._current_item.file_key or self._current_item.text(0)
            self._viewer_cloud_keys.discard(key)
            self._rebuild_display_caches()
            self._refresh_viewer()

            stats_text = " | ".join(
                f"{k}: {v:,}" if isinstance(v, int) else f"{k}: {v}"
                for k, v in stats.items())
            self._log(f"后处理完成：{stats_text}", "success")
            QMessageBox.information(self, "处理完成", f"处理结果统计：\n{stats_text}")
        except Exception as e:
            self._log(f"后处理失败：{e}", "error")
            QMessageBox.critical(self, "处理失败", f"后处理出错：\n{e}")

    def _on_reset_current(self):
        if self._current_item is None:
            return
        if self._current_item.original_pcd is not None:
            self._current_item.pcd = self._current_item.original_pcd
            self._cache_render_arrays(self._current_item)
            key = self._current_item.file_key or self._current_item.text(0)
            self._viewer_cloud_keys.discard(key)
            self._rebuild_display_caches()
            self._refresh_viewer()
            self._log(f"已重置 {self._current_item.text(0)} 为原始点云", "info")
            QMessageBox.information(self, "提示", "已重置为原始点云。")

    def _on_save_current(self):
        if self._current_item is None or self._current_item.pcd is None:
            self._log("保存失败：未选择点云", "warn")
            QMessageBox.information(self, "提示", "请先在 DB 树中选择一个点云对象。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存点云", "processed.ply",
            "PLY 文件 (*.ply);;PCD 文件 (*.pcd)")
        if not path:
            return
        try:
            o3d.io.write_point_cloud(path, self._current_item.pcd)
            self._log(f"已保存当前点云到 {path}", "success")
            QMessageBox.information(self, "保存成功", f"已保存至：\n{path}")
        except Exception as e:
            self._log(f"保存失败：{e}", "error")
            QMessageBox.critical(self, "保存失败", f"无法保存：\n{e}")

    def _log(self, message: str, level: str = "info"):
        """输出到内置日志栏。"""
        self._log_panel.append(message, level)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    win = PostProcessTestWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
