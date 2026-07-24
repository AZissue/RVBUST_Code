# -*- coding: utf-8 -*-
"""
相机预览卡片组件（CameraPreviewCard）。

AspectRatioLabel 从 DualCameraFusion/src/app.py:1905-1966 原样抽取并增强：
  - 标记叠加由纯红点改为「绿圈 + code 文字」（编码圆检测结果）；
CameraPreviewCard 为新写的可复用单相机卡片：
  - 2D 预览 + 状态行（分辨率 / 帧率 / 连接状态彩点）
  - 拍摄 / 断开按钮
  - 浮动信息：标记数量、3D 有效数
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from PySide6.QtCore import Qt, Signal, QSize, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QBrush, QPen, QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy,
)

from core.frame_data import FrameData
from core.utils import logger

from .icons import get_icon, has_icon, icon_text, apply_icon


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
            rgb = np.ascontiguousarray(img[:, :, ::-1])  # BGR → RGB
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
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


# ---------------------------------------------------------------------------
# 保持宽高比的预览标签（从 DualCameraFusion 抽取，标记叠加增强为绿圈+code）
# ---------------------------------------------------------------------------
class AspectRatioLabel(QLabel):
    """保持固定宽高比的 QLabel，图像居中显示不被拉伸，支持编码圆标记叠加。"""

    def __init__(self, ratio=4.0 / 3.0, parent=None):
        super().__init__(parent)
        self._ratio = ratio
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #1A1A20; border: 1px solid #2A2A34;")
        self._pixmap: Optional[QPixmap] = None
        self._markers: List[Dict] = []   # [{'x','y','code', 'valid_3d'}]
        self._marker_radius = 6

    def set_markers(self, markers: List[Dict]):
        """markers: 编码圆列表，元素含 x/y（原图坐标）、code、可选 valid_3d。"""
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
            painter.setPen(QPen(QColor(90, 90, 90), 1))
            painter.drawText(self.rect(), Qt.AlignCenter, "无图像")
            return
        # 在标签内居中按比例缩放绘制
        pw, ph = self._pixmap.width(), self._pixmap.height()
        lw, lh = self.width(), self.height()
        scale = min(lw / pw, lh / ph)
        sw, sh = int(pw * scale), int(ph * scale)
        x, y = (lw - sw) // 2, (lh - sh) // 2
        painter = QPainter(self)
        painter.drawPixmap(x, y, sw, sh, self._pixmap)

        # 标记叠加：
        #   - 编码圆：绿圈 + code 文字（无 3D 的用黄色区分）
        #   - 标定板圆心：蓝圈 + 索引
        if self._markers:
            font = QFont("Consolas", 9)
            font.setBold(True)
            painter.setFont(font)
            for m in self._markers:
                dx = x + m['x'] * scale
                dy = y + m['y'] * scale
                marker_type = m.get('marker_type', 'coded')
                if marker_type == 'board':
                    color = QColor(60, 160, 255)
                else:
                    has_3d = m.get('valid_3d', True)
                    color = QColor(0, 230, 80) if has_3d else QColor(255, 200, 40)
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(dx, dy), self._marker_radius, self._marker_radius)
                painter.setPen(QPen(color, 1))
                painter.drawText(QPointF(dx + self._marker_radius + 2, dy - self._marker_radius - 2),
                                 str(m.get('code', '')))

    def minimumSizeHint(self):
        h = 200
        return QSize(int(h * self._ratio), h)

    def sizeHint(self):
        h = 280
        return QSize(int(h * self._ratio), h)


# ---------------------------------------------------------------------------
# 单相机预览卡片（可复用组件）
# ---------------------------------------------------------------------------
class CameraPreviewCard(QFrame):
    """单相机预览卡片：2D 预览 + 状态标签 + 连接/拍摄按钮 + 标记叠加。"""

    capture_requested = Signal(str)          # camera_id
    disconnect_requested = Signal(str)       # camera_id
    preview_toggled = Signal(str, bool)      # camera_id, active（持续 2D 预览）

    def __init__(self, camera_id: str, parent=None):
        super().__init__(parent)
        self.camera_id = camera_id
        self._connected = False
        self._capture_count = 0
        self._is_preview_mode = False    # True：按钮为「预览/停止预览」持续 2D
        self._preview_active = False     # 当前是否正在持续预览
        self._preview_icon_name = "preview"
        self._capture_icon_name = "capture"
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        self.setObjectName("cameraCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame#cameraCard { background-color: #1A1A20; border: 1px solid #2A2A34; "
            "border-radius: 6px; }"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(4)

        # 标题行：图标（有自定义图标文件时显示）+ 相机 ID + 连接状态彩点
        title_lo = QHBoxLayout()
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(16, 16)
        self.lbl_icon.setStyleSheet("background: transparent; border: none;")
        self.lbl_icon.hide()  # 无图标文件时隐藏，标题保持 emoji 兜底
        title_lo.addWidget(self.lbl_icon)
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-weight: bold; color: #2979FF; font-size: 10pt;")
        title_lo.addWidget(self.lbl_title)
        title_lo.addStretch(1)

        self.dot_status = QLabel()
        self.dot_status.setFixedSize(12, 12)
        self.dot_status.setToolTip("连接状态")
        title_lo.addWidget(self.dot_status)
        self.lbl_status = QLabel("未连接")
        self.lbl_status.setStyleSheet("font-size: 8pt; color: #aaaaaa;")
        title_lo.addWidget(self.lbl_status)
        lo.addLayout(title_lo)

        # 2D 预览（保持宽高比 + 标记叠加）
        self.preview = AspectRatioLabel()
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lo.addWidget(self.preview, 1)

        # 浮动信息行：标记数量 / 3D 有效数
        self.lbl_markers = QLabel("标记: - | 3D 有效: -")
        self.lbl_markers.setObjectName("infoLabel")
        self.lbl_markers.setAlignment(Qt.AlignCenter)
        lo.addWidget(self.lbl_markers)

        # 状态行：分辨率 / 拍摄计数
        self.lbl_info = QLabel("分辨率: - | 拍摄: 0")
        self.lbl_info.setObjectName("infoLabel")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        lo.addWidget(self.lbl_info)

        # 按钮行：拍摄 / 断开
        btn_lo = QHBoxLayout()
        self.btn_capture = QPushButton(icon_text("capture", "📸 拍摄"))
        self.btn_capture.setObjectName("primaryButton")
        self.btn_capture.setEnabled(False)
        self.btn_capture.clicked.connect(self._on_capture_button_clicked)
        apply_icon(self.btn_capture, "capture")
        btn_lo.addWidget(self.btn_capture)

        self.btn_disconnect = QPushButton(icon_text("disconnect", "✖ 断开"))
        self.btn_disconnect.setObjectName("dangerButton")
        self.btn_disconnect.clicked.connect(lambda: self.disconnect_requested.emit(self.camera_id))
        apply_icon(self.btn_disconnect, "disconnect")
        btn_lo.addWidget(self.btn_disconnect)
        lo.addLayout(btn_lo)

        self.set_title(f"📷 {self.camera_id}", "camera")
        self._update_status_display()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def update_frame(self, frame_data: FrameData, markers: Optional[List[Dict]] = None):
        """更新 2D 预览 + 标记叠加 + 浮动信息（不递增拍摄计数）。"""
        try:
            pixmap = numpy_to_qpixmap(frame_data.image_np)
            if pixmap is not None:
                self.preview.setPixmap(pixmap)

            markers = markers if markers is not None else frame_data.markers
            is_board = frame_data.board_pattern_name is not None
            overlay = []
            n_3d = 0
            for m in markers:
                x = m.get('x_2d', m.get('x', 0))
                y = m.get('y_2d', m.get('y', 0))
                has_3d = 'x_3d' in m
                n_3d += 1 if has_3d else 0
                overlay.append({
                    'x': x, 'y': y,
                    'code': m.get('code', '?'),
                    'valid_3d': has_3d,
                    'marker_type': 'board' if is_board else 'coded',
                })
            self.preview.set_markers(overlay)

            h, w = frame_data.image_np.shape[:2] if frame_data.image_np is not None else (0, 0)
            self.lbl_info.setText(f"分辨率: {w}×{h} | 拍摄: {self._capture_count}")
            if is_board:
                self.lbl_markers.setText(f"标定板: {frame_data.board_pattern_name} | 圆心: {len(markers)}")
            elif markers:
                self.lbl_markers.setText(f"标记: {len(markers)} | 3D 有效: {n_3d}")
            else:
                self.lbl_markers.setText("标记: - | 3D 有效: -")
        except Exception as e:
            logger.error(f"更新卡片 {self.camera_id} 帧失败: {e}")

    def update_captured(self, frame_data: FrameData, markers: Optional[List[Dict]] = None):
        """更新 2D 预览并递增拍摄计数（仅真实拍摄/保存帧时调用）。"""
        self._capture_count += 1
        self.update_frame(frame_data, markers)

    def set_connected(self, connected: bool, resolution: str = ""):
        """更新连接状态显示。"""
        self._connected = connected
        self.btn_capture.setEnabled(connected)
        if resolution:
            h_text = self.lbl_info.text()
            self.lbl_info.setText(f"分辨率: {resolution} | " + h_text.split("|")[-1].strip())
        self._update_status_display()

    def is_connected(self) -> bool:
        return self._connected

    def set_title(self, text: str, icon_name: str = "camera"):
        """设置卡片标题（如「当前相机（取景）」「站位 N」，Phase 5 站位模式用）。
        icon_name 对应 assets/icons/ 文件名：有图标文件时标题行显示图标、
        文本剥离开头 emoji；无文件时保持 emoji 文本兜底。"""
        if has_icon(icon_name):
            self.lbl_icon.setPixmap(get_icon(icon_name).pixmap(16, 16))
            self.lbl_icon.show()
        else:
            self.lbl_icon.hide()
        self.lbl_title.setText(icon_text(icon_name, text))

    def set_capture_button_text(self, text: str, icon_name: str = "capture"):
        """修改底部拍摄按钮的文本与图标（Phase 5 把当前相机按钮改为「预览」）。"""
        self.btn_capture.setText(icon_text(icon_name, text))
        apply_icon(self.btn_capture, icon_name)

    def set_preview_mode(self, enabled: bool, icon_name: str = "preview"):
        """把底部按钮设为持续 2D 预览模式：点击开始预览，再点击停止预览。"""
        self._is_preview_mode = enabled
        self._preview_icon_name = icon_name
        self._update_preview_button()

    def is_preview_active(self) -> bool:
        """当前是否处于持续 2D 预览中。"""
        return self._is_preview_mode and self._preview_active

    def stop_preview(self):
        """外部调用停止持续预览并更新按钮显示。"""
        if self._is_preview_mode and self._preview_active:
            self._preview_active = False
            self._update_preview_button()

    def _on_capture_button_clicked(self):
        """处理底部拍摄/预览按钮点击。"""
        if not self._is_preview_mode:
            self.capture_requested.emit(self.camera_id)
            return
        self._preview_active = not self._preview_active
        self._update_preview_button()
        self.preview_toggled.emit(self.camera_id, self._preview_active)

    def _update_preview_button(self):
        """根据预览状态更新按钮文本与图标。"""
        if not self._is_preview_mode:
            self.set_capture_button_text("📸 拍摄", self._capture_icon_name)
            return
        if self._preview_active:
            self.btn_capture.setObjectName("dangerButton")
            self.set_capture_button_text("⏹ 停止预览", self._preview_icon_name)
        else:
            self.btn_capture.setObjectName("primaryButton")
            self.set_capture_button_text("👁 预览", self._preview_icon_name)
        # 重新应用样式
        self.btn_capture.style().unpolish(self.btn_capture)
        self.btn_capture.style().polish(self.btn_capture)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _update_status_display(self):
        if self._connected:
            self.dot_status.setStyleSheet(
                "background-color: #43a047; border-radius: 6px; border: 1px solid #2e7d32;")
            self.lbl_status.setText("已连接")
        else:
            self.dot_status.setStyleSheet(
                "background-color: #e53935; border-radius: 6px; border: 1px solid #c62828;")
            self.lbl_status.setText("未连接")
