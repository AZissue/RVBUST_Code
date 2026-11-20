"""Shared 2D canvas: image-space geometry and screen-space annotations."""
from math import isfinite
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QPolygonF
from PySide6.QtWidgets import QWidget
from .industrial_scene.marker_display import GREEN, RED, YELLOW, MarkerDisplay, classify_markers

def load_image(image):
    if isinstance(image, QImage):
        return image.copy()
    if isinstance(image, np.ndarray):
        pixels = image
        if pixels.dtype == np.uint16:
            pixels = (pixels/256).astype(np.uint8)
        pixels = np.ascontiguousarray(np.clip(pixels, 0, 255), dtype=np.uint8)
        if pixels.ndim == 2:
            return QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_Grayscale8).copy()
        if pixels.ndim == 3 and pixels.shape[2] == 3:
            return QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_BGR888).copy()
        if pixels.ndim == 3 and pixels.shape[2] == 4:
            return QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_ARGB32).copy()
        raise ValueError('2D图像需为灰度、BGR或BGRA数组')
    return QImage() if image is None else QImage(str(image))


class ImagePreviewCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.display = MarkerDisplay((), frozenset(), frozenset(), False)
        self.match_triangle = ()
        self.feature_points = ()
        self.feature_overlay = QImage()
        self.feature_regions = ()
        self.setFixedHeight(175)
        self.zoom = 1.0
        self.pan = QPointF()
        self._drag = None
        self._fill = False

    def set_image(self, image, markers=None):
        """Set a numpy/QImage/path image and optional raw pixel-coordinate markers."""
        self.image = load_image(image)
        if markers is not None:
            self.set_marker_data(markers)
        self.update()

    def set_marker_data(self, markers, reference_markers=None):
        """Shared raw detector interface; retains ellipse, validity and pair semantics."""
        self.display = classify_markers(markers or [], reference_markers)
        self.update()

    def set_fill(self, enabled):
        self._fill = bool(enabled)
        self.update()

    def reset_view(self):
        self.zoom = 1.
        self.pan = QPointF()
        self._drag = None
        self.update()

    def clear_image(self):
        self.image = QImage()
        self.display = MarkerDisplay((), frozenset(), frozenset(), False)
        self.match_triangle = ()
        self.feature_points = ()
        self.feature_overlay = QImage()
        self.feature_regions = ()
        self.reset_view()

    def wheelEvent(self,event):
        if not event.angleDelta().y():
            event.ignore()
            return
        self.zoom=max(.2,min(20,self.zoom*(1.15 if event.angleDelta().y()>0 else 1/1.15)))
        self.update();event.accept()

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self._drag=event.position()

    def mouseMoveEvent(self,event):
        if self._drag is not None:
            self.pan+=event.position()-self._drag;self._drag=event.position();self.update()

    def mouseReleaseEvent(self,event):self._drag=None
    def mouseDoubleClickEvent(self,event):
        self.reset_view()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#1c1c1c'))
        if self.image.isNull():
            painter.setPen(QColor('#aaaaaa'))
            painter.drawText(self.rect(), Qt.AlignCenter, '未关联当前帧2D图像')
            return
        scale = (max if self._fill else min)(self.width()/self.image.width(), self.height()/self.image.height())*self.zoom
        width, height = self.image.width()*scale, self.image.height()*scale
        x, y = (self.width()-width)/2+self.pan.x(), (self.height()-height)/2+self.pan.y()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(QRectF(x, y, width, height), self.image)
        if not self.feature_overlay.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            painter.drawImage(QRectF(x, y, width, height), self.feature_overlay)
        painter.setRenderHint(QPainter.Antialiasing)
        for box, color in self.feature_regions:
            painter.setPen(QPen(QColor(color), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(x+box[0]*scale, y+box[1]*scale,
                                    (box[2]-box[0])*scale, (box[3]-box[1])*scale))
        if self.match_triangle:
            painter.setPen(QPen(QColor(YELLOW), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(QPolygonF([QPointF(x+px*scale, y+py*scale) for px, py in self.match_triangle]))
        colors = (YELLOW, RED, GREEN, '#56c9ff')
        for px, py, category in self.feature_points:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors[category]))
            painter.drawEllipse(QPointF(x + px * scale, y + py * scale), 2.5, 2.5)
        for row in self.display.rows:
            px, py = x+row.xy[0]*scale, y+row.xy[1]*scale
            if not 0 <= row.xy[0] < self.image.width() or not 0 <= row.xy[1] < self.image.height():
                continue
            center = QPointF(px, py)
            self._draw_circle(painter, row, center, scale)

    @staticmethod
    def _draw_circle(painter, row, center, scale):
        radius_x = radius_y = 6.0
        angle = 0.0
        try:
            width, height, rotation = map(float, row.marker.get('ellipse_2d', ()))
            if width > 0 and height > 0 and all(map(isfinite, (width, height, rotation))):
                radius_x, radius_y = width*scale/2, height*scale/2
                angle = rotation
        except (TypeError, ValueError):
            pass  # Older rows can lack ellipse data.

        painter.save()
        painter.translate(center)
        painter.rotate(angle)
        painter.setPen(QPen(QColor(GREEN if row.marker.get('marker_type') == 'unencoded_circle' else row.color), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(), radius_x, radius_y)
        painter.restore()

        color = QColor(row.color)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, 2, 2)
        if row.code is not None:
            painter.setPen(color)
            painter.drawText(center + QPointF(6, -6), str(row.code))
