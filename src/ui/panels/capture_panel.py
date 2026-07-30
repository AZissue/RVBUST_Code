# -*- coding: utf-8 -*-
"""
采集控制面板（CapturePanel）—— 右面板 Tab。

功能：
  - 采集控制：拍摄所有相机 / 连续拍摄（间隔定时）/ 拍摄参数应用；
  - 离线会话：保存当前帧到会话 / 保存会话 / 加载会话 / 批量检测 / 批量标定。

所有业务动作通过信号发给主窗口，面板本身不触碰 core 模块。
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QDoubleSpinBox, QSpinBox,
    QFormLayout, QAbstractItemView,
)

from ..icons import icon_text, apply_icon, make_group_box, apply_group_icon


class CapturePanel(QWidget):
    """采集控制 + 离线会话面板。"""

    capture_all_requested = Signal()              # 拍摄所有相机（同步软触发）
    capture_sequential_requested = Signal()       # 分开拍摄所有相机（串行触发）
    continuous_capture_toggled = Signal(bool, int)  # (开启, 间隔ms)
    capture_params_changed = Signal(dict)         # 拍摄参数
    save_frame_to_session_requested = Signal()    # 保存当前帧到会话
    save_session_requested = Signal()             # 保存会话
    load_session_requested = Signal()             # 加载会话
    batch_detect_requested = Signal()             # 批量检测会话标记
    batch_calibrate_requested = Signal()          # 批量标定会话

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(6)

        # ---- 采集控制 ----
        self.grp_capture = make_group_box("camera", "📸 采集控制")
        cap_lo = QVBoxLayout(self.grp_capture)
        apply_group_icon(self.grp_capture)

        self.btn_capture_all = QPushButton(icon_text("capture", "📸 同步拍摄（所有相机同时触发）"))
        self.btn_capture_all.setObjectName("primaryButton")
        self.btn_capture_all.clicked.connect(self.capture_all_requested.emit)
        apply_icon(self.btn_capture_all, "capture", size=20)
        cap_lo.addWidget(self.btn_capture_all)

        self.btn_capture_seq = QPushButton(icon_text("capture", "⏭ 分开拍摄（相机依次触发）"))
        self.btn_capture_seq.setObjectName("primaryButton")
        self.btn_capture_seq.clicked.connect(self.capture_sequential_requested.emit)
        apply_icon(self.btn_capture_seq, "capture", size=20)
        cap_lo.addWidget(self.btn_capture_seq)

        cont_lo = QHBoxLayout()
        self.btn_continuous = QPushButton("▶ 连续拍摄")
        self.btn_continuous.setCheckable(True)
        self.btn_continuous.toggled.connect(self._on_continuous_toggled)
        cont_lo.addWidget(self.btn_continuous, 1)
        cont_lo.addWidget(QLabel("间隔(ms):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(100, 60000)
        self.spin_interval.setValue(1000)
        self.spin_interval.setSingleStep(100)
        cont_lo.addWidget(self.spin_interval)
        cap_lo.addLayout(cont_lo)

        # 拍摄参数
        form = QFormLayout()
        form.setSpacing(4)
        self.spin_exp2d = QDoubleSpinBox(); self.spin_exp2d.setRange(0.1, 1000.0); self.spin_exp2d.setValue(20.0); self.spin_exp2d.setSuffix(" ms")
        self.spin_exp3d = QDoubleSpinBox(); self.spin_exp3d.setRange(0.1, 1000.0); self.spin_exp3d.setValue(30.0); self.spin_exp3d.setSuffix(" ms")
        self.spin_gain2d = QSpinBox(); self.spin_gain2d.setRange(0, 64); self.spin_gain2d.setValue(0)
        self.spin_gain3d = QSpinBox(); self.spin_gain3d.setRange(0, 64); self.spin_gain3d.setValue(0)
        self.spin_brightness = QSpinBox(); self.spin_brightness.setRange(0, 1023); self.spin_brightness.setValue(512)
        form.addRow("2D 曝光:", self.spin_exp2d)
        form.addRow("3D 曝光:", self.spin_exp3d)
        form.addRow("2D 增益:", self.spin_gain2d)
        form.addRow("3D 增益:", self.spin_gain3d)
        form.addRow("投射亮度:", self.spin_brightness)
        cap_lo.addLayout(form)

        self.btn_apply_params = QPushButton(icon_text("settings", "⚙ 应用参数到所有相机"))
        self.btn_apply_params.clicked.connect(self._on_apply_params)
        apply_icon(self.btn_apply_params, "settings")
        cap_lo.addWidget(self.btn_apply_params)
        lo.addWidget(self.grp_capture)

        # ---- 离线会话 ----
        self.grp_offline = make_group_box("session", "💾 离线会话")
        off_lo = QVBoxLayout(self.grp_offline)
        apply_group_icon(self.grp_offline)

        self.btn_save_frame = QPushButton(icon_text("save_frame", "📥 保存当前帧到会话"))
        self.btn_save_frame.setEnabled(False)  # 拍摄后启用
        self.btn_save_frame.clicked.connect(self.save_frame_to_session_requested.emit)
        apply_icon(self.btn_save_frame, "save_frame")
        off_lo.addWidget(self.btn_save_frame)

        sess_btn_lo = QHBoxLayout()
        self.btn_save_session = QPushButton(icon_text("save", "💾 保存会话"))
        self.btn_save_session.clicked.connect(self.save_session_requested.emit)
        apply_icon(self.btn_save_session, "save")
        sess_btn_lo.addWidget(self.btn_save_session)
        self.btn_load_session = QPushButton(icon_text("load", "📂 加载会话"))
        self.btn_load_session.setObjectName("primaryButton")
        self.btn_load_session.clicked.connect(self.load_session_requested.emit)
        apply_icon(self.btn_load_session, "load")
        sess_btn_lo.addWidget(self.btn_load_session)
        off_lo.addLayout(sess_btn_lo)

        batch_btn_lo = QHBoxLayout()
        self.btn_batch_detect = QPushButton(icon_text("detect", "🔎 批量检测标记"))
        self.btn_batch_detect.setEnabled(False)  # 加载会话后启用
        self.btn_batch_detect.clicked.connect(self.batch_detect_requested.emit)
        apply_icon(self.btn_batch_detect, "detect")
        batch_btn_lo.addWidget(self.btn_batch_detect)
        self.btn_batch_calibrate = QPushButton(icon_text("calibrate", "📐 批量标定会话"))
        self.btn_batch_calibrate.setEnabled(False)
        self.btn_batch_calibrate.clicked.connect(self.batch_calibrate_requested.emit)
        apply_icon(self.btn_batch_calibrate, "calibrate")
        batch_btn_lo.addWidget(self.btn_batch_calibrate)
        off_lo.addLayout(batch_btn_lo)

        self.lbl_session = QLabel("会话: （未创建）")
        self.lbl_session.setObjectName("infoLabel")
        self.lbl_session.setWordWrap(True)
        off_lo.addWidget(self.lbl_session)
        lo.addWidget(self.grp_offline)
        lo.addStretch(1)

    # ------------------------------------------------------------------
    # 采集控制
    # ------------------------------------------------------------------
    def _on_continuous_toggled(self, checked: bool):
        self.btn_continuous.setText("⏸ 停止连续拍摄" if checked else "▶ 连续拍摄")
        self.continuous_capture_toggled.emit(checked, self.spin_interval.value())

    def stop_continuous(self):
        """外部停止连续拍摄（同步按钮状态，不重复发信号）。"""
        if self.btn_continuous.isChecked():
            self.btn_continuous.setChecked(False)

    def _on_apply_params(self):
        self.capture_params_changed.emit(self.get_capture_params())

    def get_capture_params(self) -> dict:
        return {
            'exposure_time_2d': self.spin_exp2d.value(),
            'exposure_time_3d': self.spin_exp3d.value(),
            'gain_2d': self.spin_gain2d.value(),
            'gain_3d': self.spin_gain3d.value(),
            'brightness': self.spin_brightness.value(),
        }

    def set_capture_enabled(self, enabled: bool):
        """无已连接相机时禁用拍摄按钮。"""
        self.btn_capture_all.setEnabled(enabled)
        self.btn_capture_seq.setEnabled(enabled)
        self.btn_continuous.setEnabled(enabled)
        self.btn_apply_params.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 离线会话
    # ------------------------------------------------------------------
    def set_save_frame_enabled(self, enabled: bool):
        """拍摄到帧后启用「保存当前帧到会话」。"""
        self.btn_save_frame.setEnabled(enabled)

    def set_batch_enabled(self, enabled: bool):
        """加载会话后启用批量检测 / 批量标定。"""
        self.btn_batch_detect.setEnabled(enabled)
        self.btn_batch_calibrate.setEnabled(enabled)

    def set_session_path(self, text: str):
        """显示当前会话路径。"""
        self.lbl_session.setText(f"会话: {text}" if text else "会话: （未创建）")
