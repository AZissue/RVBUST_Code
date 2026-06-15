"""
浮动 Toast 通知组件。
在窗口右上角显示自动消失的提示消息。
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QLabel, QWidget

import resources as res


class ToastOverlay(QWidget):
    """
    Toast 浮动通知。
    显示在父窗口右上角，3 秒后自动消失，用于操作结果的非阻塞反馈。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 设置为无边框、置顶的工具窗口（不抢焦点）
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)   # 透明背景
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # 不激活窗口

        # 消息标签
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMinimumWidth(300)
        self._label.setMinimumHeight(40)
        self._label.setWordWrap(True)

        # 自动隐藏定时器（单次触发）
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self.hide()

    def show_message(self, text, type_="success", duration_ms=3000):
        """
        显示 Toast 通知。
        text: 消息文本
        type_: "success"（绿色）或 "error"（红色）
        duration_ms: 显示时长（毫秒），默认 3 秒
        """
        # 根据类型选择背景色
        bg = res.SUCCESS if type_ == "success" else res.ERROR

        self._label.setText(text)
        self._label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: #FFFFFF;
                padding: 8px 24px;
                border-radius: 6px;
                font-size: {res.FONT_BODY}px;
            }}
        """)
        self._label.adjustSize()
        self.resize(self._label.size())

        # 定位到父窗口右上角（距离右边缘 24px，顶部 72px）
        if self.parent():
            pw = self.parent().width()
            self.move(pw - self.width() - 24, 72)

        self.show()
        self.raise_()  # 确保在最上层
        self._hide_timer.start(duration_ms)
