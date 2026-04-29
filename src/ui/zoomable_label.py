import numpy as np
import cv2
from PySide6.QtWidgets import QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QWheelEvent, QMouseEvent


class ZoomableImageLabel(QLabel):
    """支持滚轮缩放、双击恢复、右键拖动的图像显示控件（修复内存安全）"""
    scale_changed = Signal(float)

    _MAX_IMAGE_SIZE = 1920

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_pixmap = None
        self._current_scale = 1.0
        self._min_scale = 0.1
        self._max_scale = 5.0
        self._scale_step = 0.1

        self._is_panning = False
        self._pan_start_pos = None
        self._pan_offset = [0, 0]
        self._last_pan_offset = [0, 0]

        self._scaled_pixmap_cache = None
        self._cached_scale = None

        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setScaledContents(False)
        self.setMouseTracking(True)

    def set_image(self, image: np.ndarray, reset_zoom=True):
        if image is None:
            self._original_pixmap = None
            self._current_scale = 1.0
            self._pan_offset = [0, 0]
            self._last_pan_offset = [0, 0]
            self._scaled_pixmap_cache = None
            self._cached_scale = None
            self.clear()
            return

        h, w = image.shape[:2]
        if max(h, w) > self._MAX_IMAGE_SIZE:
            scale = self._MAX_IMAGE_SIZE / max(h, w)
            image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)

        if len(image.shape) == 3:
            image = np.ascontiguousarray(image)
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb_image.shape
            bytes_per_line = channels * width
            # 深拷贝确保内存安全
            q_image = QImage(rgb_image.data, width, height, bytes_per_line, QImage.Format_RGB888).copy()
        else:
            image = np.ascontiguousarray(image)
            height, width = image.shape
            q_image = QImage(image.data, width, height, width, QImage.Format_Grayscale8).copy()

        self._original_pixmap = QPixmap.fromImage(q_image)
        self._scaled_pixmap_cache = None
        self._cached_scale = None

        if reset_zoom:
            self._current_scale = 1.0
            self._pan_offset = [0, 0]
            self._last_pan_offset = [0, 0]

        self._update_display()

    def _update_display(self):
        if self._original_pixmap is None:
            return

        if self._cached_scale == self._current_scale and self._scaled_pixmap_cache is not None:
            scaled_pixmap = self._scaled_pixmap_cache
            new_width = scaled_pixmap.width()
            new_height = scaled_pixmap.height()
        else:
            new_width = int(self._original_pixmap.width() * self._current_scale)
            new_height = int(self._original_pixmap.height() * self._current_scale)
            transform_mode = Qt.FastTransformation if new_width * new_height > 1000000 else Qt.SmoothTransformation
            scaled_pixmap = self._original_pixmap.scaled(new_width, new_height, Qt.KeepAspectRatio, transform_mode)
            self._scaled_pixmap_cache = scaled_pixmap
            self._cached_scale = self._current_scale

        widget_w = self.width()
        widget_h = self.height()

        offset_x = max(-max(0, (new_width - widget_w) // 2), min(self._pan_offset[0], max(0, (new_width - widget_w) // 2)))
        offset_y = max(-max(0, (new_height - widget_h) // 2), min(self._pan_offset[1], max(0, (new_height - widget_h) // 2)))
        self._pan_offset = [offset_x, offset_y]

        if new_width > widget_w or new_height > widget_h:
            display_pixmap = QPixmap(widget_w, widget_h)
            display_pixmap.fill(Qt.black)
            painter = QPainter(display_pixmap)
            base_x = (widget_w - new_width) // 2
            base_y = (widget_h - new_height) // 2
            painter.drawPixmap(base_x - offset_x, base_y - offset_y, scaled_pixmap)
            painter.end()
            super().setPixmap(display_pixmap)
        else:
            super().setPixmap(scaled_pixmap)

    def wheelEvent(self, event: QWheelEvent):
        if self._original_pixmap is None:
            return
        delta = event.angleDelta().y()
        if delta > 0:
            new_scale = min(self._current_scale + self._scale_step, self._max_scale)
        else:
            new_scale = max(self._current_scale - self._scale_step, self._min_scale)
        if new_scale != self._current_scale:
            self._current_scale = new_scale
            self._update_display()
            self.scale_changed.emit(self._current_scale)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if self._original_pixmap is None:
            return
        self._current_scale = 1.0
        self._pan_offset = [0, 0]
        self._last_pan_offset = [0, 0]
        self._update_display()
        self.scale_changed.emit(self._current_scale)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if self._original_pixmap is None:
            return
        if event.button() == Qt.RightButton:
            self._is_panning = True
            self._pan_start_pos = event.pos()
            self._last_pan_offset = self._pan_offset.copy()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        elif event.button() == Qt.LeftButton:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_panning and self._pan_start_pos is not None:
            delta_x = event.pos().x() - self._pan_start_pos.x()
            delta_y = event.pos().y() - self._pan_start_pos.y()
            self._pan_offset[0] = self._last_pan_offset[0] - delta_x
            self._pan_offset[1] = self._last_pan_offset[1] - delta_y
            self._update_display()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.RightButton and self._is_panning:
            self._is_panning = False
            self._pan_start_pos = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def get_current_scale(self):
        return self._current_scale

    def reset_zoom(self):
        self._current_scale = 1.0
        self._pan_offset = [0, 0]
        self._last_pan_offset = [0, 0]
        self._update_display()
        self.scale_changed.emit(self._current_scale)
