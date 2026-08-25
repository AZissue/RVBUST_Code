# -*- coding: utf-8 -*-
"""
ui_v2.widgets.mode_card —— 启动小窗的工作模式选择卡片。

两张卡片上下排列（多相机外参标定 / 单相机移动拼接），
自绘可选中卡片，选中态仅保留 RVC 红边框。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from .. import icons as ui_icons
from ..theme import (
    ACCENT, ACCENT_DIM, BG_CARD, BORDER, TEXT_PRIMARY, TEXT_SECONDARY,
)


class ModeCard(QFrame):
    """可选中的模式卡片（图标 + 模式名 + 一句话说明）。"""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, desc: str, parent=None):
        super().__init__(parent)
        self._checked = False
        self._icon_name = icon_name

        lo = QHBoxLayout(self)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(12)

        self._icon = QLabel()
        self._icon.setFixedSize(32, 32)
        self._icon.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self._title = QLabel(title)
        self._title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {TEXT_PRIMARY};")
        text_col.addWidget(self._title)
        self._desc = QLabel(desc)
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")
        text_col.addWidget(self._desc)
        lo.addLayout(text_col, 1)

        # 选中圆点指示
        self._dot = QLabel("●")
        self._dot.setFixedWidth(18)
        self._dot.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._dot)

        self.setCursor(Qt.PointingHandCursor)
        self.setChecked(False)

    def is_checked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        self._checked = checked
        # 选中态：图标着 RVC 红；未选中：次要文本色
        icon_color = ACCENT if checked else TEXT_SECONDARY
        self._icon.setPixmap(ui_icons.pixmap(self._icon_name, icon_color, 28))
        if checked:
            self.setStyleSheet(
                f"ModeCard {{ background-color: {BG_CARD};"
                f" border: 2px solid {ACCENT}; border-radius: 8px; }}")
            self._dot.setStyleSheet(f"color: {ACCENT}; font-size: 14px;")
        else:
            self.setStyleSheet(
                f"ModeCard {{ background-color: {BG_CARD};"
                f" border: none; border-radius: 8px; }}")
            self._dot.setStyleSheet("color: transparent; font-size: 14px;")

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)
