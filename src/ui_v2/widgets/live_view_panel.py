# -*- coding: utf-8 -*-
"""
ui_v2.widgets.live_view_panel —— 模式 B 实时取景面板。

中央上部单相机实时画面，**拍摄后自动执行检测**（核心需求：
不提供手动「检测」按钮，检测/匹配由工作流自动触发，UI 只负责叠加呈现）：
  1. 检测编码圆 → 红/绿圈 + code 号叠加（绿=3D 有效，红=2D 检出但 3D
     无有效深度，圆心处深度成片无效时用户可直接看到是哪个标记需要调整）；
  2. 与上一机位的共有标记 → 底部引导文字提示；
  3. 上一机位标记在当前视野中的位置 → 半透明蓝圈引导提示（待实现）。

画布复用 ui.camera_card.AspectRatioLabel（按比缩放绘制 + 标记预渲染层）。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
)

from ..theme import (
    ACCENT, BG_PANEL, BORDER, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY,
)
from .. import icons as ui_icons
from ui.camera_card import AspectRatioLabel

# 一个标记的叠加描述：(x, y, code, valid_3d)
#   x, y      归一化坐标 0~1（相对画面）
#   code      编码圆 code 号
#   valid_3d  3D 深度是否有效（False = 红圈，提示圆心附近无有效深度）
MarkerOverlay = Tuple[float, float, int, bool]


class LiveViewPanel(QFrame):
    """实时取景占位面板（自动检测叠加接口预留）。

    信号：
        mode_toggled(bool)  「自动/手动」开关切换（默认自动；
                            手动模式才显示原有手动 pair 标定面板，作为兜底）。
    """

    mode_toggled = Signal(bool)  # True=自动

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_mode = True
        self._current_pixmap: Optional[QPixmap] = None

        self.setStyleSheet(
            f"LiveViewPanel {{ background-color: {BG_PANEL};"
            f" border: none; border-radius: 6px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部条：标题 + 自动/手动开关 ----
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 6)
        video_icon = QLabel()
        video_icon.setPixmap(ui_icons.pixmap("video", TEXT_SECONDARY, 15))
        video_icon.setFixedSize(18, 18)
        bar.addWidget(video_icon)
        title = QLabel("实时取景（自动检测）")
        title.setStyleSheet(f"font-weight: 600; color: {TEXT_SECONDARY};")
        bar.addWidget(title)
        bar.addStretch(1)

        self._auto_hint = QLabel("自动检测已开启")
        self._auto_hint.setStyleSheet(f"color: {STATUS_OK}; font-size: 12px;")
        bar.addWidget(self._auto_hint)

        self._mode_btn = QToolButton()
        self._mode_btn.setText("自动 ▾")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setChecked(True)
        self._mode_btn.setToolTip(
            "默认自动：拍摄后自动检测/匹配/评估。\n"
            "手动模式仅作高级用户兜底（显示手动标定面板）。")
        self._mode_btn.toggled.connect(self._on_mode_toggled)
        bar.addWidget(self._mode_btn)
        root.addLayout(bar)

        # ---- 画面区：AspectRatioLabel 自带按比缩放绘制与标记叠加 ----
        self._canvas = AspectRatioLabel(ratio=4.0 / 3.0)
        root.addWidget(self._canvas, 1)

        # ---- 底部提示条：共有标记引导 ----
        self._guide = QLabel("")
        self._guide.setAlignment(Qt.AlignCenter)
        self._guide.setStyleSheet(
            f"color: #64B5F6; font-size: 12px; padding: 4px;")
        self._guide.hide()
        root.addWidget(self._guide)

    # ------------------------------------------------------------ 公共接口
    def set_frame(self, pixmap: Optional[QPixmap]):
        """刷新实时画面；传入 None 时清空画布与叠加。"""
        self._current_pixmap = pixmap
        if pixmap is None:
            self._canvas.clear_image()
        else:
            self._canvas.setPixmap(pixmap)

    def _refresh_frame(self):
        """按当前画布尺寸重绘（AspectRatioLabel.paintEvent 自行等比缩放）。"""
        self._canvas.update()

    def set_detection_overlay(self, markers: Sequence[MarkerOverlay]):
        """叠加识别结果（拍摄后由工作流自动检测并调用）。

        红圈 = 2D 检出但 3D 无有效深度；绿圈 = 3D 有效；均带 code 号。
        """
        overlay = [{
            'x': float(m[0]), 'y': float(m[1]),
            'code': m[2], 'valid_3d': bool(m[3]),
        } for m in (markers or [])]
        self._canvas.set_markers(overlay)
        total = len(overlay)
        n_valid = sum(1 for m in overlay if m['valid_3d'])
        if not total:
            self._guide.hide()
            return
        if n_valid < total:
            self._guide.setText(
                f"检测到 {total} 个编码圆，其中 {total - n_valid} 个 3D 无有效深度"
                "（红圈）— 请调整该标记角度/光照")
        else:
            self._guide.setText(f"检测到 {total} 个编码圆（全部 3D 有效）")
        self._guide.show()

    def clear_overlay(self):
        """清空叠加（移动相机/重拍时调用）。"""
        self._canvas.clear_markers()
        self._guide.hide()

    def is_auto_mode(self) -> bool:
        return self._auto_mode

    # ------------------------------------------------------------ 内部
    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._refresh_frame()

    def _on_mode_toggled(self, checked: bool):
        self._auto_mode = checked
        self._mode_btn.setText("自动 ▾" if checked else "手动 ▾")
        self._auto_hint.setText("自动检测已开启" if checked else "手动模式（兜底）")
        self._auto_hint.setStyleSheet(
            f"color: {STATUS_OK if checked else ACCENT}; font-size: 12px;")
        self.mode_toggled.emit(checked)
