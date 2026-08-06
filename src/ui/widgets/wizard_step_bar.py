# -*- coding: utf-8 -*-
"""
向导式步骤条（WizardStepBar）—— 功能一专用。

显示当前工作流程的步骤进度，完成步骤高亮，当前步骤放大显示，
前置未完成步骤置灰，点击可回退（如果允许）。
"""

from __future__ import annotations

from typing import List, Tuple, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame,
)


class StepWidget(QFrame):
    """单个步骤指示器。"""

    clicked = Signal(int)

    def __init__(self, index: int, title: str, parent=None):
        super().__init__(parent)
        self._index = index
        self._title = title
        self._state = "pending"  # pending / current / done / disabled
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QFrame.StyledPanel)
        self.setLineWidth(1)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 4, 8, 4)
        lo.setSpacing(2)

        self.lbl_num = QLabel(str(self._index + 1))
        self.lbl_num.setAlignment(Qt.AlignCenter)
        self.lbl_num.setStyleSheet(
            "font-size: 14pt; font-weight: bold; color: #8B8D98;")
        lo.addWidget(self.lbl_num)

        self.lbl_title = QLabel(self._title)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 8pt; color: #8B8D98;")
        lo.addWidget(self.lbl_title)

        self.setMinimumWidth(80)
        self.setMaximumWidth(100)

    def set_state(self, state: str):
        """设置步骤状态：pending / current / done / disabled。"""
        self._state = state
        if state == "done":
            self.setStyleSheet(
                "StepWidget { background-color: #1B5E20; border: 1px solid #43a047; border-radius: 6px; }")
            self.lbl_num.setStyleSheet(
                "font-size: 14pt; font-weight: bold; color: #43a047;")
            self.lbl_title.setStyleSheet("font-size: 8pt; color: #43a047;")
        elif state == "current":
            self.setStyleSheet(
                "StepWidget { background-color: #0D47A1; border: 2px solid #2979FF; border-radius: 6px; }")
            self.lbl_num.setStyleSheet(
                "font-size: 16pt; font-weight: bold; color: #2979FF;")
            self.lbl_title.setStyleSheet("font-size: 9pt; color: #2979FF; font-weight: bold;")
        elif state == "disabled":
            self.setStyleSheet(
                "StepWidget { background-color: #1A1A20; border: 1px solid #2A2A34; border-radius: 6px; }")
            self.lbl_num.setStyleSheet(
                "font-size: 14pt; font-weight: bold; color: #4A4A52;")
            self.lbl_title.setStyleSheet("font-size: 8pt; color: #4A4A52;")
        else:  # pending
            self.setStyleSheet(
                "StepWidget { background-color: #1A1A20; border: 1px solid #2A2A34; border-radius: 6px; }")
            self.lbl_num.setStyleSheet(
                "font-size: 14pt; font-weight: bold; color: #8B8D98;")
            self.lbl_title.setStyleSheet("font-size: 8pt; color: #8B8D98;")

    def mousePressEvent(self, event):
        if self._state in ("done", "current"):
            self.clicked.emit(self._index)
        super().mousePressEvent(event)


class WizardStepBar(QWidget):
    """向导式步骤条。"""

    step_clicked = Signal(int)

    def __init__(self, steps: List[str], parent=None):
        super().__init__(parent)
        self._steps = steps
        self._current = 0
        self._step_widgets: List[StepWidget] = []
        self._setup_ui()

    def _setup_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)

        for i, title in enumerate(self._steps):
            step = StepWidget(i, title)
            step.clicked.connect(self._on_step_clicked)
            self._step_widgets.append(step)
            lo.addWidget(step)
            if i < len(self._steps) - 1:
                arrow = QLabel("→")
                arrow.setStyleSheet("color: #4A4A52; font-size: 12pt;")
                arrow.setAlignment(Qt.AlignCenter)
                lo.addWidget(arrow)
        lo.addStretch(1)
        self._update_states()

    def set_current(self, index: int):
        """设置当前步骤索引。"""
        self._current = max(0, min(index, len(self._steps) - 1))
        self._update_states()

    def set_step_done(self, index: int, done: bool = True):
        """设置指定步骤为完成/未完成。"""
        if 0 <= index < len(self._step_widgets):
            if done:
                self._step_widgets[index].set_state("done")
            else:
                self._step_widgets[index].set_state("pending")
            self._update_states()

    def get_current(self) -> int:
        return self._current

    def _update_states(self):
        for i, w in enumerate(self._step_widgets):
            if i < self._current:
                w.set_state("done")
            elif i == self._current:
                w.set_state("current")
            else:
                w.set_state("pending")

    def _on_step_clicked(self, index: int):
        if index <= self._current:
            self.step_clicked.emit(index)
