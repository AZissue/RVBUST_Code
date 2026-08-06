# -*- coding: utf-8 -*-
"""
ui_v2.widgets.evaluation_card —— 模式 B 评估卡片。

每拍一帧自动更新（不阻塞操作）：
  共视标记数 / 内点率 / RMS(mm) / 建议动作。
三色语义：
  🟢 绿「重合度充足，可继续移动」
  🟡 黄「可继续，建议减小移动距离」
  🔴 红「配准失败，请重拍或微调位置后重试」
评估结果同步写入机位时间线节点，形成可回放记录。

术语约束：使用「机位 / 重合度 / 误差」，不出现标定术语。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ..theme import (
    BG_CARD, BORDER, STATUS_ERR, STATUS_OK, STATUS_WARN,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)

_LEVEL_STYLE = {
    "ok": STATUS_OK,
    "warn": STATUS_WARN,
    "fail": STATUS_ERR,
}


class EvaluationCard(QFrame):
    """单步配准评估卡片（空壳，等待工作流评估结果驱动）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = "idle"

        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 10, 12, 10)
        lo.setSpacing(6)

        self._head = QLabel("本步评估")
        self._head.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {TEXT_SECONDARY};")
        lo.addWidget(self._head)

        metrics = QHBoxLayout()
        metrics.setSpacing(16)
        self._shared = self._metric(metrics, "共视标记", "—")
        self._inlier = self._metric(metrics, "内点率", "—")
        self._rms = self._metric(metrics, "误差", "—")
        metrics.addStretch(1)
        lo.addLayout(metrics)

        self._suggestion = QLabel("拍摄机位后自动评估")
        self._suggestion.setWordWrap(True)
        self._suggestion.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        lo.addWidget(self._suggestion)

        self._apply_style()

    @staticmethod
    def _metric(parent_lo: QHBoxLayout, name: str, value: str) -> QLabel:
        col = QVBoxLayout()
        col.setSpacing(2)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        col.addWidget(name_lbl)
        value_lbl = QLabel(value)
        value_lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        col.addWidget(value_lbl)
        parent_lo.addLayout(col)
        return value_lbl

    # ------------------------------------------------------------ 公共接口
    def set_evaluation(
        self,
        shared_markers: int,
        inlier_ratio: float,
        rms_mm: Optional[float],
        level: str,
        suggestion: str,
    ):
        """刷新评估结果。

        参数：
            shared_markers  与上一机位的共视标记数
            inlier_ratio    内点率 0~1
            rms_mm          本步误差 mm（失败可为 None）
            level           ok / warn / fail（🟢/🟡/🔴 三色语义）
            suggestion      建议动作文案（由工作流给出，UI 不自行编造）

        # TODO(BACKEND): 评估阈值（共视≥6 / 内点率≥0.7 / RMS 达标）
        由移动链式工作流判定后传入 level 与 suggestion。
        """
        self._shared.setText(str(shared_markers))
        self._inlier.setText(f"{inlier_ratio * 100:.0f}%")
        self._rms.setText(f"{rms_mm:.2f}mm" if rms_mm is not None else "—")

        self._level = level if level in _LEVEL_STYLE else "idle"
        color = _LEVEL_STYLE.get(self._level)
        if color:
            self._suggestion.setText(f"● {suggestion}")
            self._suggestion.setStyleSheet(
                f"color: {color}; font-size: 12px; font-weight: 600;")
        else:
            self._suggestion.setText(suggestion)
            self._suggestion.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 12px;")
        self._apply_style()

    def reset(self):
        """恢复待评估状态（撤销/重拍/新会话时调用）。"""
        self._level = "idle"
        self._shared.setText("—")
        self._inlier.setText("—")
        self._rms.setText("—")
        self._suggestion.setText("拍摄机位后自动评估")
        self._suggestion.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._apply_style()

    # ------------------------------------------------------------ 内部
    def _apply_style(self):
        color = _LEVEL_STYLE.get(self._level, BORDER)
        self.setStyleSheet(
            f"EvaluationCard {{ background-color: {BG_CARD};"
            f" border: 1px solid {color}; border-left: 4px solid {color};"
            f" border-radius: 6px; }}")
