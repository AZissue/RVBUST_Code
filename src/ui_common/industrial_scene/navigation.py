"""One mouse contract for GPU and software canvases; no drag-distance threshold."""
import numpy as np
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter
from .trackball import Trackball


class _RotationOverlay(QWidget):
    """Qt compositor layer keeps annotations independent of native GL state."""
    def __init__(self, canvas):
        super().__init__(canvas)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet('background:transparent; border:0;')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.parentWidget()._paint_rotation_geometry(painter)
        self.parentWidget()._paint_cloud_markers(painter)
        self.parentWidget()._paint_navigation_pivot(painter)
        painter.end()


class NavigationMixin:
    def _init_navigation(self):
        self._rotation_geometry = None
        self._cloud_markers = []
        self.marker_centers = True
        self._rotation_overlay = _RotationOverlay(self)
        self._rotation_overlay.setGeometry(self.rect())
        self.rotation = Trackball()
        self._drag_button = Qt.NoButton
        self._last = None
        self._navigation_enabled = True
        self._pivot_highlight = False
        self._pivot_flash = QTimer(self)
        self._pivot_flash.setSingleShot(True)
        self._pivot_flash.setInterval(650)
        self._pivot_flash.timeout.connect(self._hide_pivot_highlight)
        self.setFocusPolicy(Qt.StrongFocus)

    def _notify_view_changed(self):
        self._rotation_overlay.setVisible(self._rotation_geometry is not None or bool(self._cloud_markers)
            or self._navigation_pivot_visible())
        self._rotation_overlay.raise_()
        self._rotation_overlay.update()
        self.update()
        if hasattr(self, 'view_changed'):
            self.view_changed.emit()

    def set_rotation_geometry(self, axis=None, center=None):
        self._rotation_geometry = None
        if axis is not None and center is not None:
            axis, center = np.asarray(axis, dtype=float), np.asarray(center, dtype=float)
            if axis.shape == (3,) and center.shape == (3,) and np.isfinite(axis).all() and np.isfinite(center).all() and np.linalg.norm(axis) > 1e-9:
                self._rotation_geometry = (axis / np.linalg.norm(axis), center.copy())
        self._rotation_overlay.setVisible(self._rotation_geometry is not None or bool(self._cloud_markers)
            or self._navigation_pivot_visible())
        self._rotation_overlay.raise_()
        self._rotation_overlay.update()
        self.update()

    def set_cloud_markers(self, points):
        self._cloud_markers = list(points)
        self._rotation_overlay.setVisible(self._rotation_geometry is not None or bool(self._cloud_markers)
            or self._navigation_pivot_visible())
        self._rotation_overlay.raise_()
        self._rotation_overlay.update()

    def _paint_cloud_markers(self, painter):
        if not self.marker_centers or not self._cloud_markers:
            return
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPen
        xyz = np.asarray([item[1][0] for item in self._cloud_markers], dtype=float)
        camera = (xyz-self.center) @ self.rotation.matrix.T
        scale = min(self.width(), self.height())*1.65/self.extent*self.zoom
        pixels = camera[:, :2]*[scale, -scale] + [self.width()/2+self.pan[0], self.height()/2+self.pan[1]]
        painter.save()
        painter.setClipRect(self.rect())
        painter.setBrush(Qt.NoBrush)
        occupied = [child.geometry() for child in self.children() if isinstance(child, QWidget)
                    and child.objectName() == 'markerInspector' and child.isVisible()]
        for (code, (_, color)), (x, y) in zip(self._cloud_markers, pixels):
            if not np.isfinite([x, y]).all() or not 0 <= x < self.width() or not 0 <= y < self.height():
                continue
            point = QPointF(x, y)
            painter.setPen(QPen(QColor('#202226'), 4))
            painter.drawEllipse(point, 6, 6)
            painter.setPen(QPen(QColor(color), 2))
            painter.drawEllipse(point, 6, 6)
            painter.drawLine(point+QPointF(-9, 0), point+QPointF(9, 0))
            painter.drawLine(point+QPointF(0, -9), point+QPointF(0, 9))
            painter.setPen(QPen(QColor('#202226'), 3))
            label = f'ID {code}'
            box = None
            for level in range(5):
                for side in (1, -1):
                    for vertical in (-1, 1):
                        candidate = painter.fontMetrics().boundingRect(label).adjusted(-3, -2, 3, 2)
                        left = x+11 if side > 0 else x-11-candidate.width()
                        top = y-10-candidate.height()-level*18 if vertical < 0 else y+10+level*18
                        candidate.moveTopLeft(QPointF(left, top).toPoint())
                        if self.rect().contains(candidate) and not any(candidate.adjusted(-2, -2, 2, 2).intersects(other) for other in occupied):
                            box = candidate
                            break
                    if box is not None:
                        break
                if box is not None:
                    break
            if box is None:
                continue  # Keep the centre visible when the label cannot fit.
            occupied.append(box)
            painter.setPen(QPen(QColor(color), 1))
            painter.drawLine(point, QPointF(box.center()))
            painter.fillRect(box, QColor(24, 26, 29, 210))
            painter.setPen(QColor(color))
            painter.drawText(box, Qt.AlignCenter, label)
        painter.restore()

    def _paint_rotation_geometry(self, painter):
        if self._rotation_geometry is None:
            return
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPen
        axis, center = self._rotation_geometry
        # Draw the visible portion of an infinite axis near the current view,
        # while marking the actual gauge-fixed centre independently.
        base = center + axis * np.dot(self.center-center, axis)
        length = max(self.extent*.25, 10.)
        points = np.asarray([base-axis*length, base+axis*length, center])
        rotated = (points-self.center) @ self.rotation.matrix.T
        scale = min(self.width(), self.height())*1.65/self.extent*self.zoom
        xy = rotated[:, :2]*[scale, -scale] + [self.width()/2+self.pan[0], self.height()/2+self.pan[1]]
        if not np.isfinite(xy).all() or np.max(np.abs(xy)) > 1e7:
            return
        painter.save()
        painter.setClipRect(self.rect())
        painter.setPen(QPen(QColor('#50d4e8'), 2, Qt.DashLine))
        painter.drawLine(QPointF(*xy[0]), QPointF(*xy[1]))
        direction = xy[1]-xy[0]
        norm = np.linalg.norm(direction)
        if norm > 1:
            direction /= norm
            tip = xy[1]
            side = np.array([-direction[1], direction[0]])
            for sign in (-1, 1):
                painter.drawLine(QPointF(*tip), QPointF(*(tip-direction*12+sign*side*5)))
            painter.drawText(QPointF(*((xy[0]+xy[1])*.5+[12, 20])), '旋转轴')
        p = QPointF(*xy[2])
        painter.setPen(QPen(QColor('#ff8c7e'), 2))
        painter.drawEllipse(p, 5, 5)
        painter.drawLine(p+QPointF(-10, 0), p+QPointF(10, 0))
        painter.drawLine(p+QPointF(0, -10), p+QPointF(0, 10))
        painter.drawText(p+QPointF(12, -10), '旋转中心')
        painter.restore()

    def _pivot_pixel(self):
        return self.width()/2+self.pan[0], self.height()/2+self.pan[1]

    def _paint_navigation_pivot(self, painter):
        if not self._navigation_pivot_visible():
            return
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPen
        x, y = self._pivot_pixel()
        if not np.isfinite([x, y]).all() or not self.rect().contains(QPointF(x, y).toPoint()):
            return
        p = QPointF(x, y)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#171a20'), 1))
        painter.setBrush(QColor('#ffe45c'))
        painter.drawEllipse(p, 5, 5)
        painter.restore()

    def _navigation_pivot_visible(self):
        return self._pivot_highlight or (self._last is not None and self._drag_button == Qt.LeftButton)

    def _hide_pivot_highlight(self):
        self._pivot_flash.stop()
        self._pivot_highlight = False
        self._notify_view_changed()

    def set_pivot(self, point):
        """Change orbit centre without a jump in the projected scene."""
        point = np.asarray(point, dtype=float)
        shift = self.rotation.matrix @ (point-self.center)
        scale = min(self.width(), self.height())*1.65/self.extent*self.zoom
        self.pan += [shift[0]*scale, -shift[1]*scale]
        self.center = point.copy()
        self._pivot_highlight = True
        self._pivot_flash.start()
        self._notify_view_changed()

    def set_view(self, name):
        self.rotation.set_view(name)
        self._notify_view_changed()

    def mousePressEvent(self, event):
        if event.button() not in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            event.ignore()
            return
        self.setFocus(Qt.MouseFocusReason)
        if event.button() == Qt.MiddleButton:
            # Picking must not enter the reduced-detail drag path. Restore the
            # static scene first, including a pending drag/wheel LOD timeout.
            self._cancel_drag()
            self._restore.stop()
            self._end_interaction()
            point = self.pick_pivot(event.position())
            if point is not None:
                self.set_pivot(point)
            event.accept()
            return
        self._drag_button = event.button()
        self._pivot_flash.stop()
        self._pivot_highlight = False
        self._last = event.position()
        self.setCursor(Qt.ClosedHandCursor)
        self._begin_interaction()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        if not event.buttons() & self._drag_button:
            self._cancel_drag()
            return
        current = event.position()
        delta = current-self._last
        if self._drag_button == Qt.RightButton:
            self.pan += [delta.x(), delta.y()]
        else:
            self.rotation.drag((self._last.x(), self._last.y()), (current.x(), current.y()),
                               self.width(), self.height(), self._pivot_pixel())
        self._last = current
        self._begin_interaction()
        event.accept()

    def _cancel_drag(self):
        self._last = None
        self._drag_button = Qt.NoButton
        self.setCursor(Qt.OpenHandCursor)
        if getattr(self, '_navigation_enabled', False):
            self._restore.start(220)
            self._notify_view_changed()

    def mouseReleaseEvent(self, event):
        if event.button() == self._drag_button:
            remaining = event.buttons() & (Qt.LeftButton | Qt.RightButton)
            if remaining:
                self._drag_button = next(button for button in (Qt.RightButton, Qt.LeftButton)
                                         if remaining & button)
                self._last = event.position()
                self._begin_interaction()
            else:
                self._cancel_drag()
        event.accept()

    def axis_endpoints(self):
        origin = np.array([45., self.height()-65.])
        for index, (label, color) in enumerate([('X', '#f18484'), ('Y', '#b4dc79'), ('Z', '#84c4ff')]):
            axis = self.rotation.matrix[:, index]
            yield label, color, origin, origin+32*np.array([axis[0], -axis[1]])

    def wheelEvent(self, event):
        self._pivot_flash.stop()
        self._pivot_highlight = False
        steps = event.angleDelta().y()/120
        if not steps and not event.pixelDelta().isNull():
            steps = event.pixelDelta().y()/60
        self.zoom = float(np.clip(self.zoom*1.12**steps, .1, 25))
        self._begin_interaction()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # Qt sends a double-click event instead of the second press. Keep
        # dragging consistent, but never use a left double-click to pick.
        self.mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_F, Qt.Key_Z):
            self.fit_view()
            event.accept()
        else:
            super().keyPressEvent(event)

    def event(self, event):
        if event.type() == QEvent.Resize and hasattr(self, '_rotation_overlay'):
            self._rotation_overlay.setGeometry(self.rect())
        if event.type() in (QEvent.UngrabMouse, QEvent.WindowDeactivate, QEvent.FocusOut):
            if getattr(self, '_last', None) is not None:
                self._cancel_drag()
        return super().event(event)

    def _stop_navigation(self):
        self._navigation_enabled = False
        self._last = None
        self._pivot_flash.stop()
        self._pivot_highlight = False
        self._restore.stop()
