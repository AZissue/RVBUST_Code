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

from ui_v2.theme import TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BG_PANEL, BG_CARD, BORDER


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
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedHeight(40)
        self.setObjectName("ccToolbar")
        # 局部 QSS 只管字号/间距；底色/边框/hover/checked 全部交回 GLOBAL_QSS
        # （S3.5 复刻口径：QPushButton 默认 BG_CARD、QToolButton:checked ACCENT_DIM）。
        # 注意必须用 objectName 限定背景规则——Qt 的 QWidget{} 类选择器会命中所有
        # 子控件，把按钮底也刷成 BG_PANEL，应用级 QPushButton/QToolButton 规则全废。
        self.setStyleSheet(
            f"QWidget#ccToolbar {{ background-color: {BG_PANEL}; "
            f"border-bottom: 1px solid {BORDER}; }}"
            f"QToolButton, QPushButton {{ font-size: 10pt; padding: 2px 8px; min-height: 24px; }}"
            f"QComboBox, QSpinBox {{ font-size: 10pt; min-height: 22px; }}"
            f"QLabel {{ color: {TEXT_MUTED}; font-size: 10pt; background: transparent; }}"
        )

        lo = QHBoxLayout(self)
        lo.setContentsMargins(10, 2, 10, 2)
        lo.setSpacing(8)

        # 标题
        lbl = QLabel("CloudCompare-Like")
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 700;")
        lo.addWidget(lbl)
        lo.addSpacing(20)

        # 文件
        btn_open = QPushButton("打开")
        btn_open.clicked.connect(self.open_requested.emit)
        lo.addWidget(btn_open)

        btn_save = QPushButton("导出")
        btn_save.clicked.connect(self.save_requested.emit)
        lo.addWidget(btn_save)

        lo.addSpacing(15)

        # 编辑
        self._btn_undo = QPushButton("撤销")
        self._btn_undo.clicked.connect(self.undo_requested.emit)
        lo.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("重做")
        self._btn_redo.clicked.connect(self.redo_requested.emit)
        lo.addWidget(self._btn_redo)

        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self.delete_requested.emit)
        lo.addWidget(btn_del)

        lo.addSpacing(15)

        # 视角
        lbl_view = QLabel("视角:")
        lo.addWidget(lbl_view)

        for text, preset in (("顶", "top"), ("前", "front"), ("侧", "side"), ("等轴", "iso")):
            btn = QToolButton()
            btn.setText(text)
            btn.clicked.connect(lambda _=False, p=preset: self.view_preset_requested.emit(p))
            lo.addWidget(btn)

        btn_fit = QPushButton("适配")
        btn_fit.clicked.connect(self.reset_view_requested.emit)
        lo.addWidget(btn_fit)

        lo.addSpacing(15)

        # 点大小
        lbl_size = QLabel("点大小:")
        lo.addWidget(lbl_size)
        self._spin_size = QSpinBox()
        self._spin_size.setRange(1, 10)
        self._spin_size.setValue(1)
        self._spin_size.valueChanged.connect(self.point_size_changed.emit)
        lo.addWidget(self._spin_size)

        lo.addSpacing(15)

        # 选择工具
        self._btn_roi = QToolButton()
        self._btn_roi.setText("ROI框选")
        self._btn_roi.setCheckable(True)
        self._btn_roi.clicked.connect(lambda c: self.roi_mode_toggled.emit(c))
        lo.addWidget(self._btn_roi)

        lo.addSpacing(15)

        # Colorbar
        self._btn_colorbar = QToolButton()
        self._btn_colorbar.setText("Colorbar")
        self._btn_colorbar.setCheckable(True)
        self._btn_colorbar.clicked.connect(lambda c: self.colorbar_toggled.emit(c))
        lo.addWidget(self._btn_colorbar)

        # 背景
        self._btn_bg = QToolButton()
        self._btn_bg.setText("深色")
        self._btn_bg.setCheckable(True)
        self._btn_bg.setChecked(True)
        self._btn_bg.clicked.connect(lambda c: self.background_toggled.emit(not c))
        lo.addWidget(self._btn_bg)

        lo.addStretch(1)

    def set_roi_active(self, active: bool):
        self._btn_roi.setChecked(active)

    def set_undo_enabled(self, enabled: bool):
        """K4 落实现（K3 遗留①）：撤销栈为空时灰显，而非点了只落一条 warn。

        调用方 `cc_workspace.set_state` 早已接好，此前是空实现 → 按钮恒 enabled。
        """
        self._btn_undo.setEnabled(bool(enabled))

    def set_redo_enabled(self, enabled: bool):
        """K4 落实现（K3 遗留①）：同上。"""
        self._btn_redo.setEnabled(bool(enabled))

    def is_undo_enabled(self) -> bool:
        return self._btn_undo.isEnabled()

    def is_redo_enabled(self) -> bool:
        return self._btn_redo.isEnabled()
