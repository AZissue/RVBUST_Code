# -*- coding: utf-8 -*-
"""
标定面板（CalibrationPanel）—— 右面板 Tab。

功能：
  - 参考相机选择（QComboBox）；
  - 标定控制：检测标记 / 标定所有 pair（参考 vs 每台其他相机）/
    累积多帧 / 多帧标定 / 保存 / 加载；
  - 结果显示：pair 标定表（RMS、平均误差、内点数、内点率、质量评分），
    选中行显示 4x4 变换矩阵；
  - 质量评分：优 <0.5mm / 良 <1mm / 合格 <2mm / 差 >=2mm。

所有业务动作通过信号发给主窗口。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..icons import icon_text, apply_icon, make_group_box, apply_group_icon


def quality_rating(rms_mm: float) -> Tuple[str, str]:
    """标定质量评分：返回 (等级, 颜色)。"""
    if rms_mm < 0.5:
        return "优", "#43a047"
    if rms_mm < 1.0:
        return "良", "#8bc34a"
    if rms_mm < 2.0:
        return "合格", "#ff9800"
    return "差", "#e53935"


class CalibrationPanel(QWidget):
    """标定控制 + 结果显示面板。"""

    detect_requested = Signal()
    calibrate_pair_requested = Signal(str, str)   # (ref_id, cam_id)
    add_frame_requested = Signal()                # 累积当前帧到多帧缓存
    calibrate_multi_requested = Signal()
    clear_frames_requested = Signal()             # 清空多帧缓存
    save_calibration_requested = Signal()
    load_calibration_requested = Signal()
    reference_changed = Signal(str)               # 参考相机变化
    pair_selected = Signal(str, str)              # 结果表选中某对 pair (ref_id, cam_id)
    marker_type_changed = Signal(str)             # 标记物类型变化

    MARKER_TYPES = [
        ("coded_circle", "🔵 旋转编码圆"),
        ("asymmetric_grid", "⚪ 非对称黑底白圆标定板"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pair_results: Dict[Tuple[str, str], dict] = {}
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(6)

        # ---- 参考相机 ----
        self.grp_ref = make_group_box("target", "🎯 参考相机")
        ref_outer = QVBoxLayout(self.grp_ref)
        apply_group_icon(self.grp_ref)
        ref_lo = QHBoxLayout()
        ref_lo.addWidget(QLabel("参考相机:"))
        self.combo_ref = QComboBox()
        self.combo_ref.currentTextChanged.connect(self._on_ref_changed)
        ref_lo.addWidget(self.combo_ref, 1)
        ref_outer.addLayout(ref_lo)
        lo.addWidget(self.grp_ref)

        # ---- 标记物类型 ----
        self.grp_marker = make_group_box("marker_type", "🏷 标记物类型")
        marker_outer = QVBoxLayout(self.grp_marker)
        apply_group_icon(self.grp_marker)
        marker_lo = QHBoxLayout()
        marker_lo.addWidget(QLabel("识别目标:"))
        self.combo_marker_type = QComboBox()
        for key, text in self.MARKER_TYPES:
            self.combo_marker_type.addItem(text, key)
        self.combo_marker_type.currentIndexChanged.connect(self._on_marker_type_changed)
        marker_lo.addWidget(self.combo_marker_type, 1)
        marker_outer.addLayout(marker_lo)
        lo.addWidget(self.grp_marker)

        # ---- 标定控制 ----
        self.grp_ctrl = make_group_box("process", "🧮 标定控制")
        ctrl_lo = QVBoxLayout(self.grp_ctrl)
        apply_group_icon(self.grp_ctrl)

        self.btn_detect = QPushButton(icon_text("detect", "🔎 检测标记（所有相机当前帧）"))
        self.btn_detect.setObjectName("primaryButton")
        self.btn_detect.clicked.connect(self.detect_requested.emit)
        apply_icon(self.btn_detect, "detect")
        ctrl_lo.addWidget(self.btn_detect)

        self.btn_calibrate = QPushButton(icon_text("calibrate", "📐 标定所有 pair（单帧）"))
        self.btn_calibrate.setObjectName("successButton")
        self.btn_calibrate.clicked.connect(self._on_calibrate_all)
        apply_icon(self.btn_calibrate, "calibrate")
        ctrl_lo.addWidget(self.btn_calibrate)

        mf_lo = QHBoxLayout()
        self.btn_add_frame = QPushButton(icon_text("add", "➕ 累积当前帧"))
        self.btn_add_frame.clicked.connect(self.add_frame_requested.emit)
        apply_icon(self.btn_add_frame, "add")
        mf_lo.addWidget(self.btn_add_frame)
        self.lbl_frames = QLabel("已累积: 0 帧")
        self.lbl_frames.setObjectName("infoLabel")
        mf_lo.addWidget(self.lbl_frames)
        self.btn_clear_frames = QPushButton(icon_text("clear", "🗑 清空"))
        self.btn_clear_frames.clicked.connect(self.clear_frames_requested.emit)
        apply_icon(self.btn_clear_frames, "clear")
        mf_lo.addWidget(self.btn_clear_frames)
        ctrl_lo.addLayout(mf_lo)

        self.btn_calibrate_multi = QPushButton(icon_text("chart", "📊 多帧标定（平均）"))
        self.btn_calibrate_multi.setObjectName("successButton")
        self.btn_calibrate_multi.clicked.connect(self.calibrate_multi_requested.emit)
        apply_icon(self.btn_calibrate_multi, "chart")
        ctrl_lo.addWidget(self.btn_calibrate_multi)

        io_lo = QHBoxLayout()
        self.btn_save = QPushButton(icon_text("save", "💾 保存标定结果"))
        self.btn_save.clicked.connect(self.save_calibration_requested.emit)
        apply_icon(self.btn_save, "save")
        io_lo.addWidget(self.btn_save)
        self.btn_load = QPushButton(icon_text("load", "📂 加载标定结果"))
        self.btn_load.clicked.connect(self.load_calibration_requested.emit)
        apply_icon(self.btn_load, "load")
        io_lo.addWidget(self.btn_load)
        ctrl_lo.addLayout(io_lo)
        lo.addWidget(self.grp_ctrl)

        # ---- pair 结果表 ----
        self.grp_result = make_group_box("list", "📋 标定结果")
        res_lo = QVBoxLayout(self.grp_result)
        apply_group_icon(self.grp_result)
        self.table_pairs = QTableWidget(0, 6)
        self.table_pairs.setHorizontalHeaderLabels(
            ["Pair", "RMS(mm)", "平均(mm)", "内点数", "内点率", "质量"])
        self.table_pairs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_pairs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_pairs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_pairs.itemSelectionChanged.connect(self._on_pair_selected)
        res_lo.addWidget(self.table_pairs)
        lo.addWidget(self.grp_result, 1)

        # ---- 4x4 变换矩阵 ----
        self.grp_matrix = make_group_box("matrix", "🔢 变换矩阵 T（cam→ref）")
        mat_lo = QVBoxLayout(self.grp_matrix)
        apply_group_icon(self.grp_matrix)
        self.table_matrix = QTableWidget(4, 4)
        self.table_matrix.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_matrix.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_matrix.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_matrix.setMaximumHeight(160)
        mat_lo.addWidget(self.table_matrix)
        lo.addWidget(self.grp_matrix)

    # ------------------------------------------------------------------
    # 参考相机
    # ------------------------------------------------------------------
    def set_camera_ids(self, camera_ids: List[str], keep_current: bool = True):
        """更新可选相机列表（尽量保留当前选择）。"""
        current = self.combo_ref.currentText() if keep_current else ""
        self.combo_ref.blockSignals(True)
        self.combo_ref.clear()
        self.combo_ref.addItems(camera_ids)
        if current in camera_ids:
            self.combo_ref.setCurrentText(current)
        self.combo_ref.blockSignals(False)
        # 列表变化后主动通知一次
        if self.combo_ref.currentText():
            self.reference_changed.emit(self.combo_ref.currentText())

    def get_reference(self) -> str:
        return self.combo_ref.currentText()

    def set_reference(self, camera_id: str):
        idx = self.combo_ref.findText(camera_id)
        if idx >= 0:
            self.combo_ref.setCurrentIndex(idx)

    def _on_ref_changed(self, text: str):
        if text:
            self.reference_changed.emit(text)

    def _on_marker_type_changed(self, index: int):
        key = self.combo_marker_type.itemData(index)
        self._update_calibrate_button_text(key)
        self.marker_type_changed.emit(key)

    def get_marker_type(self) -> str:
        return self.combo_marker_type.currentData()

    def set_marker_type(self, marker_type: str):
        for i in range(self.combo_marker_type.count()):
            if self.combo_marker_type.itemData(i) == marker_type:
                self.combo_marker_type.setCurrentIndex(i)
                return

    def _update_calibrate_button_text(self, marker_type: str):
        if marker_type == "asymmetric_grid":
            self.btn_calibrate.setText(icon_text("calibrate", "📐 标定所有 pair（标定板位姿）"))
        else:
            self.btn_calibrate.setText(icon_text("calibrate", "📐 标定所有 pair（单帧）"))

    def other_camera_ids(self) -> List[str]:
        """除参考相机外的所有相机 ID。"""
        ref = self.get_reference()
        return [self.combo_ref.itemText(i) for i in range(self.combo_ref.count())
                if self.combo_ref.itemText(i) != ref]

    # ------------------------------------------------------------------
    # 标定控制
    # ------------------------------------------------------------------
    def _on_calibrate_all(self):
        ref = self.get_reference()
        if not ref:
            return
        for cid in self.other_camera_ids():
            self.calibrate_pair_requested.emit(ref, cid)

    def set_accumulated_frames(self, n: int):
        self.lbl_frames.setText(f"已累积: {n} 帧")

    # ------------------------------------------------------------------
    # 结果显示
    # ------------------------------------------------------------------
    def update_results(self, pair_results: Dict[Tuple[str, str], dict]):
        """刷新 pair 标定表。pair_results: {(ref_id, cam_id): result_dict}"""
        self._pair_results = dict(pair_results)
        self.table_pairs.setRowCount(0)
        for (ref_id, cam_id), res in self._pair_results.items():
            row = self.table_pairs.rowCount()
            self.table_pairs.insertRow(row)
            pair_name = f"{cam_id}→{ref_id}"
            board_name = res.get('board_pattern_name')
            if board_name:
                pair_name += f" [{board_name}]"
            if not res.get('success'):
                self.table_pairs.setItem(row, 0, QTableWidgetItem(pair_name))
                self.table_pairs.setItem(row, 1, QTableWidgetItem("失败"))
                for c in range(2, 6):
                    self.table_pairs.setItem(row, c, QTableWidgetItem("-"))
                continue
            rms = res.get('rms_mm', 0.0)
            rating, color = quality_rating(rms)
            # 内点数列：标记内点/匹配总数；多帧结果追加帧数信息（如 "19/21 (3帧)"）
            inlier_text = f"{res.get('inlier_count', 0)}/{res.get('total_pairs', 0)}"
            if 'valid_frames' in res:
                inlier_text += f" ({res['valid_frames']}帧)"
            values = [
                pair_name,
                f"{rms:.4f}",
                f"{res.get('mean_mm', 0.0):.4f}",
                inlier_text,
                f"{res.get('inlier_ratio', 0.0) * 100:.1f}%",
                rating,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if col == 5:
                    item.setForeground(QColor(color))
                self.table_pairs.setItem(row, col, item)

    def _on_pair_selected(self):
        rows = self.table_pairs.selectionModel().selectedRows()
        if not rows:
            return
        pair_name = self.table_pairs.item(rows[0].row(), 0).text()
        # pair_name 格式 "cam→ref"，还原为 (ref, cam) 键
        for (ref_id, cam_id), res in self._pair_results.items():
            if f"{cam_id}→{ref_id}" == pair_name:
                T = res.get('T')
                if T is not None:
                    self.show_matrix(np.asarray(T))
                self.pair_selected.emit(ref_id, cam_id)
                return

    def show_matrix(self, T: np.ndarray):
        """显示 4x4 变换矩阵（只读）。"""
        for i in range(4):
            for j in range(4):
                item = QTableWidgetItem(f"{T[i, j]:.6f}")
                item.setTextAlignment(Qt.AlignCenter)
                self.table_matrix.setItem(i, j, item)

    def clear_results(self):
        self._pair_results = {}
        self.table_pairs.setRowCount(0)
        self.table_matrix.clearContents()
