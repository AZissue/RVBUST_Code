# -*- coding: utf-8 -*-
"""
ui_v2.widgets.floating_container —— 通用浮动容器。

可包裹任意 QWidget，提供：
  - 无边框浮动窗口；
  - 标题栏（标题 + 折叠/关闭按钮）；
  - 拖拽标题栏移动位置；
  - 折叠后仅保留标题栏。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..theme import BG_PANEL, BORDER, STATUS_ERR, TEXT_PRIMARY, TEXT_SECONDARY


class FloatingContainer(QFrame):
    """通用浮动容器，用于把任意控件做成可拖拽、可折叠的浮动面板。"""

    closed = Signal()
    """点击关闭按钮时发射。"""

    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"FloatingContainer {{ background-color: {BG_PANEL}; "
            f"border: none; border-radius: 6px; }}"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # ---- 标题栏 ----
        self._title_bar = QFrame()
        self._title_bar.setStyleSheet(
            f"background-color: {BG_PANEL}; border-bottom: 1px solid {BORDER};"
        )
        title_lo = QHBoxLayout(self._title_bar)
        title_lo.setContentsMargins(6, 4, 6, 4)
        title_lo.setSpacing(6)

        title_lo.addWidget(QLabel(title or "浮动面板"))
        title_lo.addStretch(1)

        self._btn_collapse = QPushButton("−")
        self._btn_collapse.setFixedSize(22, 22)
        self._btn_collapse.setStyleSheet(
            "QPushButton { background-color: transparent; color: " + TEXT_SECONDARY + "; "
            "border: none; font-size: 14px; }"
            "QPushButton:hover { color: " + TEXT_PRIMARY + "; }"
        )
        self._btn_collapse.setToolTip("折叠")
        self._btn_collapse.clicked.connect(self._toggle_collapse)
        title_lo.addWidget(self._btn_collapse)

        self._btn_close = QPushButton("✕")
        self._btn_close.setFixedSize(22, 22)
        self._btn_close.setStyleSheet(
            "QPushButton { background-color: transparent; color: " + TEXT_SECONDARY + "; "
            "border: none; font-size: 12px; }"
            "QPushButton:hover { color: " + STATUS_ERR + "; }"
        )
        self._btn_close.setToolTip("关闭")
        self._btn_close.clicked.connect(self.closed.emit)
        title_lo.addWidget(self._btn_close)

        # 允许拖拽标题栏移动面板
        self._title_bar.mousePressEvent = self._on_title_press
        self._title_bar.mouseMoveEvent = self._on_title_move
        self._drag_pos = None

        root.addWidget(self._title_bar)

        # ---- 内容区 ----
        self._content = QFrame()
        self._content.setStyleSheet("background-color: transparent; border: none;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setSpacing(0)
        root.addWidget(self._content, 1)

        self._collapsed = False
        self._normal_height = 320
        self.setMinimumSize(280, 120)
        self.resize(520, self._normal_height)

    def set_widget(self, widget: QWidget):
        """设置容器内部控件。"""
        # 清空旧内容
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._content_layout.addWidget(widget)

    def set_title(self, title: str):
        """更新标题栏文字。"""
        layout = self._title_bar.layout()
        if layout and layout.count() > 0:
            item = layout.itemAt(0)
            if item and item.widget():
                item.widget().setText(title)

    # ------------------------------------------------------------ 内部
    def _toggle_collapse(self):
        if self._collapsed:
            self.resize(self.width(), self._normal_height)
            self._content.show()
            self._btn_collapse.setText("−")
            self._btn_collapse.setToolTip("折叠")
        else:
            self._normal_height = self.height()
            self.resize(self.width(), self._title_bar.height() + 6)
            self._content.hide()
            self._btn_collapse.setText("+")
            self._btn_collapse.setToolTip("展开")
        self._collapsed = not self._collapsed

    def _on_title_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _on_title_move(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
