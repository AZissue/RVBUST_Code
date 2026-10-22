"""Reusable Qt busy spinner, message card and parent-bound loading overlay.

No application, workflow, device or ui_v2 imports. Animation runs only while
visible. No elapsed-time label or invented progress percentage is displayed.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .appearance import LoadingAppearance

__all__ = ['LoadingSpinner', 'LoadingCard', 'LoadingOverlay']


class LoadingSpinner(QWidget):
    """Standalone animated ring; hide/close/parent destruction stop its timer."""

    def __init__(self, parent=None, *, appearance=None):
        super().__init__(parent)
        self._appearance = appearance or LoadingAppearance()
        self.setFixedSize(48, 48)
        self.phase = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def restart(self):
        self._clock.start()
        self._tick()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._clock.isValid():
            self._clock.start()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        if self._clock.isValid():
            self.phase = (self._clock.elapsed() % 1400) / 1400.0
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = QRectF(7, 7, 34, 34)
        painter.setPen(QPen(QColor(self._appearance.ring), 3))
        painter.drawEllipse(ring)
        pen = QPen(QColor(self._appearance.accent), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        span = 100 + 35 * math.sin(self.phase * 2 * math.pi)
        painter.drawArc(ring, round((90-self.phase*360)*16), round(-span*16))


class LoadingCard(QWidget):
    """Embeddable spinner/title/detail card, independent from overlay behavior."""

    def __init__(self, parent=None, *, appearance=None):
        super().__init__(parent)
        appearance = appearance or LoadingAppearance()
        self.setObjectName('loadingCard')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.setStyleSheet(f'''
            QWidget#loadingCard {{
                background:{appearance.background}; border:1px solid {appearance.border}; border-radius:12px;
            }}
            QWidget#loadingCard QWidget {{ background:transparent; border:0; padding:0; }}
            QLabel#loadingTitle {{ color:{appearance.text}; font-size:15px; font-weight:600; }}
            QLabel#loadingDetail {{ color:{appearance.muted}; font-size:12px; }}
        ''')
        self.setMaximumWidth(appearance.card_width)
        row = QHBoxLayout(self)
        row.setContentsMargins(22, 22, 22, 22)
        row.setSpacing(14)
        self.spinner = LoadingSpinner(self, appearance=appearance)
        row.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setContentsMargins(0, 3, 0, 0)
        column.setSpacing(6)
        self.title_label = QLabel()
        self.title_label.setObjectName('loadingTitle')
        self.detail_label = QLabel()
        self.detail_label.setObjectName('loadingDetail')
        for label in (self.title_label, self.detail_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            column.addWidget(label)
        row.addLayout(column, 1)
        self.set_message('处理中...')

    def set_message(self, text: str, detail=None):
        """Accept a title/detail pair or legacy 'title；detail...' message."""
        message = text.strip().rstrip('.…') or '处理中'
        title, separator, suffix = message.partition('；')
        self.title_label.setText(title)
        self.detail_label.setText(str(detail) if detail is not None else
                                  suffix.strip() if separator and suffix.strip() else '任务完成后将自动关闭')
        self.setAccessibleName(title + '；' + self.detail_label.text())


class LoadingOverlay(QWidget):
    """Parent-bound feedback. block_input=True intercepts pointer events.

    Call on the GUI thread; keep expensive work on the existing worker runner.
    The overlay does not create workers, start SDKs, or change business gates.
    """

    def __init__(self, parent=None, *, appearance=None, block_input=False):
        super().__init__(parent)
        self._appearance = appearance or LoadingAppearance()
        self.setObjectName('loadingOverlay')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not block_input)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, not block_input)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        background = self._appearance.scrim if block_input else 'transparent'
        self.setStyleSheet(f'QWidget#loadingOverlay {{ background:{background}; }}')
        self.card = LoadingCard(self, appearance=self._appearance)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addStretch(1)
        root.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)
        root.addStretch(1)
        if parent is not None:
            parent.installEventFilter(self)
        self.hide()

    def _fit_parent(self):
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.card.setFixedWidth(max(1, min(self._appearance.card_width, self.width()-32)))

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._fit_parent()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_parent()

    def show_message(self, text: str = '处理中...', *, detail=None):
        self.update_message(text, detail=detail)
        self.card.spinner.restart()
        self._fit_parent()
        self.show()
        self.raise_()
        QApplication.processEvents()

    def update_message(self, text: str, *, detail=None):
        """Update text without restarting the animation or pumping GUI events."""
        self.card.set_message(text, detail)
        self.setAccessibleName(self.card.accessibleName())

    def hide_overlay(self):
        self.hide()
        QApplication.processEvents()
