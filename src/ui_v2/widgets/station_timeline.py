# -*- coding: utf-8 -*-
"""
ui_v2.widgets.station_timeline —— 模式 B 核心控件：机位时间线。

左侧竖排节点链 #1 → #2 → #3 → …
  - 节点卡片：机位号 / 共视标记数 / 与上一机位重合度 / 误差 mm / 状态色标；
  - 当前机位高亮；失败机位节点内嵌「重拍」按钮；
  - 点击节点选中 → 工作区提供「重拍该机位 / 删除该节点（后续链自动重算）」；
  - 链末尾检测到与早期机位共视时，底部出现「🔁 发现闭环，可优化全局精度」。

术语约束：本控件只使用「机位 / 重合度 / 链 / 误差」，禁止标定术语。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..theme import (
    ACCENT, ACCENT_DIM, BG_CARD, BG_PANEL, BORDER,
    STATUS_ERR, STATUS_OK, STATUS_WARN,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)
from .. import icons as ui_icons

# 节点状态色标
STATUS_STYLE = {
    "ok": (STATUS_OK, "通过"),
    "warn": (STATUS_WARN, "谨慎"),
    "fail": (STATUS_ERR, "失败"),
}


@dataclass
class StationNodeData:
    """机位节点数据（UI 层结构）。"""

    index: int                      # 机位号（从 1 开始）
    shared_markers: int = 0         # 与上一机位的共视标记数
    overlap_ratio: float = 0.0      # 与上一机位重合度 0~1
    rms_mm: Optional[float] = None  # 本步误差 mm（失败时可为 None）
    status: str = "ok"              # ok / warn / fail
    backend_ref: object = None      # 后端机位句柄，UI 不解释，原样回传


class StationNode(QFrame):
    """单个机位节点卡片。"""

    clicked = Signal(int)
    recapture_clicked = Signal(int)

    def __init__(self, data: StationNodeData, parent=None):
        super().__init__(parent)
        self._data = data
        self._selected = False

        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 8, 10, 8)
        lo.setSpacing(3)

        head = QHBoxLayout()
        self._title = QLabel(f"#{data.index}")
        self._title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {TEXT_PRIMARY};")
        head.addWidget(self._title)
        head.addStretch(1)

        color, status_text = STATUS_STYLE.get(data.status, STATUS_STYLE["ok"])
        self._status = QLabel(f"● {status_text}")
        self._status.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600;")
        head.addWidget(self._status)
        lo.addLayout(head)

        self._detail = QLabel(self._detail_text(data))
        self._detail.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px;")
        lo.addWidget(self._detail)

        # 失败机位：内嵌重拍按钮
        if data.status == "fail":
            self._btn_recapture = QPushButton("重拍")
            self._btn_recapture.setObjectName("danger")
            ui_icons.apply(self._btn_recapture, "refresh", STATUS_ERR, 13)
            self._btn_recapture.clicked.connect(
                lambda: self.recapture_clicked.emit(self._data.index))
            lo.addWidget(self._btn_recapture)

        self.setCursor(Qt.PointingHandCursor)
        self._apply_style()

    @staticmethod
    def _detail_text(d: StationNodeData) -> str:
        parts = [f"共视 {d.shared_markers}", f"重合度 {d.overlap_ratio * 100:.0f}%"]
        if d.rms_mm is not None:
            parts.append(f"误差 {d.rms_mm:.2f}mm")
        return " ｜ ".join(parts)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    def _apply_style(self):
        if self._selected:
            self.setStyleSheet(
                f"StationNode {{ background-color: {ACCENT_DIM};"
                f" border: none; border-radius: 6px; }}")
        else:
            self.setStyleSheet(
                f"StationNode {{ background-color: {BG_CARD};"
                f" border: none; border-radius: 6px; }}")

    def mousePressEvent(self, event):
        self.clicked.emit(self._data.index)
        super().mousePressEvent(event)


class StationTimeline(QScrollArea):
    """机位时间线（竖排节点链）。

    信号：
        node_selected(int)          点击选中某机位节点
        recapture_requested(int)    节点内「重拍」按钮
        loop_closure_requested()    底部「发现闭环，可优化全局精度」按钮
    """

    node_selected = Signal(int)
    recapture_requested = Signal(int)
    loop_closure_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes: List[StationNode] = []
        self._current_index = 0

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumWidth(220)
        self.setMaximumWidth(260)

        container = QWidget()
        self._vbox = QVBoxLayout(container)
        self._vbox.setContentsMargins(6, 6, 6, 6)
        self._vbox.setSpacing(6)

        header = QLabel("机位时间线")
        header.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {TEXT_SECONDARY};")
        self._vbox.addWidget(header)

        self._vbox.addStretch(1)

        # 闭环提示按钮（默认隐藏，检测到与早期机位共视时显示）
        self._btn_loop = QPushButton("发现闭环，可优化全局精度")
        self._btn_loop.setStyleSheet(
            f"border: 1px solid {STATUS_WARN}; color: {STATUS_WARN};"
            "background: transparent; font-weight: 600;")
        ui_icons.apply(self._btn_loop, "loop", STATUS_WARN, 14)
        self._btn_loop.clicked.connect(self.loop_closure_requested)
        self._btn_loop.hide()
        self._vbox.addWidget(self._btn_loop)

        # 空链提示
        self._empty_hint = QLabel("尚未拍摄机位\n点击下方「拍摄机位」开始")
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; padding: 12px 0;")
        self._vbox.insertWidget(1, self._empty_hint)

        self.setWidget(container)

    # ------------------------------------------------------------ 公共接口
    def add_station(self, data: StationNodeData):
        """追加一个机位节点（评估通过后由工作区调用）。

        # TODO(BACKEND): 数据来源为移动链式工作流的评估结果
        """
        node = StationNode(data)
        node.clicked.connect(self._on_node_clicked)
        node.recapture_clicked.connect(self.recapture_requested)
        # 插入到 stretch 之前，保持链顺序
        self._vbox.insertWidget(self._vbox.count() - 2, node)
        self._nodes.append(node)
        self._empty_hint.hide()
        self.set_current(data.index)

    def update_station(self, data: StationNodeData):
        """更新已有节点（重拍覆盖 / 闭环优化后误差刷新）。

        空壳实现：移除旧节点并按原位重建。
        """
        for i, node in enumerate(self._nodes):
            if node._data.index == data.index:
                self._vbox.removeWidget(node)
                node.deleteLater()
                new_node = StationNode(data)
                new_node.clicked.connect(self._on_node_clicked)
                new_node.recapture_clicked.connect(self.recapture_requested)
                self._vbox.insertWidget(i + 1, new_node)  # +1 跳过 header
                self._nodes[i] = new_node
                break

    def remove_station(self, index: int):
        """删除节点。

        # TODO(BACKEND): 删除后由后端触发后续链自动重算并刷新节点
        """
        for node in self._nodes:
            if node._data.index == index:
                self._vbox.removeWidget(node)
                node.deleteLater()
                self._nodes.remove(node)
                break
        if not self._nodes:
            self._empty_hint.show()

    def clear(self):
        """清空整条链（新会话）。"""
        for node in self._nodes:
            node.deleteLater()
        self._nodes.clear()
        self._current_index = 0
        self._empty_hint.show()
        self.set_loop_closure_available(False)

    def set_current(self, index: int):
        """高亮当前机位节点。"""
        self._current_index = index
        for node in self._nodes:
            node.set_selected(node._data.index == index)

    def station_count(self) -> int:
        return len(self._nodes)

    def set_loop_closure_available(self, available: bool):
        """显示/隐藏闭环优化提示（链末尾与早期机位共视时置 True）。

        # TODO(BACKEND): 由位姿图闭环检测结果驱动
        """
        self._btn_loop.setVisible(available)

    # ------------------------------------------------------------ 内部
    def _on_node_clicked(self, index: int):
        self.set_current(index)
        self.node_selected.emit(index)
