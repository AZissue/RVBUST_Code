"""Polygon picking overlay: child of the canvas, locks navigation while active."""
from PySide6.QtCore import Qt, QEvent, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class PolygonSelectionOverlay(QWidget):
    polygon_closed = Signal(list)
    cancelled = Signal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._vertices = []
        self._cursor = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        canvas.installEventFilter(self)
        self.setGeometry(canvas.rect())
        self.deactivate()

    def eventFilter(self, obj, event):
        if obj is self._canvas and event.type() == QEvent.Resize:
            self.setGeometry(self._canvas.rect())
        return False

    @property
    def active(self):
        return self.isVisible()

    def activate(self):
        self._vertices = []
        self._cursor = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setGeometry(self._canvas.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    def deactivate(self):
        self._vertices = []
        self._cursor = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._vertices.append((event.position().x(), event.position().y()))
            self._cursor = event.position()
            self.update()
            event.accept()
        elif event.button() == Qt.RightButton:
            self._close()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._close()
            event.accept()

    def mouseMoveEvent(self, event):
        self._cursor = event.position()
        self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _close(self):
        if len(self._vertices) >= 3:
            self.polygon_closed.emit(list(self._vertices))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(15, 15, 15, 70))
        lines = ['框选模式：左键添加顶点，双击或右键闭合（至少 3 点），Esc 取消']
        if self._vertices:
            lines.append(f'已添加 {len(self._vertices)} 个顶点')
        metrics = painter.fontMetrics()
        line_height = metrics.height() + 4
        banner_width = max(metrics.horizontalAdvance(line) for line in lines) + 48
        banner_height = len(lines) * line_height + 18
        banner = QRectF((self.width() - banner_width) / 2, 10, banner_width, banner_height)
        painter.setPen(QPen(QColor('#D32F2F'), 1))
        painter.setBrush(QColor(30, 32, 38, 220))
        painter.drawRoundedRect(banner, 8, 8)
        painter.setPen(QColor('#E8EAED'))
        for i, line in enumerate(lines):
            painter.drawText(QRectF(banner.left(), banner.top() + 9 + i * line_height,
                                    banner.width(), line_height), Qt.AlignCenter, line)
        if self._vertices:
            painter.setPen(QPen(QColor('#d32f2f'), 2))
            polygon = QPolygonF([QPointF(x, y) for x, y in self._vertices])
            painter.drawPolyline(polygon)
            if self._cursor is not None:
                painter.setPen(QPen(QColor('#ff8a80'), 1, Qt.DashLine))
                painter.drawLine(QPointF(*self._vertices[-1]), self._cursor)
            painter.setBrush(QColor('#d32f2f'))
            painter.setPen(Qt.NoPen)
            for x, y in self._vertices:
                painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
        painter.end()
