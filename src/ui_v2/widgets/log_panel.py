# -*- coding: utf-8 -*-
"""
ui_v2.widgets.log_panel —— 日志面板（主窗口「日志」按钮 toggle 显示）。

接口与现有 CollapsibleLogPanel 对齐：append(str) / clear()。
后端日志（core.utils.logger）接入点在 MainWindowShell.log()，
空壳阶段由 UI 内部事件写入。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from ..theme import STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_PRIMARY


class LogPanel(QWidget):
    """只读日志视图，支持等级配色。"""

    _LEVEL_COLOR = {
        "info": TEXT_PRIMARY,
        "success": STATUS_OK,
        "warn": STATUS_WARN,
        "error": STATUS_ERR,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(0)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        lo.addWidget(self._text)

    # ------------------------------------------------------------ 公共接口
    def append(self, message: str, level: str = "info"):
        """追加一行日志。level: info / success / warn / error。"""
        color = self._LEVEL_COLOR.get(level, TEXT_PRIMARY)
        escaped = (message.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        self._text.appendHtml(f'<span style="color:{color}">{escaped}</span>')

    def clear(self):
        self._text.clear()
