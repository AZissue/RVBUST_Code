# -*- coding: utf-8 -*-
"""
属性面板（Properties Panel）。

CloudCompare 式右侧面板：
  - 点云基础属性：名称、点数、包围盒、中心
  - 显示属性：点大小、颜色模式、标量场选择
  - 标量场 Colorbar 控制
  - 法线显示开关
  - 测量结果
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QPushButton,
    QFormLayout, QSlider, QSizePolicy,
)

from ui_v2.theme import TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BG_PANEL, BORDER


class PropertiesPanel(QWidget):
    """点云属性面板。"""

    # 信号
    point_size_changed = Signal(int)
    color_mode_changed = Signal(str)       # "rgb" | "height" | "density" | "curvature" | "intensity"
    scalar_field_changed = Signal(str)     # 标量场名称或 ""
    colormap_changed = Signal(str)
    show_normals_changed = Signal(bool)
    auto_tune_requested = Signal()
    estimate_normals_requested = Signal()
    detect_plane_requested = Signal()
    euclidean_cluster_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._node_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(12)

        lbl = QLabel("属性")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        lo.addWidget(lbl)

        # ===== 基础信息 =====
        info_group = QGroupBox("基本信息")
        info_lo = QFormLayout(info_group)
        self._lbl_name = QLabel("未选择")
        self._lbl_name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        info_lo.addRow("名称:", self._lbl_name)

        self._lbl_points = QLabel("-")
        self._lbl_points.setStyleSheet(f"color: {TEXT_MUTED};")
        info_lo.addRow("点数:", self._lbl_points)

        self._lbl_bbox = QLabel("-")
        self._lbl_bbox.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._lbl_bbox.setWordWrap(True)
        info_lo.addRow("包围盒:", self._lbl_bbox)

        self._lbl_center = QLabel("-")
        self._lbl_center.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        info_lo.addRow("中心:", self._lbl_center)
        lo.addWidget(info_group)

        # ===== 显示属性 =====
        display_group = QGroupBox("显示")
        disp_lo = QFormLayout(display_group)

        row_size = QHBoxLayout()
        self._spin_size = QSpinBox()
        self._spin_size.setRange(1, 10)
        self._spin_size.setValue(1)
        self._spin_size.valueChanged.connect(self.point_size_changed.emit)
        row_size.addWidget(self._spin_size)
        row_size.addStretch(1)
        disp_lo.addRow("点大小:", row_size)

        self._combo_color = QComboBox()
        self._combo_color.addItem("RGB 颜色", "rgb")
        self._combo_color.addItem("高度 (Z)", "height")
        self._combo_color.addItem("点密度", "density")
        self._combo_color.addItem("曲率", "curvature")
        self._combo_color.addItem("灰度", "gray")
        self._combo_color.currentIndexChanged.connect(
            lambda: self.color_mode_changed.emit(self._combo_color.currentData()))
        disp_lo.addRow("着色模式:", self._combo_color)

        self._combo_scalar = QComboBox()
        self._combo_scalar.addItem("无", "")
        self._combo_scalar.currentIndexChanged.connect(
            lambda: self.scalar_field_changed.emit(self._combo_scalar.currentData() or ""))
        disp_lo.addRow("标量场:", self._combo_scalar)

        self._combo_colormap = QComboBox()
        self._combo_colormap.addItem("Jet", "jet")
        self._combo_colormap.addItem("Hot", "hot")
        self._combo_colormap.addItem("Coolwarm", "coolwarm")
        self._combo_colormap.addItem("Viridis", "viridis")
        self._combo_colormap.currentIndexChanged.connect(
            lambda: self.colormap_changed.emit(self._combo_colormap.currentData()))
        disp_lo.addRow("色映射:", self._combo_colormap)

        self._chk_normals = QCheckBox("显示法线")
        self._chk_normals.stateChanged.connect(
            lambda s: self.show_normals_changed.emit(s == Qt.Checked))
        disp_lo.addRow(self._chk_normals)

        lo.addWidget(display_group)

        # ===== 后处理快捷操作 =====
        process_group = QGroupBox("处理")
        proc_lo = QVBoxLayout(process_group)

        btn_normals = QPushButton("估计法线")
        btn_normals.clicked.connect(self.estimate_normals_requested.emit)
        proc_lo.addWidget(btn_normals)

        btn_plane = QPushButton("检测平面 (RANSAC)")
        btn_plane.clicked.connect(self.detect_plane_requested.emit)
        proc_lo.addWidget(btn_plane)

        btn_cluster = QPushButton("欧式聚类分割")
        btn_cluster.clicked.connect(self.euclidean_cluster_requested.emit)
        proc_lo.addWidget(btn_cluster)

        btn_auto = QPushButton("自动参数估计")
        btn_auto.clicked.connect(self.auto_tune_requested.emit)
        proc_lo.addWidget(btn_auto)

        lo.addWidget(process_group)

        lo.addStretch(1)

    # ------------------------------------------------------------------
    # 数据绑定
    # ------------------------------------------------------------------
    def set_node(self, node_id: str, name: str, point_count: int,
                 bbox_str: str = "", center_str: str = "",
                 scalar_fields: Optional[list] = None):
        self._node_id = node_id
        self._lbl_name.setText(name)
        self._lbl_points.setText(f"{point_count:,}")
        self._lbl_bbox.setText(bbox_str or "-")
        self._lbl_center.setText(center_str or "-")

        # 更新标量场下拉
        self._combo_scalar.clear()
        self._combo_scalar.addItem("无", "")
        if scalar_fields:
            for sf_name in scalar_fields:
                self._combo_scalar.addItem(sf_name, sf_name)

    def clear(self):
        self._node_id = None
        self._lbl_name.setText("未选择")
        self._lbl_points.setText("-")
        self._lbl_bbox.setText("-")
        self._lbl_center.setText("-")
        self._combo_scalar.clear()
        self._combo_scalar.addItem("无", "")

    def set_point_size(self, size: int):
        self._spin_size.setValue(size)

    def get_point_size(self) -> int:
        return self._spin_size.value()
