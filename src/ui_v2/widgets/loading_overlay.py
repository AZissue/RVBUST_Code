# -*- coding: utf-8 -*-
"""
ui_v2.widgets.loading_overlay —— 加载遮罩（重设计版）。

与现有 ``src/ui/loading_overlay.py`` 接口对齐：
  show_message(str) / hide_overlay()

视觉差异：边框改用 RVC 品牌红，面板色跟随新主题。
耗时操作（拍摄 / 标定 / 拼接 / 自动设IP）统一经此遮罩反馈。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ..theme import ACCENT, BG_PANEL, TEXT_PRIMARY


class LoadingOverlay(QWidget):
    """覆盖父窗口的半透明加载遮罩。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 160);")

        container = QWidget(self)
        container.setStyleSheet(
            f"background-color: {BG_PANEL}; border: 2px solid {ACCENT};"
            "border-radius: 10px; padding: 20px;"
        )
        lay = QVBoxLayout(container)
        lay.setContentsMargins(30, 24, 30, 24)

        self._label = QLabel("处理中...")
        self._label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700;")
        self._label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._label)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)
        root.addWidget(container, 0, Qt.AlignCenter)
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._base_text = "处理中"
        self._dots = 0
        self.hide()

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self._label.setText(f"{self._base_text}{'.' * self._dots}")

    # ------------------------------------------------------------ 公共接口
    def show_message(self, text: str = "处理中..."):
        self._base_text = text.rstrip(".")
        self._dots = 0
        self._label.setText(self._base_text)
        parent = self.parentWidget()
        if parent:
            # 覆盖父窗口整个区域（QMainWindow 也包含 dock、工具栏等）
            self.setGeometry(0, 0, parent.width(), parent.height())
        self.show()
        self.raise_()
        self._timer.start(400)
        QApplication.processEvents()

    def hide_overlay(self):
        self._timer.stop()
        self.hide()
        QApplication.processEvents()
