"""Software point preview: bounded sampling, works without an OpenGL context."""
import numpy as np
from PySide6.QtCore import Qt, QPointF, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QLinearGradient
from PySide6.QtWidgets import QWidget
from .navigation import NavigationMixin


class CloudCanvas(NavigationMixin, QWidget):
    view_changed = Signal()
    status_changed = Signal()
    MAX_PREVIEW = 18000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.zoom = 1.
        self.pan = np.zeros(2)
        self.center = np.zeros(3)
        self.extent = 340.
        self.grid = True
        self.axes = True
        self.point_size = 2
        self.color_mode = '原始颜色'
        self._points = np.empty((0, 3))
        self._colors = np.empty((0, 3))
        self.total_points = 0
        self._last = None
        self._layers = []
        self._moving = False
        self.backend_name = '兼容软件预览（不具备 GPU 大点云能力）'
        self._restore = QTimer(self)
        self._restore.setSingleShot(True)
        self._restore.timeout.connect(self._end_interaction)
        self._init_navigation()

    @property
    def is_busy(self):
        return False

    @property
    def displayed_points(self):
        return len(self._points)

    def set_policy(self, name):
        # Explicit compatibility path, never claims the GPU point budget.
        pass

    def shutdown(self):
        self._stop_navigation()

    def _begin_interaction(self):
        if not self._moving:
            self._moving = True
            self.set_layers(self._layers)
        self._restore.start(220)
        self._notify_view_changed()

    def _end_interaction(self):
        if self._last is not None:
            self._restore.start(220)
            return
        self._moving = False
        self.set_layers(self._layers)

    def set_layers(self, layers, fit=False):
        self._layers = list(layers)
        budget = min(self.MAX_PREVIEW, 3000) if self._moving else self.MAX_PREVIEW
        visible = [layer for layer in layers if layer.visible]
        self.total_points = sum(len(layer.points) for layer in visible)
        points, colors = [], []
        # One global sample budget independent of the number of imported layers.
        cumulative = 0
        for layer in visible:
            begin = cumulative * budget // max(1, self.total_points)
            cumulative += len(layer.points)
            end = cumulative * budget // max(1, self.total_points)
            count = min(len(layer.points), end - begin)
            if not count:
                continue
            idx = np.linspace(0, len(layer.points) - 1, count, dtype=int)
            sample = np.asarray(layer.points)[idx]
            valid = np.isfinite(sample).all(axis=1) & (np.abs(sample).sum(axis=1) > 0)
            sample = sample[valid]
            points.append(sample)
            colors.append(np.asarray(layer.colors)[idx][valid] if layer.colors is not None else
                          np.tile([.66, .81, .91], (len(sample), 1)))
        self._points = np.vstack(points) if points else np.empty((0, 3))
        self._colors = np.vstack(colors) if colors else np.empty((0, 3))
        if fit:
            self.fit_view()
        self.update()
        self.status_changed.emit()

    def fit_view(self):
        self._pivot_flash.stop()
        self._pivot_highlight = False
        if len(self._points):
            low, high = self._points.min(axis=0), self._points.max(axis=0)
            self.center = (low + high) / 2
            self.extent = max(float(np.linalg.norm(high - low)), 10.)
        self.zoom = 1.0
        self.pan[:] = 0
        self._notify_view_changed()

    def project(self, points):
        rotated = (np.asarray(points) - self.center) @ self.rotation.matrix.T
        scale = min(self.width(), self.height()) * 1.65 / self.extent * self.zoom
        xy = rotated[:, :2] * [scale, -scale]
        xy += [self.width() / 2 + self.pan[0], self.height() / 2 + self.pan[1]]
        return xy, rotated[:, 2]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor('#777777'))
        gradient.setColorAt(1, QColor('#494949'))
        painter.fillRect(self.rect(), gradient)
        if self.grid:
            step = 10 ** np.floor(np.log10(self.extent / 12))
            radius = step * 15
            z = min(0, self.center[2] - self.extent * .06)
            painter.setPen(QPen(QColor(194, 216, 157, 65), 1))
            for v in np.arange(-radius, radius + step / 2, step):
                for line in ([[v, -radius, z], [v, radius, z]],
                             [[-radius, v, z], [radius, v, z]]):
                    xy, _ = self.project(np.asarray(line) + [self.center[0], self.center[1], 0])
                    painter.drawLine(QPointF(*xy[0]), QPointF(*xy[1]))
        if len(self._points):
            xy, depth = self.project(self._points)
            valid = (xy[:, 0] >= 0) & (xy[:, 0] < self.width()) & (xy[:, 1] >= 0) & (xy[:, 1] < self.height())
            xy, depth = xy[valid], depth[valid]
            colors = self._colors[valid]
            if self.color_mode == '高度着色':
                z = self._points[valid, 2]
                t = (z - z.min()) / max(float(np.ptp(z)), 1e-6) if len(z) else z
                colors = np.column_stack((.25 + .65 * t, .7 + .2 * t, .95 - .65 * t))
            elif self.color_mode == '统一颜色':
                colors = np.tile([.66, .81, .91], (len(xy), 1))
            # Quantize colors for batch painting rather than a Python draw call per point.
            bins = np.clip((colors * 5).astype(int), 0, 5)
            ids = bins[:, 0] * 36 + bins[:, 1] * 6 + bins[:, 2]
            for value in np.unique(ids):
                mask = ids == value
                color = QColor.fromRgbF(*np.clip(colors[mask].mean(axis=0), 0, 1))
                painter.setPen(QPen(color, self.point_size, Qt.SolidLine, Qt.RoundCap))
                painter.drawPoints(QPolygonF([QPointF(float(x), float(y)) for x, y in xy[mask]]))
        painter.setPen(QColor('#e4e9ed'))
        painter.drawText(22, 31, '3D VIEW / 正交投影预览')
        painter.setPen(QColor('#c9d0d5'))
        painter.drawText(22, 53, f'{self.total_points:,} 点  ·  预览 {len(self._points):,} 点  ·  mm')
        middle = '中键拖动平移' if self.property('postprocessMiddlePan') else '中键设旋转中心'
        painter.drawText(22, self.height() - 20, f'左键旋转 · 右键拖动平移 · {middle} · 滚轮缩放 · F/Z 适配')
        if self.axes:
            for label, color, origin_xy, end_xy in self.axis_endpoints():
                origin, end = QPointF(*origin_xy), QPointF(*end_xy)
                painter.setPen(QPen(QColor(color), 2))
                painter.drawLine(origin, end)
                painter.drawText(end + QPointF(3, -3), label)

    def pick_pivot(self, position):
        if not len(self._points):
            return None
        xy, depth = self.project(self._points)
        distance = np.linalg.norm(xy-[position.x(), position.y()], axis=1)
        candidates = np.flatnonzero(distance <= max(3., self.point_size))
        if not len(candidates):
            return None
        return self._points[candidates[np.argmax(depth[candidates])]].copy()
