"""Bounded floating log, shared by production and prototypes."""
from collections import deque
from datetime import datetime
import logging
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox, QPlainTextEdit,
    QWidget, QFileDialog, QMessageBox)


class _Relay(QObject):
    message = Signal(str, str, str, str)


class _Handler(logging.Handler):
    def __init__(self, relay):
        super().__init__()
        self.relay = relay

    def emit(self, record):
        if getattr(record, 'activity_owned', False):
            return
        level = 'error' if record.levelno >= logging.ERROR else 'warn' if record.levelno >= logging.WARNING else 'info'
        try:
            self.relay.message.emit(record.getMessage(), level, str(getattr(record, 'frame_id', '')), record.name)
        except RuntimeError:
            pass


class ActivityLogPanel(QFrame):
    closed = Signal()
    COLORS = dict(info='#d6dce3', success='#80d69b', warn='#f1c86a', error='#ff7c82')
    LABELS = dict(info='信息', success='成功', warn='警告', error='错误')

    def __init__(self, parent=None, *, max_records=2000):
        super().__init__(parent)
        self.setObjectName('activityLog')
        self.setStyleSheet('QFrame#activityLog {background:#232b34;border:1px solid #475360;border-radius:5px;} QLabel {background:transparent;}')
        self.records = deque(maxlen=max_records)
        self._rendered_rows = []
        self._collapsed = False
        self._normal_height = 320
        self._drag_pos = None
        self._bindings = []
        self._relay = _Relay(self)
        self._relay.message.connect(self.append, Qt.QueuedConnection)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(75)
        self._render_timer.timeout.connect(self._render)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 5, 6, 6)
        root.setSpacing(5)
        self._title_bar = QFrame()
        header = QHBoxLayout(self._title_bar)
        header.setContentsMargins(2, 0, 2, 0)
        header.addWidget(QLabel('运行日志'), 1)
        self._btn_collapse = QPushButton('−')
        self._btn_close = QPushButton('×')
        for button in (self._btn_collapse, self._btn_close):
            button.setFixedSize(26, 25)
            button.setStyleSheet('QPushButton {padding:0px;}')
            header.addWidget(button)
        self._btn_collapse.setToolTip('折叠 / 展开日志')
        self._btn_close.setToolTip('关闭日志')
        self._btn_collapse.clicked.connect(self._toggle_collapse)
        self._btn_close.clicked.connect(self.closed.emit)
        self._title_bar.mousePressEvent = self._on_title_press
        self._title_bar.mouseMoveEvent = self._on_title_move
        root.addWidget(self._title_bar)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)
        filters = QHBoxLayout()
        self.level_filter = QComboBox()
        self.level_filter.addItem('全部等级', '')
        for level, label in self.LABELS.items():
            self.level_filter.addItem(label, level)
        filters.addWidget(self.level_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索内容 / 帧 / 任务')
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        body.addLayout(filters)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(max_records)
        body.addWidget(self._text, 1)
        footer = QHBoxLayout()
        self.auto_scroll = QCheckBox('自动滚动')
        self.auto_scroll.setChecked(True)
        footer.addWidget(self.auto_scroll)
        self.count = QLabel('0 条')
        footer.addWidget(self.count, 1)
        for label, callback in [('复制', self.copy_visible), ('导出', self.export_dialog), ('清空', self.clear)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            footer.addWidget(button)
        body.addLayout(footer)
        root.addWidget(self.body, 1)
        self.level_filter.currentIndexChanged.connect(self._schedule)
        self.search.textChanged.connect(self._schedule)
        self.auto_scroll.toggled.connect(self._schedule)
        self.setMinimumWidth(340)
        self.resize(540, self._normal_height)

    def attach_logger(self, logger):
        if any(item[0] is logger for item in self._bindings):
            return
        handler = _Handler(self._relay)
        logger.addHandler(handler)
        self._bindings.append((logger, handler))
        self.destroyed.connect(lambda *_: logger.removeHandler(handler))

    def detach_loggers(self):
        for logger, handler in self._bindings:
            logger.removeHandler(handler)
        self._bindings.clear()

    def append(self, message, level='info', frame='', task=''):
        level = 'warn' if level == 'warning' else level
        if level not in self.COLORS:
            level = 'info'
        stamp = datetime.now().astimezone().isoformat(timespec='seconds')
        self.records.append((stamp, level, str(frame), str(task), str(message).replace('\n', ' ↵ ')[:4000]))
        self._schedule()

    def appendPlainText(self, message):
        self.append(message)

    def toPlainText(self):
        return '\n'.join(self._line(row) for row in self.records)

    @staticmethod
    def _line(row):
        stamp, level, frame, task, text = row
        context = (' [帧 '+frame+']' if frame else '') + (' ['+task+']' if task else '')
        return f'{stamp} [{ActivityLogPanel.LABELS[level]}]{context} {text}'

    def visible_records(self):
        level = self.level_filter.currentData()
        query = self.search.text().strip().casefold()
        return [row for row in self.records if (not level or row[1] == level)
                and (not query or query in self._line(row).casefold())]

    def _schedule(self, *_):
        if self.isVisible() and not self._collapsed and not self._render_timer.isActive():
            self._render_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule()

    def _render(self):
        self._render_timer.stop()
        rows = self.visible_records()
        bar = self._text.verticalScrollBar()
        previous = bar.value()
        self._text.setUpdatesEnabled(False)
        old = self._rendered_rows
        incremental = len(rows) >= len(old) and all(a is b for a, b in zip(old, rows))
        if not incremental:
            self._text.clear()
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)
        start = len(old) if incremental else 0
        for index, row in enumerate(rows[start:], start):
            if index:
                cursor.insertBlock()
            style = QTextCharFormat()
            style.setForeground(QColor(self.COLORS[row[1]]))
            cursor.insertText(self._line(row), style)
        self._text.setUpdatesEnabled(True)
        self._rendered_rows = rows
        bar.setValue(bar.maximum() if self.auto_scroll.isChecked() else previous)
        self.count.setText(f'{len(rows)} / {len(self.records)} 条')

    def copy_visible(self):
        QApplication.clipboard().setText('\n'.join(self._line(row) for row in self.visible_records()))

    def export_to(self, path):
        Path(path).write_text('\n'.join(self._line(row) for row in self.visible_records()), encoding='utf-8')

    def export_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出当前筛选日志', 'scan_log.txt', '日志 (*.txt)')
        if path:
            try:
                self.export_to(path)
            except OSError as exc:
                QMessageBox.warning(self, '导出失败', str(exc))

    def clear(self):
        self.records.clear()
        self._render()

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._normal_height = self.height()
            self.body.hide()
            self.setFixedHeight(self._title_bar.sizeHint().height()+12)
        else:
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(180)
            self.body.show()
            self.resize(self.width(), self._normal_height)
            self._schedule()
        self._btn_collapse.setText('+' if self._collapsed else '−')

    def _on_title_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()-self.pos()
            event.accept()

    def _on_title_move(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            point = event.globalPosition().toPoint()-self._drag_pos
            parent = self.parentWidget()
            if parent:
                point.setX(max(0, min(point.x(), parent.width()-self.width())))
                point.setY(max(0, min(point.y(), parent.height()-self.height())))
            self.move(point)
            event.accept()
