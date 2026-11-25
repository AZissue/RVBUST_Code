from math import cos, hypot, pi, sin

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


def flange_faces():
    # An original demonstration part in millimetres with no external assets.
    profile = (
        (53, 0), (56, 3), (56, 12), (53, 15), (36, 15), (34, 18),
        (34, 43), (31, 47), (27, 47), (27, 60), (24, 63), (16, 63),
        (13, 60), (13, 13), (16, 9), (16, 0), (53, 0),
    )
    faces = []

    def add_profile(points, count, center=(0, 0), tone=1.0):
        cx, cy = center
        for (r0, z0), (r1, z1) in zip(points, points[1:]):
            if z0 == z1 == 15:
                continue
            for i in range(count):
                a, b = 2 * pi * i / count, 2 * pi * (i + 1) / count
                mid = (a + b) / 2
                vertices = (
                    (cx + r0 * cos(a), cy + r0 * sin(a), z0),
                    (cx + r0 * cos(b), cy + r0 * sin(b), z0),
                    (cx + r1 * cos(b), cy + r1 * sin(b), z1),
                    (cx + r1 * cos(a), cy + r1 * sin(a), z1),
                )
                normal = ((z1 - z0) * cos(mid), (z1 - z0) * sin(mid), r0 - r1)
                length = ((z1 - z0) ** 2 + (r1 - r0) ** 2) ** 0.5
                faces.append((vertices, tuple(value / length for value in normal), tone))

    add_profile(profile, 64)
    for index in range(8):
        angle = index * pi / 4
        center_x, center_y = 45 * cos(angle), 45 * sin(angle)
        start, end = angle - pi / 8, angle + pi / 8
        boundary = (
            [(36 + 17 * i / 8, start) for i in range(8)]
            + [(53, start + (end - start) * i / 8) for i in range(8)]
            + [(53 - 17 * i / 8, end) for i in range(8)]
            + [(36, end - (end - start) * i / 8) for i in range(8)]
        )
        outer, rim, floor = [], [], []
        for radius, theta in boundary:
            x, y = radius * cos(theta), radius * sin(theta)
            dx, dy = x - center_x, y - center_y
            distance = hypot(dx, dy)
            hole_x = center_x + 5.4 * dx / distance
            hole_y = center_y + 5.4 * dy / distance
            outer.append((x, y, 15))
            rim.append((hole_x, hole_y, 15))
            floor.append((hole_x, hole_y, 6))

        for i in range(len(boundary)):
            j = (i + 1) % len(boundary)
            faces.append(((outer[i], outer[j], rim[j], rim[i]), (0, 0, 1), 1.0))
            nx = center_x - (rim[i][0] + rim[j][0]) / 2
            ny = center_y - (rim[i][1] + rim[j][1]) / 2
            length = hypot(nx, ny)
            faces.append(((rim[i], rim[j], floor[j], floor[i]), (nx / length, ny / length, 0), 0.65))
        faces.append((tuple(floor), (0, 0, 1), 0.32))
    return faces


class PartViewport(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("partViewport")
        self.setMinimumSize(360, 300)
        self.setAccessibleName("工件三维演示视窗")
        self.setToolTip("拖动旋转 · 滚轮缩放 · 双击复位")
        self.faces = flange_faces()
        self.sample_visible = True
        self.drag_origin = None
        self.reset_view()

    def reset_view(self):
        self.yaw = -0.31
        self.elevation = 0.59
        self.zoom = 1.0
        self.update()

    def set_sample_visible(self, visible):
        self.sample_visible = visible
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.sample_visible:
            self.drag_origin = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_origin is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self.drag_origin
        self.drag_origin = event.position()
        self.yaw += delta.x() * 0.012
        self.elevation = max(-1.36, min(1.36, self.elevation + delta.y() * 0.009))
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = None
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = None
            self.unsetCursor()
            self.reset_view()
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if not self.sample_visible:
            super().wheelEvent(event)
            return
        self.zoom = max(0.55, min(2.35, self.zoom * (1.15 ** (event.angleDelta().y() / 120))))
        self.update()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QLinearGradient(0, 0, 0, self.height())
        background.setColorAt(0, QColor("#1b1b1b"))
        background.setColorAt(1, QColor("#272727"))
        painter.fillRect(self.rect(), background)
        self.draw_scene(painter)

    def draw_scene(self, painter):
        width, height = self.width(), self.height()
        scale = min(width / 194, height / 145) * self.zoom
        cx, cy = width / 2, height * 0.64
        ca, sa = cos(self.yaw), sin(self.yaw)
        ce, se = cos(self.elevation), sin(self.elevation)

        def transform(x, y, z):
            x, y = x * ca - y * sa, x * sa + y * ca
            return x, -(y * se + z * ce), -y * ce + z * se

        def project(vertex):
            x, y, depth = transform(*vertex)
            return QPointF(cx + x * scale, cy + y * scale), depth

        painter.setPen(QPen(QColor("#383838"), 1))
        for tick in range(-140, 141, 14):
            painter.drawLine(project((tick, -140, -1))[0], project((tick, 140, -1))[0])
            painter.drawLine(project((-140, tick, -1))[0], project((140, tick, -1))[0])

        grid_fade = QLinearGradient(0, 0, 0, height * 0.65)
        grid_fade.setColorAt(0, QColor(27, 27, 27, 220))
        grid_fade.setColorAt(1, QColor(27, 27, 27, 0))
        painter.fillRect(self.rect(), grid_fade)

        if self.sample_visible:
            self.draw_part(painter, project, transform)
        else:
            painter.setPen(QColor("#b6b6b6"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "当前视图为空")

        origin = QPointF(39, height - 35)
        for direction, color, label in (
            ((1, 0, 0), "#ef777e", "X"),
            ((0, 1, 0), "#c6c6c6", "Y"),
            ((0, 0, 1), "#8d8d8d", "Z"),
        ):
            x, y, _ = transform(*direction)
            tip = origin + QPointF(x * 22, y * 22)
            painter.setPen(QPen(QColor(color), 1.6))
            painter.drawLine(origin, tip)
            painter.drawText(tip + QPointF(4, -2), label)

    def draw_part(self, painter, project, transform):
        visible_faces = []
        for vertices, normal, tone in self.faces:
            nx, ny, nz = transform(*normal)
            if nz <= 0:
                continue
            light = max(0, -0.42 * nx - 0.64 * ny + 0.64 * nz)
            brightness = (0.52 + 0.52 * light) * tone
            color = QColor(*(min(255, round(channel * brightness)) for channel in (205, 76, 83)))
            projected = [project(vertex) for vertex in vertices]
            depth = sum(vertex[1] for vertex in projected) / len(projected)
            visible_faces.append((depth, QPolygonF([point for point, _ in projected]), color))

        # Opaque faces are drawn back to front so the bore and flange read in depth.
        for _, polygon, color in sorted(visible_faces, key=lambda face: face[0]):
            painter.setPen(QPen(color, 0.75))
            painter.setBrush(color)
            painter.drawPolygon(polygon)

