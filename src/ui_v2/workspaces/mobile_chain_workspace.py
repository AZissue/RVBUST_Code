# -*- coding: utf-8 -*-
"""
ui_v2.workspaces.mobile_chain_workspace —— 模式 B：单相机工作区（空壳）。

移动链式拼接流程，布局：左机位时间线 + 中央上下分栏（实时取景 / 3D 预览）
+ 底部评估卡片与操作按钮区。

核心需求（UI 严格遵循）：
  - 拍摄后**自动**检测标记物：不提供任何手动「检测」按钮，
    拍摄 → 自动检测 → 自动匹配 → 评估 → 入链，全流程由工作流驱动；
  - 拍摄按钮与「移动到下一机位」语义分离；
  - 上一帧评估通过前不覆盖已拍机位数据（帧即存盘）。

状态机（UI 严格跟随，见 set_state）：
  待机 → 已连接 → 拍摄机位 → 自动检测/匹配 → 评估
      ├─ 通过🟢/谨慎🟡 → 入链 + 实时拼接刷新 → 提示继续移动
      └─ 失败🔴 → 拒绝入链，提示重拍/调整位置
  → 检测到与早期机位共视 → 闭环提示 → 全局优化 → 保存

术语：机位 / 重合度 / 链 / 漂移 / 误差。**禁止**「参考相机/pair/RMS」等标定术语
（内部字段名沿用 rms_mm 仅作数据键，UI 文案一律显示「误差」）。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from ..theme import STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_MUTED, TEXT_SECONDARY
from .. import icons as ui_icons
from ..widgets import (
    EvaluationCard, LiveViewPanel, StationNodeData, StationTimeline, ViewerPanel,
)
from ..widgets.device_table import DeviceInfo


class MobileChainWorkspace(QWidget):
    """模式 B 工作区（UI 空壳 + 操作门控）。"""

    STATES = ("idle", "connected", "capturing", "evaluating", "chaining")

    # ---------------------------------------------------------------- 信号（接口预留）
    capture_station_requested = Signal()
    """拍摄机位（主操作）。拍完自动走 检测→匹配→评估→入链 全流程。"""

    preview_toggled = Signal(bool)
    """实时取景开关（True=开始预览，False=停止）。"""

    undo_requested = Signal()
    """撤销上一步（防误操作兜底）。"""

    recapture_requested = Signal(int)
    """重拍指定机位（-1 表示当前机位）。"""

    delete_station_requested = Signal(int)
    """删除指定机位节点（后续链自动重算）。"""

    save_requested = Signal()
    """保存拼接数据：会话 + 拼接点云 PLY + 误差报告 error_report.json。"""

    optimize_requested = Signal()
    """闭环全局优化（弹出优化前后误差对比由后端结果回填）。"""

    station_selected = Signal(int)
    """时间线中选中某个机位节点（供后端刷新 2D 预览）。"""

    auto_mode_changed = Signal(bool)
    """自动/手动模式切换（默认自动；手动才显示手动标定面板兜底）。"""

    log_message = Signal(str, str)
    """工作区日志（message, level）。"""

    chain_stats_changed = Signal(str)
    """链统计变化（供主窗口状态栏常驻显示）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._devices: List[DeviceInfo] = []
        self._station_count = 0
        self._total_error_mm = 0.0

        self._setup_ui()
        self.set_state("idle")

    # ------------------------------------------------------------ UI 搭建
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        body = QHBoxLayout()
        body.setSpacing(8)

        # ---- 左：机位时间线 ----
        self._timeline = StationTimeline()
        self._timeline.node_selected.connect(self._on_node_selected)
        self._timeline.recapture_requested.connect(self.recapture_requested)
        self._timeline.loop_closure_requested.connect(self.optimize_requested)
        body.addWidget(self._timeline)

        # ---- 中央：左实时取景 / 右 3D 预览（水平布局，便于边拍边看） ----
        center_split = QSplitter(Qt.Horizontal)
        self._live_view = LiveViewPanel()
        self._live_view.setMinimumWidth(420)
        self._live_view.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._live_view.mode_toggled.connect(self.auto_mode_changed)
        center_split.addWidget(self._live_view)

        self._viewer = ViewerPanel("实时 3D 拼接预览（按机位分色）")
        self._viewer.setMinimumWidth(420)
        self._viewer.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer.viewer_message.connect(
            lambda m: self.log_message.emit(m, "info"))
        center_split.addWidget(self._viewer)
        center_split.setStretchFactor(0, 1)
        center_split.setStretchFactor(1, 1)
        center_split.setSizes([600, 600])
        body.addWidget(center_split, 1)

        root.addLayout(body, 1)

        # ---- 底部：评估卡片 + 操作按钮区 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self._eval_card = EvaluationCard()
        bottom.addWidget(self._eval_card, 1)

        actions = QVBoxLayout()
        actions.setSpacing(6)

        self._btn_preview = QPushButton("开始取景")
        self._btn_preview.setCheckable(True)
        self._btn_preview.setObjectName("bigAction")
        ui_icons.apply(self._btn_preview, "video", TEXT_SECONDARY, 18)
        self._btn_preview.toggled.connect(self._on_preview_toggled)
        actions.addWidget(self._btn_preview)

        self._btn_capture = QPushButton("拍摄机位")
        self._btn_capture.setObjectName("bigAction")
        ui_icons.apply(self._btn_capture, "camera", "#FFFFFF", 20)
        self._btn_capture.clicked.connect(self.capture_station_requested)
        actions.addWidget(self._btn_capture)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._btn_undo = QPushButton("撤销上一步")
        ui_icons.apply(self._btn_undo, "undo", TEXT_SECONDARY, 14)
        self._btn_undo.clicked.connect(self.undo_requested)
        row.addWidget(self._btn_undo)
        self._btn_recapture = QPushButton("重拍当前")
        self._btn_recapture.setObjectName("danger")
        ui_icons.apply(self._btn_recapture, "refresh", STATUS_ERR, 14)
        self._btn_recapture.clicked.connect(
            lambda: self.recapture_requested.emit(-1))
        row.addWidget(self._btn_recapture)
        actions.addLayout(row)

        self._btn_save = QPushButton("保存拼接数据")
        ui_icons.apply(self._btn_save, "save", TEXT_SECONDARY, 14)
        self._btn_save.clicked.connect(self.save_requested)
        actions.addWidget(self._btn_save)

        # 选中节点的删除入口（点击时间线节点后可用）
        self._btn_delete_node = QPushButton("删除选中机位（后续链自动重算）")
        self._btn_delete_node.setObjectName("danger")
        ui_icons.apply(self._btn_delete_node, "trash", STATUS_ERR, 14)
        self._btn_delete_node.setEnabled(False)
        self._btn_delete_node.clicked.connect(self._on_delete_selected)
        actions.addWidget(self._btn_delete_node)

        bottom.addLayout(actions)
        root.addLayout(bottom)

        # ---- 底部常驻统计行：已接 N 机位 | 累计误差 | 平均单步误差 ----
        self._stats_label = QLabel("已接 0 机位 ｜ 累计误差 — ｜ 平均单步误差 —")
        self._stats_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 12px; padding: 2px 4px;")
        root.addWidget(self._stats_label)

        self._selected_node: Optional[int] = None

    # ------------------------------------------------------------ 状态机（UI 门控）
    def set_state(self, state: str):
        """设置工作区状态，按钮可用性跟随。

        # TODO(BACKEND): 状态迁移由工作流事件驱动，UI 不自行推进。
        """
        if state not in self.STATES:
            raise ValueError(f"未知状态: {state}")
        self._state = state

        connected = state != "idle"
        busy = state in ("capturing", "evaluating")

        # 拍摄中/评估中禁用全部操作（防止并发与覆盖已拍机位）
        self._btn_capture.setEnabled(connected and not busy)
        self._btn_undo.setEnabled(self._station_count > 0 and not busy)
        self._btn_recapture.setEnabled(self._station_count > 0 and not busy)
        self._btn_save.setEnabled(self._station_count > 0 and not busy)
        self._btn_delete_node.setEnabled(
            self._selected_node is not None and not busy)

    def current_state(self) -> str:
        return self._state

    def live_view(self) -> LiveViewPanel:
        """实时取景面板（预览帧回填入口）。"""
        return self._live_view

    def viewer(self) -> ViewerPanel:
        """3D 拼接预览组件。"""
        return self._viewer

    # ------------------------------------------------------------ 内部
    def _on_preview_toggled(self, checked: bool):
        self._btn_preview.setText("停止取景" if checked else "开始取景")
        self.preview_toggled.emit(checked)

    # ------------------------------------------------------------ 后端回填接口（stub 文档）
    def set_devices(self, devices: List[DeviceInfo]):
        """填充已连接设备（单相机模式恰好 1 台）。"""
        self._devices = list(devices)

    def on_capture_done(self, frame_pixmap=None):
        """拍摄完成：刷新实时画面（随后工作流自动检测，UI 等待叠加数据）。

        # TODO(BACKEND): frame → QPixmap；检测完成后回 on_detection_done
        """
        self._live_view.set_frame(frame_pixmap)
        self._live_view.clear_overlay()

    def on_detection_done(self, markers):
        """自动检测完成：叠加绿框编码圆 + 共有标记蓝圈引导。

        参数：markers = [(x, y, code, shared), ...]（见 LiveViewPanel）
        """
        self._live_view.set_detection_overlay(markers)

    def set_evaluation(
        self,
        shared_markers: int,
        inlier_ratio: float,
        rms_mm: Optional[float],
        level: str,
        suggestion: str,
    ):
        """仅更新评估卡片（不修改时间线）。用于重拍/删除后刷新当前评估。"""
        self._eval_card.set_evaluation(
            shared_markers, inlier_ratio, rms_mm, level, suggestion)

    def on_evaluation_done(
        self,
        shared_markers: int,
        inlier_ratio: float,
        rms_mm: Optional[float],
        level: str,
        suggestion: str,
        backend_ref: object = None,
    ):
        """评估完成：更新评估卡片；通过/谨慎时同步入链时间线节点。

        level: ok / warn / fail（🟢/🟡/🔴）
        fail 时拒绝入链（不追加节点）。
        """
        self.set_evaluation(shared_markers, inlier_ratio, rms_mm, level, suggestion)

        if level in ("ok", "warn"):
            self._station_count += 1
            self._timeline.add_station(StationNodeData(
                index=self._station_count,
                shared_markers=shared_markers,
                overlap_ratio=inlier_ratio,
                rms_mm=rms_mm,
                status=level,
                backend_ref=backend_ref,
            ))
            self._recompute_stats()
        # fail：拒绝入链，等待重拍（评估卡片已显示红色建议）
        # 入链/评估后回到可拍摄状态，按钮门控跟随机位数量
        self.set_state("chaining")

    def on_loop_closure_detected(self):
        """检测到链末尾与早期机位共视：显示闭环优化入口。"""
        self._timeline.set_loop_closure_available(True)

    def on_optimize_done(self, before_mm: float, after_mm: float):
        """全局优化完成：弹出前后误差对比（空壳以日志 + 统计刷新呈现）。

        # TODO(BACKEND): 正式接入时弹对比对话框
        """
        self._timeline.set_loop_closure_available(False)
        self._total_error_mm = after_mm * max(1, self._station_count)
        self._refresh_stats()
        self.log_message.emit(
            f"全局优化完成：误差 {before_mm:.2f}mm → {after_mm:.2f}mm", "success")

    def on_undo_done(self):
        """撤销完成：移除链尾节点并复位评估卡片。"""
        if self._station_count > 0:
            self._timeline.remove_station(self._station_count)
            self._station_count -= 1
        self._eval_card.reset()
        self._recompute_stats()
        self.set_state(self._state)

    def on_recapture_done(
        self,
        index: int,
        shared_markers: int,
        inlier_ratio: float,
        rms_mm: Optional[float],
        level: str,
        suggestion: str,
        backend_ref: object = None,
    ):
        """重拍完成：替换指定索引节点数据并刷新统计。"""
        self._timeline.update_station(StationNodeData(
            index=index,
            shared_markers=shared_markers,
            overlap_ratio=inlier_ratio,
            rms_mm=rms_mm,
            status=level,
            backend_ref=backend_ref,
        ))
        self._eval_card.set_evaluation(
            shared_markers, inlier_ratio, rms_mm, level, suggestion)
        self._recompute_stats()
        self.set_state("chaining")

    def reset_session(self):
        """新会话：清空链 / 评估 / 统计。"""
        self._station_count = 0
        self._total_error_mm = 0.0
        self._timeline.clear()
        self._eval_card.reset()
        self._refresh_stats()
        self.set_state(self._state)

    def set_stations(self, evaluations: List[Dict]):
        """根据后端当前机位列表重建时间线（删除/重排后调用）。"""
        self._timeline.clear()
        self._station_count = 0
        self._total_error_mm = 0.0
        self._selected_node = None
        for ev in evaluations:
            self._station_count += 1
            self._timeline.add_station(StationNodeData(
                index=self._station_count,
                shared_markers=ev.get('shared_markers', 0),
                overlap_ratio=ev.get('inlier_ratio', 0.0),
                rms_mm=ev.get('rms_mm'),
                status=ev.get('status', 'ok'),
                backend_ref=ev.get('station_id'),
            ))
        self._recompute_stats()
        self.set_state(self._state)

    def get_station_id(self, index: int) -> Optional[str]:
        """由时间线索引获取后端 station_id（backend_ref）。"""
        for node in self._timeline._nodes:
            if node._data.index == index:
                ref = node._data.backend_ref
                return ref if isinstance(ref, str) else None
        return None

    def viewer(self) -> ViewerPanel:
        """3D 预览组件（增量拼接刷新入口，按机位分色）。"""
        return self._viewer

    def live_view(self) -> LiveViewPanel:
        return self._live_view

    # ------------------------------------------------------------ 内部
    def _recompute_stats(self):
        """根据时间线节点重新计算累计误差与机位数（撤销/删除/重拍后调用）。"""
        total = 0.0
        for node in self._timeline._nodes:
            if node._data.rms_mm is not None:
                total += node._data.rms_mm
        self._station_count = len(self._timeline._nodes)
        self._total_error_mm = total
        self._refresh_stats()

    def _refresh_stats(self):
        """底部常驻统计：已接 N 机位 | 累计误差 | 平均单步误差（超阈值变红）。"""
        n = self._station_count
        if n == 0:
            text = "已接 0 机位 ｜ 累计误差 — ｜ 平均单步误差 —"
            color = TEXT_MUTED
        else:
            avg = self._total_error_mm / n
            text = (f"已接 {n} 机位 ｜ 累计误差 {self._total_error_mm:.2f}mm ｜ "
                    f"平均单步误差 {avg:.2f}mm")
            # TODO(BACKEND): 阈值由工作流配置；超阈值建议全局优化
            threshold = 1.0
            color = STATUS_ERR if avg > threshold else STATUS_OK
            if avg > threshold:
                text += "  ⚠ 建议执行全局优化"
        self._stats_label.setText(text)
        self._stats_label.setStyleSheet(
            f"color: {color}; font-size: 12px; padding: 2px 4px;")
        self.chain_stats_changed.emit(text)

    def _on_node_selected(self, index: int):
        self._selected_node = index
        self._btn_delete_node.setEnabled(self._state not in ("capturing", "evaluating"))
        self.station_selected.emit(index)

    def _on_delete_selected(self):
        if self._selected_node is not None:
            self.delete_station_requested.emit(self._selected_node)
            self._selected_node = None
            self._btn_delete_node.setEnabled(False)
