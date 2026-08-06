# -*- coding: utf-8 -*-
"""
ui_v2.workspaces.multi_cam_workspace —— 模式 A：多相机工作区（空壳）。

固定多相机外参标定流程，三栏布局：
  - 顶部：步骤条（连接相机→拍摄标定→检测标记→计算外参→扫描拼接→保存）；
  - 左面板：已连接设备列表（只读）+ 拍摄控制（同步/异步 + 拍摄）+ 参考相机；
  - 中央：相机取景网格 + 3D 拼接预览；
  - 右面板：标定 Tab（检测 / 结果表格 / 质量评分 / 外参存取）
            + 扫描 Tab（撤板提醒横幅 / 扫描控制 / 批量拍摄）。

状态机（UI 严格跟随，见 set_state）：
  待机 → 已连接 → 已拍标定帧 → 已检测 → 已计算外参 → 质量门禁
      ├─ 通过 → [外参锁定] → 扫描阶段（可循环）
      └─ 不通过 → 提示重拍/重新检测，禁止进入扫描

术语：标定 / 外参 / RMS / 内点率 / 参考相机 / pair。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QVBoxLayout, QWidget,
)

from ..theme import (
    ACCENT_DIM, STATUS_ERR, STATUS_OK, STATUS_WARN,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)
from .. import icons as ui_icons
from ..widgets import CameraGrid, StepBar, ViewerPanel
from ..widgets.device_table import DeviceInfo


class MultiCamWorkspace(QWidget):
    """模式 A 工作区（UI 空壳 + 步骤状态门控）。

    状态集合（与提示词状态机一一对应）：
        idle → connected → captured → detected → calibrated → locked(扫描)
    """

    STATES = ("idle", "connected", "captured", "detected",
              "calibrated", "locked")
    STEPS = ("连接相机", "拍摄标定", "检测标记", "计算外参", "扫描拼接", "保存")

    # 状态 → 步骤条索引
    _STATE_STEP = {
        "idle": 0, "connected": 1, "captured": 2,
        "detected": 3, "calibrated": 4, "locked": 4,
    }

    # ---------------------------------------------------------------- 信号（接口预留）
    capture_requested = Signal(bool)
    """拍摄标定帧（参数：是否同步拍摄）。
    # TODO(BACKEND): CameraManager 全部相机拍摄，完成后回 on_capture_done"""

    detect_requested = Signal(str)
    """检测标记物（参数：检测方式 'coded_circle' | 'calib_board'）。
    # TODO(BACKEND): MarkerDetector / CalibBoardDetector，完成后回 on_detect_done"""

    calibrate_requested = Signal()
    """计算外参。# TODO(BACKEND): CalibrationEngine，完成后回 on_calibrate_done"""

    save_extrinsics_requested = Signal()
    load_extrinsics_requested = Signal()
    """保存/加载外参 JSON。# TODO(BACKEND): CalibrationEngine 序列化"""

    capture_scan_requested = Signal()
    """拍摄扫描帧。# TODO(BACKEND): 外参锁定后的扫描拍摄"""

    stitch_save_requested = Signal()
    """应用外参拼接并保存 PLY。# TODO(BACKEND): StitchEngine"""

    batch_scan_requested = Signal(int)
    """连续拍摄 N 次批量拼接保存（产线巡检）。"""

    reference_changed = Signal(str)
    """参考相机变更（参与标定计算）。"""

    step_back_requested = Signal(int)
    """步骤条回退请求。"""

    log_message = Signal(str, str)
    """工作区日志（message, level）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._devices: List[DeviceInfo] = []
        self._quality_passed = False

        self._setup_ui()
        self.set_state("idle")

    # ------------------------------------------------------------ UI 搭建
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ===== 顶部步骤条 =====
        self._step_bar = StepBar(list(self.STEPS))
        self._step_bar.step_clicked.connect(self._on_step_back)
        root.addWidget(self._step_bar)

        # ===== 三栏主体 =====
        body = QHBoxLayout()
        body.setSpacing(8)

        # ---- 左面板：设备 + 拍摄控制 ----
        left = QVBoxLayout()
        left.setSpacing(8)

        dev_group = QGroupBox("① 已连接设备")
        dev_lo = QVBoxLayout(dev_group)
        self._device_list = QListWidget()
        self._device_list.setMinimumHeight(90)
        dev_lo.addWidget(self._device_list)
        left.addWidget(dev_group)

        cap_group = QGroupBox("② 拍摄控制")
        cap_lo = QVBoxLayout(cap_group)
        cap_lo.setSpacing(6)
        sync_row = QHBoxLayout()
        self._rb_sync = QRadioButton("同步拍摄")
        self._rb_sync.setChecked(True)
        self._rb_async = QRadioButton("异步拍摄")
        sync_row.addWidget(self._rb_sync)
        sync_row.addWidget(self._rb_async)
        sync_row.addStretch(1)
        cap_lo.addLayout(sync_row)

        self._btn_capture = QPushButton("拍摄标定帧")
        self._btn_capture.setObjectName("primary")
        self._btn_capture.setMinimumHeight(34)
        ui_icons.apply(self._btn_capture, "camera", "#FFFFFF", 16)
        self._btn_capture.clicked.connect(self._on_capture)
        cap_lo.addWidget(self._btn_capture)

        ref_row = QHBoxLayout()
        ref_row.addWidget(QLabel("参考相机:"))
        self._ref_combo = QComboBox()
        self._ref_combo.currentTextChanged.connect(self.reference_changed)
        ref_row.addWidget(self._ref_combo, 1)
        cap_lo.addLayout(ref_row)
        left.addWidget(cap_group)
        left.addStretch(1)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(220)
        body.addWidget(left_widget)

        # ---- 中央：相机网格 + 3D 预览（上下分割） ----
        center_split = QSplitter(Qt.Vertical)
        self._camera_grid = CameraGrid()
        center_split.addWidget(self._camera_grid)
        self._viewer = ViewerPanel("3D 拼接预览")
        self._viewer.viewer_message.connect(
            lambda m: self.log_message.emit(m, "info"))
        center_split.addWidget(self._viewer)
        center_split.setStretchFactor(0, 3)
        center_split.setStretchFactor(1, 2)
        body.addWidget(center_split, 1)

        # ---- 右面板：标定 / 扫描 Tab ----
        right_widget = QWidget()
        right_widget.setFixedWidth(300)
        right_lo = QVBoxLayout(right_widget)
        right_lo.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_calib_tab(), "③ 标定")
        self._tabs.addTab(self._build_scan_tab(), "扫描")
        right_lo.addWidget(self._tabs)
        body.addWidget(right_widget)

        root.addLayout(body, 1)

    def _build_calib_tab(self) -> QWidget:
        tab = QWidget()
        lo = QVBoxLayout(tab)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(8)

        # 检测方式 + 检测按钮
        det_row = QHBoxLayout()
        det_row.addWidget(QLabel("检测方式:"))
        self._detect_combo = QComboBox()
        self._detect_combo.addItem("编码圆", "coded_circle")
        self._detect_combo.addItem("标定板", "calib_board")
        det_row.addWidget(self._detect_combo, 1)
        lo.addLayout(det_row)

        self._btn_detect = QPushButton("检测标记物")
        self._btn_detect.setObjectName("primary")
        ui_icons.apply(self._btn_detect, "detect", "#FFFFFF", 15)
        self._btn_detect.clicked.connect(
            lambda: self.detect_requested.emit(
                self._detect_combo.currentData()))
        lo.addWidget(self._btn_detect)

        self._btn_calibrate = QPushButton("计算外参")
        self._btn_calibrate.setObjectName("primary")
        ui_icons.apply(self._btn_calibrate, "calibrate", "#FFFFFF", 15)
        self._btn_calibrate.clicked.connect(self.calibrate_requested)
        lo.addWidget(self._btn_calibrate)

        # 标定结果表格：pair | RMS(mm) | 内点率 | 状态
        result_label = QLabel("标定结果")
        result_label.setObjectName("sectionTitle")
        lo.addWidget(result_label)
        self._result_table = QTableWidget(0, 4)
        self._result_table.setHorizontalHeaderLabels(
            ["pair", "RMS(mm)", "内点率", "状态"])
        self._result_table.verticalHeader().setVisible(False)
        self._result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self._result_table.setMinimumHeight(130)
        lo.addWidget(self._result_table, 1)

        # 质量评分条 + 门禁提示
        score_row = QHBoxLayout()
        score_row.addWidget(QLabel("质量评分:"))
        self._score_bar = QProgressBar()
        self._score_bar.setRange(0, 100)
        self._score_bar.setValue(0)
        score_row.addWidget(self._score_bar, 1)
        lo.addLayout(score_row)

        self._gate_hint = QLabel("质量门禁：任一 pair 未达标时禁止进入扫描")
        self._gate_hint.setWordWrap(True)
        self._gate_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        lo.addWidget(self._gate_hint)

        # 外参存取
        ext_row = QHBoxLayout()
        self._btn_save_ext = QPushButton("保存外参")
        ui_icons.apply(self._btn_save_ext, "save", TEXT_SECONDARY, 14)
        self._btn_save_ext.clicked.connect(self.save_extrinsics_requested)
        ext_row.addWidget(self._btn_save_ext)
        self._btn_load_ext = QPushButton("加载外参")
        ui_icons.apply(self._btn_load_ext, "folder_open", TEXT_SECONDARY, 14)
        self._btn_load_ext.clicked.connect(self.load_extrinsics_requested)
        ext_row.addWidget(self._btn_load_ext)
        lo.addLayout(ext_row)
        return tab

    def _build_scan_tab(self) -> QWidget:
        tab = QWidget()
        lo = QVBoxLayout(tab)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(8)

        # 撤板提醒横幅
        self._lock_banner = QFrame()
        self._lock_banner.setStyleSheet(
            f"QFrame {{ background-color: {ACCENT_DIM};"
            f" border: 1px solid #E53935; border-radius: 6px; }}")
        banner_lo = QHBoxLayout(self._lock_banner)
        banner_lo.setContentsMargins(10, 8, 10, 8)
        lock_icon = QLabel()
        lock_icon.setPixmap(ui_icons.pixmap("lock", "#E53935", 18))
        lock_icon.setFixedSize(22, 22)
        banner_lo.addWidget(lock_icon, 0, Qt.AlignTop)
        self._banner_label = QLabel(
            "外参已锁定 — 请移除标定板后开始扫描，拍摄期间请勿移动相机")
        self._banner_label.setWordWrap(True)
        self._banner_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: 600;")
        banner_lo.addWidget(self._banner_label, 1)
        lo.addWidget(self._lock_banner)

        # 断线重连警告（默认隐藏）
        self._recalib_warn = QLabel(
            "⚠ 检测到相机断线重连，外参可能失效，请重新标定")
        self._recalib_warn.setWordWrap(True)
        self._recalib_warn.setStyleSheet(
            f"color: {STATUS_WARN}; font-size: 11px; font-weight: 600;")
        self._recalib_warn.hide()
        lo.addWidget(self._recalib_warn)

        self._btn_scan_capture = QPushButton("拍摄扫描帧")
        self._btn_scan_capture.setObjectName("primary")
        self._btn_scan_capture.setMinimumHeight(34)
        ui_icons.apply(self._btn_scan_capture, "camera", "#FFFFFF", 16)
        self._btn_scan_capture.clicked.connect(self.capture_scan_requested)
        lo.addWidget(self._btn_scan_capture)

        self._btn_stitch_save = QPushButton("拼接并保存")
        self._btn_stitch_save.setObjectName("primary")
        ui_icons.apply(self._btn_stitch_save, "stitch", "#FFFFFF", 15)
        self._btn_stitch_save.clicked.connect(self.stitch_save_requested)
        lo.addWidget(self._btn_stitch_save)

        # 批量拍摄（产线巡检）
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("连续拍摄:"))
        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(2, 99)
        self._batch_spin.setValue(5)
        self._batch_spin.setSuffix(" 次")
        batch_row.addWidget(self._batch_spin)
        self._btn_batch = QPushButton("批量拼接保存")
        ui_icons.apply(self._btn_batch, "layers", TEXT_SECONDARY, 14)
        self._btn_batch.clicked.connect(
            lambda: self.batch_scan_requested.emit(self._batch_spin.value()))
        batch_row.addWidget(self._btn_batch)
        lo.addLayout(batch_row)

        lo.addStretch(1)
        return tab

    # ------------------------------------------------------------ 状态机（UI 门控）
    def set_state(self, state: str):
        """推进/回退工作区状态，按钮可用性与步骤条严格跟随。

        # TODO(BACKEND): 状态迁移由工作流事件驱动（拍摄完成/检测完成/
        标定完成/质量门禁结果），UI 不自行推进。
        """
        if state not in self.STATES:
            raise ValueError(f"未知状态: {state}")
        self._state = state
        idx = self.STATES.index(state)

        # 步骤条：当前步骤 + 后续置灰
        step = self._STATE_STEP[state]
        self._step_bar.set_current(step)
        for i in range(len(self.STEPS)):
            self._step_bar.set_step_enabled(i, i <= step + 1)

        connected = idx >= self.STATES.index("connected")
        captured = idx >= self.STATES.index("captured")
        detected = idx >= self.STATES.index("detected")
        calibrated = idx >= self.STATES.index("calibrated")
        locked = state == "locked"

        # 拍摄控制
        self._btn_capture.setEnabled(connected and not locked)
        self._rb_sync.setEnabled(connected and not locked)
        self._rb_async.setEnabled(connected and not locked)
        self._ref_combo.setEnabled(connected and not locked)

        # 标定 Tab
        self._btn_detect.setEnabled(captured and not locked)
        self._btn_calibrate.setEnabled(detected and not locked)
        self._btn_save_ext.setEnabled(calibrated)
        self._btn_load_ext.setEnabled(not locked)

        # 扫描 Tab：质量门禁（任一 pair 未达标禁止进入扫描）
        scan_ok = locked or (calibrated and self._quality_passed)
        self._btn_scan_capture.setEnabled(scan_ok)
        self._btn_stitch_save.setEnabled(locked)
        self._btn_batch.setEnabled(locked)
        self._batch_spin.setEnabled(locked)
        self._lock_banner.setVisible(locked)

    def current_state(self) -> str:
        return self._state

    # ------------------------------------------------------------ 后端回填接口（stub 文档）
    def set_devices(self, devices: List[DeviceInfo]):
        """填充已连接设备（连接成功后由主窗口调用）。"""
        self._devices = list(devices)
        self._device_list.clear()
        self._ref_combo.blockSignals(True)
        self._ref_combo.clear()
        for d in devices:
            self._device_list.addItem(
                f"{'●' if d.online else '○'} {d.model}  {d.ip}")
            self._ref_combo.addItem(f"{d.model} ({d.serial})", d.serial)
        self._ref_combo.blockSignals(False)
        self._camera_grid.set_cameras(
            [f"cam{i}" for i in range(len(devices))])

    def on_capture_done(self, thumbnails: Optional[Dict[str, object]] = None):
        """拍摄完成回填（标定帧缩略图 + 帧分区标签）。

        # TODO(BACKEND): thumbnails = {camera_id: QPixmap}
        """
        for cid in self._camera_grid.camera_ids():
            card = self._camera_grid.card(cid)
            if card:
                card.set_frame_kind("标定帧")
                if thumbnails and cid in thumbnails:
                    card.set_thumbnail(thumbnails[cid])

    def on_detect_done(self, marker_counts: Dict[str, int]):
        """检测完成回填：各卡片标记数角标 + 共视状态硬提示。"""
        for cid, count in marker_counts.items():
            card = self._camera_grid.card(cid)
            if card:
                card.set_marker_count(count)
                card.set_covis_status(count > 0)

    def on_calibrate_done(
        self,
        pairs: List[Dict],
        score: int,
        quality_passed: bool,
    ):
        """标定完成回填：结果表格 + 质量评分 + 质量门禁。

        参数：
            pairs  [{'pair': 'cam0-cam1', 'rms_mm': 0.42,
                     'inlier_ratio': 0.94, 'level': 'ok'|'warn'|'fail'}]
            score  质量评分 0~100
            quality_passed  质量门禁结果（False 时扫描按钮保持置灰）
        """
        self._quality_passed = quality_passed
        self._score_bar.setValue(max(0, min(100, score)))
        self._result_table.setRowCount(len(pairs))
        level_style = {
            "ok": (STATUS_OK, "● 优"), "warn": (STATUS_WARN, "● 良"),
            "fail": (STATUS_ERR, "● 差"),
        }
        for row, p in enumerate(pairs):
            color, text = level_style.get(p.get("level", "ok"),
                                          level_style["ok"])
            self._result_table.setItem(row, 0, QTableWidgetItem(p["pair"]))
            self._result_table.setItem(
                row, 1, QTableWidgetItem(f"{p['rms_mm']:.2f}"))
            self._result_table.setItem(
                row, 2, QTableWidgetItem(f"{p['inlier_ratio'] * 100:.0f}%"))
            status_item = QTableWidgetItem(text)
            status_item.setForeground(QColor(color))
            self._result_table.setItem(row, 3, status_item)

        if quality_passed:
            self._gate_hint.setText("✓ 质量门禁通过，可进入扫描阶段")
            self._gate_hint.setStyleSheet(
                f"color: {STATUS_OK}; font-size: 11px; font-weight: 600;")
        else:
            self._gate_hint.setText(
                "✗ 任一 pair 未达标，请重拍或重新检测（扫描已禁用）")
            self._gate_hint.setStyleSheet(
                f"color: {STATUS_ERR}; font-size: 11px; font-weight: 600;")

    def show_recalibration_warning(self):
        """相机断线重连后提示「外参可能失效，请重新标定」。"""
        self._recalib_warn.show()

    def viewer(self) -> ViewerPanel:
        """3D 预览组件（拼接结果回填入口）。"""
        return self._viewer

    def camera_grid(self) -> CameraGrid:
        """相机取景网格（拍摄/检测后帧回填入口）。"""
        return self._camera_grid

    # ------------------------------------------------------------ 内部
    def _on_capture(self):
        self.capture_requested.emit(self._rb_sync.isChecked())

    def _on_step_back(self, index: int):
        """已完成步骤点击回退（仅发请求，实际回退由工作流确认）。"""
        self.step_back_requested.emit(index)
