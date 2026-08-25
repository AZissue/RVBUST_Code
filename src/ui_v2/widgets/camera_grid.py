# -*- coding: utf-8 -*-
"""
ui_v2.widgets.camera_grid —— 模式 A 中央相机取景网格。

每台相机一张卡片：
  - 实时缩略图（拍完刷新）+ 相机名；
  - 标记数量角标；
  - 共视状态角标：绿「✓ 共视正常」/ 红「● 未看到标定板」（标定阶段硬提示）；
  - 帧分区标签：标定帧 / 扫描帧（不同标签色，互不覆盖）。

正式接入时缩略图渲染可替换为现有 ``camera_card.py`` 的 AspectRatioLabel
叠加逻辑（绿圈 + code 号），本壳仅保留布局与状态接口。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core.frame_data import FrameData
from ui.camera_card import AspectRatioLabel, numpy_to_qpixmap

from ..theme import (
    ACCENT, ACCENT_DIM, BG_CARD, BG_PANEL, BORDER, BORDER_HOVER,
    STATUS_ERR, STATUS_OK, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)
from .. import icons as ui_icons

FRAME_KIND_STYLE = {
    # 帧分区标签色：标定帧 / 扫描帧 互不覆盖
    "标定帧": ("#5C6BC0", "标定帧"),
    "扫描帧": (STATUS_OK, "扫描帧"),
}


class CameraCard(QFrame):
    """单相机取景卡片。

    信号：
        clicked(str)                  点击卡片（选中该相机）。
        preview_toggled(str, bool)    单相机 2D 预览开关。
        capture_requested(str)        单相机 3D 拍摄。
        detect_requested(str)         单相机检测标记。
    """

    clicked = Signal(str)
    preview_toggled = Signal(str, bool)
    capture_requested = Signal(str)
    detect_requested = Signal(str)

    def __init__(self, camera_id: str, title: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.camera_id = camera_id
        self._current_frame: Optional[FrameData] = None

        self.setStyleSheet(
            f"CameraCard {{ background-color: {BG_CARD};"
            f" border: none; border-radius: 6px; }}")
        self.setMinimumSize(300, 270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(4)

        # 标题行：相机名 + 帧分区标签
        title_row = QHBoxLayout()
        cam_icon = QLabel()
        cam_icon.setPixmap(ui_icons.pixmap("camera", TEXT_SECONDARY, 14))
        cam_icon.setFixedSize(16, 16)
        title_row.addWidget(cam_icon)
        self._name = QLabel(title or camera_id)
        self._name.setStyleSheet(
            f"font-weight: 600; color: {TEXT_PRIMARY};")
        title_row.addWidget(self._name)
        title_row.addStretch(1)
        self._kind = QLabel("")
        self._kind.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        title_row.addWidget(self._kind)
        lo.addLayout(title_row)

        # 缩略图占位（4:3，宽度随卡片水平铺满，保持比例）
        self._thumb = AspectRatioLabel(ratio=4.0 / 3.0)
        self._thumb.setMinimumSize(260, 180)
        self._thumb.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        lo.addWidget(self._thumb, 1)

        # 底部角标 + 单相机控制按钮
        bottom = QHBoxLayout()
        self._marker_badge = QLabel("标记: —")
        self._marker_badge.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px;"
            f" background-color: {BG_PANEL}; border-radius: 4px; padding: 3px 8px;")
        bottom.addWidget(self._marker_badge)
        bottom.addStretch(1)

        self._covis_badge = QLabel("")
        self._covis_badge.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        bottom.addWidget(self._covis_badge)
        bottom.addSpacing(6)

        # 单相机控制按钮（图标 + 文字，紧凑排列）
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {BG_PANEL};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 4px;"
            f"  padding: 4px 10px;"
            f"  color: {TEXT_SECONDARY};"
            f"  font-size: 12px;"
            f"  min-width: 60px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {BG_CARD};"
            f"  border-color: {BORDER_HOVER};"
            f"  color: {TEXT_PRIMARY};"
            f"}}"
            f"QPushButton:pressed {{ background-color: #3E424E; }}"
            f"QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: #2E313A; }}"
            f"QPushButton:checked {{"
            f"  background-color: {ACCENT_DIM};"
            f"  border-color: {ACCENT};"
            f"  color: {ACCENT};"
            f"  font-weight: 600;"
            f"}}"
        )

        self._btn_preview = QPushButton("2D预览")
        self._btn_preview.setCheckable(True)
        self._btn_preview.setStyleSheet(btn_style)
        self._btn_preview.setFixedHeight(30)
        self._btn_preview.setIconSize(QSize(16, 16))
        ui_icons.apply(self._btn_preview, "video", TEXT_SECONDARY, 16)
        self._btn_preview.toggled.connect(self._on_preview_toggled)
        bottom.addWidget(self._btn_preview)

        self._btn_capture = QPushButton("3D拍")
        self._btn_capture.setStyleSheet(btn_style)
        self._btn_capture.setFixedHeight(30)
        self._btn_capture.setIconSize(QSize(16, 16))
        ui_icons.apply(self._btn_capture, "camera", TEXT_SECONDARY, 16)
        self._btn_capture.clicked.connect(
            lambda: self.capture_requested.emit(self.camera_id))
        bottom.addWidget(self._btn_capture)

        self._btn_detect = QPushButton("检测")
        self._btn_detect.setStyleSheet(btn_style)
        self._btn_detect.setFixedHeight(30)
        self._btn_detect.setIconSize(QSize(16, 16))
        ui_icons.apply(self._btn_detect, "detect", TEXT_SECONDARY, 16)
        self._btn_detect.clicked.connect(
            lambda: self.detect_requested.emit(self.camera_id))
        bottom.addWidget(self._btn_detect)

        bottom.setSpacing(8)
        lo.addLayout(bottom)

    # ------------------------------------------------------------ 公共接口
    def set_thumbnail(self, pixmap: Optional[QPixmap]):
        """刷新缩略图（拍摄完成后调用）。"""
        if pixmap is None:
            self._thumb.clear_image()
            return
        self._thumb.setPixmap(pixmap)

    def set_frame(self, frame: Optional[FrameData], markers: Optional[list] = None):
        """由 FrameData 更新缩略图与标记叠加，并保留当前帧供检测使用。"""
        self._current_frame = frame
        if frame is None or frame.image_np is None:
            self._thumb.clear_image()
            return
        pixmap = numpy_to_qpixmap(frame.image_np)
        self._thumb.setPixmap(pixmap)

        # AspectRatioLabel 期望归一化坐标 [0,1] 与 x/y/code/valid_3d 字段，
        # 而 frame.markers 中的编码圆只含 x_2d/y_2d，标定板含 x/y/x_2d/y_2d，
        # 因此需要统一转换。
        markers = markers if markers is not None else frame.markers
        h, w = frame.image_np.shape[:2]
        is_board = frame.board_pattern_name is not None
        overlay = []
        for m in markers or []:
            px = m.get('x_2d', m.get('x', 0.0))
            py = m.get('y_2d', m.get('y', 0.0))
            has_3d = 'x_3d' in m
            overlay.append({
                'x': float(px) / w if w > 0 else 0.0,
                'y': float(py) / h if h > 0 else 0.0,
                'code': m.get('code', '?'),
                'valid_3d': has_3d,
                'marker_type': 'board' if is_board else 'coded',
            })
        self._thumb.set_markers(overlay)

    def current_frame(self) -> Optional[FrameData]:
        """返回当前卡片持有的最新帧（预览/拍摄/检测用）。"""
        return self._current_frame

    def set_marker_count(self, count: Optional[int]):
        """更新标记数量角标。"""
        if count is None:
            self._marker_badge.setText("标记: —")
            return
        self._marker_badge.setText(f"标记: {count}")
        color = STATUS_OK if count > 0 else STATUS_ERR
        self._marker_badge.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 600;"
            f" background-color: {BG_PANEL}; border-radius: 4px; padding: 3px 8px;")

    def set_covis_status(self, ok: Optional[bool]):
        """共视状态角标（标定阶段硬提示）。

        ok=True  → 绿「✓ 共视正常」
        ok=False → 红「● 未看到标定板」
        ok=None  → 清空
        """
        if ok is None:
            self._covis_badge.setText("")
        elif ok:
            self._covis_badge.setText("✓ 共视正常")
            self._covis_badge.setStyleSheet(
                f"color: {STATUS_OK}; font-size: 12px; font-weight: 600;")
        else:
            self._covis_badge.setText("● 未看到标定板")
            self._covis_badge.setStyleSheet(
                f"color: {STATUS_ERR}; font-size: 12px; font-weight: 600;")

    def set_frame_kind(self, kind: Optional[str]):
        """帧分区标签：'标定帧' / '扫描帧' / None。"""
        if kind in FRAME_KIND_STYLE:
            color, text = FRAME_KIND_STYLE[kind]
            self._kind.setText(text)
            self._kind.setStyleSheet(
                f"color: {color}; font-size: 12px; font-weight: 600;")
        else:
            self._kind.setText("")

    def set_title(self, title: str):
        self._name.setText(title)

    def set_controls_enabled(self, enabled: bool):
        """设置单相机控制按钮可用性。"""
        self._btn_capture.setEnabled(enabled)
        self._btn_detect.setEnabled(enabled)
        if not enabled:
            self._btn_preview.setChecked(False)
        self._btn_preview.setEnabled(enabled)

    def set_preview_checked(self, checked: bool):
        """同步 2D 预览按钮勾选状态（不触发 toggled 信号）。"""
        self._btn_preview.blockSignals(True)
        self._btn_preview.setChecked(checked)
        self._btn_preview.blockSignals(False)
        self._update_preview_icon(checked)

    def _on_preview_toggled(self, checked: bool):
        """2D 预览按钮切换：同步图标颜色并向上转发信号。"""
        self._update_preview_icon(checked)
        self.preview_toggled.emit(self.camera_id, checked)

    def _update_preview_icon(self, checked: bool):
        """根据勾选状态更新预览按钮图标颜色。"""
        color = ACCENT if checked else TEXT_SECONDARY
        ui_icons.apply(self._btn_preview, "video", color, 16)

    def mousePressEvent(self, event):
        self.clicked.emit(self.camera_id)
        super().mousePressEvent(event)


class CameraGrid(QScrollArea):
    """相机卡片网格（响应式列数，N 台相机水平平铺）。

    信号：
        card_clicked(str)  点击某张卡片。
    """

    card_clicked = Signal(str)
    CARD_WIDTH = 300
    CARD_HEIGHT = 270
    H_SPACING = 8
    V_SPACING = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: Dict[str, CameraCard] = {}
        self._titles: Dict[str, str] = {}
        self._last_cols: Optional[int] = None

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(self.H_SPACING)
        self._grid.setVerticalSpacing(self.V_SPACING)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setWidget(self._container)

    # ------------------------------------------------------------ 公共接口
    def set_cameras(self, camera_ids: List[str], titles: Optional[Dict[str, str]] = None):
        """重建网格（连接设备变化时调用）。

        titles: {camera_id: 显示名称}，未提供时显示 camera_id。
        """
        for card in self._cards.values():
            card.deleteLater()
        self._cards.clear()
        self._titles = dict(titles or {})

        for cid in camera_ids:
            card = CameraCard(cid, title=self._titles.get(cid, cid))
            card.clicked.connect(self.card_clicked)
            self._cards[cid] = card
        self._last_cols = None
        self._relayout()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        """根据当前 viewport 宽度计算列数并重新排布卡片，列宽水平铺满。

        仅当列数真正变化时才移除/重加卡片，避免拖动 splitter 或窗口
        缩放时频繁全量 relayout 造成卡顿。
        """
        n = len(self._cards)
        if n == 0:
            return

        viewport_w = self.viewport().width()
        # 每个卡片最小占用宽度 = 卡片最小宽 + 水平间距
        col_unit = self.CARD_WIDTH + self.H_SPACING
        cols = max(1, viewport_w // col_unit)
        cols = min(cols, n)

        if cols == self._last_cols:
            # 列数未变，QGridLayout 的 stretch 会让卡片自动均分宽度，
            # 无需移除并重排所有卡片。
            return

        # 清空布局
        for card in self._cards.values():
            self._grid.removeWidget(card)
        # 重置列拉伸（先清零，再为当前列数设置均分）
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)
        # 重新按行添加
        for i, card in enumerate(self._cards.values()):
            self._grid.addWidget(card, i // cols, i % cols)
        # 当前使用的列均分可用宽度
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

        self._last_cols = cols

    def card(self, camera_id: str) -> Optional[CameraCard]:
        return self._cards.get(camera_id)

    def camera_ids(self) -> List[str]:
        return list(self._cards.keys())

    def set_frame(self, camera_id: str, frame: Optional[FrameData],
                  markers: Optional[list] = None):
        """更新指定相机卡片的帧与标记叠加。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_frame(frame, markers)

    def set_marker_count(self, camera_id: str, count: Optional[int]):
        """更新指定相机卡片的标记数量角标。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_marker_count(count)

    def set_covis_status(self, camera_id: str, ok: Optional[bool]):
        """更新指定相机卡片的共视状态角标。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_covis_status(ok)

    def set_frame_kind(self, camera_id: str, kind: Optional[str]):
        """更新指定相机卡片的帧分区标签。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_frame_kind(kind)
