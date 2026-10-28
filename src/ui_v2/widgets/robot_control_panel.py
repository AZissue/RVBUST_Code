"""Controls for the robot hand-eye workspace; validation stays in core."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ..theme import STATUS_OK, STATUS_WARN, TEXT_MUTED

PLACEHOLDER = '请选择'
LOG_ORDERS = ('ZYX', 'ZXY', 'YZX', 'YXZ', 'XZY', 'XYZ',
              'zyx', 'zxy', 'yzx', 'yxz', 'xzy', 'xyz')


def _combo(items):
    combo = QComboBox()
    combo.addItem(PLACEHOLDER, None)
    for text, value in items:
        combo.addItem(text, value)
    return combo


class RobotControlPanel(QWidget):
    sig_load_handeye = Signal(str, object, object)
    sig_manual_handeye = Signal(str, object, object)
    sig_import_handeye_file = Signal()
    sig_export_handeye_file = Signal()
    sig_pose_kind = Signal(str)
    sig_manual_pose = Signal(str, str, str, str, str)
    sig_load_csv = Signal(str, str, str)
    sig_capture = Signal()
    sig_clear = Signal()
    sig_tip_record = Signal(str)
    sig_tip_check = Signal()
    sig_overlap = Signal()
    sig_save_ply = Signal()
    sig_publish = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.addWidget(self._build_handeye_group())
        layout.addWidget(self._build_pose_group())
        layout.addWidget(self._build_capture_group())
        layout.addWidget(self._build_verify_group())
        layout.addStretch(1)
        self._on_pose_kind('manual')

    def _build_handeye_group(self):
        group = QGroupBox('1 · 手眼矩阵')
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel('单位'))
        self.combo_he_unit = _combo([('毫米 (mm)', 'mm'), ('米 (m)', 'm')])
        row.addWidget(self.combo_he_unit)
        row.addWidget(QLabel('安装'))
        self.combo_he_mount = _combo([('眼在手上', True), ('眼在手外', False)])
        row.addWidget(self.combo_he_mount)
        layout.addLayout(row)
        self.btn_import_he_file = QPushButton('导入矩阵文件 / 旧 JSON')
        self.btn_import_he_file.clicked.connect(self.sig_import_handeye_file.emit)
        layout.addWidget(self.btn_import_he_file)
        self.edit_he_manual = QLineEdit()
        self.edit_he_manual.setPlaceholderText('或输入 4×4 矩阵的 16 个数（行优先）')
        layout.addWidget(self.edit_he_manual)
        self.btn_manual_he = QPushButton('录入手眼矩阵')
        self.btn_manual_he.clicked.connect(self._emit_manual_handeye)
        layout.addWidget(self.btn_manual_he)
        self.btn_export_he_file = QPushButton('导出矩阵文件')
        self.btn_export_he_file.setEnabled(False)
        self.btn_export_he_file.clicked.connect(self.sig_export_handeye_file.emit)
        layout.addWidget(self.btn_export_he_file)
        self.lbl_he_meta = QLabel('尚未加载矩阵')
        self.lbl_he_meta.setWordWrap(True)
        self.lbl_he_meta.setStyleSheet(f'color: {TEXT_MUTED};')
        layout.addWidget(self.lbl_he_meta)
        return group

    def _build_pose_group(self):
        group = QGroupBox('2 · 机器人绝对位姿')
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel('来源'))
        self.combo_pose_kind = QComboBox()
        self.combo_pose_kind.addItem('手动录入', 'manual')
        self.combo_pose_kind.addItem('CSV 回放', 'csv')
        self.combo_pose_kind.currentIndexChanged.connect(
            lambda: self._on_pose_kind(self.combo_pose_kind.currentData()))
        row.addWidget(self.combo_pose_kind, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('单位'))
        self.combo_pose_unit = _combo([('毫米 (mm)', 'mm'), ('米 (m)', 'm')])
        row.addWidget(self.combo_pose_unit)
        row.addWidget(QLabel('类型'))
        self.combo_pose_type = _combo([('绝对', 'absolute')])
        row.addWidget(self.combo_pose_type)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('欧拉顺序'))
        self.combo_pose_order = _combo([(order, order) for order in LOG_ORDERS])
        row.addWidget(self.combo_pose_order, 1)
        layout.addLayout(row)
        self.manual_pose_widgets = []
        for placeholder in ('XYZ（如 400,100,420）', 'RPY 度（如 0,0,15）'):
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            layout.addWidget(edit)
            self.manual_pose_widgets.append(edit)
        self.edit_xyz, self.edit_rpy = self.manual_pose_widgets
        self.btn_apply_pose = QPushButton('录入当前位姿')
        self.btn_apply_pose.clicked.connect(self._emit_manual_pose)
        layout.addWidget(self.btn_apply_pose)
        self.manual_pose_widgets.append(self.btn_apply_pose)
        self.csv_widgets = []
        self.edit_csv = QLineEdit()
        self.edit_csv.setPlaceholderText('CSV 路径；须含 # pose_type: absolute')
        layout.addWidget(self.edit_csv)
        self.csv_widgets.append(self.edit_csv)
        self.btn_load_csv = QPushButton('选择并加载 CSV 位姿')
        self.btn_load_csv.clicked.connect(self._emit_load_csv)
        layout.addWidget(self.btn_load_csv)
        self.csv_widgets.append(self.btn_load_csv)
        self.lbl_pose = QLabel('位姿未就绪；单位、类型和欧拉顺序均须显式选择')
        self.lbl_pose.setWordWrap(True)
        self.lbl_pose.setStyleSheet(f'color: {TEXT_MUTED};')
        layout.addWidget(self.lbl_pose)
        return group

    def _build_capture_group(self):
        group = QGroupBox('3 · 采集与基座系拼接')
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.btn_capture = QPushButton('拍摄一帧并转到基座系')
        self.btn_capture.setObjectName('primary')
        self.btn_capture.setEnabled(False)
        self.btn_capture.clicked.connect(self.sig_capture.emit)
        row.addWidget(self.btn_capture, 1)
        self.btn_clear = QPushButton('清空')
        self.btn_clear.clicked.connect(self.sig_clear.emit)
        row.addWidget(self.btn_clear)
        layout.addLayout(row)
        self.btn_publish = QPushButton('发布合并结果到项目 DB')
        self.btn_publish.setEnabled(False)
        self.btn_publish.clicked.connect(self.sig_publish.emit)
        layout.addWidget(self.btn_publish)
        self.lbl_points = QLabel('尚未采集；正式模式只使用相机或离线原始帧')
        self.lbl_points.setWordWrap(True)
        layout.addWidget(self.lbl_points)
        return group

    def _build_verify_group(self):
        group = QGroupBox('4 · 戳点验证与导出')
        layout = QVBoxLayout(group)
        self.lbl_state = QLabel('状态：IDLE')
        self.lbl_state.setWordWrap(True)
        layout.addWidget(self.lbl_state)
        self.edit_tip_xyz = QLineEdit()
        self.edit_tip_xyz.setPlaceholderText('针尖相机系坐标 X,Y,Z（毫米，每姿态单点）')
        layout.addWidget(self.edit_tip_xyz)
        self.btn_tip_record = QPushButton('记录本姿态戳点（至少 3 个离面姿态）')
        self.btn_tip_record.setEnabled(False)
        self.btn_tip_record.clicked.connect(
            lambda: self.sig_tip_record.emit(self.edit_tip_xyz.text().strip()))
        layout.addWidget(self.btn_tip_record)
        self.btn_tip_check = QPushButton('运行戳点门禁')
        self.btn_tip_check.setObjectName('primary')
        self.btn_tip_check.setEnabled(False)
        self.btn_tip_check.clicked.connect(self.sig_tip_check.emit)
        layout.addWidget(self.btn_tip_check)
        self.btn_overlap = QPushButton('两帧重合度快检（仅参考）')
        self.btn_overlap.setEnabled(False)
        self.btn_overlap.clicked.connect(self.sig_overlap.emit)
        layout.addWidget(self.btn_overlap)
        self.btn_save_ply = QPushButton('导出合并 PLY（需 VERIFIED）')
        self.btn_save_ply.setEnabled(False)
        self.btn_save_ply.clicked.connect(self.sig_save_ply.emit)
        layout.addWidget(self.btn_save_ply)
        hint = QLabel('判别下限约 1.0 mm；验证通过不等于亚毫米保证。'
                      '两帧重合度存在轴向盲区，不能替代戳点门禁。')
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color: {STATUS_WARN};')
        layout.addWidget(hint)
        return group

    @staticmethod
    def parse_floats(text) -> Optional[list]:
        values = (text or '').replace(',', ' ').replace('，', ' ').split()
        if not values:
            return None
        try:
            return [float(value) for value in values]
        except ValueError:
            return None

    def handeye_meta(self):
        return self.combo_he_unit.currentData(), self.combo_he_mount.currentData()

    def _emit_manual_handeye(self):
        unit, mount = self.handeye_meta()
        self.sig_manual_handeye.emit(self.edit_he_manual.text().strip(), unit, mount)

    def _emit_manual_pose(self):
        self.sig_manual_pose.emit(
            self.edit_xyz.text(), self.edit_rpy.text(),
            self.combo_pose_order.currentData() or '',
            self.combo_pose_unit.currentData() or '',
            self.combo_pose_type.currentData() or '')

    def _emit_load_csv(self):
        self.sig_load_csv.emit(self.edit_csv.text().strip(),
            self.combo_pose_unit.currentData() or '',
            self.combo_pose_type.currentData() or '')

    def _on_pose_kind(self, kind):
        for widget in self.manual_pose_widgets:
            widget.setVisible(kind == 'manual')
        for widget in self.csv_widgets:
            widget.setVisible(kind == 'csv')
        if kind:
            self.sig_pose_kind.emit(kind)

    def set_pose_status(self, text):
        self.lbl_pose.setText(text)

    def set_he_meta(self, text):
        self.lbl_he_meta.setText(text or '尚未加载矩阵')

    def set_state(self, text, color=STATUS_WARN):
        self.lbl_state.setText('状态：' + text)
        self.lbl_state.setStyleSheet(f'color: {color};')

    def set_verified(self, verified):
        self.set_state('VERIFIED（允许导出合并点云）' if verified else
            'UNVERIFIED（须通过戳点门禁）', STATUS_OK if verified else STATUS_WARN)

    def refresh_actions(self, *, loaded, pose_ready, capture_available, frames, verified, busy=False):
        self.btn_capture.setEnabled(loaded and pose_ready and capture_available and not busy)
        self.btn_tip_record.setEnabled(loaded and pose_ready and not busy)
        self.btn_tip_check.setEnabled(loaded and not busy)
        self.btn_export_he_file.setEnabled(loaded and not busy)
        self.btn_export_he_file.setToolTip('请先导入或录入手眼矩阵' if not loaded else
            '当前任务进行中，请等待完成后导出' if busy else '导出当前手眼矩阵文件')
        self.btn_overlap.setEnabled(frames >= 2 and not busy)
        self.btn_save_ply.setEnabled(verified and frames >= 1 and not busy)
        self.btn_publish.setEnabled(verified and frames >= 1 and not busy)
        self.btn_clear.setEnabled(not busy)
