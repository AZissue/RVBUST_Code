# -*- coding: utf-8 -*-
"""
CloudCompare 式主工作区（CloudCompareWorkspace）。

布局：
  - 顶部：CCToolBar
  - 左侧：CloudDBTree（DB 树）
  - 中间：PointCloudViewerLOD（3D 查看器）
  - 右侧：PropertiesPanel（属性面板）
  - 底部：LogPanel（日志）

信号/接口与 src/ui_v2/workspaces/ 现有工作区对齐，方便后期合并。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QFileDialog, QMessageBox,
)

# 让原型能引用 src/ 下的模块
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_APP_DIR)))
if os.path.join(_PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core.utils import logger
from ui_v2.theme import GLOBAL_QSS, BG_WINDOW, BG_PANEL, BORDER
from ui_v2.widgets import LogPanel

from ..core.cc_workflow import CloudCompareWorkflow, CCNode
from .cc_gl_viewer import PointCloudViewerLOD
from .cc_db_tree import CloudDBTree
from .cc_properties import PropertiesPanel
from .cc_toolbar import CCToolBar


# 默认调色板
COLOR_PALETTE = [
    (0.20, 0.80, 1.00), (1.00, 0.60, 0.20), (0.40, 1.00, 0.40),
    (1.00, 0.40, 0.70), (1.00, 1.00, 0.30), (0.70, 0.50, 1.00),
    (0.40, 0.90, 0.80), (0.95, 0.50, 0.50),
]


class CloudCompareWorkspace(QWidget):
    """CloudCompare 式后处理工作区。"""

    STATES = ("idle", "loaded", "processing")

    log_message = Signal(str, str)
    dirty_changed = Signal(bool)
    cloud_list_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._workflow = CloudCompareWorkflow()
        self._current_node_id: Optional[str] = None
        self._color_idx = 0

        self._setup_ui()
        self._connect_signals()
        self.set_state("idle")

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 工具栏
        self._toolbar = CCToolBar(self)
        root.addWidget(self._toolbar)

        # 主体：左 DB 树 | 中 3D | 右属性
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        self._left_panel = self._build_left_panel()
        self._left_panel.setMinimumWidth(240)
        self._left_panel.setMaximumWidth(340)

        self._viewer = PointCloudViewerLOD(self)
        self._viewer.setStyleSheet(f"background-color: {BG_WINDOW}; border: none;")

        self._right_panel = self._build_right_panel()
        self._right_panel.setMinimumWidth(280)
        self._right_panel.setMaximumWidth(380)

        body.addWidget(self._left_panel)
        body.addWidget(self._viewer, 1)
        body.addWidget(self._right_panel)

        root.addLayout(body, 1)

        # 日志
        self._log_panel = LogPanel(self)
        self._log_panel.setFixedHeight(120)
        self._log_panel.setStyleSheet(
            f"QWidget {{ background-color: {BG_PANEL}; border-top: 1px solid {BORDER}; }}")
        root.addWidget(self._log_panel)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._db_tree = CloudDBTree(self)
        lo.addWidget(self._db_tree)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._props = PropertiesPanel(self)
        lo.addWidget(self._props)
        return panel

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # 工具栏
        self._toolbar.open_requested.connect(self._on_open_files)
        self._toolbar.save_requested.connect(self._on_export)
        self._toolbar.delete_requested.connect(self._on_delete)
        self._toolbar.undo_requested.connect(self._on_undo)
        self._toolbar.redo_requested.connect(self._on_redo)
        self._toolbar.view_preset_requested.connect(self._viewer.set_view_preset)
        self._toolbar.point_size_changed.connect(self._on_point_size_changed)
        self._toolbar.background_toggled.connect(self._viewer.set_background)
        self._toolbar.roi_mode_toggled.connect(self._on_roi_mode)
        self._toolbar.colorbar_toggled.connect(self._on_colorbar_toggled)
        self._toolbar.reset_view_requested.connect(self._viewer.reset_view)

        # DB 树
        self._db_tree.selection_changed.connect(self._on_tree_selection)
        self._db_tree.visibility_changed.connect(self._on_tree_visibility)
        self._db_tree.delete_requested.connect(self._on_delete_node)

        # 属性面板
        self._props.point_size_changed.connect(self._on_point_size_changed)
        self._props.color_mode_changed.connect(self._on_color_mode_changed)
        self._props.scalar_field_changed.connect(self._on_scalar_field_changed)
        self._props.colormap_changed.connect(self._on_colormap_changed)
        self._props.estimate_normals_requested.connect(self._on_estimate_normals)
        self._props.detect_plane_requested.connect(self._on_detect_plane)
        self._props.euclidean_cluster_requested.connect(self._on_euclidean_cluster)
        self._props.auto_tune_requested.connect(self._on_auto_tune)

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------
    def set_state(self, state: str):
        if state not in self.STATES:
            raise ValueError(f"未知状态: {state}")
        self._state = state
        has_cloud = len(self._workflow.list_cloud_nodes()) > 0
        self._toolbar.set_undo_enabled(self._workflow.can_undo())
        self._toolbar.set_redo_enabled(self._workflow.can_redo())
        if not has_cloud:
            self._props.clear()

    # ------------------------------------------------------------------
    # 点云加载
    # ------------------------------------------------------------------
    def _on_open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择点云文件", "",
            "点云文件 (*.ply *.pcd *.xyz);;所有文件 (*)")
        if not files:
            return
        for path in files:
            ok, msg, node_id = self._workflow.load_from_file(path)
            self._log(msg, "info" if ok else "error")
            if not ok:
                continue
            node = self._workflow.get_node(node_id)
            self._add_node_to_ui(node)
        self._refresh_viewer()
        self.set_state("loaded")

    def _add_node_to_ui(self, node: CCNode):
        color = COLOR_PALETTE[self._color_idx % len(COLOR_PALETTE)]
        self._color_idx += 1
        node.color = color

        if node.parent_id:
            parent = self._workflow.get_node(node.parent_id)
            if parent:
                self._db_tree.add_cloud_node(node.node_id, node.name,
                                              parent_id=parent.node_id, color=color)
        else:
            self._db_tree.add_cloud_node(node.node_id, node.name, color=color)

        self._current_node_id = node.node_id
        self._update_properties()
        self.cloud_list_changed.emit()
        self.dirty_changed.emit(True)

    # ------------------------------------------------------------------
    # DB 树事件
    # ------------------------------------------------------------------
    def _on_tree_selection(self, node_id: str):
        node = self._workflow.get_node(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return
        self._current_node_id = node_id
        self._workflow.select(node_id)
        self._update_properties()
        self._update_bbox_highlight()

    def _on_tree_visibility(self, node_id: str, visible: bool):
        node = self._workflow.get_node(node_id)
        if node is None:
            return
        node.visible = visible
        self._workflow.set_visible(node_id, visible)
        self._refresh_viewer()

    def _on_delete_node(self, node_id: str):
        self._workflow.remove_node(node_id)
        self._db_tree.remove_node(node_id)
        self._viewer.clear_pointclouds()
        # 当前选中被删除（或其父支被删）时清理选中状态
        if self._current_node_id and self._workflow.get_node(self._current_node_id) is None:
            self._current_node_id = None
        self._refresh_viewer()
        self._update_properties()
        self.set_state("loaded" if self._workflow.list_cloud_nodes() else "idle")

    def _on_delete(self):
        node_id = self._db_tree.selected_node_id()
        if node_id:
            self._on_delete_node(node_id)

    # ------------------------------------------------------------------
    # 属性面板事件
    # ------------------------------------------------------------------
    def _update_properties(self):
        node_id = self._current_node_id
        node = self._workflow.get_node(node_id) if node_id else None
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            self._props.clear()
            return

        pts = np.asarray(node.pcd.points) if node.pcd else np.zeros((0, 3))
        n = len(pts)
        bbox_str = "-"
        center_str = "-"
        if n > 0:
            mask = np.isfinite(pts).all(axis=1)
            if mask.any():
                valid = pts[mask]
                mins = valid.min(axis=0)
                maxs = valid.max(axis=0)
                center = (mins + maxs) / 2
                bbox_str = f"X[{mins[0]:.1f},{maxs[0]:.1f}] Y[{mins[1]:.1f},{maxs[1]:.1f}] Z[{mins[2]:.1f},{maxs[2]:.1f}]"
                center_str = f"({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})"

        scalar_names = list(node.scalar_fields.keys()) if node.scalar_fields else []
        self._props.set_node(node_id, node.name, n, bbox_str, center_str, scalar_names)

    def _on_point_size_changed(self, size: int):
        self._viewer.set_point_size(size)
        if self._current_node_id:
            node = self._workflow.get_node(self._current_node_id)
            if node:
                node.point_size = size

    def _on_color_mode_changed(self, mode: str):
        self._refresh_viewer()

    def _on_scalar_field_changed(self, name: str):
        if not self._current_node_id:
            return
        self._workflow.set_active_scalar(self._current_node_id, name or None)
        self._refresh_viewer()

    def _on_colormap_changed(self, cmap: str):
        if self._current_node_id:
            node = self._workflow.get_node(self._current_node_id)
            if node and node.active_scalar:
                sf = node.scalar_fields.get(node.active_scalar)
                if sf:
                    sf.colormap = cmap
        self._refresh_viewer()

    # ------------------------------------------------------------------
    # 后处理操作
    # ------------------------------------------------------------------
    def _on_estimate_normals(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        self.set_state("processing")
        ok, msg = self._workflow.estimate_normals(self._current_node_id)
        self._log(msg, "success" if ok else "error")
        self.set_state("loaded")

    def _on_detect_plane(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        self.set_state("processing")
        ok, msg, result = self._workflow.detect_geometry(self._current_node_id, "plane")
        self._log(msg, "success" if ok else "error")
        if ok and result:
            inliers = result.get("inliers", [])
            if inliers:
                node = self._workflow.get_node(self._current_node_id)
                # 平面内点作为子节点挂在源点云下（CloudCompare 风格分支）
                inlier_pcd = node.pcd.select_by_index(inliers)
                new_id = self._workflow.add_cloud(f"{node.name}_plane", inlier_pcd,
                                                   parent_id=node.node_id)
                new_node = self._workflow.get_node(new_id)
                self._add_node_to_ui(new_node)
        self.set_state("loaded")

    def _on_euclidean_cluster(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        self.set_state("processing")
        ok, msg, created = self._workflow.euclidean_clustering(self._current_node_id)
        self._log(msg, "success" if ok else "error")
        if ok:
            for cid in created:
                node = self._workflow.get_node(cid)
                if node:
                    self._add_node_to_ui(node)
        self.set_state("loaded")

    def _on_auto_tune(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        ok, msg, params = self._workflow.auto_tune(self._current_node_id)
        self._log(msg, "info" if ok else "error")
        if ok and params:
            notes = "\n".join(f"• {n}" for n in params.get("notes", []))
            QMessageBox.information(self, "自动参数估计", notes)

    # ------------------------------------------------------------------
    # 撤销/重做
    # ------------------------------------------------------------------
    def _on_undo(self):
        ok, msg = self._workflow.undo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            self._refresh_viewer()
            self._update_properties()
        self.set_state("loaded")

    def _on_redo(self):
        ok, msg = self._workflow.redo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            self._refresh_viewer()
            self._update_properties()
        self.set_state("loaded")

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------
    def _on_export(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出点云", "processed.ply",
            "PLY 文件 (*.ply);;PCD 文件 (*.pcd)")
        if not path:
            return
        ok, msg = self._workflow.export_cloud(self._current_node_id, path)
        self._log(msg, "success" if ok else "error")
        if ok:
            self.dirty_changed.emit(False)

    # ------------------------------------------------------------------
    # ROI
    # ------------------------------------------------------------------
    def _on_roi_mode(self, enabled: bool):
        self._viewer.set_roi_mode(enabled)
        if enabled:
            self._roi_timer = QTimer(self)
            self._roi_timer.timeout.connect(self._check_roi)
            self._roi_timer.start(200)
        else:
            if hasattr(self, '_roi_timer') and self._roi_timer:
                self._roi_timer.stop()

    def _check_roi(self):
        selection = self._viewer.get_roi_selection()
        total = sum(len(v) for v in selection.values())
        if total > 0:
            self._log(f"ROI 已选中 {total:,} 个点", "info")

    def _on_colorbar_toggled(self, on: bool):
        if on and self._current_node_id:
            node = self._workflow.get_node(self._current_node_id)
            if node and node.active_scalar:
                sf = node.scalar_fields.get(node.active_scalar)
                if sf:
                    self._viewer.set_show_colorbar(True, sf.min_val, sf.max_val, sf.name)
                    return
        self._viewer.set_show_colorbar(False)

    # ------------------------------------------------------------------
    # 3D 刷新
    # ------------------------------------------------------------------
    def _refresh_viewer(self):
        self._viewer.clear_pointclouds()
        for node in self._workflow.list_cloud_nodes():
            if not node.visible:
                continue
            pts = np.asarray(node.pcd.points, dtype=np.float32)
            cols = node.get_display_colors()
            if cols is None:
                cols = np.tile(np.array(node.color, dtype=np.float32), (len(pts), 1))
            self._viewer.set_pointcloud(node.node_id, pts, cols,
                                         visible=True, point_size=node.point_size)
        self._update_bbox_highlight()

    def _update_bbox_highlight(self):
        if not self._current_node_id:
            self._viewer.set_selection_bbox([])
            return
        node = self._workflow.get_node(self._current_node_id)
        if node is None or node.pcd is None or len(node.pcd.points) == 0:
            self._viewer.set_selection_bbox([])
            return
        pts = np.asarray(node.pcd.points)
        mask = np.isfinite(pts).all(axis=1)
        if not mask.any():
            self._viewer.set_selection_bbox([])
            return
        valid = pts[mask]
        self._viewer.set_selection_bbox([(valid.min(axis=0).tolist(), valid.max(axis=0).tolist())])

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _log(self, message: str, level: str = "info"):
        self._log_panel.append(message, level)
        self.log_message.emit(message, level)


# =========================================================================
# 独立运行入口
# =========================================================================
class CloudCompareWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CloudCompare-Like 后处理原型")
        self.resize(1600, 1000)

        central = QWidget()
        self.setCentralWidget(central)
        lo = QVBoxLayout(central)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self.workspace = CloudCompareWorkspace()
        lo.addWidget(self.workspace)

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    win = CloudCompareWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
