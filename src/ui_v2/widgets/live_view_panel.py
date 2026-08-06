# -*- coding: utf-8 -*-
"""
ui_v2.widgets.live_view_panel —— 模式 B 实时取景面板（占位）。

中央上部单相机实时画面，**拍摄后自动执行检测**（核心需求：
不提供手动「检测」按钮，检测/匹配由工作流自动触发，UI 只负责叠加呈现）：
  1. 检测编码圆 → 绿框 + code 号叠加；
  2. 与上一机位的共有标记 → 蓝色圆圈高亮；
  3. 上一机位标记在当前视野中的位置 → 半透明蓝圈引导提示。

正式接入时替换为 camera_card.AspectRatioLabel 的叠加渲染
（绿圈 + code 文字已有实现），本壳保留布局、状态与叠加数据接口。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout,
)

from ..theme import (
    ACCENT, BG_PANEL, BORDER, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY,
)

# 一个标记的叠加描述：(x, y, code, shared)
#   x, y    归一化坐标 0~1（相对画面）
#   code    编码圆 code 号
#   shared  是否为与上一机位的共有标记（蓝圈高亮）
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

        self.setStyleSheet(
            f"LiveViewPanel {{ background-color: {BG_PANEL};"
            f" border: 1px solid {BORDER}; border-radius: 6px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部条：标题 + 自动/手动开关 ----
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 6)
        title = QLabel("📷 实时取景（自动检测）")
        title.setStyleSheet(f"font-weight: 600; color: {TEXT_SECONDARY};")
        bar.addWidget(title)
        bar.addStretch(1)

        self._auto_hint = QLabel("自动检测已开启")
        self._auto_hint.setStyleSheet(f"color: {STATUS_OK}; font-size: 11px;")
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

        # ---- 画面占位区 ----
        self._canvas = QLabel("实时画面区\n\n（接口预留：拍摄后自动叠加\n"
                              "绿框编码圆 + 共有标记蓝圈引导）")
        self._canvas.setAlignment(Qt.AlignCenter)
        self._canvas.setMinimumHeight(220)
        self._canvas.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        root.addWidget(self._canvas, 1)

        # ---- 底部提示条：共有标记引导 ----
        self._guide = QLabel("")
        self._guide.setAlignment(Qt.AlignCenter)
        self._guide.setStyleSheet(
            f"color: #64B5F6; font-size: 11px; padding: 4px;")
        self._guide.hide()
        root.addWidget(self._guide)

    # ------------------------------------------------------------ 公共接口
    def set_frame(self, pixmap: Optional[QPixmap]):
        """刷新实时画面。

        # TODO(BACKEND): 相机帧 → QPixmap（复用 camera_card.numpy_to_qpixmap）
        """
        if pixmap is None:
            self._canvas.setText("实时画面区\n\n（接口预留）")
            return
        self._canvas.setPixmap(pixmap.scaled(
            self._canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_detection_overlay(self, markers: Sequence[MarkerOverlay]):
        """叠加检测结果（拍摄后由工作流自动检测并调用，无手动检测入口）。

        # TODO(BACKEND): 工作流检测结果 → 绿框 + code 号 / 共有标记蓝圈
        """
        total = len(markers)
        shared = sum(1 for m in markers if m[3])
        if total:
            self._canvas.setText(
                f"实时画面区（占位）\n\n检测到 {total} 个编码圆，"
                f"其中共有标记 {shared} 个")
        if shared:
            self._guide.setText(
                f"上一机位共有标记 {shared} 个（蓝圈）— "
                "保持这些区域在视野内可提高重合度")
            self._guide.show()
        else:
            self._guide.hide()

    def clear_overlay(self):
        """清空叠加（移动相机/重拍时调用）。"""
        self._guide.hide()

    def is_auto_mode(self) -> bool:
        return self._auto_mode

    # ------------------------------------------------------------ 内部
    def _on_mode_toggled(self, checked: bool):
        self._auto_mode = checked
        self._mode_btn.setText("自动 ▾" if checked else "手动 ▾")
        self._auto_hint.setText("自动检测已开启" if checked else "手动模式（兜底）")
        self._auto_hint.setStyleSheet(
            f"color: {STATUS_OK if checked else ACCENT}; font-size: 11px;")
        self.mode_toggled.emit(checked)
