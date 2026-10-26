"""Polygon picking overlay: two-stage state machine (drawing -> confirmed/staged)."""
from PySide6.QtCore import Qt, QEvent, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget, QApplication


class PolygonSelectionOverlay(QWidget):
    polygon_confirmed = Signal(list)
    cancelled = Signal()
    changed = Signal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._vertices = []
        self._cursor = None
        self._confirmed_polygon = None
        self._confirmed_info = ''
        self._view_locked = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        canvas.installEventFilter(self)
        self.setGeometry(canvas.rect())
        self.clear()

    def eventFilter(self, obj, event):
        if obj is self._canvas and self._view_locked:
            if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                    QEvent.MouseButtonDblClick, QEvent.MouseMove, QEvent.Wheel,
                    QEvent.NativeGesture, QEvent.Gesture):
                event.accept()
                return True
            if event.type() in (QEvent.KeyPress, QEvent.ShortcutOverride):
                if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                    self.cancelled.emit()
                event.accept()
                return True
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
    def view_locked(self):
        return self._view_locked

    def set_confirmed(self, polygon):
        """Keep the staged screen-space polygon attached to its frozen view."""
        self._vertices = list(polygon)
        self._confirmed_polygon = list(polygon)
        self._view_locked = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        # Run before other canvas filters, including middle-button navigation.
        self._canvas.removeEventFilter(self)
        self._canvas.installEventFilter(self)
        self.setGeometry(self._canvas.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    @property
    def vertex_count(self):
        return len(self._vertices)

    def activate(self):
        self._view_locked = False
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
        self.changed.emit()

    def clear(self):
        self._view_locked = False
        self._vertices = []
        self._cursor = None
        self._confirmed_polygon = None
        self._confirmed_info = ''
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()
        self.changed.emit()

    def cancel(self):
        self.cancelled.emit()

    def show_confirmed(self, info):
        self._confirmed_info = str(info)
        self.update()

    def remove_last_vertex(self):
        if self._confirmed_polygon is None and self._vertices:
            self._vertices.pop()
            self.update()
            self.changed.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            QApplication.sendEvent(self._canvas, event)
            return
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
            self.changed.emit()
            event.accept()
        elif event.button() == Qt.RightButton:
            self._confirm()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._confirmed_polygon is None:
            self._confirm()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MiddleButton:
            QApplication.sendEvent(self._canvas, event)
            return
        self._cursor = event.position()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            QApplication.sendEvent(self._canvas, event)
        else:
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
        self.changed.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(15, 15, 15, 70))
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
