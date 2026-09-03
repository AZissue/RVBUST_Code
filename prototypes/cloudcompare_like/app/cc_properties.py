# -*- coding: utf-8 -*-
"""
属性面板（Properties Panel）—— CloudCompare 式右侧属性编辑。

功能：
  - 选中点云后显示基本信息（点数、包围盒、密度）
  - 变换：平移 / 旋转 / 缩放（实时矩阵编辑）
  - 颜色：RGB 纯色、按标量场着色
  - 标量场：列表 + min/max 滑块
  - 法线：显示/隐藏、长度调节
"""

from __future__ import annotations

import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSlider, QGroupBox, QFormLayout,
    QColorDialog, QCheckBox, QSpinBox, QDoubleSpinBox,
)

from ui_v2.theme import TEXT_PRIMARY, TEXT_SECONDARY, BG_CARD, BG_PANEL, BORDER


class CCPropertiesPanel(QWidget):
    """右侧属性面板。"""

    transform_changed = Signal(np.ndarray)  # 4×4 矩阵
    color_changed = Signal(tuple)  # (r,g,b)
    scalar_field_changed = Signal(str)  # 标量场名称
    scalar_range_changed = Signal(float, float)  # vmin, vmax
    normals_visible_changed = Signal(bool)
    normals_scale_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self._build_ui()
        self._current_cloud_id: str | None = None

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # ── 基本信息 ──
        self.group_info = QGroupBox("Info")
        info_layout = QFormLayout(self.group_info)
        self.lbl_points = QLabel("—")
        self.lbl_bbox = QLabel("—")
        self.lbl_density = QLabel("—")
        info_layout.addRow("Points:", self.lbl_points)
        info_layout.addRow("BBox:", self.lbl_bbox)
        info_layout.addRow("Density:", self.lbl_density)
        layout.addWidget(self.group_info)

        # ── 变换 ──
        self.group_xform = QGroupBox("Transform")
        xform_layout = QFormLayout(self.group_xform)

        self._tx = QDoubleSpinBox()
        self._tx.setRange(-9999, 9999)
        self._tx.setDecimals(3)
        self._tx.valueChanged.connect(self._emit_transform)
        xform_layout.addRow("Tx:", self._tx)

        self._ty = QDoubleSpinBox()
        self._ty.setRange(-9999, 9999)
        self._ty.setDecimals(3)
        self._ty.valueChanged.connect(self._emit_transform)
        xform_layout.addRow("Ty:", self._ty)

        self._tz = QDoubleSpinBox()
        self._tz.setRange(-9999, 9999)
        self._tz.setDecimals(3)
        self._tz.valueChanged.connect(self._emit_transform)
        xform_layout.addRow("Tz:", self._tz)

        self._rx = QDoubleSpinBox()
        self._rx.setRange(-360, 360)
        self._rx.valueChanged.connect(self._emit_transform)
        xform_layout.addRow("Rx(°):", self._rx)

        self._ry = QDoubleSpinBox()
        self._ry.setRange(-360, 360)
        self._ry.valueChanged.connect(self._emit_transform)
        xform_layout.addRow("Ry(°):", self._ry)

        self._rz = QDoubleSpinBox()
        self._rz.setRange(-360, 360)
        self._rz.valueChanged.connect(self._emit_transform)
        xform_layout.addRow("Rz(°):", self._rz)

        self._scale = QDoubleSpinBox()
        self._scale.setRange(0.001, 1000)
        self._scale.setValue(1.0)
        self._scale.valueChanged.connect(self._emit_transform)
        xform_layout.addRow("Scale:", self._scale)

        layout.addWidget(self.group_xform)

        # ── 颜色 ──
        self.group_color = QGroupBox("Color")
        color_layout = QVBoxLayout(self.group_color)

        self.btn_pick_color = QPushButton("Pick Solid Color")
        self.btn_pick_color.clicked.connect(self._pick_color)
        color_layout.addWidget(self.btn_pick_color)

        self.combo_sf = QComboBox()
        self.combo_sf.currentTextChanged.connect(self.scalar_field_changed.emit)
        color_layout.addWidget(QLabel("Scalar Field:"))
        color_layout.addWidget(self.combo_sf)

        self.slider_sf_min = QSlider(Qt.Horizontal)
        self.slider_sf_min.setRange(0, 1000)
        self.slider_sf_min.valueChanged.connect(self._emit_sf_range)
        color_layout.addWidget(QLabel("SF Min:"))
        color_layout.addWidget(self.slider_sf_min)

        self.slider_sf_max = QSlider(Qt.Horizontal)
        self.slider_sf_max.setRange(0, 1000)
        self.slider_sf_max.setValue(1000)
        self.slider_sf_max.valueChanged.connect(self._emit_sf_range)
        color_layout.addWidget(QLabel("SF Max:"))
        color_layout.addWidget(self.slider_sf_max)

        layout.addWidget(self.group_color)

        # ── 法线 ──
        self.group_normals = QGroupBox("Normals")
        normals_layout = QFormLayout(self.group_normals)
        self.chk_normals = QCheckBox("Show")
        self.chk_normals.toggled.connect(self.normals_visible_changed.emit)
        normals_layout.addRow(self.chk_normals)

        self.spin_nscale = QDoubleSpinBox()
        self.spin_nscale.setRange(0.1, 50)
        self.spin_nscale.setValue(5.0)
        self.spin_nscale.valueChanged.connect(self.normals_scale_changed.emit)
        normals_layout.addRow("Length:", self.spin_nscale)

        layout.addWidget(self.group_normals)

        layout.addStretch()

    # ── 内部信号处理 ──

    def _emit_transform(self):
        import numpy as np
        tx, ty, tz = self._tx.value(), self._ty.value(), self._tz.value()
        rx, ry, rz = np.radians(self._rx.value()), np.radians(self._ry.value()), np.radians(self._rz.value())
        s = self._scale.value()

        cx, sx = np.cos(rx), np.sin(rx)
        cy, sy = np.cos(ry), np.sin(ry)
        cz, sz = np.cos(rz), np.sin(rz)

        Rx = np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
        Ry = np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
        Rz = np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])
        R = Rz @ Ry @ Rx

        T = np.eye(4, dtype=np.float32)
        T[:3,:3] = R * s
        T[:3,3] = [tx, ty, tz]
        self.transform_changed.emit(T)

    def _pick_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.color_changed.emit((color.redF(), color.greenF(), color.blueF()))

    def _emit_sf_range(self):
        vmin = self.slider_sf_min.value() / 1000.0
        vmax = self.slider_sf_max.value() / 1000.0
        self.scalar_range_changed.emit(vmin, vmax)

    # ── 公开 API ──

    def set_cloud_info(self, n_points: int, bbox: tuple, density: float):
        self.lbl_points.setText(f"{n_points:,}")
        self.lbl_bbox.setText(f"[{bbox[0][0]:.2f}, {bbox[0][1]:.2f}, {bbox[0][2]:.2f}] → "
                              f"[{bbox[1][0]:.2f}, {bbox[1][1]:.2f}, {bbox[1][2]:.2f}]")
        self.lbl_density.setText(f"{density:.2f} pts/unit³")

    def set_scalar_fields(self, names: list[str]):
        self.combo_sf.clear()
        self.combo_sf.addItems(names)

    def set_transform_values(self, tx=0.0, ty=0.0, tz=0.0, rx=0.0, ry=0.0, rz=0.0, scale=1.0):
        self._tx.setValue(tx)
        self._ty.setValue(ty)
        self._tz.setValue(tz)
        self._rx.setValue(rx)
        self._ry.setValue(ry)
        self._rz.setValue(rz)
        self._scale.setValue(scale)
