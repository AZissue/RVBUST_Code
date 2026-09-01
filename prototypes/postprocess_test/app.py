# -*- coding: utf-8 -*-
"""
后处理测试工具 —— 独立原型（ui_v2 风格）。

布局参考 CloudCompare：
  - 左侧：DB 树（文件 → 点云对象），顶部提供打开 PLY 文件按钮；
  - 中间：完整 3D 点云查看器（复用 src/ui_v2/widgets/viewer_panel.py）；
  - 右侧：后处理参数面板（下采样、离群点去除、AABB/球/OBB 裁切）；
  - 底部：日志栏，输出加载/处理/保存信息。

显示控制由左侧 DB 树统一负责：勾选的点云自动叠加显示，取消勾选则隐藏，
不再依赖 3D 查看器内部的"全部叠加/合并结果"下拉框。

点云按原始数据渲染：不触发显示级下采样，NaN/Inf 点由 OpenGL 层替换为
零点以维持索引对应，但不会被删除。

运行方式：
    python prototypes/postprocess_test/app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import open3d as o3d

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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
        # 渲染缓存：避免每次切换/勾选都重新从 open3d 对象转换
        self._render_points: Optional[np.ndarray] = None
        self._render_colors: Optional[np.ndarray] = None


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

        # 左侧 DB 树
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
        # 禁用显示级下采样，保证原始点云完整渲染
        self._viewer_panel.viewer().MAX_RENDER_POINTS = 100_000_000
        # 隐藏 3D 查看器自带的"显示"下拉框，统一由左侧 DB 树控制可见性
        self._hide_viewer_display_combo()

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
            }}
            QTreeWidget::item {{
                padding: 4px 2px;
                border: none;
            }}
            QTreeWidget::item:selected {{
                background-color: {ACCENT};
                color: #FFFFFF;
            }}
        """)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.itemChanged.connect(self._on_tree_item_changed)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        lo.addWidget(self._tree, 1)

        return panel

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
    def _hide_viewer_display_combo(self):
        """隐藏 3D 查看器工具栏里的"显示"下拉框及其标签，统一由 DB 树控制。"""
        viewer = self._viewer_panel.viewer()
        viewer.combo_mode.hide()
        # 查找并隐藏对应的"显示:"标签
        for w in viewer.children():
            if isinstance(w, QWidget):
                for lbl in w.findChildren(QLabel):
                    if lbl.text() == "显示:":
                        lbl.hide()
                        return

    @staticmethod
    def _color_for_index(idx: int):
        return COLOR_PALETTE[idx % len(COLOR_PALETTE)]

    def _cache_render_arrays(self, item: DBTreeItem):
        """从点云对象生成渲染缓存，避免每次刷新都重复转换。"""
        pcd = item.pcd
        if pcd is None or len(pcd.points) == 0:
            item._render_points = None
            item._render_colors = None
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

    def _on_crop_mode_changed(self, idx: int):
        mode = self._combo_crop.itemData(idx)
        self._processor.crop_mode = mode
        if mode == "sphere":
            self._line_crop_param.setText(str(self._processor.crop_radius))
        else:
            self._line_crop_param.setText(str(self._processor.crop_ratio))
        if self._chk_crop_preview.isChecked():
            self._refresh_viewer()

    def _on_open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择点云文件", "",
            "点云文件 (*.ply *.pcd *.xyz);;所有文件 (*)")
        if not files:
            return
        self._batch_loading = True
        self._tree.blockSignals(True)
        try:
            for path in files:
                self._load_file(path)
        finally:
            self._tree.blockSignals(False)
            self._batch_loading = False
            self._refresh_viewer()

    def _on_open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择点云文件夹")
        if not folder:
            return
        count_before = len(self._loaded_pcds)
        self._batch_loading = True
        self._tree.blockSignals(True)
        try:
            for ext in (".ply", ".pcd", ".xyz"):
                for path in Path(folder).glob(f"*{ext}"):
                    self._load_file(str(path))
        finally:
            self._tree.blockSignals(False)
            self._batch_loading = False
            self._refresh_viewer()
            loaded = len(self._loaded_pcds) - count_before
            self._log(f"文件夹加载完成，新增 {loaded} 个点云", "success")

    def _load_file(self, path: str):
        try:
            pcd = o3d.io.read_point_cloud(path)
            n_points = len(pcd.points)
            if n_points == 0:
                self._log(f"文件为空或无法解析：{path}", "warn")
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
                self._refresh_viewer()
        except Exception as e:
            self._log(f"加载失败 {path}：{e}", "error")
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
            self._refresh_viewer()
            self._on_tree_selection_changed()

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0:
            return
        self._refresh_viewer()

    def _on_tree_selection_changed(self):
        selected = self._tree.selectedItems()
        if not selected:
            self._current_item = None
            self._lbl_info.setText("未选择点云")
            if self._chk_crop_preview.isChecked():
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
        info = (
            f"名称: {cloud_item.text(0)}\n"
            f"点数: {len(pcd.points):,}\n"
            f"{self._bbox_info(pcd)}"
        )
        self._lbl_info.setText(info)
        self._log(f"选中 {cloud_item.text(0)}，点数 {len(pcd.points):,}", "info")
        if self._chk_crop_preview.isChecked():
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
        """根据 DB 树勾选状态刷新 3D 视图。"""
        visible = []
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            if file_item.checkState(0) != Qt.Checked:
                continue
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if not isinstance(child, DBTreeItem):
                    continue
                if child.checkState(0) == Qt.Checked and child.pcd is not None:
                    visible.append(child)

        gl_viewer = self._viewer_panel.viewer().viewer()
        if not visible:
            if gl_viewer is not None:
                gl_viewer.clear()
                gl_viewer.set_overlay_text("未加载点云")
            return

        if len(visible) == 1:
            item = visible[0]
            points = item._render_points
            colors = item._render_colors
            name = item.text(0)
        else:
            points = np.concatenate([it._render_points for it in visible], axis=0)
            colors = np.concatenate([it._render_colors for it in visible], axis=0)
            name = f"全部叠加 ({len(visible)} 个点云)"

        # 叠加裁切范围预览
        if self._chk_crop_preview.isChecked() and self._current_item is not None:
            preview_pts, preview_colors = self._crop_preview_arrays(self._current_item)
            if preview_pts is not None:
                points = np.concatenate([points, preview_pts], axis=0)
                colors = np.concatenate([colors, preview_colors], axis=0)

        # 调用内部渲染接口，保留着色模式切换等工具栏功能
        self._viewer_panel.viewer()._load_to_viewer(
            points, colors, name, highlight=None, cache=True)

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
