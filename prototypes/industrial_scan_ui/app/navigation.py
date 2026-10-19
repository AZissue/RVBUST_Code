"""One mouse contract for GPU and software canvases; no drag-distance threshold."""
import numpy as np
from PySide6.QtCore import Qt, QEvent
from ..core.trackball import Trackball


class NavigationMixin:
    def _init_navigation(self):
        self.rotation = Trackball()
        self._drag_button = Qt.NoButton
        self._last = None
        self._navigation_enabled = True
        self.setFocusPolicy(Qt.StrongFocus)

    def _pivot_pixel(self):
        return self.width()/2+self.pan[0], self.height()/2+self.pan[1]

    def set_pivot(self, point):
        """Change orbit centre without a jump in the projected scene."""
        point = np.asarray(point, dtype=float)
        shift = self.rotation.matrix @ (point-self.center)
        scale = min(self.width(), self.height())*1.65/self.extent*self.zoom
        self.pan += [shift[0]*scale, -shift[1]*scale]
        self.center = point.copy()
        self.update()

    def set_view(self, name):
        self.rotation.set_view(name)
        self.update()

    def mousePressEvent(self, event):
        if event.button() not in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            event.ignore()
            return
        self.setFocus(Qt.MouseFocusReason)
        self._drag_button = event.button()
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
        if self._drag_button in (Qt.RightButton, Qt.MiddleButton) or event.modifiers() & Qt.ShiftModifier:
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

    def mouseReleaseEvent(self, event):
        if event.button() == self._drag_button:
            remaining = event.buttons() & (Qt.LeftButton | Qt.RightButton | Qt.MiddleButton)
            if remaining:
                self._drag_button = next(button for button in (Qt.RightButton, Qt.MiddleButton, Qt.LeftButton)
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
        steps = event.angleDelta().y()/120
        if not steps and not event.pixelDelta().isNull():
            steps = event.pixelDelta().y()/60
        self.zoom = float(np.clip(self.zoom*1.12**steps, .1, 25))
        self._begin_interaction()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            point = self.pick_pivot(event.position())
            if point is not None:
                self.set_pivot(point)
        self._cancel_drag()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_F, Qt.Key_Z):
            self.fit_view()
            event.accept()
        else:
            super().keyPressEvent(event)

    def event(self, event):
        if event.type() in (QEvent.UngrabMouse, QEvent.WindowDeactivate, QEvent.FocusOut):
            if getattr(self, '_last', None) is not None:
                self._cancel_drag()
        return super().event(event)

    def _stop_navigation(self):
        self._navigation_enabled = False
        self._last = None
        self._restore.stop()
