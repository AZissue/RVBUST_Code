# -*- coding: utf-8 -*-
"""
加载遮罩层（LoadingOverlay）—— 耗时操作期间显示忙碌状态。

特性：
  - 半透明黑色遮罩覆盖整个父窗口，阻止用户点击其他控件；
  - 中央显示提示文本 + 循环点动画（如 "处理中." → "处理中.." → "处理中..."）；
  - show_message(text) 显示遮罩并强制刷新 UI；
  - hide_overlay() 隐藏遮罩并恢复交互。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QApplication,
)


class LoadingOverlay(QWidget):
    """加载提示：背景不遮挡父窗口，中央显示带框面板的操作文字。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 透明背景，不拦截鼠标事件
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        # 中央醒目面板
        container = QWidget(self)
        container.setStyleSheet(
            "background-color: #1E1F24; border: 2px solid #2979FF; "
            "border-radius: 10px; padding: 20px;"
        )
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(30, 24, 30, 24)

        self.label = QLabel("处理中...")
        self.label.setStyleSheet(
            "color: #E8EAED; font-size: 14pt; font-weight: bold;"
            "background-color: transparent;"
        )
        self.label.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(self.label)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addStretch(1)
        main_layout.addWidget(container, 0, Qt.AlignCenter)
        main_layout.addStretch(1)

        # 循环点动画定时器
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._update_dots)
        self._base_text = "处理中"
        self._dots_count = 0

        self.hide()

    def _update_dots(self):
        """更新循环点动画：. → .. → ... → . → ..."""
        self._dots_count = (self._dots_count + 1) % 4
        dots = "." * self._dots_count if self._dots_count > 0 else ""
        self.label.setText(f"{self._base_text}{dots}")

    def show_message(self, text: str = "处理中..."):
        """在中央显示操作文字并刷新 UI（同步耗时操作前调用）。"""
        # 去掉用户传入文本末尾的点，由动画统一控制
        self._base_text = text.rstrip(".")
        self._dots_count = 0
        self.label.setText(self._base_text)
        if self.parentWidget():
            self.resize(self.parentWidget().size())
        self.show()
        self.raise_()
        self._anim_timer.start(400)  # 400ms 切换一次，节奏适中
        QApplication.processEvents()

    def hide_overlay(self):
        """隐藏提示。"""
        self._anim_timer.stop()
        self.hide()
        QApplication.processEvents()
