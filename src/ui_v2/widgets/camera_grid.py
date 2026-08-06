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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from ..theme import (
    ACCENT, BG_CARD, BG_PANEL, BORDER, STATUS_ERR, STATUS_OK,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)
from .. import icons as ui_icons

FRAME_KIND_STYLE = {
    # 帧分区标签色：标定帧 / 扫描帧 互不覆盖
    "标定帧": ("#5C6BC0", "标定帧"),
    "扫描帧": (STATUS_OK, "扫描帧"),
}


class CameraCard(QFrame):
    """单相机取景卡片（空壳）。

    信号：
        clicked(str)  点击卡片（选中该相机）。
    """

    clicked = Signal(str)

    def __init__(self, camera_id: str, parent=None):
        super().__init__(parent)
        self.camera_id = camera_id

        self.setStyleSheet(
            f"CameraCard {{ background-color: {BG_CARD};"
            f" border: 1px solid {BORDER}; border-radius: 6px; }}")
        self.setMinimumHeight(150)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(4)

        # 标题行：相机名 + 帧分区标签
        title_row = QHBoxLayout()
        cam_icon = QLabel()
        cam_icon.setPixmap(ui_icons.pixmap("camera", TEXT_SECONDARY, 13))
        cam_icon.setFixedSize(16, 16)
        title_row.addWidget(cam_icon)
        self._name = QLabel(camera_id)
        self._name.setStyleSheet(
            f"font-weight: 600; color: {TEXT_PRIMARY};")
        title_row.addWidget(self._name)
        title_row.addStretch(1)
        self._kind = QLabel("")
        self._kind.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        title_row.addWidget(self._kind)
        lo.addLayout(title_row)

        # 缩略图占位（16:9）
        self._thumb = QLabel("无画面\n（等待拍摄）")
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setMinimumSize(160, 90)
        self._thumb.setStyleSheet(
            f"background-color: {BG_PANEL}; border: 1px dashed {BORDER};"
            f" border-radius: 4px; color: {TEXT_MUTED}; font-size: 11px;")
        lo.addWidget(self._thumb, 1)

        # 底部角标行：标记数 + 共视状态
        badge_row = QHBoxLayout()
        self._marker_badge = QLabel("标记: —")
        self._marker_badge.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px;"
            f" background-color: {BG_PANEL}; border-radius: 4px; padding: 2px 6px;")
        badge_row.addWidget(self._marker_badge)
        badge_row.addStretch(1)
        self._covis_badge = QLabel("")
        self._covis_badge.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        badge_row.addWidget(self._covis_badge)
        lo.addLayout(badge_row)

    # ------------------------------------------------------------ 公共接口
    def set_thumbnail(self, pixmap: Optional[QPixmap]):
        """刷新缩略图（拍摄完成后调用）。

        # TODO(BACKEND): 由 FrameData 渲染 QPixmap 后传入
        （复用 camera_card.numpy_to_qpixmap + 标记叠加）。
        """
        if pixmap is None:
            self._thumb.setText("无画面\n（等待拍摄）")
            return
        self._thumb.setPixmap(pixmap.scaled(
            self._thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_marker_count(self, count: Optional[int]):
        """更新标记数量角标。"""
        if count is None:
            self._marker_badge.setText("标记: —")
            return
        self._marker_badge.setText(f"标记: {count}")
        color = STATUS_OK if count > 0 else STATUS_ERR
        self._marker_badge.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600;"
            f" background-color: {BG_PANEL}; border-radius: 4px; padding: 2px 6px;")

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
                f"color: {STATUS_OK}; font-size: 11px; font-weight: 600;")
        else:
            self._covis_badge.setText("● 未看到标定板")
            self._covis_badge.setStyleSheet(
                f"color: {STATUS_ERR}; font-size: 11px; font-weight: 600;")

    def set_frame_kind(self, kind: Optional[str]):
        """帧分区标签：'标定帧' / '扫描帧' / None。"""
        if kind in FRAME_KIND_STYLE:
            color, text = FRAME_KIND_STYLE[kind]
            self._kind.setText(text)
            self._kind.setStyleSheet(
                f"color: {color}; font-size: 10px; font-weight: 600;")
        else:
            self._kind.setText("")

    def set_title(self, title: str):
        self._name.setText(title)

    def mousePressEvent(self, event):
        self.clicked.emit(self.camera_id)
        super().mousePressEvent(event)


class CameraGrid(QScrollArea):
    """相机卡片网格（自动换行，N 台相机自适应）。

    信号：
        card_clicked(str)  点击某张卡片。
    """

    card_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: Dict[str, CameraCard] = {}

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(8)
        self.setWidget(self._container)

    # ------------------------------------------------------------ 公共接口
    def set_cameras(self, camera_ids: List[str]):
        """重建网格（连接设备变化时调用）。"""
        for card in self._cards.values():
            card.deleteLater()
        self._cards.clear()

        cols = max(1, min(3, len(camera_ids)))  # 1~3 列自适应
        for i, cid in enumerate(camera_ids):
            card = CameraCard(cid)
            card.clicked.connect(self.card_clicked)
            self._cards[cid] = card
            self._grid.addWidget(card, i // cols, i % cols)

    def card(self, camera_id: str) -> Optional[CameraCard]:
        return self._cards.get(camera_id)

    def camera_ids(self) -> List[str]:
        return list(self._cards.keys())
