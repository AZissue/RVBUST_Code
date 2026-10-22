# -*- coding: utf-8 -*-
"""耗时操作反馈：静态文案与连续旋转指示器。"""

from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ..theme import ACCENT, TEXT_PRIMARY, TEXT_SECONDARY


class _BusyIndicator(QWidget):
    """按实际经过的时间绘制，避免事件循环抖动导致旋转忽快忽慢。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self.phase = 0.0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = QRectF(7, 7, 34, 34)
        painter.setPen(QPen(QColor('#404047'), 3))
        painter.drawEllipse(ring)
        pen = QPen(QColor(ACCENT), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        span = 100 + 35 * math.sin(self.phase * 2 * math.pi)
        painter.drawArc(ring, round((90 - self.phase * 360) * 16), round(-span * 16))


class LoadingOverlay(QWidget):
    """轻量非模态提示，沿用 show/update/hide 接口及鼠标穿透行为。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('loadingOverlay')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 保持为父窗口内的控件，避免置顶窗口抢焦点或脱离主窗口。
        self.setStyleSheet('QWidget#loadingOverlay { background: transparent; }')

        self._container = QWidget(self)
        self._container.setObjectName('loadingCard')
        # 精确选择器防止边框、圆角和内边距被 QLabel 继承。
        self._container.setStyleSheet(f'''
            QWidget#loadingCard {{
                background: #27272B; border: 1px solid #4A4A50; border-radius: 12px;
            }}
            QWidget#loadingCard QWidget {{ background: transparent; border: 0; padding: 0; }}
            QLabel#loadingTitle {{ color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 600; }}
            QLabel#loadingDetail {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
        ''')
        content = QVBoxLayout(self._container)
        content.setContentsMargins(22, 22, 22, 22)
        content.setSpacing(14)

        row = QHBoxLayout()
        row.setSpacing(14)
        self._spinner = _BusyIndicator(self._container)
        row.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignTop)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 3, 0, 0)
        text_column.setSpacing(6)
        self._label = QLabel()
        self._label.setObjectName('loadingTitle')
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._detail = QLabel()
        self._detail.setObjectName('loadingDetail')
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        text_column.addWidget(self._label)
        text_column.addWidget(self._detail)
        row.addLayout(text_column, 1)
        content.addLayout(row)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addStretch(1)
        root.addWidget(self._container, 0, Qt.AlignmentFlag.AlignCenter)
        root.addStretch(1)

        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._base_text = ''
        self._set_message('处理中...')
        if parent is not None:
            parent.installEventFilter(self)
        self.hide()

    def _set_message(self, text: str):
        self._base_text = text.strip().rstrip('.…') or '处理中'
        title, separator, detail = self._base_text.partition('；')
        self._label.setText(title)
        self._detail.setText(detail.strip() if separator and detail.strip()
                             else '任务完成后将自动关闭')
        self.setAccessibleName(self._base_text)

    def _fit_parent(self):
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._container.setFixedWidth(max(1, min(380, self.width() - 32)))

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._fit_parent()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_parent()
        if not self._clock.isValid():
            self._clock.start()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        if not self._clock.isValid():
            return
        milliseconds = self._clock.elapsed()
        self._spinner.phase = (milliseconds % 1400) / 1400.0
        self._spinner.update()

    def show_message(self, text: str = '处理中...'):
        self._set_message(text)
        self._clock.start()
        self._tick()
        self._fit_parent()
        self.show()
        self.raise_()
        QApplication.processEvents()

    def update_message(self, text: str):
        """更新任务文案，保留当前动画相位。"""
        self._set_message(text)
        QApplication.processEvents()

    def hide_overlay(self):
        self.hide()
        self._timer.stop()
        QApplication.processEvents()
