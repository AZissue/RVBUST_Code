"""Polygon picking overlay: two-stage state machine (drawing -> confirmed/staged)."""
from PySide6.QtCore import Qt, QEvent, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class PolygonSelectionOverlay(QWidget):
    polygon_confirmed = Signal(list)
    cancelled = Signal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._vertices = []
        self._cursor = None
        self._confirmed_polygon = None
        self._confirmed_info = ''
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        canvas.installEventFilter(self)
        self.setGeometry(canvas.rect())
        self.clear()

    def eventFilter(self, obj, event):
        if obj is self._canvas and event.type() == QEvent.Resize:
            self.setGeometry(self._canvas.rect())
            if self._vertices or self._confirmed_polygon is not None:
                self.cancelled.emit()
        return False

    @property
    def active(self):
        return self.isVisible()

    @property
    def has_mask(self):
        return self._confirmed_polygon is not None

    @property
    def confirmed_polygon(self):
        return self._confirmed_polygon

    @property
    def vertex_count(self):
        return len(self._vertices)

    def activate(self):
        self._vertices = []
        self._cursor = None
        self._confirmed_polygon = None
        self._confirmed_info = ''
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setGeometry(self._canvas.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    def clear(self):
        self._vertices = []
        self._cursor = None
        self._confirmed_polygon = None
        self._confirmed_info = ''
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def cancel(self):
        self.cancelled.emit()

    def show_confirmed(self, info):
        self._confirmed_info = str(info)
        self.update()

    def remove_last_vertex(self):
        if self._confirmed_polygon is None and self._vertices:
            self._vertices.pop()
            self.update()

    def mousePressEvent(self, event):
        if self._confirmed_polygon is not None:
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.AltModifier:
                self.remove_last_vertex()
            else:
                self._vertices.append((event.position().x(), event.position().y()))
                self._cursor = event.position()
            self.update()
            event.accept()
        elif event.button() == Qt.RightButton:
            self._confirm()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._confirmed_polygon is None:
            self._confirm()
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

    def _confirm(self):
        if self._confirmed_polygon is not None or len(self._vertices) < 3:
            return
        self._confirmed_polygon = list(self._vertices)
        self.polygon_confirmed.emit(list(self._confirmed_polygon))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(15, 15, 15, 70))
        if self._confirmed_polygon is not None:
            lines = [f'已封闭 {len(self._confirmed_polygon)} 顶点' + (f'；{self._confirmed_info}' if self._confirmed_info else ''),
                     '请在左侧选择 保留框内 / 保留框外，或按 Esc / 放弃框选 丢弃']
        else:
            lines = ['框选模式：左键添加顶点，Alt+左键撤销顶点，右键或双击封闭（至少 3 点），Esc 取消']
            if self._vertices:
                lines.append(f'已添加 {len(self._vertices)} 个顶点')
        metrics = painter.fontMetrics()
        line_height = metrics.height() + 4
        banner_width = max(metrics.horizontalAdvance(line) for line in lines) + 48
        banner_height = len(lines) * line_height + 18
        banner = QRectF((self.width() - banner_width) / 2, 70, banner_width, banner_height)
        painter.setPen(QPen(QColor('#D32F2F'), 1))
        painter.setBrush(QColor(30, 32, 38, 220))
        painter.drawRoundedRect(banner, 8, 8)
        painter.setPen(QColor('#E8EAED'))
        for i, line in enumerate(lines):
            painter.drawText(QRectF(banner.left(), banner.top() + 9 + i * line_height,
                                    banner.width(), line_height), Qt.AlignCenter, line)
        outline = self._confirmed_polygon if self._confirmed_polygon is not None else self._vertices
        if outline:
            painter.setPen(QPen(QColor('#d32f2f'), 2))
            painter.setBrush(Qt.NoBrush)
            polygon = QPolygonF([QPointF(x, y) for x, y in outline])
            if self._confirmed_polygon is not None:
                painter.drawPolygon(polygon)
            else:
                painter.drawPolyline(polygon)
                if self._cursor is not None:
                    painter.setPen(QPen(QColor('#ff8a80'), 1, Qt.DashLine))
                    painter.drawLine(QPointF(*outline[-1]), self._cursor)
            painter.setBrush(QColor('#d32f2f'))
            painter.setPen(Qt.NoPen)
            for x, y in outline:
                painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
        painter.end()
