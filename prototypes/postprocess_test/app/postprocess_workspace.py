# -*- coding: utf-8 -*-
"""
后处理工作区（PostprocessWorkspace）—— 基于 ui_v2 风格。

布局参考 CloudCompare：
  - 左侧：DB 树（点云列表 + 分支）；
  - 中间：3D 点云查看器（ViewerPanel）；
  - 右侧：后处理参数面板（裁剪 / 去噪 / 下采样 / ICP / 合并）；
  - 底部：日志栏。

设计目标：
  - 信号/接口与 src/ui_v2/workspaces/ 现有工作区对齐；
  - 业务逻辑全部走 PostprocessWorkflow，UI 不直接操作 open3d；
  - 后期可整体迁入 src/ui_v2/workspaces/postprocess_workspace.py。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import open3d as o3d

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

# 让原型能引用 src/ 下的模块和本原型 core
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_APP_DIR)))
if os.path.join(_PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
if os.path.join(os.path.dirname(_APP_DIR), "core") not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(_APP_DIR), "core"))

from core.utils import logger
from ui_v2.theme import (
    ACCENT, BG_CARD, BG_INPUT, BG_PANEL, BG_WINDOW, BORDER,
    STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_MUTED, TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from ui_v2 import icons as ui_icons
from ui_v2.widgets import LogPanel, ViewerPanel

from postprocess_workflow import CloudNode, ICPResult, PostprocessWorkflow


# DB 树默认配色
COLOR_PALETTE = [
    (0.20, 0.80, 1.00),
    (1.00, 0.60, 0.20),
    (0.40, 1.00, 0.40),
    (1.00, 0.40, 0.70),
    (1.00, 1.00, 0.30),
    (0.70, 0.50, 1.00),
    (0.40, 0.90, 0.80),
    (0.95, 0.50, 0.50),
]


def _to_qcolor(color: Tuple[float, float, float]) -> QColor:
    r = max(0, min(255, int(color[0] * 255)))
    g = max(0, min(255, int(color[1] * 255)))
    b = max(0, min(255, int(color[2] * 255)))
    return QColor(r, g, b)


class CloudTreeItem(QTreeWidgetItem):
    """DB 树点云节点（文件节点的子节点）：携带点云对象与显示缓存。"""

    def __init__(self, node_id: str, name: str, pcd=None,
                 parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.pcd = pcd
        self.original_pcd = pcd
        self.color = (0.7, 0.7, 0.7)
        self.point_size = 1
        # 原始渲染缓存（用于后处理/保存）
        self._render_points: Optional[np.ndarray] = None
        self._render_colors: Optional[np.ndarray] = None
        # 显示级降采样缓存（上传 GPU）
        self._display_points: Optional[np.ndarray] = None
        self._display_colors: Optional[np.ndarray] = None
        self._display_step: int = 1
        # 精确映射：每个显示点对应的原始点云索引（ROI 选择时使用）
        self._display_to_orig_indices: Optional[np.ndarray] = None
        self.setText(0, name)
        self.setFlags(self.flags() | Qt.ItemIsUserCheckable)
        self.setCheckState(0, Qt.Checked)


class FileTreeItem(QTreeWidgetItem):
    """DB 树文件节点：表示一个加载的文件，可包含多个点云子节点。"""

    def __init__(self, file_key: str, name: str, parent=None):
        super().__init__(parent)
        self.setText(0, name)
        self.setFlags(self.flags() | Qt.ItemIsUserCheckable)
        self.setCheckState(0, Qt.Checked)
        self.file_key = file_key
        self.color = (0.7, 0.7, 0.7)


class PostprocessWorkspace(QWidget):
    """后处理工作区（CloudCompare 式）。"""

    STATES = ("idle", "loaded", "processing")

    # ---------------------------------------------------------------- 信号
    log_message = Signal(str, str)
    """工作区日志（message, level）。"""

    dirty_changed = Signal(bool)
    """是否有未保存的处理结果。"""

    cloud_list_changed = Signal()
    """点云列表发生变化。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._workflow = PostprocessWorkflow()

        # UI 内部状态
        self._current_item: Optional[CloudTreeItem] = None
        self._render_budget = 5_000_000
        self._viewer_cloud_keys: set = set()
        self._roi_mode = False
        self._roi_timer: Optional[QTimer] = None

        self._setup_ui()
        self.set_state("idle")

    # ------------------------------------------------------------ 公共接口
    def workflow(self) -> PostprocessWorkflow:
        """返回后处理工作流实例（供 backend_bridge 使用）。"""
        return self._workflow

    def viewer_panel(self) -> ViewerPanel:
        """返回 3D 查看器面板。"""
        return self._viewer_panel

    # ------------------------------------------------------------ UI 搭建
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部工具栏
        root.addWidget(self._build_toolbar())

        # 主体：左 DB 树 | 中 3D | 右后处理面板
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        self._left_panel = self._build_db_panel()
        self._left_panel.setMinimumWidth(260)
        self._left_panel.setMaximumWidth(360)

        self._viewer_panel = ViewerPanel("3D 点云预览")
        self._viewer_panel.setStyleSheet(
            f"QFrame {{ background-color: {BG_WINDOW}; border: none; }}")
        self._viewer_panel.viewer().set_toolbar_minimal(True)
        # 精简视图：隐藏坐标轴、网格，保留深色背景
        self._viewer_panel.viewer().set_show_axes(False)
        self._viewer_panel.viewer().set_show_grid(False)
        self._viewer_panel.viewer().set_background(True)
        self._viewer_panel.viewer_message.connect(
            lambda m: self.log_message.emit(m, "info"))

        self._right_panel = self._build_process_panel()
        self._right_panel.setMinimumWidth(300)
        self._right_panel.setMaximumWidth(400)

        body.addWidget(self._left_panel)
        body.addWidget(self._viewer_panel, 1)
        body.addWidget(self._right_panel)

        root.addLayout(body, 1)

        # 底部日志
        self._log_panel = LogPanel(self)
        self._log_panel.setFixedHeight(140)
        self._log_panel.setStyleSheet(
            f"QWidget {{ background-color: {BG_PANEL}; border-top: 1px solid {BORDER}; }}")
        root.addWidget(self._log_panel)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            f"background-color: {BG_PANEL}; border-bottom: 1px solid {BORDER};")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(8)

        lbl_title = QLabel("点云后处理")
        lbl_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700;")
        lo.addWidget(lbl_title)
        lo.addSpacing(20)

        self._btn_open = QPushButton("打开点云")
        ui_icons.apply(self._btn_open, "folder_open", TEXT_SECONDARY, 15)
        self._btn_open.clicked.connect(self._on_open_files)
        lo.addWidget(self._btn_open)

        self._btn_save = QPushButton("导出选中")
        ui_icons.apply(self._btn_save, "save", TEXT_SECONDARY, 15)
        self._btn_save.clicked.connect(self._on_export_selected)
        lo.addWidget(self._btn_save)

        self._btn_delete = QPushButton("删除选中")
        ui_icons.apply(self._btn_delete, "trash", STATUS_ERR, 15)
        self._btn_delete.clicked.connect(self._on_delete_selected)
        lo.addWidget(self._btn_delete)

        lo.addSpacing(20)

        self._btn_undo = QPushButton("撤销")
        ui_icons.apply(self._btn_undo, "undo", TEXT_SECONDARY, 15)
        self._btn_undo.clicked.connect(self._on_undo)
        lo.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("重做")
        ui_icons.apply(self._btn_redo, "refresh", TEXT_SECONDARY, 15)
        self._btn_redo.clicked.connect(self._on_redo)
        lo.addWidget(self._btn_redo)

        lo.addStretch(1)

        # 显示预算
        lo.addWidget(QLabel("显示预算:"))
        self._spin_budget = QSpinBox()
        self._spin_budget.setRange(50, 10000)
        self._spin_budget.setValue(self._render_budget // 10000)
        self._spin_budget.setSuffix(" 万点")
        self._spin_budget.valueChanged.connect(self._on_budget_changed)
        lo.addWidget(self._spin_budget)

        return bar

    def _build_db_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(f"background-color: {BG_PANEL}; border: none;")
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(8)

        lbl = QLabel("DB 树")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        lo.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.ExtendedSelection)
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
        """)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.itemChanged.connect(self._on_tree_item_changed)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        lo.addWidget(self._tree, 1)

        # 属性页
        self._build_property_panel(lo)

        return panel

    def _build_property_panel(self, parent_layout: QVBoxLayout):
        group = QGroupBox("属性")
        group.setStyleSheet(
            f"QGroupBox {{ color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; "
            f"margin-top: 8px; padding-top: 8px; }}")
        form = QVBoxLayout(group)
        form.setSpacing(6)

        self._prop_name = QLabel("未选择点云")
        self._prop_name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        form.addWidget(self._prop_name)

        self._prop_points = QLabel("原始点数: -")
        self._prop_points.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        form.addWidget(self._prop_points)

        row_vis = QHBoxLayout()
        self._prop_visible = QCheckBox("可见")
        self._prop_visible.stateChanged.connect(self._on_prop_visible_changed)
        row_vis.addWidget(self._prop_visible)
        row_vis.addStretch(1)
        form.addLayout(row_vis)

        row_size = QHBoxLayout()
        row_size.addWidget(QLabel("点大小:"))
        self._prop_size = QSpinBox()
        self._prop_size.setRange(1, 10)
        self._prop_size.setValue(1)
        self._prop_size.valueChanged.connect(self._on_prop_size_changed)
        row_size.addWidget(self._prop_size)
        row_size.addStretch(1)
        form.addLayout(row_size)

        row_color = QHBoxLayout()
        row_color.addWidget(QLabel("颜色:"))
        self._prop_color = QPushButton()
        self._prop_color.setFixedSize(28, 22)
        self._prop_color.clicked.connect(self._on_prop_color_clicked)
        row_color.addWidget(self._prop_color)
        btn_reset = QPushButton("恢复默认")
        btn_reset.setFixedHeight(24)
        btn_reset.clicked.connect(self._on_prop_color_reset)
        row_color.addWidget(btn_reset)
        row_color.addStretch(1)
        form.addLayout(row_color)

        # 详细属性：包围盒与中心点（CloudCompare 风格）
        self._prop_bbox = QLabel("包围盒: -")
        self._prop_bbox.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._prop_bbox.setWordWrap(True)
        form.addWidget(self._prop_bbox)

        self._prop_center = QLabel("中心: -")
        self._prop_center.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._prop_center.setWordWrap(True)
        form.addWidget(self._prop_center)

        parent_layout.addWidget(group)

    def _build_process_panel(self) -> QWidget:
        panel = QScrollArea()
        panel.setWidgetResizable(True)
        panel.setStyleSheet(f"background-color: {BG_PANEL}; border: none;")
        panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        lo = QVBoxLayout(inner)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(12)

        lbl = QLabel("后处理")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        lo.addWidget(lbl)

        # 视图控制（精简：只保留重置视角）
        view_group = QGroupBox("视图")
        view_lo = QVBoxLayout(view_group)
        btn_reset = QPushButton("重置视角")
        btn_reset.setFixedHeight(32)
        btn_reset.clicked.connect(self._on_reset_view)
        view_lo.addWidget(btn_reset)

        # 交互说明
        lbl_hint = QLabel(
            "左键: 旋转视角\n"
            "右键: 平移视角\n"
            "滚轮: 缩放\n"
            "中键点击: 设置旋转中心"
        )
        lbl_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        lbl_hint.setWordWrap(True)
        view_lo.addWidget(lbl_hint)
        lo.addWidget(view_group)

        # 体素下采样
        voxel_group = QGroupBox("体素下采样")
        voxel_lo = QVBoxLayout(voxel_group)
        self._chk_down = QCheckBox("启用下采样")
        self._chk_down.setChecked(self._workflow.processor.enable_voxel_downsample)
        self._chk_down.stateChanged.connect(
            lambda s: setattr(self._workflow.processor, "enable_voxel_downsample", s == Qt.Checked))
        voxel_lo.addWidget(self._chk_down)
        row_voxel = QHBoxLayout()
        row_voxel.addWidget(QLabel("体素大小(mm):"))
        self._spin_voxel = QSpinBox()
        self._spin_voxel.setRange(1, 50)
        self._spin_voxel.setValue(int(self._workflow.processor.voxel_size))
        self._spin_voxel.valueChanged.connect(
            lambda v: setattr(self._workflow.processor, "voxel_size", float(v)))
        row_voxel.addWidget(self._spin_voxel)
        voxel_lo.addLayout(row_voxel)
        lo.addWidget(voxel_group)

        # 离群点去除
        outlier_group = QGroupBox("统计离群点去除")
        outlier_lo = QVBoxLayout(outlier_group)
        self._chk_out = QCheckBox("启用离群点去除")
        self._chk_out.setChecked(self._workflow.processor.enable_outlier_removal)
        self._chk_out.stateChanged.connect(
            lambda s: setattr(self._workflow.processor, "enable_outlier_removal", s == Qt.Checked))
        outlier_lo.addWidget(self._chk_out)
        row_nb = QHBoxLayout()
        row_nb.addWidget(QLabel("邻域点数:"))
        self._spin_nb = QSpinBox()
        self._spin_nb.setRange(2, 100)
        self._spin_nb.setValue(self._workflow.processor.outlier_nb_neighbors)
        self._spin_nb.valueChanged.connect(
            lambda v: setattr(self._workflow.processor, "outlier_nb_neighbors", v))
        row_nb.addWidget(self._spin_nb)
        outlier_lo.addLayout(row_nb)
        row_std = QHBoxLayout()
        row_std.addWidget(QLabel("标准差倍数:"))
        self._spin_std = QSpinBox()
        self._spin_std.setRange(1, 10)
        self._spin_std.setValue(int(self._workflow.processor.outlier_std_ratio))
        self._spin_std.valueChanged.connect(
            lambda v: setattr(self._workflow.processor, "outlier_std_ratio", float(v)))
        row_std.addWidget(self._spin_std)
        outlier_lo.addLayout(row_std)
        lo.addWidget(outlier_group)

        # 裁切
        crop_group = QGroupBox("裁切")
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
        self._line_crop_param = QLineEdit(str(self._workflow.processor.crop_ratio))
        self._line_crop_param.setPlaceholderText("AABB/OBB 填 0~1；球填半径 mm")
        row_ratio.addWidget(self._line_crop_param)
        crop_lo.addLayout(row_ratio)
        self._chk_crop_preview = QCheckBox("预览裁切范围")
        self._chk_crop_preview.stateChanged.connect(
            lambda s: self._refresh_viewer())
        crop_lo.addWidget(self._chk_crop_preview)
        lo.addWidget(crop_group)

        # ICP 配准
        icp_group = QGroupBox("ICP 点云配准")
        icp_lo = QFormLayout(icp_group)
        self._combo_icp_source = QComboBox()
        self._combo_icp_target = QComboBox()
        icp_lo.addRow("源点云:", self._combo_icp_source)
        icp_lo.addRow("目标点云:", self._combo_icp_target)
        self._combo_icp_method = QComboBox()
        self._combo_icp_method.addItem("点到点", "point_to_point")
        self._combo_icp_method.addItem("点到面", "point_to_plane")
        icp_lo.addRow("方法:", self._combo_icp_method)
        self._btn_icp = QPushButton("执行 ICP 配准")
        self._btn_icp.setObjectName("primary")
        self._btn_icp.clicked.connect(self._on_icp_register)
        icp_lo.addRow(self._btn_icp)
        lo.addWidget(icp_group)

        # 点云合并
        merge_group = QGroupBox("点云合并")
        merge_lo = QVBoxLayout(merge_group)
        self._btn_merge = QPushButton("合并选中点云")
        self._btn_merge.clicked.connect(self._on_merge_selected)
        merge_lo.addWidget(self._btn_merge)
        lo.addWidget(merge_group)

        # ROI 框选
        roi_group = QGroupBox("ROI 框选")
        roi_lo = QVBoxLayout(roi_group)
        self._btn_roi_start = QPushButton("开始框选")
        self._btn_roi_start.setCheckable(True)
        self._btn_roi_start.setToolTip("在 3D 视图中按住左键拖拽矩形选择区域")
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
        self._btn_segment_in.clicked.connect(lambda: self._apply_roi_segment(True))
        row_roi.addWidget(self._btn_segment_in)
        self._btn_segment_out = QPushButton("剔除选中")
        self._btn_segment_out.setToolTip("将框选区域外的点保存为新点云")
        self._btn_segment_out.setEnabled(False)
        self._btn_segment_out.clicked.connect(lambda: self._apply_roi_segment(False))
        row_roi.addWidget(self._btn_segment_out)
        roi_lo.addLayout(row_roi)

        btn_roi_cancel = QPushButton("取消框选")
        btn_roi_cancel.clicked.connect(self._on_roi_cancel)
        roi_lo.addWidget(btn_roi_cancel)
        lo.addWidget(roi_group)

        # 自动参数
        auto_group = QGroupBox("自动参数估计")
        auto_lo = QVBoxLayout(auto_group)
        self._btn_auto_tune = QPushButton("根据当前点云自动推荐参数")
        self._btn_auto_tune.clicked.connect(self._on_auto_tune)
        auto_lo.addWidget(self._btn_auto_tune)
        lo.addWidget(auto_group)

        lo.addStretch(1)
        panel.setWidget(inner)
        return panel

    # ------------------------------------------------------------ 状态机
    def set_state(self, state: str):
        if state not in self.STATES:
            raise ValueError(f"未知状态: {state}")
        self._state = state
        busy = state == "processing"
        has_cloud = len(self._iter_cloud_items()) > 0
        has_selection = self._current_item is not None

        self._btn_open.setEnabled(not busy)
        self._btn_save.setEnabled(has_cloud and has_selection and not busy)
        self._btn_delete.setEnabled(has_cloud and has_selection and not busy)
        self._btn_undo.setEnabled(self._workflow.can_undo() and not busy)
        self._btn_redo.setEnabled(self._workflow.can_redo() and not busy)
        self._btn_icp.setEnabled(has_cloud and not busy)
        self._btn_merge.setEnabled(has_cloud and not busy)
        self._btn_auto_tune.setEnabled(has_cloud and has_selection and not busy)
        self._btn_roi_start.setEnabled(has_cloud and not busy)
        if not has_cloud:
            self._on_roi_cancel()

    # ------------------------------------------------------------ 视图
    def _on_reset_view(self):
        """重置视角到默认等轴视图，并重新适配场景。"""
        self._viewer_panel.reset_view()
        self._viewer_panel.viewer().set_pivot_visible(False)
        self._log("视角已重置", "info")

    # ------------------------------------------------------------ 点云加载
    def _on_open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择点云文件", "",
            "点云文件 (*.ply *.pcd *.xyz);;所有文件 (*)")
        if not files:
            return
        self._load_files(files)

    def _load_files(self, files: List[str]):
        for path in files:
            ok, msg, node_id = self._workflow.load_from_file(path)
            self._log(msg, "info" if ok else "error")
            if not ok:
                continue
            node = self._workflow.get_node(node_id)
            self._add_node_to_tree(node)
        self._refresh_viewer()
        self._update_icp_combos()
        self.set_state("loaded")

    def _add_node_to_tree(self, node: CloudNode):
        """添加点云到 DB 树：文件节点（父）+ 点云节点（子）。"""
        color = COLOR_PALETTE[self._tree.topLevelItemCount() % len(COLOR_PALETTE)]
        node.color = color

        # 查找或创建文件节点
        file_item = self._find_file_item(node.name)
        if file_item is None:
            file_item = FileTreeItem(node.node_id, node.name)
            file_item.color = color
            self._tree.addTopLevelItem(file_item)

        # 创建点云子节点
        cloud_item = CloudTreeItem(node.node_id, f"{node.name} - Cloud", node.pcd,
                                   parent=file_item)
        cloud_item.color = color
        self._cache_render_arrays(cloud_item)
        file_item.setExpanded(True)

        self._current_item = cloud_item
        self._update_property_panel()
        self.cloud_list_changed.emit()
        self.dirty_changed.emit(True)

    def _find_file_item(self, file_name: str) -> Optional[FileTreeItem]:
        """根据文件名查找文件节点。"""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if isinstance(item, FileTreeItem) and item.text(0) == file_name:
                return item
        return None

    # ------------------------------------------------------------ 属性页
    def _update_property_panel(self):
        if self._current_item is None:
            self._prop_name.setText("未选择点云")
            self._prop_points.setText("原始点数: -")
            if hasattr(self, "_prop_bbox"):
                self._prop_bbox.setText("包围盒: -")
                self._prop_center.setText("中心: -")
            return
        self._prop_name.setText(self._current_item.text(0))
        raw_n = len(self._current_item.pcd.points) if self._current_item.pcd else 0
        self._prop_points.setText(f"原始点数: {raw_n:,}")
        self._prop_visible.setChecked(self._current_item.checkState(0) == Qt.Checked)
        self._prop_size.setValue(self._current_item.point_size)
        self._set_color_button(self._current_item.color)

        # 详细属性：包围盒与中心
        if self._current_item.pcd is not None and len(self._current_item.pcd.points) > 0:
            pts = np.asarray(self._current_item.pcd.points)
            mask = np.isfinite(pts).all(axis=1)
            if mask.any():
                pts = pts[mask]
                mins = pts.min(axis=0)
                maxs = pts.max(axis=0)
                center = (mins + maxs) / 2
                dims = maxs - mins
                if hasattr(self, "_prop_bbox"):
                    self._prop_bbox.setText(
                        f"包围盒: X[{mins[0]:.2f}, {maxs[0]:.2f}] "
                        f"Y[{mins[1]:.2f}, {maxs[1]:.2f}] Z[{mins[2]:.2f}, {maxs[2]:.2f}]")
                    self._prop_center.setText(
                        f"中心: ({center[0]:.2f}, {center[1]:.2f}, {center[2]:.2f}) | "
                        f"尺寸: ({dims[0]:.2f}, {dims[1]:.2f}, {dims[2]:.2f})")

    def _set_color_button(self, color: Tuple[float, float, float]):
        qc = _to_qcolor(color)
        self._prop_color.setStyleSheet(
            f"QPushButton {{ background-color: {qc.name()}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; }}")

    def _iter_cloud_items(self) -> List[CloudTreeItem]:
        """遍历 DB 树中所有点云子节点。"""
        items = []
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            if not isinstance(file_item, FileTreeItem):
                continue
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if isinstance(child, CloudTreeItem):
                    items.append(child)
        return items

    def _selected_cloud_items(self) -> List[CloudTreeItem]:
        """获取当前选中的点云节点（若选中文件节点则取其第一个子点云）。"""
        items = []
        for item in self._tree.selectedItems():
            if isinstance(item, CloudTreeItem):
                items.append(item)
            elif isinstance(item, FileTreeItem) and item.childCount() > 0:
                child = item.child(0)
                if isinstance(child, CloudTreeItem):
                    items.append(child)
        return items

    def _on_prop_visible_changed(self, state: int):
        if self._current_item is None:
            return
        self._current_item.setCheckState(
            0, Qt.Checked if state == Qt.Checked else Qt.Unchecked)

    def _on_prop_size_changed(self, value: int):
        if self._current_item is None:
            return
        self._current_item.point_size = value
        self._refresh_viewer()

    def _on_prop_color_clicked(self):
        if self._current_item is None:
            return
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self._current_item.color = (color.redF(), color.greenF(), color.blueF())
            self._set_color_button(self._current_item.color)
            self._cache_render_arrays(self._current_item)
            self._refresh_viewer()

    def _on_prop_color_reset(self):
        if self._current_item is None:
            return
        # 根据文件节点在顶层中的索引确定默认颜色
        file_item = self._current_item.parent()
        idx = 0
        if isinstance(file_item, FileTreeItem):
            idx = self._tree.indexOfTopLevelItem(file_item)
        self._current_item.color = COLOR_PALETTE[idx % len(COLOR_PALETTE)]
        self._set_color_button(self._current_item.color)
        self._cache_render_arrays(self._current_item)
        self._refresh_viewer()

    # ------------------------------------------------------------ 显示缓存
    def _cache_render_arrays(self, item: CloudTreeItem):
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
        item._display_points = None
        item._display_colors = None

    def _rebuild_display_caches(self):
        visible_items = []
        total_raw = 0
        for item in self._iter_cloud_items():
            # 文件节点未勾选时，其下所有点云不可见
            file_visible = item.parent() is not None and item.parent().checkState(0) == Qt.Checked
            if not file_visible or item.checkState(0) != Qt.Checked or item.pcd is None:
                item._display_points = None
                item._display_colors = None
                continue
            if item._render_points is None:
                self._cache_render_arrays(item)
            if item._render_points is not None:
                visible_items.append(item)
                total_raw += len(item._render_points)

        if total_raw <= self._render_budget or not visible_items:
            for item in visible_items:
                item._display_points = item._render_points.copy()
                item._display_colors = item._render_colors.copy()
                item._display_step = 1
                item._display_to_orig_indices = np.arange(
                    len(item._render_points), dtype=np.int64)
            return

        min_pts = max(1000, self._render_budget // (len(visible_items) * 100))
        for item in visible_items:
            n = len(item._render_points)
            target = max(min_pts, int(self._render_budget * n / total_raw))
            if target >= n:
                item._display_points = item._render_points.copy()
                item._display_colors = item._render_colors.copy()
                item._display_step = 1
                item._display_to_orig_indices = np.arange(n, dtype=np.int64)
            else:
                k = max(1, int(np.ceil(n / target)))
                idx = np.arange(0, n, k)
                item._display_points = item._render_points[idx].copy()
                item._display_colors = item._render_colors[idx].copy()
                item._display_step = k
                item._display_to_orig_indices = idx.astype(np.int64)

    def _on_budget_changed(self, value: int):
        self._render_budget = value * 10000
        self._log(f"显示预算调整为 {self._render_budget:,} 点", "info")
        self._rebuild_display_caches()
        self._refresh_viewer()

    # ------------------------------------------------------------ 3D 刷新
    def _refresh_viewer(self):
        try:
            self._do_refresh_viewer()
        except Exception as e:
            self._log(f"刷新 3D 视图失败：{e}", "error")
            import traceback
            traceback.print_exc()

    def _do_refresh_viewer(self):
        gl_viewer = self._viewer_panel.viewer().viewer()
        if gl_viewer is None:
            return

        gl_viewer.clear_pointclouds()
        self._rebuild_display_caches()

        visible_keys = set()
        for item in self._iter_cloud_items():
            file_visible = item.parent() is not None and item.parent().checkState(0) == Qt.Checked
            if not file_visible or item.checkState(0) != Qt.Checked or item.pcd is None:
                continue
            if item._display_points is None:
                continue
            gl_viewer.set_pointcloud(
                item.node_id, item._display_points, item._display_colors,
                visible=True, point_size=item.point_size)
            visible_keys.add(item.node_id)

        # 选中点云包围盒
        if self._current_item is not None and self._current_item.pcd is not None:
            bounds = self._compute_item_bounds(self._current_item)
            if bounds:
                gl_viewer.set_selection_bbox([bounds])

        # 裁切范围预览
        if self._chk_crop_preview.isChecked() and self._current_item is not None:
            preview_pts, preview_cols = self._crop_preview_arrays(self._current_item)
            if preview_pts is not None:
                gl_viewer.set_pointcloud(
                    "__crop_preview__", preview_pts, preview_cols, visible=True)
                visible_keys.add("__crop_preview__")

        if not visible_keys:
            gl_viewer.set_overlay_text("未加载点云")
        else:
            total = 0
            for key in visible_keys:
                if key == "__crop_preview__":
                    continue
                cloud = gl_viewer._clouds.get(key)
                if cloud is not None:
                    total += cloud["point_count"]
            gl_viewer.set_overlay_text(
                f"可见点云 {len(visible_keys)} 个 | 显示总点数 {total:,} / 预算 {self._render_budget:,}")

    def _compute_item_bounds(self, item: CloudTreeItem) -> Optional[Tuple[List[float], List[float]]]:
        """计算点云包围盒（min/max），用于选中高亮显示。"""
        pcd = item.pcd
        if pcd is None or len(pcd.points) == 0:
            return None
        pts = np.asarray(pcd.points)
        mask = np.isfinite(pts).all(axis=1)
        if not mask.any():
            return None
        pts = pts[mask]
        return (pts.min(axis=0).tolist(), pts.max(axis=0).tolist())

    def _crop_preview_arrays(self, item: CloudTreeItem):
        if item is None or self._workflow.processor.crop_mode == "none":
            return None, None
        pcd = item.original_pcd if item.original_pcd is not None else item.pcd
        if pcd is None or len(pcd.points) == 0:
            return None, None
        bbox = self._workflow.processor.get_crop_bbox(pcd)
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

    # ------------------------------------------------------------ 树事件
    def _on_tree_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {BG_CARD}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; padding: 4px; }}")
        act = QAction("删除选中点云", self)
        act.triggered.connect(self._on_delete_selected)
        menu.addAction(act)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0:
            return
        self._rebuild_display_caches()
        self._refresh_viewer()

    def _on_tree_selection_changed(self):
        selected = self._tree.selectedItems()
        if not selected:
            self._current_item = None
            self._update_property_panel()
            return
        item = selected[0]
        cloud_item = None
        if isinstance(item, CloudTreeItem):
            cloud_item = item
        elif isinstance(item, FileTreeItem) and item.childCount() > 0:
            child = item.child(0)
            if isinstance(child, CloudTreeItem):
                cloud_item = child
        if cloud_item is not None:
            self._current_item = cloud_item
            self._workflow.select(cloud_item.node_id)
            self._update_property_panel()
            if self._chk_crop_preview.isChecked():
                self._refresh_viewer()

    # ------------------------------------------------------------ 工具栏动作
    def _on_delete_selected(self):
        items = self._tree.selectedItems()
        if not items:
            self._log("请先选择要删除的点云", "warn")
            return
        # 收集要删除的点云节点和文件节点
        cloud_ids_to_remove = set()
        file_items_to_remove = []
        for item in items:
            if isinstance(item, CloudTreeItem):
                cloud_ids_to_remove.add(item.node_id)
            elif isinstance(item, FileTreeItem):
                file_items_to_remove.append(item)

        # 删除点云节点
        for item in self._iter_cloud_items():
            if item.node_id in cloud_ids_to_remove:
                self._workflow.remove_cloud(item.node_id)
                file_item = item.parent()
                if file_item is not None:
                    file_item.removeChild(item)
                    # 文件节点为空时也删除
                    if file_item.childCount() == 0:
                        idx = self._tree.indexOfTopLevelItem(file_item)
                        if idx >= 0:
                            self._tree.takeTopLevelItem(idx)
                if self._current_item is item:
                    self._current_item = None

        # 删除整个文件节点
        for file_item in file_items_to_remove:
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if isinstance(child, CloudTreeItem):
                    self._workflow.remove_cloud(child.node_id)
                    if self._current_item is child:
                        self._current_item = None
            idx = self._tree.indexOfTopLevelItem(file_item)
            if idx >= 0:
                self._tree.takeTopLevelItem(idx)

        self._update_property_panel()
        self._refresh_viewer()
        self._update_icp_combos()
        self.cloud_list_changed.emit()
        self.set_state("loaded" if len(self._iter_cloud_items()) > 0 else "idle")

    def _on_undo(self):
        ok, msg = self._workflow.undo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            node_id = self._workflow.selected_id()
            if node_id:
                self._sync_item_from_workflow(node_id)
            self._refresh_viewer()
            self.set_state("loaded")

    def _on_redo(self):
        ok, msg = self._workflow.redo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            node_id = self._workflow.selected_id()
            if node_id:
                self._sync_item_from_workflow(node_id)
            self._refresh_viewer()
            self.set_state("loaded")

    def _sync_item_from_workflow(self, node_id: str):
        node = self._workflow.get_node(node_id)
        if node is None:
            return
        for item in self._iter_cloud_items():
            if item.node_id == node_id:
                item.pcd = node.pcd
                self._cache_render_arrays(item)
                if self._current_item is item:
                    self._update_property_panel()
                break

    # ------------------------------------------------------------ 后处理
    def _on_crop_mode_changed(self, idx: int):
        mode = self._combo_crop.itemData(idx)
        self._workflow.processor.crop_mode = mode
        if mode == "sphere":
            self._line_crop_param.setText(str(self._workflow.processor.crop_radius))
        else:
            self._line_crop_param.setText(str(self._workflow.processor.crop_ratio))
        if self._chk_crop_preview.isChecked():
            self._refresh_viewer()

    def _on_apply_process(self):
        if self._current_item is None:
            self._log("请先选择点云", "warn")
            return
        try:
            value = float(self._line_crop_param.text())
            if self._workflow.processor.crop_mode == "sphere":
                self._workflow.processor.crop_radius = value
            else:
                self._workflow.processor.crop_ratio = value
        except ValueError:
            self._log("裁切参数格式错误", "error")
            return

        self.set_state("processing")
        node_id = self._current_item.node_id
        ok, msg, stats = self._workflow.apply_process(node_id)
        self._log(msg, "success" if ok else "error")
        if ok:
            self._sync_item_from_workflow(node_id)
            self._refresh_viewer()
            self.dirty_changed.emit(True)
        self.set_state("loaded")

    # ------------------------------------------------------------ ICP
    def _update_icp_combos(self):
        self._combo_icp_source.clear()
        self._combo_icp_target.clear()
        # 按 DB 树层级显示：文件 / 点云
        for file_idx in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(file_idx)
            if not isinstance(file_item, FileTreeItem):
                continue
            for child_idx in range(file_item.childCount()):
                child = file_item.child(child_idx)
                if isinstance(child, CloudTreeItem):
                    display = f"{file_item.text(0)} / {child.text(0)}"
                    self._combo_icp_source.addItem(display, child.node_id)
                    self._combo_icp_target.addItem(display, child.node_id)

    def _on_icp_register(self):
        source_id = self._combo_icp_source.currentData()
        target_id = self._combo_icp_target.currentData()
        if source_id is None or target_id is None:
            self._log("请选择源点云和目标点云", "warn")
            return
        if source_id == target_id:
            self._log("源点云与目标点云不能相同", "warn")
            return

        method = self._combo_icp_method.currentData()
        self.set_state("processing")
        ok, msg, result = self._workflow.icp_register(
            source_id, target_id, estimation_method=method)
        self._log(msg, "success" if ok else "error")
        if ok:
            self._sync_item_from_workflow(source_id)
            self._refresh_viewer()
            self.dirty_changed.emit(True)
            if result is not None:
                QMessageBox.information(
                    self, "ICP 结果",
                    f"fitness: {result.fitness:.4f}\n"
                    f"inlier_rmse: {result.inlier_rmse:.4f}")
        self.set_state("loaded")

    # ------------------------------------------------------------ 合并
    def _on_merge_selected(self):
        items = self._selected_cloud_items()
        node_ids = [item.node_id for item in items]
        if len(node_ids) < 2:
            self._log("请至少选择两朵点云进行合并", "warn")
            return
        self.set_state("processing")
        ok, msg, new_id = self._workflow.merge_clouds(node_ids)
        self._log(msg, "success" if ok else "error")
        if ok and new_id:
            node = self._workflow.get_node(new_id)
            self._add_node_to_tree(node)
            self._refresh_viewer()
            self._update_icp_combos()
        self.set_state("loaded")

    # ------------------------------------------------------------ 自动参数
    def _on_auto_tune(self):
        if self._current_item is None:
            self._log("请先选择点云", "warn")
            return
        ok, msg, params = self._workflow.auto_tune(self._current_item.node_id)
        self._log(msg, "info" if ok else "error")
        if ok and params:
            self._workflow.processor.crop_mode = params["crop_mode"]
            self._workflow.processor.crop_ratio = params["crop_ratio"]
            self._workflow.processor.crop_radius = params["crop_radius"]
            self._workflow.processor.enable_voxel_downsample = params["enable_voxel_downsample"]
            self._workflow.processor.voxel_size = params["voxel_size"]
            self._workflow.processor.enable_outlier_removal = params["enable_outlier_removal"]
            self._workflow.processor.outlier_nb_neighbors = params["outlier_nb_neighbors"]
            self._workflow.processor.outlier_std_ratio = params["outlier_std_ratio"]

            self._chk_down.setChecked(params["enable_voxel_downsample"])
            self._spin_voxel.setValue(max(1, int(params["voxel_size"])))
            self._chk_out.setChecked(params["enable_outlier_removal"])
            self._spin_nb.setValue(params["outlier_nb_neighbors"])
            self._spin_std.setValue(int(params["outlier_std_ratio"]))
            idx = self._combo_crop.findData(params["crop_mode"])
            if idx >= 0:
                self._combo_crop.setCurrentIndex(idx)
            self._line_crop_param.setText(
                str(params["crop_radius"] if params["crop_mode"] == "sphere"
                    else params["crop_ratio"]))

            notes = "\n".join(f"• {n}" for n in params.get("notes", []))
            QMessageBox.information(self, "自动参数估计", notes)

    # ------------------------------------------------------------ 导出
    def _on_export_selected(self):
        if self._current_item is None:
            self._log("请先选择点云", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出点云", "processed.ply",
            "PLY 文件 (*.ply);;PCD 文件 (*.pcd)")
        if not path:
            return
        ok, msg = self._workflow.export_cloud(self._current_item.node_id, path)
        self._log(msg, "success" if ok else "error")
        if ok:
            self.dirty_changed.emit(False)

    # ------------------------------------------------------------ ROI 框选
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
        self._roi_timer = QTimer(self)
        self._roi_timer.timeout.connect(self._check_roi_selection)
        self._roi_timer.start(200)

    def _stop_roi_timer(self):
        if self._roi_timer is not None:
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

    def _find_item_by_node_id(self, node_id: str) -> Optional[CloudTreeItem]:
        for item in self._iter_cloud_items():
            if item.node_id == node_id:
                return item
        return None

    def _apply_roi_segment(self, segment_in: bool):
        selection = self._viewer_panel.viewer().get_roi_selection()
        if not selection:
            self._log("ROI 未选中任何点", "warn")
            return

        created = []
        for cloud_id, display_indices in selection.items():
            item = self._find_item_by_node_id(cloud_id)
            if item is None or item.pcd is None:
                continue
            pcd = item.pcd
            pts = np.asarray(pcd.points)
            if len(pts) == 0:
                continue

            # 精确映射：显示索引 -> 原始索引
            if item._display_to_orig_indices is None:
                orig_indices = display_indices.astype(np.int64)
            else:
                max_idx = len(item._display_to_orig_indices) - 1
                clipped = np.clip(display_indices.astype(np.int64), 0, max_idx)
                orig_indices = item._display_to_orig_indices[clipped]

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
            # 使用文件节点名称作为基础名
            file_item = item.parent()
            base_name = file_item.text(0) if isinstance(file_item, FileTreeItem) else item.text(0)
            new_name = f"{base_name}{suffix}"
            counter = 1
            unique_name = new_name
            existing_names = {self._tree.topLevelItem(i).text(0)
                              for i in range(self._tree.topLevelItemCount())}
            while unique_name in existing_names:
                counter += 1
                unique_name = f"{new_name}_{counter}"

            # 通过工作流添加新点云（保证历史/撤销一致性）
            node_id = self._workflow.add_cloud(unique_name, new_pcd,
                                               parent_id=cloud_id)
            node = self._workflow.get_node(node_id)
            self._add_node_to_tree(node)
            created.append(unique_name)

        self._viewer_panel.viewer().clear_roi_selection()
        self._btn_roi_start.setChecked(False)
        self._lbl_roi_status.setText(f"已生成：{', '.join(created)}")
        self._btn_segment_in.setEnabled(False)
        self._btn_segment_out.setEnabled(False)
        self._stop_roi_timer()
        self._refresh_viewer()
        self._update_icp_combos()
        self.set_state("loaded")
        self._log(
            f"ROI {'保留' if segment_in else '剔除'} 结果：{', '.join(created)}",
            "success")

    # ------------------------------------------------------------ 日志
    def _log(self, message: str, level: str = "info"):
        self._log_panel.append(message, level)
        self.log_message.emit(message, level)
