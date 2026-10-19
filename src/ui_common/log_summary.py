"""One-line log preview with queued delivery from Python logging threads."""
from datetime import datetime
from itertools import count
import logging
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy


class _Relay(QObject):
    message = Signal(str, str, float, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.sequence = count()


class _SummaryHandler(logging.Handler):
    def __init__(self, relay):
        super().__init__(logging.INFO)
        self.relay = relay

    def emit(self, record):
        level = ('error' if record.levelno >= logging.ERROR else
                 'warn' if record.levelno >= logging.WARNING else
                 getattr(record, 'ui_level', 'info'))
        try:
            self.relay.message.emit(record.getMessage(), level, record.created,
                                    next(self.relay.sequence))
        except RuntimeError:
            pass  # A worker may finish while its owning dialog is being destroyed.


class LogSummary(QFrame):
    COLORS = dict(info='#aaaaaa', success='#80d69b', warn='#f1c86a', error='#ff7c82')
    LABELS = dict(info='信息', success='成功', warn='警告', error='错误')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('logSummary')
        self.setFixedHeight(32)
        self._bindings = []
        self._relay = _Relay(self)
        self._relay.message.connect(self.append, Qt.QueuedConnection)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 9, 0)
        layout.setSpacing(10)
        layout.addWidget(QLabel('最新日志'))
        self.badge = QLabel()
        layout.addWidget(self.badge)
        self.message = QLabel()
        self.message.setTextFormat(Qt.PlainText)
        self.message.setMinimumWidth(0)
        self.message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.message, 1)
        self.full_text = ''
        self.level = 'info'
        self._last_sequence = -1
        self.append('等待操作；警告和错误将在此显示。')

    def attach_logger(self, logger):
        if any(bound is logger for bound, _ in self._bindings):
            return
        handler = _SummaryHandler(self._relay)
        logger.addHandler(handler)
        self._bindings.append((logger, handler))
        self.destroyed.connect(lambda *_: logger.removeHandler(handler))

    def detach_loggers(self):
        for logger, handler in self._bindings:
            logger.removeHandler(handler)
        self._bindings.clear()

    def append(self, message, level='info', created=None, sequence=None):
        created = time.time() if created is None else created
        sequence = next(self._relay.sequence) if sequence is None else sequence
        if sequence < self._last_sequence:
            return
        self._last_sequence = sequence
        level = 'warn' if level == 'warning' else level
        self.level = level if level in self.COLORS else 'info'
        stamp = datetime.fromtimestamp(created).strftime('%H:%M:%S')
        self.full_text = f'{stamp}  ' + ' '.join(str(message).split())[:4000]
        self.badge.setText(self.LABELS[self.level])
        color = self.COLORS[self.level]
        self.badge.setStyleSheet(f'color:{color};background:transparent;')
        self.setStyleSheet(f'QFrame#logSummary {{background:#242424;border:1px solid #454545;border-left:3px solid {color};border-radius:3px;}}')
        self.message.setStyleSheet(f'color:{color};background:transparent;')
        self.setToolTip(self.full_text)
        self._elide()

    def _elide(self):
        self.message.setText(self.message.fontMetrics().elidedText(
            self.full_text, Qt.ElideRight, max(0, self.message.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()
