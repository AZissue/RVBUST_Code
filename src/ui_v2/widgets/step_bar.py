# -*- coding: utf-8 -*-
"""
ui_v2.widgets.step_bar —— 横向向导步骤条（模式 A 骨架控件）。

对应现有 ``src/ui/widgets/wizard_step_bar.py`` 的重设计版：
  - 状态机驱动：pending / current / done / disabled 四态；
  - 当前步骤高亮（RVC 红），已完成可点击回退；
  - 步骤状态应由工作流结果驱动，UI 仅呈现（见 set_current / set_step_enabled）。

正式接入时可整体替换回 WizardStepBar，接口已对齐：
  set_current(int) / set_step_done(int, bool) / step_clicked(int)。
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..theme import (
    ACCENT, BG_CARD, BG_PANEL, BORDER, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY,
)

_STATE_STYLE = {
    # state: (frame_bg, border, num_color, title_color)
    "done": (BG_CARD, STATUS_OK, STATUS_OK, STATUS_OK),
    "current": (BG_CARD, ACCENT, ACCENT, ACCENT),
    "pending": (BG_PANEL, BORDER, TEXT_SECONDARY, TEXT_SECONDARY),
    "disabled": (BG_PANEL, "#2B2E37", TEXT_MUTED, TEXT_MUTED),
}


class _StepItem(QFrame):
    """单个步骤节点（序号 + 标题）。"""

    clicked = Signal(int)

    def __init__(self, index: int, title: str, parent=None):
        super().__init__(parent)
        self._index = index
        self._state = "pending"

        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(2)

        self._num = QLabel(f"{index + 1:02d}")
        self._num.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._num)

        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._title)

        self.setMinimumWidth(92)
        self.set_state("pending")

    def set_state(self, state: str):
        """pending / current / done / disabled。"""
        self._state = state
        bg, border, num_c, title_c = _STATE_STYLE[state]
        weight = "700" if state == "current" else "400"
        bw = "2px" if state == "current" else "1px"
        self.setStyleSheet(
            f"_StepItem {{ background-color: {bg}; border: {bw} solid {border};"
            f" border-radius: 6px; }}"
        )
        self._num.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {num_c};")
        self._title.setStyleSheet(
            f"font-size: 11px; font-weight: {weight}; color: {title_c};")
        self.setCursor(
            Qt.PointingHandCursor if state == "done" else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        # 仅已完成步骤允许点击回退（提示词：已完成步骤可点击回退）
        if self._state == "done":
            self.clicked.emit(self._index)
        super().mousePressEvent(event)


class StepBar(QWidget):
    """横向步骤条。

    信号：
        step_clicked(int)  用户点击已完成步骤（请求回退到该步骤）。
    """

    step_clicked = Signal(int)

    def __init__(self, steps: List[str], parent=None):
        super().__init__(parent)
        self._items: List[_StepItem] = []
        self._enabled: List[bool] = [True] * len(steps)
        self._current = 0

        lo = QHBoxLayout(self)
        lo.setContentsMargins(4, 2, 4, 2)
        lo.setSpacing(6)

        for i, title in enumerate(steps):
            item = _StepItem(i, title)
            item.clicked.connect(self.step_clicked)
            self._items.append(item)
            lo.addWidget(item)
            if i < len(steps) - 1:
                arrow = QLabel("→")
                arrow.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px;")
                arrow.setAlignment(Qt.AlignCenter)
                lo.addWidget(arrow)
        lo.addStretch(1)
        self._refresh()

    # ------------------------------------------------------------ 公共接口
    def set_current(self, index: int):
        """设置当前步骤（之前的步骤标记为 done，之后的按可用性显示）。"""
        self._current = max(0, min(index, len(self._items) - 1))
        self._refresh()

    def get_current(self) -> int:
        return self._current

    def set_step_enabled(self, index: int, enabled: bool):
        """设置某步骤是否可用（不可用时置灰，前置未完成时后续应置灰）。"""
        if 0 <= index < len(self._enabled):
            self._enabled[index] = enabled
            self._refresh()

    def set_all_enabled_from(self, index: int, enabled: bool):
        """从某步骤起批量设置可用性（状态机推进/回退时使用）。"""
        for i in range(index, len(self._enabled)):
            self._enabled[i] = enabled
        self._refresh()

    # ------------------------------------------------------------ 内部
    def _refresh(self):
        for i, item in enumerate(self._items):
            if not self._enabled[i]:
                item.set_state("disabled")
            elif i < self._current:
                item.set_state("done")
            elif i == self._current:
                item.set_state("current")
            else:
                item.set_state("pending")
