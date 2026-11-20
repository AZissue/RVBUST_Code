"""Image conversion and aspect-preserving preview shared by all presentations."""
from __future__ import annotations
from typing import Optional
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPixmap
from core.utils import logger
from .appearance import ImagePreviewAppearance

def numpy_to_qpixmap(img: np.ndarray) -> Optional[QPixmap]:
    """numpy 图像 → QPixmap（兼容 uint16 / 灰度 / BGR / BGRA）。"""
    if img is None:
        return None
    try:
        if img.dtype == np.uint16:
            img = (img / 256).astype(np.uint8)
        elif img.dtype != np.uint8:
            img = np.clip(img, 0, 255).astype(np.uint8)

        if img.ndim == 2:
            h, w = img.shape
            buf = np.ascontiguousarray(img)
            qimg = QImage(buf.data, w, h, w, QImage.Format_Grayscale8)
        elif img.ndim == 3 and img.shape[2] == 3:
            h, w, _ = img.shape
            buf = np.ascontiguousarray(img)
            # PyRVC 图像通常为 BGR，直接用 BGR888 避免一次 RGB 翻转拷贝
            qimg = QImage(buf.data, w, h, w * 3, QImage.Format_BGR888)
        elif img.ndim == 3 and img.shape[2] == 4:
            h, w, _ = img.shape
            buf = np.ascontiguousarray(img)
            qimg = QImage(buf.data, w, h, w * 4, QImage.Format_BGRA8888)
        else:
            return None
        return QPixmap.fromImage(qimg.copy())
    except Exception as e:
        logger.error(f"图像转换失败: {e}")
        return None


from .image_canvas import ImagePreviewCanvas


class AspectRatioLabel(ImagePreviewCanvas):
    """Compatibility adapter for normalized marker lists and QPixmap callers."""

    def __init__(self, ratio=4.0 / 3.0, parent=None, *, appearance=None):
        super().__init__(parent)
        self._appearance = appearance or ImagePreviewAppearance()
        self._ratio = ratio
        self.setStyleSheet(f"background-color: {self._appearance.background}; border: 1px solid {self._appearance.border};")
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)

    def setPixmap(self, pixmap):
        self.set_image(None if pixmap is None else pixmap.toImage())

    def set_markers(self, markers):
        converted = []
        for marker in markers or ():
            row = dict(marker)
            row['x_2d'] = float(row.get('x', 0)) * self.image.width()
            row['y_2d'] = float(row.get('y', 0)) * self.image.height()
            converted.append(row)
        self.set_marker_data(converted)
        # Legacy normalized overlays carry only depth validity, never XYZ.
        from dataclasses import replace
        from .industrial_scene.marker_display import GREEN, YELLOW
        self.display = replace(self.display, rows=tuple(
            replace(row, color=row.marker.get('display_color') or
                    (GREEN if row.marker.get('valid_3d', True) else YELLOW))
            for row in self.display.rows))

    def clear_markers(self):
        self.set_marker_data([])

    def heightForWidth(self, width: int) -> int:
        return int(width / self._ratio)

    def hasHeightForWidth(self) -> bool:
        return True

    def minimumSizeHint(self):
        h = 200
        return QSize(int(h * self._ratio), h)

    def sizeHint(self):
        h = 280
        return QSize(int(h * self._ratio), h)
