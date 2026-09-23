# -*- coding: utf-8 -*-
"""
控制面板（左）—— 手眼矩阵 / 机器人位姿 / 采集 三组（批 2）。

设计约定（方案 v4.1）：
  - 单位、安装方式、位姿类型、欧拉顺序**一律不预选**（下拉首项为「请选择」），
    与 core 侧「无默认」一致（D4 / A2 / R11）。面板不做几何校验，全部交给 core
    的 `HandEyeResult` / `admit_pose`，失败原因原样显示（core 已保证可读）。
  - 导出按钮常置灰：戳点验证（A3）批 3 才实现，未 VERIFIED 不允许导出。
  - 只放核心参数，不堆控件。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

PLACEHOLDER = "请选择"
LOG_ORDERS = ("ZYX", "ZXY", "YZX", "YXZ", "XZY", "XYZ",
              "zyx", "zxy", "yzx", "yxz", "xzy", "xyz")


def _combo(items, empty_text: str = PLACEHOLDER) -> QComboBox:
    """下拉框：首项为占位（data=None），**无默认值**。"""
    c = QComboBox()
    c.addItem(empty_text, None)
    for it in items:
        if isinstance(it, tuple):
            c.addItem(it[0], it[1])
        else:
            c.addItem(str(it), it)
    return c


class ControlPanel(QWidget):
    """左侧控制面板。信号里的参数都是原始输入，校验由 core 做。"""

    sig_load_handeye = Signal(str, str, bool)      # path, unit, eye_in_hand
    sig_manual_handeye = Signal(str, str, bool)    # 16 数文本, unit, eye_in_hand
    sig_pose_kind = Signal(str)                    # manual | mock | csv
    sig_manual_pose = Signal(str, str, str, str, str)  # xyz, rpy, order, unit, pose_type
    sig_mock_step = Signal()
    sig_load_csv = Signal(str, str, str)           # path, unit, pose_type
    sig_capture = Signal()
    sig_clear = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(330)
        self.setMaximumWidth(420)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(6)
        lo.addWidget(self._build_handeye_group())
        lo.addWidget(self._build_pose_group())
        lo.addWidget(self._build_capture_group())
        lo.addWidget(self._build_verify_group())
        lo.addStretch(1)

    # ------------------------------------------------------------------
    def _build_handeye_group(self) -> QWidget:
        g = QGroupBox("手眼矩阵（来自独立标定工具 / 手动录入）")
        v = QVBoxLayout(g)
        v.setSpacing(4)

        row = QHBoxLayout()
        self.edit_he_path = QLineEdit()
        self.edit_he_path.setPlaceholderText("handeye.json 路径")
        row.addWidget(self.edit_he_path, 1)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("单位"))
        self.combo_he_unit = _combo(["mm", "m"])
        row2.addWidget(self.combo_he_unit)
        row2.addWidget(QLabel("安装"))
        self.combo_he_mount = _combo([("眼在手上", True), ("眼在手外", False)])
        row2.addWidget(self.combo_he_mount)
        v.addLayout(row2)

        btn = QPushButton("从 JSON 加载")
        btn.clicked.connect(self._emit_load_handeye)
        v.addWidget(btn)

        self.edit_he_manual = QLineEdit()
        self.edit_he_manual.setPlaceholderText("或手填 16 个数（行优先，逗号/空格分隔）")
        v.addWidget(self.edit_he_manual)
        btn2 = QPushButton("手动录入手眼矩阵")
        btn2.clicked.connect(self._emit_manual_handeye)
        v.addWidget(btn2)
        return g

    def _build_pose_group(self) -> QWidget:
        g = QGroupBox("机器人位姿（T_base2tool）")
        v = QVBoxLayout(g)
        v.setSpacing(4)

        row = QHBoxLayout()
        row.addWidget(QLabel("来源"))
        self.combo_pose_kind = _combo([("手动录入", "manual"),
                                       ("Mock 序列", "mock"),
                                       ("CSV 回放", "csv")])
        self.combo_pose_kind.currentIndexChanged.connect(
            lambda: self._on_pose_kind(self.combo_pose_kind.currentData()))
        row.addWidget(self.combo_pose_kind, 1)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("单位"))
        self.combo_pose_unit = _combo(["mm", "m"])
        row2.addWidget(self.combo_pose_unit)
        row2.addWidget(QLabel("类型"))
        self.combo_pose_type = _combo([("绝对", "absolute"), ("增量", "delta")])
        row2.addWidget(self.combo_pose_type)
        v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("欧拉顺序"))
        self.combo_pose_order = _combo(LOG_ORDERS)
        row3.addWidget(self.combo_pose_order)
        v.addLayout(row3)

        self.edit_xyz = QLineEdit()
        self.edit_xyz.setPlaceholderText("XYZ（如 400,100,420）")
        v.addWidget(self.edit_xyz)
        self.edit_rpy = QLineEdit()
        self.edit_rpy.setPlaceholderText("RPY 度（如 0,0,15）")
        v.addWidget(self.edit_rpy)
        self.btn_apply_pose = QPushButton("录入位姿")
        self.btn_apply_pose.clicked.connect(self._emit_manual_pose)
        v.addWidget(self.btn_apply_pose)

        self.btn_mock_step = QPushButton("Mock 序列步进（无机器人闭环）")
        self.btn_mock_step.clicked.connect(self.sig_mock_step.emit)
        v.addWidget(self.btn_mock_step)

        self.edit_csv = QLineEdit()
        self.edit_csv.setPlaceholderText("或 CSV 位姿文件路径（须带 # pose_type: 声明行）")
        v.addWidget(self.edit_csv)
        self.btn_load_csv = QPushButton("加载 CSV 位姿序列")
        self.btn_load_csv.clicked.connect(self._emit_load_csv)
        v.addWidget(self.btn_load_csv)

        self._on_pose_kind(None)
        return g

    def _build_capture_group(self) -> QWidget:
        g = QGroupBox("采集")
        v = QVBoxLayout(g)
        v.setSpacing(4)
        row = QHBoxLayout()
        self.btn_capture = QPushButton("拍一帧 → 变到基座系")
        self.btn_capture.clicked.connect(self.sig_capture.emit)
        row.addWidget(self.btn_capture, 1)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.sig_clear.emit)
        row.addWidget(btn_clear)
        v.addLayout(row)
        self.lbl_points = QLabel("无相机：使用合成点云（可复现，固定随机种子）")
        self.lbl_points.setWordWrap(True)
        self.lbl_points.setStyleSheet("color: #888;")
        v.addWidget(self.lbl_points)
        return g

    def _build_verify_group(self) -> QWidget:
        g = QGroupBox("验证 / 导出")
        v = QVBoxLayout(g)
        v.setSpacing(4)
        self.lbl_state = QLabel("状态：IDLE")
        self.lbl_state.setStyleSheet("color: #ffb300;")
        v.addWidget(self.lbl_state)
        self.btn_verify = QPushButton("戳点验证（批 3）")
        self.btn_verify.setEnabled(False)
        v.addWidget(self.btn_verify)
        self.btn_export = QPushButton("导出点云 / 会话（未 VERIFIED 置灰）")
        self.btn_export.setEnabled(False)
        v.addWidget(self.btn_export)
        hint = QLabel("判别下限声明：本工具的戳点门禁可判别的平移偏差下限 ≈ 1.0 mm；"
                      "验证通过不等于亚毫米保证。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #e0a0a0;")
        v.addWidget(hint)
        return g

    # ------------------------------------------------------------------
    # 输入解析（只做文本→数值，不做几何校验）
    # ------------------------------------------------------------------
    @staticmethod
    def parse_floats(text: str) -> Optional[list]:
        t = (text or "").replace(",", " ").replace("，", " ").split()
        if not t:
            return None
        try:
            return [float(x) for x in t]
        except ValueError:
            return None

    def handeye_meta(self) -> tuple[Optional[str], Optional[bool]]:
        return self.combo_he_unit.currentData(), self.combo_he_mount.currentData()

    def pose_meta(self) -> tuple[Optional[str], Optional[str], Optional[str]]:
        return (self.combo_pose_unit.currentData(),
                self.combo_pose_type.currentData(),
                self.combo_pose_order.currentData())

    def xyz_rpy(self) -> tuple[Optional[list], Optional[list]]:
        return self.parse_floats(self.edit_xyz.text()), \
            self.parse_floats(self.edit_rpy.text())

    def set_state(self, text: str, color: str = "#ffb300"):
        self.lbl_state.setText(f"状态：{text}")
        self.lbl_state.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------
    def _emit_load_handeye(self):
        unit, mount = self.handeye_meta()
        self.sig_load_handeye.emit(self.edit_he_path.text().strip(),
                                   unit, bool(mount))

    def _emit_manual_handeye(self):
        unit, mount = self.handeye_meta()
        self.sig_manual_handeye.emit(self.edit_he_manual.text().strip(),
                                     unit, bool(mount))

    def _emit_manual_pose(self):
        unit, pose_type, order = self.pose_meta()
        self.sig_manual_pose.emit(
            self.edit_xyz.text(), self.edit_rpy.text(),
            order or "", unit or "", pose_type or "")

    def _emit_load_csv(self):
        unit, pose_type, _ = self.pose_meta()
        self.sig_load_csv.emit(self.edit_csv.text().strip(),
                               unit or "", pose_type or "")

    def _on_pose_kind(self, kind):
        en_mock = kind == "mock"
        en_csv = kind == "csv"
        self.btn_mock_step.setVisible(en_mock)
        self.edit_csv.setVisible(en_csv)
        self.btn_load_csv.setVisible(en_csv)
        if kind:
            self.sig_pose_kind.emit(kind)
