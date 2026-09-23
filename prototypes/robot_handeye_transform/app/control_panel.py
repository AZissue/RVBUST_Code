# -*- coding: utf-8 -*-
"""
控制面板（左）—— 手眼矩阵 / 机器人位姿 / 采集 / 验证导出 四组（批 3 接线）。

设计约定（方案 v4.1）：
  - 单位、安装方式、位姿类型、欧拉顺序**一律不预选**（下拉首项为「请选择」），
    与 core 侧「无默认」一致（D4 / A2 / R11）。面板不做几何校验，全部交给 core
    的 `HandEyeResult` / `admit_pose`，失败原因原样显示（core 已保证可读）。
  - 状态机（A3）：矩阵加载 → UNVERIFIED（戳点按钮可用，导出置灰）→ 戳点门禁
    PASS → VERIFIED（导出可用）/ FAIL → 红字 FAILED。重合度快检是 warning 级，
    **不改变**状态（R2 轴向盲区，不能判可用）。
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
    sig_tip_record = Signal(str)     # 针尖相机系坐标文本 "x,y,z"（毫米）
    sig_tip_check = Signal()         # 运行戳点门禁
    sig_overlap = Signal()           # 两帧重合度快检（warning，非门禁）
    sig_save_session = Signal()      # 保存会话（A6，仅 VERIFIED 可用）
    sig_save_ply = Signal()          # 保存合并 PLY（A4，仅 VERIFIED 可用）
    sig_export_handeye_file = Signal()   # 导出 v1 矩阵文件（A10）
    sig_import_handeye_file = Signal()   # 导入矩阵文件（v1 或 MCC 旧 JSON，A10）

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
        self.combo_he_unit = _combo([("毫米 (mm)", "mm"), ("米 (m)", "m")])
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

        # 批 6A：矩阵落文件（A10）。导出不卡 A3 门禁（现场要把矩阵带走用），
        # 但文件里 stamp validated，未 VERIFIED 的矩阵接手方须自行复核。
        row3 = QHBoxLayout()
        self.btn_export_he_file = QPushButton("导出矩阵文件")
        self.btn_export_he_file.setEnabled(False)      # 加载矩阵后才可用
        self.btn_export_he_file.setToolTip(
            "导出 v1 矩阵文件（含 unit / 欧拉口径 / 时间戳 / rms / sha256）。\n"
            "未通过戳点门禁也能导出，但文件里 validated=false，接手方须复核。")
        self.btn_export_he_file.clicked.connect(self.sig_export_handeye_file.emit)
        row3.addWidget(self.btn_export_he_file)
        self.btn_import_he_file = QPushButton("导入矩阵文件")
        self.btn_import_he_file.setToolTip(
            "读 v1 矩阵文件（单位以文件为准；与界面选择冲突即拒）或 MCC 旧 JSON\n"
            "（旧格式无 unit 字段 → 界面单位必选）。")
        self.btn_import_he_file.clicked.connect(self.sig_import_handeye_file.emit)
        row3.addWidget(self.btn_import_he_file)
        v.addLayout(row3)
        return g

    def _build_pose_group(self) -> QWidget:
        g = QGroupBox("机器人位姿（T_base2tool，绝对位姿）")
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
        # 全称，避免 "M" 与 "mm" 的单字母歧义（v4.3 §4.4）
        self.combo_pose_unit = _combo([("毫米 (mm)", "mm"), ("米 (m)", "m")])
        row2.addWidget(self.combo_pose_unit)
        row2.addWidget(QLabel("类型"))
        self.combo_pose_type = _combo([("绝对", "absolute"), ("增量（未支持）", "delta")])
        self._disable_item(self.combo_pose_type, "delta",
                           "增量位姿（delta）本原型未实现累积合成，已 fail-closed 禁用"
                           "（R11）：把 Δ 当绝对位姿用会静默错数百毫米。")
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
        self.btn_save_ply = QPushButton("保存合并 PLY（未 VERIFIED 置灰）")
        self.btn_save_ply.setEnabled(False)
        self.btn_save_ply.clicked.connect(self.sig_save_ply.emit)
        v.addWidget(self.btn_save_ply)
        self.lbl_points = QLabel("无相机：使用合成点云（可复现，固定随机种子）")
        self.lbl_points.setWordWrap(True)
        self.lbl_points.setStyleSheet("color: #888;")
        v.addWidget(self.lbl_points)
        return g

    def _build_verify_group(self) -> QWidget:
        g = QGroupBox("验证 / 导出（A3 戳点门禁，批 3）")
        v = QVBoxLayout(g)
        v.setSpacing(4)
        self.lbl_state = QLabel("状态：IDLE")
        self.lbl_state.setStyleSheet("color: #ffb300;")
        v.addWidget(self.lbl_state)

        self.edit_tip_xyz = QLineEdit()
        self.edit_tip_xyz.setPlaceholderText(
            "针尖相机系坐标 X,Y,Z（毫米；每姿态单点=ROI 质心/球心）")
        v.addWidget(self.edit_tip_xyz)
        self.btn_tip_record = QPushButton("戳点：记录本姿态（≥3 个离面姿态）")
        self.btn_tip_record.setEnabled(False)   # 矩阵加载后才可用
        self.btn_tip_record.clicked.connect(
            lambda: self.sig_tip_record.emit(self.edit_tip_xyz.text().strip()))
        v.addWidget(self.btn_tip_record)
        self.btn_tip_check = QPushButton("运行戳点门禁")
        self.btn_tip_check.setEnabled(False)
        self.btn_tip_check.clicked.connect(self.sig_tip_check.emit)
        v.addWidget(self.btn_tip_check)

        self.btn_overlap = QPushButton("两帧重合度快检（warning 级，非门禁）")
        self.btn_overlap.setEnabled(False)      # 采集 ≥2 帧后可用
        self.btn_overlap.clicked.connect(self.sig_overlap.emit)
        v.addWidget(self.btn_overlap)

        self.btn_export = QPushButton("保存会话（未 VERIFIED 置灰，A6）")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.sig_save_session.emit)
        v.addWidget(self.btn_export)
        hint = QLabel("判别下限声明：本工具的戳点门禁可判别的平移偏差下限 ≈ 1.0 mm；"
                      "验证通过不等于亚毫米保证。重合度快检存在轴向盲区"
                      "（δ∥旋转轴时恒为 0），不能判可用。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #e0a0a0;")
        v.addWidget(hint)
        return g

    # ------------------------------------------------------------------
    @staticmethod
    def _disable_item(combo: QComboBox, data, tooltip: str):
        """把某个 data 的下拉项置灰 + tooltip（QComboBox 默认模型支持 setEnabled）。"""
        idx = combo.findData(data)
        if idx < 0:
            return
        item = combo.model().item(idx)
        if item is not None:
            item.setEnabled(False)
            item.setToolTip(tooltip)

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

    def set_tip_enabled(self, enabled: bool):
        self.btn_tip_record.setEnabled(enabled)
        self.btn_tip_check.setEnabled(enabled)

    def set_overlap_enabled(self, enabled: bool):
        self.btn_overlap.setEnabled(enabled)

    def set_save_ply_enabled(self, enabled: bool):
        self.btn_save_ply.setEnabled(enabled)

    def set_export_file_enabled(self, enabled: bool):
        """批 6A：矩阵加载后才允许导出矩阵文件（A10）。"""
        self.btn_export_he_file.setEnabled(enabled)

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
