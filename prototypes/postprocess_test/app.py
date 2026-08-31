# -*- coding: utf-8 -*-
"""
后处理测试工具 —— 独立原型（ui_v2 风格）。

布局参考 CloudCompare：
  - 左侧：DB 树（文件 → 点云对象），顶部提供打开 PLY 文件按钮；
  - 中间：完整 3D 点云查看器（复用 src/ui_v2/widgets/viewer_panel.py）；
  - 右侧：后处理参数面板（下采样、离群点去除、AABB/球/OBB 裁切）；
  - 底部：日志栏，输出加载/处理/保存信息。

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
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
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


class DBTreeItem(QTreeWidgetItem):
    """DB 树节点：携带点云对象与显示名称。"""

    def __init__(self, name: str, pcd: Optional[o3d.geometry.PointCloud] = None,
                 parent=None):
        super().__init__(parent)
        self.setText(0, name)
        self.setFlags(self.flags() | Qt.ItemIsUserCheckable)
        self.setCheckState(0, Qt.Checked)
        self.pcd = pcd
        self.original_pcd = pcd


class PostProcessTestWindow(QMainWindow):
    """后处理测试主窗口（ui_v2 风格）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("后处理测试工具")
        self.resize(1500, 950)

        self._processor = PointCloudProcessor()
        self._loaded_pcds: Dict[str, o3d.geometry.PointCloud] = {}
        self._current_item: Optional[DBTreeItem] = None

        self._setup_ui()
        self._setup_menubar()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

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
        body.addWidget(self._viewer_panel, 1)

        root.addLayout(body, 1)

        # 底部日志栏
        self._log_panel = LogPanel(self)
        self._log_panel.setFixedHeight(140)
        self._log_panel.setStyleSheet(
            f"QWidget {{ background-color: {BG_PANEL}; border-top: 1px solid {BORDER}; }}")
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

        lo.addStretch(1)

        btn_clear_log = QPushButton("清空日志")
        ui_icons.apply(btn_clear_log, "trash", TEXT_SECONDARY, 15)
        btn_clear_log.clicked.connect(self._log_panel.clear)
        lo.addWidget(btn_clear_log)

        return bar

    def _setup_menubar(self):
        menubar = self.menuBar()
        menubar.setStyleSheet(f"background-color: {BG_PANEL}; border: none;")
        file_menu = menubar.addMenu("文件")

        open_action = QAction("打开点云文件...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_files)
        file_menu.addAction(open_action)

        open_folder_action = QAction("打开点云文件夹...", self)
        open_folder_action.triggered.connect(self._on_open_folder)
        file_menu.addAction(open_folder_action)

        file_menu.addSeparator()

        save_action = QAction("保存当前点云...", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._on_save_current)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

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
    def _on_crop_mode_changed(self, idx: int):
        mode = self._combo_crop.itemData(idx)
        self._processor.crop_mode = mode
        if mode == "sphere":
            self._line_crop_param.setText(str(self._processor.crop_radius))
        else:
            self._line_crop_param.setText(str(self._processor.crop_ratio))

    def _on_open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择点云文件", "",
            "点云文件 (*.ply *.pcd *.xyz);;所有文件 (*)")
        if not files:
            return
        for path in files:
            self._load_file(path)

    def _on_open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择点云文件夹")
        if not folder:
            return
        count_before = len(self._loaded_pcds)
        for ext in (".ply", ".pcd", ".xyz"):
            for path in Path(folder).glob(f"*{ext}"):
                self._load_file(str(path))
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

            file_item = DBTreeItem(base, pcd=pcd)
            cloud_item = DBTreeItem(f"{base} - Cloud", pcd=pcd, parent=file_item)
            file_item.setExpanded(True)
            self._tree.addTopLevelItem(file_item)

            self._log(
                f"加载 {base}：原始点数 {n_points:,}，路径 {path}", "info")
            self._refresh_viewer()
        except Exception as e:
            self._log(f"加载失败 {path}：{e}", "error")
            QMessageBox.critical(self, "加载失败", f"无法加载 {path}：\n{e}")

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0:
            return
        self._refresh_viewer()

    def _on_tree_selection_changed(self):
        selected = self._tree.selectedItems()
        if not selected:
            self._current_item = None
            self._lbl_info.setText("未选择点云")
            return
        item = selected[0]
        if not isinstance(item, DBTreeItem) or item.pcd is None:
            self._current_item = None
            self._lbl_info.setText("未选择点云")
            return
        self._current_item = item
        pcd = item.pcd
        info = (
            f"名称: {item.text(0)}\n"
            f"点数: {len(pcd.points):,}\n"
            f"{self._bbox_info(pcd)}"
        )
        self._lbl_info.setText(info)
        self._log(f"选中 {item.text(0)}，点数 {len(pcd.points):,}", "info")

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

    def _refresh_viewer(self):
        self._viewer_panel.clear_all()
        visible_count = 0
        for i in range(self._tree.topLevelItemCount()):
            file_item = self._tree.topLevelItem(i)
            if file_item.checkState(0) != Qt.Checked:
                continue
            for j in range(file_item.childCount()):
                cloud_item = file_item.child(j)
                if not isinstance(cloud_item, DBTreeItem):
                    continue
                if cloud_item.checkState(0) == Qt.Checked and cloud_item.pcd is not None:
                    self._viewer_panel.set_pointcloud(cloud_item.text(0), cloud_item.pcd)
                    visible_count += 1
        self._log(f"3D 视图刷新：显示 {visible_count} 个点云", "info")

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
