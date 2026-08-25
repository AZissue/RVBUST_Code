# -*- coding: utf-8 -*-
"""
ui_v2.widgets.floating_log_panel —— 浮动日志面板。

特性：
  - 不挤占中央工作区，作为叠加层从右侧向内展开；
  - 顶部标题栏左上角带「折叠 / 关闭」按钮；
  - 支持拖拽标题栏移动位置；
  - 与 MainWindowShell 的日志按钮状态同步。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ..theme import BG_PANEL, BORDER, STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_PRIMARY, TEXT_SECONDARY


class FloatingLogPanel(QFrame):
    """可折叠的浮动日志面板（叠加在主窗口内容区上方）。"""

    closed = Signal()
    """用户点击关闭按钮时发射（通知外部取消日志按钮勾选）。"""

    _LEVEL_COLOR = {
        "info": TEXT_PRIMARY,
        "success": STATUS_OK,
        "warn": STATUS_WARN,
        "error": STATUS_ERR,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"FloatingLogPanel {{ background-color: {BG_PANEL}; "
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

        # ---- 标题栏（折叠按钮放右上角） ----
        self._title_bar = QFrame()
        self._title_bar.setStyleSheet(
            f"background-color: {BG_PANEL}; border-bottom: 1px solid {BORDER};"
        )
        title_lo = QHBoxLayout(self._title_bar)
        title_lo.setContentsMargins(6, 4, 6, 4)
        title_lo.setSpacing(6)

        title_lo.addWidget(QLabel("日志"))
        title_lo.addStretch(1)

        self._btn_collapse = QPushButton("−")
        self._btn_collapse.setFixedSize(22, 22)
        self._btn_collapse.setStyleSheet(
            "QPushButton { background-color: transparent; color: " + TEXT_SECONDARY + "; "
            "border: none; font-size: 14px; }"
            "QPushButton:hover { color: " + TEXT_PRIMARY + "; }"
        )
        self._btn_collapse.setToolTip("折叠日志")
        self._btn_collapse.clicked.connect(self._toggle_collapse)
        title_lo.addWidget(self._btn_collapse)

        self._btn_close = QPushButton("✕")
        self._btn_close.setFixedSize(22, 22)
        self._btn_close.setStyleSheet(
            "QPushButton { background-color: transparent; color: " + TEXT_SECONDARY + "; "
            "border: none; font-size: 12px; }"
            "QPushButton:hover { color: " + STATUS_ERR + "; }"
        )
        self._btn_close.setToolTip("关闭日志")
        self._btn_close.clicked.connect(self.closed.emit)
        title_lo.addWidget(self._btn_close)

        # 允许拖拽标题栏移动面板
        self._title_bar.mousePressEvent = self._on_title_press
        self._title_bar.mouseMoveEvent = self._on_title_move
        self._drag_pos = None

        root.addWidget(self._title_bar)

        # ---- 日志内容 ----
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            f"QPlainTextEdit {{ background-color: transparent; border: none; "
            f"color: {TEXT_PRIMARY}; }}"
        )
        root.addWidget(self._text, 1)

        self._collapsed = False
        self._normal_height = 320
        self.setMinimumSize(280, 160)
        self.resize(360, self._normal_height)

    # ------------------------------------------------------------ 公共接口
    def append(self, message: str, level: str = "info"):
        """追加一行日志。level: info / success / warn / error。"""
        color = self._LEVEL_COLOR.get(level, TEXT_PRIMARY)
        escaped = (message.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        self._text.appendHtml(f'<span style="color:{color}">{escaped}</span>')

    def clear(self):
        self._text.clear()

    # ------------------------------------------------------------ 内部
    def _toggle_collapse(self):
        if self._collapsed:
            self.resize(self.width(), self._normal_height)
            self._text.show()
            self._btn_collapse.setText("−")
            self._btn_collapse.setToolTip("折叠日志")
        else:
            self._normal_height = self.height()
            self.resize(self.width(), self._title_bar.height() + 6)
            self._text.hide()
            self._btn_collapse.setText("+")
            self._btn_collapse.setToolTip("展开日志")
        self._collapsed = not self._collapsed

    def _on_title_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _on_title_move(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
