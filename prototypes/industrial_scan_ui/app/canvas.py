"""Software point preview: bounded sampling, works without an OpenGL context."""
import numpy as np
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QLinearGradient
from PySide6.QtWidgets import QWidget


class CloudCanvas(QWidget):
    view_changed = Signal()
    MAX_PREVIEW = 18000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.yaw, self.pitch, self.zoom = -28., 57., 1.
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

    def set_layers(self, layers, fit=False):
        visible = [layer for layer in layers if layer.visible]
        self.total_points = sum(len(layer.points) for layer in visible)
        points, colors = [], []
        # One global sample budget independent of the number of imported layers.
        cumulative = 0
        for layer in visible:
            begin = cumulative * self.MAX_PREVIEW // max(1, self.total_points)
            cumulative += len(layer.points)
            end = cumulative * self.MAX_PREVIEW // max(1, self.total_points)
            count = min(len(layer.points), end - begin)
            if not count:
                continue
            idx = np.linspace(0, len(layer.points) - 1, count, dtype=int)
            points.append(layer.points[idx])
            colors.append(layer.colors[idx] if layer.colors is not None else
                          np.tile([.66, .81, .91], (count, 1)))
        self._points = np.vstack(points) if points else np.empty((0, 3))
        self._colors = np.vstack(colors) if colors else np.empty((0, 3))
        if fit:
            self.fit_view()
        self.update()

    def fit_view(self):
        if len(self._points):
            low, high = self._points.min(axis=0), self._points.max(axis=0)
            self.center = (low + high) / 2
            self.extent = max(float(np.linalg.norm(high - low)), 10.)
        self.zoom = 1.0
        self.pan[:] = 0
        self.update()

    def set_view(self, name):
        self.yaw, self.pitch = {'等轴测': (-28, 57), '顶视': (0, 0),
                               '正视': (0, 90), '右视': (90, 90)}[name]
        self.update()

    def project(self, points):
        yaw, pitch = np.radians([self.yaw, self.pitch])
        rz = np.array([[np.cos(yaw), -np.sin(yaw), 0],
                       [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
        rx = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)],
                       [0, np.sin(pitch), np.cos(pitch)]])
        rotated = (np.asarray(points) - self.center) @ (rx @ rz).T
        scale = min(self.width(), self.height()) * 1.65 / self.extent * self.zoom
        xy = rotated[:, :2] * [scale, -scale]
        xy += [self.width() / 2 + self.pan[0], self.height() / 2 + self.pan[1] + 18]
        return xy, rotated[:, 2]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor('#727980'))
        gradient.setColorAt(1, QColor('#454d55'))
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
        painter.drawText(22, self.height() - 20, '左键旋转   ·   右键 / Shift 平移   ·   滚轮缩放   ·   双击适配')
        painter.setPen(QPen(QColor('#aab5bf'), 1))
        painter.setBrush(QColor('#59636d'))
        painter.drawRoundedRect(self.width() - 78, 24, 52, 48, 6, 6)
        painter.setPen(QColor('#e4e9ed'))
        painter.drawText(self.width() - 78, 24, 52, 48, Qt.AlignCenter, 'TOP')
        if self.axes:
            origin = QPointF(45, self.height() - 65)
            for label, color, delta in [('X', '#f18484', (31, 9)), ('Y', '#b4dc79', (-17, 17)), ('Z', '#84c4ff', (0, -34))]:
                end = origin + QPointF(*delta)
                painter.setPen(QPen(QColor(color), 2))
                painter.drawLine(origin, end)
                painter.drawText(end + QPointF(3, -3), label)

    def mousePressEvent(self, event):
        if event.position().x() > self.width() - 90 and event.position().y() < 82:
            self.set_view('顶视')
            return
        self._last = event.position()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        delta = event.position() - self._last
        if event.buttons() & Qt.RightButton or event.modifiers() & Qt.ShiftModifier:
            self.pan += [delta.x(), delta.y()]
        elif event.buttons() & Qt.LeftButton:
            self.yaw += delta.x() * .45
            self.pitch = np.clip(self.pitch + delta.y() * .45, -170, 170)
        self._last = event.position()
        self.update()

    def mouseReleaseEvent(self, event):
        self._last = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event):
        self.zoom = float(np.clip(self.zoom * 1.12 ** (event.angleDelta().y() / 120), .1, 25))
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.fit_view()
