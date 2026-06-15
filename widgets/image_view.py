"""
2D 图像可视化窗口组件。
支持鼠标滚轮缩放、标记物检测结果叠加标注（含像素坐标）。
"""

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)

import resources as res


class Image2DView(QWidget):
    """2D 可视化窗口，支持缩放和标记物叠加"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._markers = []             # [(x, y, label), ...]
        self._original_pixmap = None   # 原始完整 QPixmap
        self._zoom_level = 1.0         # 缩放倍率 (0.25 ~ 4.0)，0 表示自动适配
        self._auto_fit = True          # 自动适配视口（用户手动缩放后取消）
        self._offset_x = 0             # 平移 X
        self._offset_y = 0             # 平移 Y
        self._pan_start = None         # 拖拽起点

        self.setStyleSheet(f"""
            Image2DView {{
                border: 2px solid {res.BORDER_DEFAULT};
                border-radius: {res.BORDER_RADIUS}px;
                background-color: {res.BG_DARK_2D};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 标题栏 ──
        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setStyleSheet(f"""
            background-color: {res.BG_CARD};
            border-top-left-radius: {res.BORDER_RADIUS}px;
            border-top-right-radius: {res.BORDER_RADIUS}px;
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 8, 0)

        title = QLabel("2D 实时图像")
        title.setStyleSheet(
            f"font-size: {res.FONT_H2}px; font-weight: 600; "
            f"color: {res.TEXT_TITLE}; border: none;"
        )
        title_layout.addWidget(title)
        title_layout.addStretch()

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet(
            f"font-size: {res.FONT_HINT}px; color: {res.TEXT_HINT}; border: none;"
        )
        title_layout.addWidget(self._zoom_label)

        layout.addWidget(title_bar)

        # ── 图像显示区域 ──
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image_label.setStyleSheet(
            f"border: none; background-color: {res.BG_DARK_2D};"
        )
        self._image_label.setMouseTracking(True)
        layout.addWidget(self._image_label, 1)

    def update_frame(self, np_image):
        """更新显示的图像帧"""
        if np_image is None:
            return
        if np_image.ndim == 2:
            np_image = cv2.cvtColor(np_image, cv2.COLOR_GRAY2RGB)
        elif np_image.shape[2] == 3:
            np_image = cv2.cvtColor(np_image, cv2.COLOR_BGR2RGB)
        np_image = np.ascontiguousarray(np_image)
        h, w, ch = np_image.shape
        bytes_per_line = ch * w
        qimg = QImage(np_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self._original_pixmap = QPixmap.fromImage(qimg)
        self._auto_fit = True
        self._zoom_level = 0
        self._offset_x = 0
        self._offset_y = 0
        self._render()

    def draw_markers(self, markers):
        """
        设置标记物叠加信息。
        markers: [(像素x, 像素y, 显示标签), ...]
        """
        self._markers = markers
        self._render()

    def clear(self):
        self._original_pixmap = None
        self._markers = []
        self._auto_fit = True
        self._zoom_level = 0
        self._image_label.clear()

    def wheelEvent(self, event):
        """鼠标滚轮缩放（以鼠标位置为中心）"""
        if self._original_pixmap is None:
            return

        # 首次滚轮取消自动适配，使用当前适配倍率作为起点
        if self._auto_fit:
            self._auto_fit = False
            self._fit_zoom()
            self._offset_x = 0
            self._offset_y = 0

        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        new_zoom = self._zoom_level * factor
        new_zoom = max(0.25, min(4.0, new_zoom))

        # 以鼠标位置为中心缩放：鼠标下的图像内容保持不动
        mouse_x = event.pos().x() - self._image_label.pos().x()
        mouse_y = event.pos().y() - self._image_label.pos().y()

        actual_factor = new_zoom / max(self._zoom_level, 0.001)
        self._offset_x = (mouse_x + self._offset_x) * actual_factor - mouse_x
        self._offset_y = (mouse_y + self._offset_y) * actual_factor - mouse_y
        self._zoom_level = new_zoom
        self._render()

    def mousePressEvent(self, event):
        """鼠标按下：中键或右键开始拖拽平移"""
        if event.button() == Qt.MiddleButton or event.button() == Qt.RightButton:
            self._pan_start = (event.pos().x(), event.pos().y())
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标拖拽平移图像（画面跟随鼠标方向）"""
        if self._pan_start is not None:
            dx = event.pos().x() - self._pan_start[0]
            dy = event.pos().y() - self._pan_start[1]
            self._offset_x -= dx
            self._offset_y -= dy
            self._pan_start = (event.pos().x(), event.pos().y())
            self._render()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放：结束拖拽"""
        if event.button() == Qt.MiddleButton or event.button() == Qt.RightButton:
            self._pan_start = None
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击重置缩放"""
        if event.button() == Qt.LeftButton:
            self._auto_fit = True
            self._zoom_level = 0
            self._offset_x = 0
            self._offset_y = 0
            self._render()
        super().mouseDoubleClickEvent(event)

    def _fit_zoom(self):
        """计算铺满视口的缩放倍率"""
        label_size = self._image_label.size()
        pw = self._original_pixmap.width() if self._original_pixmap else 1
        ph = self._original_pixmap.height() if self._original_pixmap else 1
        if label_size.width() > 0 and label_size.height() > 0 and pw > 0 and ph > 0:
            self._zoom_level = min(label_size.width() / pw, label_size.height() / ph)
        else:
            self._zoom_level = 0.5

    def _render(self):
        if self._original_pixmap is None:
            return

        label_size = self._image_label.size()
        if label_size.width() <= 0 or label_size.height() <= 0:
            return

        # 自动适配视口
        if self._auto_fit:
            self._fit_zoom()

        pw = self._original_pixmap.width()
        ph = self._original_pixmap.height()

        # 按照缩放级别创建画布
        canvas_w = int(pw * self._zoom_level)
        canvas_h = int(ph * self._zoom_level)
        canvas_w = max(canvas_w, 1)
        canvas_h = max(canvas_h, 1)

        # 在画布上绘制缩放后的图像 + 标记物
        canvas = QPixmap(canvas_w, canvas_h)
        canvas.fill(QColor(res.BG_DARK_2D))
        painter = QPainter(canvas)

        # 绘制缩放后的图像
        scaled_img = self._original_pixmap.scaled(
            canvas_w, canvas_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        img_x = (canvas_w - scaled_img.width()) // 2
        img_y = (canvas_h - scaled_img.height()) // 2
        painter.drawPixmap(img_x, img_y, scaled_img)

        # 计算实际图像在画布上的缩放比例
        img_scale = scaled_img.width() / max(pw, 1)

        # 绘制标记物叠加
        if self._markers:
            painter.setFont(QFont(res.FONT_FAMILY, 9))
            circle_pen = QPen(QColor(res.PRIMARY))
            circle_pen.setWidth(3)
            painter.setPen(circle_pen)

            for i, (mx, my, mlbl) in enumerate(self._markers):
                sx = int(mx * img_scale + img_x)
                sy = int(my * img_scale + img_y)
                r = 12
                painter.setPen(circle_pen)
                painter.setBrush(QColor(22, 119, 255, 30))
                painter.drawEllipse(sx - r, sy - r, r * 2, r * 2)

                # 像素坐标标签
                coord_text = f"({mx:.1f}, {my:.1f})"
                painter.setPen(QColor("#FFFFFF"))
                painter.setBrush(QColor(0, 0, 0, 160))
                text_rect = painter.boundingRect(sx + 14, sy - 10, 200, 20)
                painter.drawRect(text_rect.adjusted(-2, -1, 2, 1))
                painter.drawText(sx + 14, sy + 4, coord_text)

        painter.end()

        # 将画布裁剪到 QLabel 可见区域（居中显示）
        visible = QPixmap(label_size)
        visible.fill(QColor(res.BG_DARK_2D))
        vp = QPainter(visible)
        label_w = label_size.width()
        label_h = label_size.height()

        # 画布小于视口时居中，大于视口时可拖拽
        if canvas_w > label_w:
            src_x = max(0, min(int(self._offset_x), canvas_w - label_w))
            src_w = label_w
            dst_x = 0
        else:
            src_x = 0
            src_w = canvas_w
            dst_x = (label_w - canvas_w) // 2

        if canvas_h > label_h:
            src_y = max(0, min(int(self._offset_y), canvas_h - label_h))
            src_h = label_h
            dst_y = 0
        else:
            src_y = 0
            src_h = canvas_h
            dst_y = (label_h - canvas_h) // 2

        vp.drawPixmap(dst_x, dst_y, canvas, src_x, src_y, src_w, src_h)
        vp.end()

        self._image_label.setPixmap(visible)
        self._zoom_label.setText(f"{int(self._zoom_level * 100)}%")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()
