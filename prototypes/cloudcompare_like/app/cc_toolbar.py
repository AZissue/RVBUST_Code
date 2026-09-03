# -*- coding: utf-8 -*-
"""
工具栏（Toolbar）—— CloudCompare 式顶部工具栏。

紧凑设计，包含：
  - 文件：打开、导出
  - 编辑：撤销、重做、删除
  - 视图：视角预设、点大小、背景切换
  - 选择：矩形 ROI、多边形、Brush（预留）
  - 着色：标量场、Colorbar 开关
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QComboBox, QSpinBox,
    QToolButton, QLabel, QSizePolicy,
)

from ui_v2.theme import TEXT_PRIMARY, TEXT_SECONDARY, BG_PANEL, BORDER


class CCToolBar(QWidget):
    """CloudCompare 式工具栏。"""

    open_requested = Signal()
    save_requested = Signal()
    delete_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    view_preset_requested = Signal(str)
    point_size_changed = Signal(int)
    background_toggled = Signal(bool)  # True=dark
    roi_mode_toggled = Signal(bool)
    colorbar_toggled = Signal(bool)
    reset_view_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        # 文件
        self.btn_open = QPushButton("Open")
        self.btn_open.clicked.connect(self.open_requested.emit)
        layout.addWidget(self.btn_open)

        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self.save_requested.emit)
        layout.addWidget(self.btn_save)

        layout.addSpacing(12)

        # 编辑
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.clicked.connect(self.undo_requested.emit)
        layout.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("Redo")
        self.btn_redo.clicked.connect(self.redo_requested.emit)
        layout.addWidget(self.btn_redo)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.delete_requested.emit)
        layout.addWidget(self.btn_delete)

        layout.addSpacing(12)

        # 视图
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(["Front", "Top", "Left", "ISO", "Back", "Bottom", "Right"])
        self.combo_preset.currentTextChanged.connect(self.view_preset_requested.emit)
        layout.addWidget(QLabel("View:"))
        layout.addWidget(self.combo_preset)

        self.spin_point_size = QSpinBox()
        self.spin_point_size.setRange(1, 10)
        self.spin_point_size.setValue(2)
        self.spin_point_size.valueChanged.connect(self.point_size_changed.emit)
        layout.addWidget(QLabel("PtSize:"))
        layout.addWidget(self.spin_point_size)

        self.btn_bg = QPushButton("Dark")
        self.btn_bg.setCheckable(True)
        self.btn_bg.setChecked(True)
        self.btn_bg.toggled.connect(self.background_toggled.emit)
        layout.addWidget(self.btn_bg)

        self.btn_reset = QPushButton("Reset View")
        self.btn_reset.clicked.connect(self.reset_view_requested.emit)
        layout.addWidget(self.btn_reset)

        layout.addSpacing(12)

        # 选择
        self.btn_roi = QPushButton("ROI")
        self.btn_roi.setCheckable(True)
        self.btn_roi.toggled.connect(self.roi_mode_toggled.emit)
        layout.addWidget(self.btn_roi)

        # 着色
        self.btn_colorbar = QPushButton("Colorbar")
        self.btn_colorbar.setCheckable(True)
        self.btn_colorbar.toggled.connect(self.colorbar_toggled.emit)
        layout.addWidget(self.btn_colorbar)

        layout.addStretch()

    def set_undo_enabled(self, enabled: bool):
        self.btn_undo.setEnabled(enabled)

    def set_redo_enabled(self, enabled: bool):
        self.btn_redo.setEnabled(enabled)
