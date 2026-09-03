# -*- coding: utf-8 -*-
"""
主工作区（Workspace）—— CloudCompare 式主窗口集成。

布局：
  ┌─────────┬─────────────────┬──────────┐
  │ DB Tree │   GL Viewer     │ Properties│
  │(左,220) │   (中央,自适应)  │(右,240)  │
  │         │                 │          │
  │         │   + Toolbar(顶)  │          │
  │         │   + Console(底)  │          │
  └─────────┴─────────────────┴──────────┘

功能：
  - 点云加载（自动构建 Octree + LOD）
  - DB Tree ↔ GL Viewer 双向同步
  - 属性面板 ↔ 点云数据绑定
  - 后处理管线一键执行
"""

from __future__ import annotations

import os
import sys
import numpy as np
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QFileDialog, QMessageBox, QProgressBar,
    QTextEdit, QLabel, QApplication,
)

from ui_v2.theme import BG_PANEL, TEXT_SECONDARY, BORDER

from cc_db_tree import CCDBTree
from cc_toolbar import CCToolBar
from cc_properties import CCPropertiesPanel
from cc_gl_viewer import CCGLViewer

from cc_octree_lod import OctreeLOD
from cc_scalar_field import ScalarField, ScalarFieldManager
from cc_geometry import bounding_box, estimate_normals
from cc_workflow import PointCloudData, Pipeline, create_default_pipeline, create_segmentation_pipeline


class CloudCompareWindow(QMainWindow):
    """CloudCompare 式主窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CloudCompare-Like Prototype")
        self.resize(1400, 900)

        self._clouds: Dict[str, dict] = {}  # cloud_id -> {points, colors, normals, lod, sf_manager, ...}
        self._pipelines: Dict[str, Pipeline] = {}
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        # 中央分割器
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)

        # 左：DB Tree
        self.db_tree = CCDBTree()
        self.splitter.addWidget(self.db_tree)

        # 中：Viewer + Toolbar + Console
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self.toolbar = CCToolBar()
        center_layout.addWidget(self.toolbar)

        self.viewer = CCGLViewer()
        center_layout.addWidget(self.viewer, 1)

        # 底部控制台
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(120)
        self.console.setStyleSheet(f"background: {BG_PANEL}; color: {TEXT_SECONDARY}; font-family: Consolas; font-size: 11px;")
        center_layout.addWidget(self.console)

        self.splitter.addWidget(center_widget)

        # 右：Properties
        self.properties = CCPropertiesPanel()
        self.splitter.addWidget(self.properties)

        # 比例
        self.splitter.setSizes([220, 940, 240])

        # 进度条（底部状态栏）
        self.status_bar = self.statusBar()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.showMessage("Ready")

    def _connect_signals(self):
        # Toolbar
        self.toolbar.open_requested.connect(self._on_open)
        self.toolbar.delete_requested.connect(self._on_delete_selected)
        self.toolbar.reset_view_requested.connect(self.viewer.reset_camera)
        self.toolbar.point_size_changed.connect(self.viewer.set_point_size)
        self.toolbar.background_toggled.connect(self.viewer.set_dark_background)
        self.toolbar.view_preset_requested.connect(self.viewer.set_view_preset)
        self.toolbar.undo_requested.connect(self._on_undo)

        # DB Tree
        self.db_tree.selection_changed.connect(self._on_tree_selection)
        self.db_tree.visibility_changed.connect(self._on_tree_visibility)
        self.db_tree.delete_requested.connect(self._on_delete_node)

        # Properties
        self.properties.transform_changed.connect(self._on_transform_changed)
        self.properties.color_changed.connect(self._on_color_changed)
        self.properties.scalar_field_changed.connect(self._on_scalar_field_changed)
        self.properties.scalar_range_changed.connect(self._on_scalar_range_changed)

    def log(self, msg: str):
        self.console.append(f"[{self._timestamp()}] {msg}")

    def _timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

    # ── 文件操作 ──

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Point Cloud", "",
            "Point Clouds (*.ply *.pcd *.xyz *.bin);;All Files (*.*)"
        )
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path: str):
        self.status_bar.showMessage(f"Loading {os.path.basename(path)}...")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # 无限旋转
        QApplication.processEvents()

        try:
            points, colors = self._read_point_cloud(path)
            if points is None:
                raise ValueError("Unsupported format or empty file")

            file_id = f"file_{len(self._clouds)}"
            cloud_id = f"cloud_{len(self._clouds)}"

            # DB Tree
            file_name = os.path.basename(path)
            self.db_tree.add_file(file_id, file_name)
            self.db_tree.add_cloud(cloud_id, file_name, file_id, color=(0.7, 0.7, 0.7))

            # LOD
            self.log(f"Building Octree + LOD for {len(points):,} points...")
            lod = OctreeLOD(points)
            lod.build_async()

            # Scalar fields
            sf_manager = ScalarFieldManager()
            if colors is not None and len(colors) == len(points):
                # 如果有颜色，创建 intensity 标量场
                intensity = colors.mean(axis=1).astype(np.float32)
                sf_manager.add(ScalarField("intensity", intensity))

            self._clouds[cloud_id] = {
                "points": points,
                "colors": colors,
                "normals": None,
                "lod": lod,
                "sf_manager": sf_manager,
                "transform": np.eye(4, dtype=np.float32),
                "visible": True,
            }

            # 添加到 Viewer
            self.viewer.add_cloud(cloud_id, points, colors)
            self.log(f"Loaded {file_name}: {len(points):,} points")

            # 选中
            self._select_cloud(cloud_id)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load file:\n{str(e)}")
            self.log(f"ERROR loading {path}: {e}")
        finally:
            self.progress.setVisible(False)
            self.status_bar.showMessage("Ready")

    def _read_point_cloud(self, path: str) -> tuple:
        """简单点云读取（支持 xyz / bin / ply）。"""
        ext = os.path.splitext(path)[1].lower()
        if ext == '.xyz':
            data = np.loadtxt(path, dtype=np.float32)
            if data.ndim == 1:
                data = data.reshape(1, -1)
            points = data[:, :3]
            colors = data[:, 3:6] / 255.0 if data.shape[1] >= 6 else None
            return points, colors
        elif ext == '.bin':
            data = np.fromfile(path, dtype=np.float32).reshape(-1, 3)
            return data, None
        elif ext == '.ply':
            try:
                from plyfile import PlyData
                ply = PlyData.read(path)
                vertex = ply['vertex']
                points = np.stack([vertex['x'], vertex['y'], vertex['z']], axis=1).astype(np.float32)
                colors = None
                if 'red' in vertex:
                    colors = np.stack([vertex['red'], vertex['green'], vertex['blue']], axis=1).astype(np.float32) / 255.0
                return points, colors
            except ImportError:
                pass
        return None, None

    # ── 选择同步 ──

    def _select_cloud(self, cloud_id: str):
        cloud = self._clouds.get(cloud_id)
        if cloud is None:
            return
        self._current_cloud_id = cloud_id

        # 更新 Properties
        pts = cloud["points"]
        bb = bounding_box(pts)
        volume = (bb[1][0]-bb[0][0])*(bb[1][1]-bb[0][1])*(bb[1][2]-bb[0][2])
        density = len(pts) / max(volume, 1e-12)
        self.properties.set_cloud_info(len(pts), bb, density)

        sf_names = cloud["sf_manager"].list_names()
        self.properties.set_scalar_fields(sf_names)

        # 更新 Viewer 高亮
        self.viewer.set_selected_cloud(cloud_id)

    def _on_tree_selection(self, ids: list):
        for cid in ids:
            if cid in self._clouds:
                self._select_cloud(cid)
                break

    def _on_tree_visibility(self, node_id: str, visible: bool):
        if node_id in self._clouds:
            self._clouds[node_id]["visible"] = visible
            self.viewer.set_cloud_visible(node_id, visible)

    def _on_delete_node(self, node_id: str):
        if node_id in self._clouds:
            self.viewer.remove_cloud(node_id)
            del self._clouds[node_id]
            self.db_tree.remove_node(node_id)
            self.log(f"Deleted cloud {node_id}")

    def _on_delete_selected(self):
        if hasattr(self, '_current_cloud_id') and self._current_cloud_id in self._clouds:
            self._on_delete_node(self._current_cloud_id)

    # ── 属性变更 ──

    def _on_transform_changed(self, T: np.ndarray):
        if not hasattr(self, '_current_cloud_id'):
            return
        cid = self._current_cloud_id
        if cid in self._clouds:
            self._clouds[cid]["transform"] = T
            self.viewer.set_cloud_transform(cid, T)

    def _on_color_changed(self, color: tuple):
        if not hasattr(self, '_current_cloud_id'):
            return
        cid = self._current_cloud_id
        if cid in self._clouds:
            # 纯色覆盖
            n = len(self._clouds[cid]["points"])
            colors = np.tile(color, (n, 1)).astype(np.float32)
            self._clouds[cid]["colors"] = colors
            self.viewer.update_cloud_colors(cid, colors)

    def _on_scalar_field_changed(self, sf_name: str):
        if not hasattr(self, '_current_cloud_id'):
            return
        cid = self._current_cloud_id
        cloud = self._clouds.get(cid)
        if cloud is None:
            return
        sf = cloud["sf_manager"].get(sf_name)
        if sf:
            rgba = sf.to_rgba()
            self.viewer.update_cloud_colors(cid, rgba[:, :3])

    def _on_scalar_range_changed(self, vmin: float, vmax: float):
        if not hasattr(self, '_current_cloud_id'):
            return
        cid = self._current_cloud_id
        cloud = self._clouds.get(cid)
        if cloud is None:
            return
        sf = cloud["sf_manager"].active_field()
        if sf:
            sf.vmin = vmin
            sf.vmax = vmax
            rgba = sf.to_rgba()
            self.viewer.update_cloud_colors(cid, rgba[:, :3])

    # ── 后处理管线 ──

    def run_pipeline(self, pipeline: Pipeline, cloud_id: str):
        """对指定点云执行后处理管线。"""
        cloud = self._clouds.get(cloud_id)
        if cloud is None:
            return

        self.status_bar.showMessage("Running pipeline...")
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        QApplication.processEvents()

        def on_progress(stage, p):
            self.progress.setValue(int(p * 100))
            self.log(f"Pipeline: {stage} ({p*100:.0f}%)")
            QApplication.processEvents()

        try:
            data = PointCloudData(
                points=cloud["points"],
                colors=cloud["colors"],
                normals=cloud["normals"],
            )
            result = pipeline.run(data, progress=on_progress)

            # 更新数据
            cloud["points"] = result.points
            cloud["colors"] = result.colors
            cloud["normals"] = result.normals
            for name, values in result.scalar_fields.items():
                cloud["sf_manager"].add(ScalarField(name, values))

            # 更新 Viewer
            self.viewer.update_cloud_geometry(cloud_id, result.points, result.colors)
            self.log(f"Pipeline complete: {len(result.points):,} points")

            # 更新 Properties
            self._select_cloud(cloud_id)

        except Exception as e:
            QMessageBox.critical(self, "Pipeline Error", str(e))
            self.log(f"Pipeline ERROR: {e}")
        finally:
            self.progress.setVisible(False)
            self.status_bar.showMessage("Ready")

    def _on_undo(self):
        pass  # 预留：通过 Pipeline.undo() 实现

    # ── 预设操作 ──

    def action_default_pipeline(self):
        if hasattr(self, '_current_cloud_id'):
            p = create_default_pipeline()
            self.run_pipeline(p, self._current_cloud_id)

    def action_segmentation_pipeline(self):
        if hasattr(self, '_current_cloud_id'):
            p = create_segmentation_pipeline()
            self.run_pipeline(p, self._current_cloud_id)
