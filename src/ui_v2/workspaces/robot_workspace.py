"""New robot hand-eye workspace using production capture and session services."""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from core.robot_handeye import (
    CsvPoseSource, HandEyeResult, ManualPoseSource, TwoFrameOverlapChecker,
)
from core.robot_handeye import handeye_file
from core.robot_handeye.transform_chain import compute_cam2base, transform_pcd
from core.robot_stitch_workflow import RobotStitchWorkflow
from ui_common.image_preview import numpy_to_qpixmap

from ..components import UiComponents
from ..dialogs import ChineseMessageBox as QMessageBox
from ..theme import BG_CARD, STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_MUTED, TEXT_SECONDARY
from ..widgets.robot_control_panel import RobotControlPanel
from ..widgets.device_table import DeviceInfo


class RobotWorkspace(QWidget):
    STATES = ('idle', 'connected', 'matrix_loaded', 'verified', 'failed')

    log_message = Signal(str, str)
    dirty_changed = Signal(bool)
    state_changed = Signal()
    result_publish_requested = Signal()

    def __init__(self, parent=None, *, components=None):
        super().__init__(parent)
        self._components = components or UiComponents()
        self._devices: List[DeviceInfo] = []
        self._state = 'idle'
        self._busy = False
        self._background_runner = None
        self._task_gate = None
        self._generation = 0
        self._capture_provider = None
        self.workflow = RobotStitchWorkflow(None, None, None, None)
        self.offline_preview = False
        self._setup_ui()
        self._wire()
        self._refresh_actions()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        self._left_panel = QScrollArea()
        self._left_panel.setWidgetResizable(True)
        self._left_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._left_panel.setFrameShape(QFrame.NoFrame)
        self._left_panel.setMinimumWidth(300)
        self._left_panel.setMaximumWidth(440)
        self.panel = RobotControlPanel()
        self._left_panel.setWidget(self.panel)
        root.addWidget(self._left_panel, 1)

        self._right_split = QSplitter(Qt.Horizontal)
        self._right_split.setChildrenCollapsible(False)
        self._preview_panel = QGroupBox('当前原始帧 · 2D')
        preview_layout = QVBoxLayout(self._preview_panel)
        preview_layout.setContentsMargins(6, 12, 6, 6)
        self.preview_2d_label = self._components.create_preview(ratio=4.0 / 3.0)
        self.preview_2d_label.setMinimumSize(300, 220)
        preview_layout.addWidget(self.preview_2d_label)
        self.lbl_camera = QLabel('未连接相机；离线模式使用项目原始帧')
        self.lbl_camera.setWordWrap(True)
        self.lbl_camera.setStyleSheet(f'color: {TEXT_MUTED};')
        preview_layout.addWidget(self.lbl_camera)
        self._right_split.addWidget(self._preview_panel)

        self._viewer = self._components.create_viewer('3D 机器人基座系拼接')
        self._viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer.setMinimumSize(360, 270)
        self._viewer.viewer_message.connect(self._log)
        self._right_split.addWidget(self._viewer)
        self._right_split.setSizes([420, 900])
        root.addWidget(self._right_split, 3)

    def _wire(self):
        panel = self.panel
        panel.sig_load_handeye.connect(self.on_load_handeye)
        panel.sig_manual_handeye.connect(self.on_manual_handeye)
        panel.sig_import_handeye_file.connect(self.on_import_handeye_file)
        panel.sig_export_handeye_file.connect(self.on_export_handeye_file)
        panel.sig_pose_kind.connect(self.on_pose_kind)
        panel.sig_manual_pose.connect(self.on_manual_pose)
        panel.sig_load_csv.connect(self.on_load_csv)
        panel.sig_capture.connect(self.on_capture)
        panel.sig_clear.connect(self.on_clear)
        panel.sig_tip_record.connect(self.on_tip_record)
        panel.sig_tip_check.connect(self.on_tip_check)
        panel.sig_overlap.connect(self.on_overlap_check)
        panel.sig_save_ply.connect(self.on_save_merged_ply)
        panel.sig_publish.connect(self.result_publish_requested.emit)

    def viewer(self):
        return self._viewer

    def _log(self, text, level='info'):
        self.log_message.emit(str(text), level)

    def set_workflow(self, workflow):
        self._generation += 1
        self.workflow = workflow
        if self._capture_provider is not None:
            self.workflow.set_frame_provider(self._capture_provider)
        self.refresh_from_workflow()

    def set_capture_provider(self, provider):
        self._capture_provider = provider
        self.offline_preview = provider is not None
        self.workflow.set_frame_provider(provider)
        self._refresh_actions()

    def set_background_runner(self, runner):
        self._background_runner = runner

    def set_task_gate(self, gate):
        self._task_gate = gate

    def _can_modify(self):
        return not self._busy and (self._task_gate is None or self._task_gate())

    def _capture_available(self):
        return self._capture_provider is not None or bool(self._devices)

    def set_devices(self, devices):
        self._devices = list(devices or [])
        self.offline_preview = self._capture_provider is not None
        self.lbl_camera.setText(
            f'已连接 {len(self._devices)} 台相机；使用第一台采集' if self._devices else
            '离线数据 · 未连接相机' if self.offline_preview else '未连接相机')
        self._refresh_actions()

    def set_state(self, state):
        if state not in self.STATES:
            raise ValueError(f'未知机器人工作区状态: {state}')
        self._state = state
        self._refresh_actions()

    def current_state(self):
        if self.workflow.handeye is None:
            return 'idle'
        if self.workflow.handeye.validated:
            return 'verified'
        if self.workflow.tip_report and self.workflow.tip_report.get('verdict') == 'FAIL':
            return 'failed'
        return 'matrix_loaded'

    def _refresh_actions(self):
        handeye = self.workflow.handeye
        pose_ready = self.workflow.pose_source is not None
        frames = self.workflow.get_frame_count()
        verified = bool(handeye and handeye.validated)
        self.panel.refresh_actions(loaded=handeye is not None, pose_ready=pose_ready,
            capture_available=self._capture_available(), frames=frames,
            verified=verified, busy=not self._can_modify())
        if handeye is None:
            self.panel.set_state('IDLE（未加载手眼矩阵）', TEXT_MUTED)
        elif verified:
            self.panel.set_state('VERIFIED（允许导出合并点云）', STATUS_OK)
        elif self.current_state() == 'failed':
            self.panel.set_state('FAILED（戳点门禁未通过）', STATUS_ERR)
        else:
            self.panel.set_state('UNVERIFIED（须通过戳点门禁）', STATUS_WARN)
        self.panel.lbl_points.setText(f'已采集 {frames} 帧；坐标单位 mm')
        self.state_changed.emit()

    def load_handeye(self, result):
        if not self._can_modify():
            self._log('当前任务进行中，不能更换手眼矩阵', 'warn')
            return False
        self._generation += 1
        ok, message = self.workflow.set_handeye(result)
        if not ok:
            self._log('手眼矩阵加载失败：' + message, 'error')
            return False
        self._viewer.clear_all()
        self._display_2d(None)
        self._update_handeye_meta()
        self._refresh_actions()
        self.dirty_changed.emit(True)
        self._log(message + '；请完成至少 3 个离面姿态的戳点验证。', 'success')
        return True

    def _update_handeye_meta(self):
        handeye = self.workflow.handeye
        if handeye is None:
            self.panel.set_he_meta('')
            return
        unknown = bool(getattr(handeye, 'rms_unknown', False)) or handeye.n_samples == 0
        metrics = 'RMS / 样本数：未知' if unknown else (
            f'RMS 平移 {handeye.rms_t_mm:g} mm · 旋转 {handeye.rms_r_deg:g}° · '
            f'样本 {handeye.n_samples}')
        self.panel.set_he_meta(
            f"{'眼在手上' if handeye.eye_in_hand else '眼在手外'} · "
            f"平移范数 {np.linalg.norm(handeye.T_handeye_mm[:3, 3]):.3f} mm\n"
            f'{metrics}\n来源：{os.path.basename(handeye.source) or "手动录入"}')

    def on_load_handeye(self, path, unit, mount):
        if not path:
            self._log('请先选择手眼 JSON 文件', 'warn')
            return
        if unit is None:
            self._log('旧 JSON 无单位字段，必须显式选择 mm 或 m', 'warn')
            return
        ok, message, result = HandEyeResult.load(path, unit, mount)
        if not ok:
            self._log(message, 'error')
            return
        self.load_handeye(result)

    def on_manual_handeye(self, text, unit, mount):
        values = self.panel.parse_floats(text)
        if values is None or len(values) != 16:
            self._log('手眼矩阵需要 16 个数（行优先）', 'warn')
            return
        if unit is None or mount is None:
            self._log('手动录入矩阵时必须显式选择单位和安装方式', 'warn')
            return
        ok, message, result = HandEyeResult.from_matrix(values, unit, mount)
        if not ok:
            self._log(message, 'error')
            return
        self.load_handeye(result)

    def on_import_handeye_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '导入手眼矩阵', '', '矩阵文件 (*.json)')
        if not path:
            return
        unit, mount = self.panel.handeye_meta()
        ok, message, result = handeye_file.read_matrix_file(
            path, unit_override=unit, eye_in_hand=mount)
        if not ok:
            self._log(message, 'error')
            return
        self.load_handeye(result)

    def on_export_handeye_file(self):
        if self.workflow.handeye is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '导出手眼矩阵', 'handeye_matrix.json', '矩阵文件 (*.json)')
        if path:
            self.export_handeye_file(path)

    def export_handeye_file(self, path):
        handeye = self.workflow.handeye
        if handeye is None:
            return False
        unit = self.panel.combo_he_unit.currentData() or 'mm'
        order = self.panel.combo_pose_order.currentData()
        unknown = bool(getattr(handeye, 'rms_unknown', False)) or handeye.n_samples == 0
        report = self.workflow.tip_report or {}
        state = 'VERIFIED' if handeye.validated else (
            'FAILED' if report.get('verdict') == 'FAIL' else 'UNVERIFIED')
        verification = {'state': state, 'validated': handeye.validated,
            'tip_verdict': report.get('verdict'),
            'err_mean_mm': report.get('err_mean_mm')}
        ok, message = handeye_file.write_matrix_file(
            path, handeye.T_handeye_mm, eye_in_hand=handeye.eye_in_hand,
            unit=unit, source=handeye_file.SOURCE_TOOL,
            rms=(None, None) if unknown else (handeye.rms_t_mm, handeye.rms_r_deg),
            n_samples=None if unknown else handeye.n_samples,
            euler={'order': order, 'intrinsic': order.isupper() if order else None,
                'output_format': handeye_file.EULER_OUTPUT_FORMAT,
                'angle_unit': handeye_file.EULER_ANGLE_UNIT},
            validated=handeye.validated, verification=verification)
        self._log(message, 'success' if ok else 'error')
        return ok

    def on_pose_kind(self, kind):
        if not self._can_modify():
            self._log('当前任务进行中，不能切换位姿来源', 'warn')
            return
        changed = False
        if kind == 'manual' and not isinstance(self.workflow.pose_source, ManualPoseSource):
            self.workflow.set_pose_source(ManualPoseSource())
            changed = True
        elif kind == 'csv' and not isinstance(self.workflow.pose_source, CsvPoseSource):
            self.workflow.clear_pose_source()
            changed = True
        self.panel.set_pose_status('手动位姿未录入' if kind == 'manual' else 'CSV 位姿未加载')
        if changed:
            self.dirty_changed.emit(True)
        self._refresh_actions()

    def on_manual_pose(self, xyz_text, rpy_text, order, unit, pose_type):
        if not self._can_modify():
            self._log('当前任务进行中，不能修改位姿', 'warn')
            return
        xyz = self.panel.parse_floats(xyz_text)
        rpy = self.panel.parse_floats(rpy_text)
        if xyz is None or rpy is None or len(xyz) != 3 or len(rpy) != 3:
            self._log('位姿需要 XYZ 3 个数和 RPY 3 个数', 'warn')
            return
        source = self.workflow.pose_source
        if not isinstance(source, ManualPoseSource):
            source = ManualPoseSource()
        ok, message = source.set_pose_xyz_rpy(xyz, rpy, order, unit, pose_type)
        if ok:
            self.workflow.set_pose_source(source)
            self.dirty_changed.emit(True)
        self.panel.set_pose_status(message)
        self._log(message, 'success' if ok else 'warn')
        self._refresh_actions()

    def on_load_csv(self, path, unit, pose_type):
        if not self._can_modify():
            self._log('当前任务进行中，不能加载位姿 CSV', 'warn')
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, '加载机器人位姿 CSV', '', '位姿文件 (*.csv *.txt)')
            if not path:
                return
            self.panel.edit_csv.setText(path)
        ok, message, source = CsvPoseSource.load(path, unit or None, pose_type or None)
        if ok:
            self.workflow.set_pose_source(source)
            self.dirty_changed.emit(True)
        self.panel.set_pose_status(message)
        self._log(message, 'success' if ok else 'error')
        self._refresh_actions()

    def on_capture(self):
        if (not self._can_modify() or self.workflow.handeye is None
                or self.workflow.pose_source is None or not self._capture_available()):
            self._log('请先加载手眼矩阵、录入绝对位姿，并确认相机或离线帧可用', 'warn')
            return
        self._busy = True
        token = self._generation
        self._refresh_actions()
        if self._background_runner is not None:
            self._background_runner(self._capture_job,
                lambda result, error: self._on_capture_done(result, error, token),
                name='robot_capture')
        else:
            self._on_capture_done(self._capture_job(), None, token)

    def _capture_job(self):
        return self.workflow.capture_frame()

    def _on_capture_done(self, result, error, token=None):
        if token is not None and token != self._generation:
            self._log('已丢弃清空或项目切换前的过期采集结果', 'warn')
            return
        self._busy = False
        if error:
            self._log(f'机器人采集失败：{error}', 'error')
        else:
            ok, message, info = result
            self._log(message, 'success' if ok else 'error')
            if ok:
                self._show_capture(info)
                self.dirty_changed.emit(True)
        self._refresh_actions()

    def _show_capture(self, info):
        self._viewer.set_pointcloud('camera', info['pcd_cam'])
        self._viewer.set_pointcloud('base', info['pcd_base'])
        self._viewer.set_pointcloud_merged(self.workflow.get_merged_pointcloud())
        self._viewer.set_reference('base')
        self._display_2d(info['frame'].image_np)

    def _display_2d(self, image):
        pixmap = numpy_to_qpixmap(image) if image is not None else None
        if pixmap is not None:
            self.preview_2d_label.setPixmap(pixmap)
        else:
            self.preview_2d_label.clear_image()
        presentation = getattr(self, '_industrial', None)
        if presentation is not None:
            presentation.set_marker_image(image, [])
            if image is None:
                presentation.restore_business_image()

    def refresh_from_workflow(self):
        self._update_handeye_meta()
        if self.workflow.get_frame_count():
            frame = self.workflow.frames[-1]
            pose = self.workflow.poses[-1]
            transform = self.workflow.transforms[-1]
            cloud = self.workflow._valid_cloud(frame)
            self._show_capture({'frame': frame, 'pcd_cam': cloud,
                'pcd_base': transform_pcd(cloud, transform),
                'T_base2tool': pose})
        else:
            self._viewer.clear_all()
            self._display_2d(None)
        self._refresh_actions()

    def on_clear(self):
        if not self._can_modify():
            self._log('当前任务进行中，不能清空机器人采集', 'warn')
            return
        self._generation += 1
        self._busy = False
        self.workflow.clear_frames()
        self._viewer.clear_all()
        self._display_2d(None)
        self._refresh_actions()
        self.dirty_changed.emit(True)
        self._log('已清空机器人采集帧；手眼矩阵和戳点样本保留')

    def reset_session(self):
        self._generation += 1
        self._busy = False
        provider = self._capture_provider
        self.workflow.reset()
        if provider is not None:
            self.workflow.set_frame_provider(provider)
        self._viewer.clear_all()
        self._display_2d(None)
        self.panel.set_he_meta('')
        self.panel.set_pose_status('位姿未就绪')
        self._refresh_actions()

    def on_tip_record(self, text):
        if not self._can_modify():
            self._log('当前任务进行中，不能修改戳点样本', 'warn')
            return
        if self.workflow.validator is None or self.workflow.pose_source is None:
            self._log('请先加载手眼矩阵并录入位姿', 'warn')
            return
        tip = self.panel.parse_floats(text)
        if tip is None or len(tip) != 3:
            self._log('针尖坐标需要 3 个数（相机系，毫米）', 'warn')
            return
        ok, message, pose = self.workflow.pose_source.get_pose()
        if not ok:
            self._log(message, 'error')
            return
        ok, message = self.workflow.add_tip_sample(pose, tip)
        self._log(message, 'success' if ok else 'warn')
        if ok:
            self.dirty_changed.emit(True)
            self._refresh_actions()

    def on_tip_check(self):
        if not self._can_modify():
            self._log('当前任务进行中，不能运行戳点门禁', 'warn')
            return
        report = self.workflow.run_tip_check()
        self._refresh_actions()
        mean = report.get('err_mean_mm')
        mean_text = f'{mean:.3f}' if isinstance(mean, (float, int)) and np.isfinite(mean) else '—'
        self._log(f"戳点门禁：{report.get('verdict')}；平均误差 {mean_text} mm",
            'success' if report.get('verdict') == 'PASS' else 'error')
        for reason in report.get('reasons', []):
            self._log(reason, 'warn')
        for warning in report.get('warnings', []):
            self._log(warning, 'warn')
        self.dirty_changed.emit(True)

    def on_overlap_check(self):
        if self.workflow.get_frame_count() < 2:
            return
        clouds = [transform_pcd(self.workflow._valid_cloud(frame), transform)
            for frame, transform in zip(self.workflow.frames[-2:], self.workflow.transforms[-2:])]
        report = TwoFrameOverlapChecker.check(clouds[0], clouds[1],
            self.workflow.poses[-2], self.workflow.poses[-1])
        self._log(f"两帧重合度（仅参考）：median={report['median_mm']:.3f} mm，"
            f"p95={report['p95_mm']:.3f} mm；{report['verdict']}")
        self._log(report['hint'], 'warn')

    def on_save_merged_ply(self):
        if self.workflow.handeye is None or not self.workflow.handeye.validated:
            self._log('合并导出需要戳点 VERIFIED', 'warn')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '导出机器人基座系合并点云', 'robot_base_merged.ply', 'PLY (*.ply)')
        if path:
            ok, message = self.workflow.save_merged_ply(path)
            self._log(message, 'success' if ok else 'error')
