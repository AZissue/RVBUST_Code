# -*- coding: utf-8 -*-
"""
拼接面板（StitchPanel）—— 右面板 Tab。

功能：
  - 拼接控制：拼接当前帧 / 拼接并保存 PLY；
  - 后处理参数：裁切（无 / AABB 中心 / 球 / OBB）、体素下采样、离群点去除；
  - 结果显示：拼接点数、耗时、保存路径。

所有业务动作通过信号发给主窗口。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QFormLayout,
)

from ..icons import icon_text, apply_icon, make_group_box, apply_group_icon


class StitchPanel(QWidget):
    """拼接控制 + 后处理面板。"""

    stitch_requested = Signal()
    stitch_save_requested = Signal()
    stitch_session_requested = Signal()   # 批量拼接离线会话
    process_params_changed = Signal(dict)
    auto_params_requested = Signal()      # 自动设置后处理参数（基于当前点云）

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

        # ---- 拼接控制 ----
        self.grp_stitch = make_group_box("link", "🔗 拼接控制")
        st_lo = QVBoxLayout(self.grp_stitch)
        apply_group_icon(self.grp_stitch)
        self.btn_stitch = QPushButton(icon_text("link", "🔗 拼接当前帧"))
        self.btn_stitch.setObjectName("primaryButton")
        self.btn_stitch.clicked.connect(self.stitch_requested.emit)
        apply_icon(self.btn_stitch, "link")
        st_lo.addWidget(self.btn_stitch)
        self.btn_stitch_save = QPushButton(icon_text("save", "💾 拼接并保存 PLY"))
        self.btn_stitch_save.setObjectName("successButton")
        self.btn_stitch_save.clicked.connect(self.stitch_save_requested.emit)
        apply_icon(self.btn_stitch_save, "save")
        st_lo.addWidget(self.btn_stitch_save)
        self.btn_stitch_session = QPushButton(icon_text("batch", "🗂 批量拼接会话"))
        self.btn_stitch_session.clicked.connect(self.stitch_session_requested.emit)
        apply_icon(self.btn_stitch_session, "batch")
        st_lo.addWidget(self.btn_stitch_session)
        lo.addWidget(self.grp_stitch)

        # ---- 后处理 ----
        self.grp_proc = make_group_box("process", "🛠 后处理")
        form = QFormLayout(self.grp_proc)
        apply_group_icon(self.grp_proc)
        form.setSpacing(4)

        # 自动设置参数（基于当前点云数据估计，避免默认参数过激滤光点云）
        self.btn_auto_params = QPushButton(
            icon_text("auto", "✨ 自动设置参数（基于当前点云）"))
        self.btn_auto_params.setObjectName("primaryButton")
        self.btn_auto_params.clicked.connect(self.auto_params_requested.emit)
        apply_icon(self.btn_auto_params, "auto")
        form.addRow(self.btn_auto_params)

        self.combo_crop = QComboBox()
        self.combo_crop.addItem("不裁切", "none")
        self.combo_crop.addItem("AABB 中心裁切", "aabb")
        self.combo_crop.addItem("球形裁切", "sphere")
        self.combo_crop.addItem("OBB 主轴裁切", "obb")
        form.addRow("裁切模式:", self.combo_crop)

        self.spin_crop_ratio = QDoubleSpinBox()
        self.spin_crop_ratio.setRange(0.05, 1.0)
        self.spin_crop_ratio.setValue(0.6)
        self.spin_crop_ratio.setSingleStep(0.05)
        form.addRow("裁切比例:", self.spin_crop_ratio)

        self.spin_crop_radius = QDoubleSpinBox()
        self.spin_crop_radius.setRange(1.0, 100000.0)
        self.spin_crop_radius.setValue(500.0)
        self.spin_crop_radius.setSuffix(" mm")
        form.addRow("球半径:", self.spin_crop_radius)

        self.chk_voxel = QCheckBox("体素下采样")
        form.addRow(self.chk_voxel)
        self.spin_voxel = QDoubleSpinBox()
        self.spin_voxel.setRange(0.01, 100.0)
        self.spin_voxel.setValue(0.5)
        self.spin_voxel.setSuffix(" mm")
        form.addRow("体素大小:", self.spin_voxel)

        self.chk_outlier = QCheckBox("统计离群点去除")
        form.addRow(self.chk_outlier)
        self.spin_nb = QSpinBox()
        self.spin_nb.setRange(2, 200)
        self.spin_nb.setValue(20)
        form.addRow("邻域点数:", self.spin_nb)
        self.spin_std = QDoubleSpinBox()
        self.spin_std.setRange(0.1, 10.0)
        self.spin_std.setValue(2.0)
        form.addRow("标准差比:", self.spin_std)
        lo.addWidget(self.grp_proc)

        # ---- 结果显示 ----
        self.grp_result = make_group_box("chart", "📊 拼接结果")
        res_lo = QVBoxLayout(self.grp_result)
        apply_group_icon(self.grp_result)
        self.lbl_points = QLabel("点数: -")
        self.lbl_time = QLabel("耗时: -")
        self.lbl_path = QLabel("保存: -")
        self.lbl_path.setWordWrap(True)
        for w in (self.lbl_points, self.lbl_time, self.lbl_path):
            w.setObjectName("infoLabel")
            res_lo.addWidget(w)
        # 自动参数估计依据（只读说明，小字体灰色）
        self.lbl_auto_notes = QLabel("")
        self.lbl_auto_notes.setWordWrap(True)
        self.lbl_auto_notes.setStyleSheet("color: #8B8D98; font-size: 8pt;")
        self.lbl_auto_notes.hide()  # 无内容时不占位
        res_lo.addWidget(self.lbl_auto_notes)
        lo.addWidget(self.grp_result)
        lo.addStretch(1)

        # 参数变化自动通知
        self.combo_crop.currentIndexChanged.connect(self._emit_params)
        self.spin_crop_ratio.valueChanged.connect(self._emit_params)
        self.spin_crop_radius.valueChanged.connect(self._emit_params)
        self.chk_voxel.toggled.connect(self._emit_params)
        self.spin_voxel.valueChanged.connect(self._emit_params)
        self.chk_outlier.toggled.connect(self._emit_params)
        self.spin_nb.valueChanged.connect(self._emit_params)
        self.spin_std.valueChanged.connect(self._emit_params)

    # ------------------------------------------------------------------
    # 参数
    # ------------------------------------------------------------------
    def _emit_params(self, *_args):
        self.process_params_changed.emit(self.get_process_params())

    def get_process_params(self) -> dict:
        """返回与 PointCloudProcessor 字段对应的参数字典。"""
        return {
            'crop_mode': self.combo_crop.currentData(),
            'crop_ratio': self.spin_crop_ratio.value(),
            'crop_radius': self.spin_crop_radius.value(),
            'enable_voxel_downsample': self.chk_voxel.isChecked(),
            'voxel_size': self.spin_voxel.value(),
            'enable_outlier_removal': self.chk_outlier.isChecked(),
            'outlier_nb_neighbors': self.spin_nb.value(),
            'outlier_std_ratio': self.spin_std.value(),
        }

    def set_process_params(self, params: dict):
        """把参数字典（如 PointCloudProcessor.auto_tune 的返回）回填到各控件。

        回填期间临时 blockSignals，避免每个控件都触发一次
        process_params_changed，最后统一发一次。
        """
        widgets = (self.combo_crop, self.spin_crop_ratio, self.spin_crop_radius,
                   self.chk_voxel, self.spin_voxel,
                   self.chk_outlier, self.spin_nb, self.spin_std)
        for w in widgets:
            w.blockSignals(True)
        try:
            if 'crop_mode' in params:
                idx = self.combo_crop.findData(params['crop_mode'])
                if idx >= 0:
                    self.combo_crop.setCurrentIndex(idx)
            if 'crop_ratio' in params:
                self.spin_crop_ratio.setValue(
                    min(max(float(params['crop_ratio']), 0.05), 1.0))
            if 'crop_radius' in params:
                self.spin_crop_radius.setValue(
                    min(max(float(params['crop_radius']), 1.0), 100000.0))
            if 'enable_voxel_downsample' in params:
                self.chk_voxel.setChecked(bool(params['enable_voxel_downsample']))
            if 'voxel_size' in params:
                self.spin_voxel.setValue(
                    min(max(float(params['voxel_size']), 0.01), 100.0))
            if 'enable_outlier_removal' in params:
                self.chk_outlier.setChecked(bool(params['enable_outlier_removal']))
            if 'outlier_nb_neighbors' in params:
                self.spin_nb.setValue(
                    min(max(int(params['outlier_nb_neighbors']), 2), 200))
            if 'outlier_std_ratio' in params:
                self.spin_std.setValue(
                    min(max(float(params['outlier_std_ratio']), 0.1), 10.0))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._emit_params()  # 统一发一次

    def set_auto_notes(self, notes):
        """显示自动参数估计依据（notes 字符串列表）；空列表则隐藏。"""
        notes = list(notes or [])
        if not notes:
            self.lbl_auto_notes.setText("")
            self.lbl_auto_notes.hide()
            return
        self.lbl_auto_notes.setText(
            "✨ 自动参数依据：\n" + "\n".join(f"• {t}" for t in notes))
        self.lbl_auto_notes.show()

    def set_points_alert(self, alert: bool):
        """后处理过滤过激时把点数标红，正常时恢复默认样式。"""
        self.lbl_points.setStyleSheet(
            "color: #DC2626; font-weight: bold;" if alert else "")

    # ------------------------------------------------------------------
    # 结果显示
    # ------------------------------------------------------------------
    def set_result(self, points: int, elapsed_ms: float, save_path: str = ""):
        self.lbl_points.setText(f"点数: {points:,}")
        self.lbl_time.setText(f"耗时: {elapsed_ms:.1f} ms")
        if save_path:
            self.lbl_path.setText(f"保存: {save_path}")

    def clear_result(self):
        self.lbl_points.setText("点数: -")
        self.lbl_time.setText("耗时: -")
        self.lbl_path.setText("保存: -")
