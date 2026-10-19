"""Image conversion and aspect-preserving preview shared by all presentations."""
from __future__ import annotations
from typing import Dict, List, Optional
import numpy as np
from PySide6.QtCore import Qt, QSize, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QLabel
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


class AspectRatioLabel(QLabel):
    """保持固定宽高比的 QLabel，图像居中显示不被拉伸，支持编码圆标记叠加。

    标记在 paintEvent 中按显示坐标绘制（圆半径为屏幕像素，与图像缩放
    无关）：原实现把圈预渲染到原图尺寸的缓存层，4px 半径在全分辨率
    图像（2448×2048）缩到预览大小时亚像素化，肉眼不可见（2026-10-10
    转台"识别圆心没有显示"的根因）。标记数量通常为几十个，逐帧绘制开销
    可忽略。
    """

    def __init__(self, ratio=4.0 / 3.0, parent=None, *, appearance=None):
        super().__init__(parent)
        self._appearance = appearance or ImagePreviewAppearance()
        self._ratio = ratio
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background-color: {self._appearance.background}; "
                          f"border: 1px solid {self._appearance.border};")
        self._pixmap: Optional[QPixmap] = None
        self._markers: List[Dict] = []   # [{'x','y','code', 'valid_3d'}] 归一化坐标
        self._marker_radius = self._appearance.marker_radius          # 屏幕像素（显示空间，不随图像缩放变化）
        self._font = QFont("Consolas", 8)
        self._font.setBold(True)

    def set_markers(self, markers: List[Dict]):
        """markers: 编码圆列表，元素含 x/y（归一化 0~1）、code、可选 valid_3d。

        颜色语义：绿圈 = 3D 有效；红圈 = 2D 检出但 3D 无有效深度
        （valid_3d=False，无 x_3d 字段）；蓝圈 = 标定板标记。
        """
        self._markers = markers or []
        self.update()

    def clear_markers(self):
        self._markers = []
        self.update()

    def setPixmap(self, pixmap):  # noqa: N802（保持 Qt 接口名）
        self._pixmap = pixmap
        self.update()

    def clear_image(self):
        self._pixmap = None
        self._markers = []
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pixmap is None or self._pixmap.isNull():
            painter = QPainter(self)
            painter.setPen(QPen(QColor(self._appearance.empty_color), 1))
            painter.drawText(self.rect(), Qt.AlignCenter, "无图像")
            return
        # 在标签内居中按比例缩放绘制
        pw, ph = self._pixmap.width(), self._pixmap.height()
        lw, lh = self.width(), self.height()
        scale = min(lw / pw, lh / ph)
        sw, sh = int(pw * scale), int(ph * scale)
        x, y = (lw - sw) // 2, (lh - sh) // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(x, y, sw, sh, self._pixmap)
        # 标记按显示坐标绘制（半径/线宽为屏幕像素，任何缩放下都清晰）
        if self._markers:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setFont(self._font)
            r = self._marker_radius
            for m in self._markers:
                dx = x + float(m['x']) * sw
                dy = y + float(m['y']) * sh
                marker_type = m.get('marker_type', 'coded')
                if marker_type == 'board':
                    color = QColor(self._appearance.board_color)
                else:
                    # 红 = 2D 检出但 3D 无有效深度；绿 = 3D 有效
                    has_3d = m.get('valid_3d', True)
                    color = QColor(self._appearance.valid_color if has_3d else self._appearance.invalid_color)
                explicit_color = m.get('display_color')
                if isinstance(explicit_color, str) and QColor(explicit_color).isValid():
                    color = QColor(explicit_color)
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(dx, dy), r, r)
                painter.setPen(QPen(color, 1))
                painter.drawText(
                    QPointF(dx + r + 2, dy - r - 2),
                    str(m.get('code', '')))
        painter.end()


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
