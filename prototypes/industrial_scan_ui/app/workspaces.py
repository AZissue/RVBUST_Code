"""Mode-specific layouts. Real offline math is reused; no camera SDK is loaded."""
from collections import Counter
import json
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QComboBox, QSplitter, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QDoubleSpinBox)
from ui_v2.widgets.camera_grid import CameraGrid
from ui_v2.widgets.step_bar import StepBar
from ui_common.image_preview import AspectRatioLabel
from ui_common.appearance import ImagePreviewAppearance
from .window import ScanWorkbench
from .marker_inspector import load_image
from ..core.marker_display import valid_xyz, code_key, classify_markers, YELLOW


class OverviewCameraGrid(CameraGrid):
    def _relayout(self):
        super()._relayout()
        if not self._cards:
            return
        rows = (len(self._cards)+self._last_cols-1)//self._last_cols
        height = max(180, min(320, (self.viewport().height()-8-(rows-1)*8)//rows))
        for card in self._cards.values():
            card.set_compact_preview()
            card.setFixedHeight(height)


def unique_markers(markers):
    counts = Counter(code_key(m.get('code')) for m in markers)
    return {code_key(m.get('code')): dict(m, code=code_key(m.get('code'))) for m in markers
            if code_key(m.get('code')) is not None and counts[code_key(m.get('code'))] == 1
            and valid_xyz(m) is not None}


def read_observation(path):
    path = Path(path)
    if path.suffix.lower() != '.json':
        return load_image(path), []
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('units', 'mm') != 'mm':
        raise ValueError('标记坐标需要明确使用毫米 mm')
    markers = data.get('markers', [])
    if not isinstance(markers, list) or not all(isinstance(m, dict) for m in markers):
        raise ValueError('markers 必须为检测结果列表')
    image = load_image(path.parent / data['image']) if data.get('image') else load_image(None)
    if data.get('image') and image.isNull():
        raise ValueError('无法读取2D图像')
    return image, markers


class ModeWorkbench(ScanWorkbench):
    mode_key = ''
    mode_title = ''

    def __init__(self, parent=None, *, camera_count=1, **kwargs):
        self.camera_count = camera_count
        super().__init__(parent, **kwargs)
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItem(self.mode_title)
        self.mode.blockSignals(False)
        self.mode.setToolTip('通过“选择功能”返回小窗切换工作方案')
        self.mode.setEnabled(False)
        self.setWindowTitle('MCC · '+self.mode_title+' · 离线原型')

    def _refresh_controls(self):
        super()._refresh_controls()
        self.mode.setEnabled(False)


class MobileWorkbench(ModeWorkbench):
    mode_key = 'mobile_chain'
    mode_title = '单相机移动链式拼接'


class MultiCameraWorkbench(ModeWorkbench):
    mode_key = 'multi_cam'
    mode_title = '多相机外参标定'

    def __init__(self, parent=None, *, camera_count=4, **kwargs):
        self.observations = {}
        self.extrinsics = {}
        super().__init__(parent, camera_count=camera_count, **kwargs)
        self.camera_ids = [f'cam{i+1}' for i in range(camera_count)]
        self.simulation_group.hide()
        self.camera_grid = OverviewCameraGrid(preview_factory=lambda **options: AspectRatioLabel(
            **options, appearance=ImagePreviewAppearance(invalid_color=YELLOW)))
        self.camera_grid.set_cameras(self.camera_ids)
        for cid in self.camera_ids:
            card = self.camera_grid.card(cid)
            card.set_controls_enabled(False)
            card.set_frame_kind('标定帧')
        grid_panel = QWidget()
        grid_layout = QVBoxLayout(grid_panel)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('各相机2D画面 · 离线输入'))
        self.camera_select = QComboBox()
        self.camera_select.addItems(self.camera_ids)
        bar.addWidget(self.camera_select)
        self.load_camera_button = QPushButton('载入图像 / 检测JSON')
        self.load_camera_button.clicked.connect(self.load_camera_dialog)
        bar.addWidget(self.load_camera_button)
        grid_layout.addLayout(bar)
        grid_layout.addWidget(self.camera_grid)
        index = self._view_layout.indexOf(self.canvas)
        self._view_layout.removeWidget(self.canvas)
        self.camera_split = QSplitter(Qt.Horizontal)
        self.camera_split.setChildrenCollapsible(False)
        self.camera_split.addWidget(grid_panel)
        self.camera_split.addWidget(self.canvas)
        self.camera_split.setSizes([800, 450])
        self._view_layout.insertWidget(index, self.camera_split, 1)
        self.marker_inspector.hide()
        self.steps = StepBar(['载入各路数据', '检查共有标记', '计算外参', '保存外参'])
        self._view_layout.insertWidget(0, self.steps)
        group = QGroupBox('02  多相机外参标定')
        controls = QVBoxLayout(group)
        controls.addWidget(QLabel('参考相机'))
        self.reference = QComboBox()
        self.reference.addItems(self.camera_ids)
        self.reference.currentTextChanged.connect(self._invalidate_extrinsics)
        controls.addWidget(self.reference)
        self.solve_button = QPushButton('计算离线外参')
        self.solve_button.clicked.connect(self.start_scan)
        controls.addWidget(self.solve_button)
        self.pairs = QTableWidget(0, 4)
        self.pairs.setHorizontalHeaderLabels(['相机', '共有', '误差mm', '结果'])
        self.pairs.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pairs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pairs.setMaximumHeight(155)
        controls.addWidget(self.pairs)
        self.save_extrinsics_button = QPushButton('保存外参JSON')
        self.save_extrinsics_button.clicked.connect(self.save_extrinsics_dialog)
        controls.addWidget(self.save_extrinsics_button)
        self.parameter_layout.insertWidget(1, group)
        self._actions['scan'].setText('计算外参')
        self.acquisition_caption.setText('离线标定')
        self._actions['pause'].hide()
        self._actions['finish'].hide()
        self.view_title.setText('多路2D标定画面 / 3D预览')
        self.device_label.setText(f'{camera_count} 路画面槽位 · 未连接相机')
        self._refresh_controls()

    def _replace_canvas(self, old, new):
        self.camera_split.replaceWidget(self.camera_split.indexOf(old), new)

    def _show_frame_observation(self):
        super()._show_frame_observation()
        self.marker_inspector.hide()

    def _renderer_failed(self, message):
        super()._renderer_failed(message)
        self.marker_inspector.hide()

    def _refresh_controls(self):
        super()._refresh_controls()
        if not hasattr(self, 'solve_button'):
            return
        ready = not self._busy and all(len(unique_markers(self.observations.get(cid, {}).get('markers', []))) >= 3
                                       for cid in self.camera_ids)
        for button in (self.solve_button, self.scan_button, self._actions['scan']):
            button.setEnabled(ready)
        self.scan_button.setText('计算离线外参')
        self.save_extrinsics_button.setEnabled(not self._busy and bool(self.extrinsics)
                                             and all(result.get('success') for result in self.extrinsics.values()))
        self.load_camera_button.setEnabled(not self._busy)
        self.reference.setEnabled(not self._busy)
        self.camera_select.setEnabled(not self._busy)

    def _invalidate_extrinsics(self, *_):
        self.extrinsics = {}
        if hasattr(self, 'pairs'):
            self.pairs.setRowCount(0)
            self.steps.set_current(1 if all(cid in self.observations for cid in self.camera_ids) else 0)
            for cid in self.camera_ids:
                self.camera_grid.card(cid).set_covis_status(None)
            self._refresh_camera_overlays()
            self._refresh_controls()

    def _refresh_camera_overlays(self):
        reference = self.reference.currentText()
        reference_markers = self.observations.get(reference, {}).get('markers', [])
        for cid in self.camera_ids:
            observation = self.observations.get(cid)
            card = self.camera_grid.card(cid)
            if observation is None or observation['image'].isNull():
                card.set_marker_overlay([])
                continue
            result = self.extrinsics.get(cid)
            display = classify_markers(observation['markers'], reference_markers if cid != reference else None,
                rejected_codes=result.get('outlier_codes', []) if result else [],
                registration_accepted=result.get('success') if result else None)
            image = observation['image']
            card.set_marker_overlay([dict(x=row.xy[0]/image.width(), y=row.xy[1]/image.height(),
                code=row.code, valid_3d=row.xyz is not None, display_color=row.color) for row in display.rows])

    def set_camera_observation(self, camera_id, image, markers=()):
        if camera_id not in self.camera_ids or self._busy:
            raise ValueError('相机槽位无效，或任务正在执行')
        image = load_image(image)
        markers = list(markers)
        if not all(isinstance(m, dict) for m in markers):
            raise ValueError('标记格式错误')
        self.observations[camera_id] = dict(image=image, markers=markers)
        card = self.camera_grid.card(camera_id)
        card.set_thumbnail(None if image.isNull() else QPixmap.fromImage(image))
        card.set_marker_count(len(unique_markers(markers)) if markers else None)
        self._invalidate_extrinsics()
        self._changed()
        self.log(f'{camera_id} 已载入离线图像 / {len(unique_markers(markers))} 个有效3D标记', task='多相机标定')

    def load_camera_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, '载入当前相机离线数据', '', '图像或检测结果 (*.png *.jpg *.bmp *.tif *.json)')
        if path:
            try:
                image, markers = read_observation(path)
                if image.isNull() and not markers:
                    raise ValueError('文件没有有效图像或标记数据')
                self.set_camera_observation(self.camera_select.currentText(), image, markers)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                QMessageBox.warning(self, '载入失败', str(exc))

    def start_scan(self):
        if not hasattr(self, 'solve_button') or not self.solve_button.isEnabled():
            return
        reference = self.reference.currentText()
        markers = {cid: list(unique_markers(self.observations[cid]['markers']).values()) for cid in self.camera_ids}
        def solve():
            from core.calibration_engine import CalibrationEngine
            engine = CalibrationEngine()
            results = {}
            for cid in self.camera_ids:
                if cid == reference:
                    continue
                first, second = unique_markers(markers[reference]), unique_markers(markers[cid])
                common = set(first) & set(second)
                points = [np.asarray([valid_xyz(group[code]) for code in common]) for group in (first, second)]
                if len(common) < 3 or any(np.linalg.matrix_rank(p-p.mean(0)) < 2 for p in points):
                    results[cid] = dict(success=False, message='至少需要3个共有非共线有效标记')
                else:
                    results[cid] = engine.calibrate_pair(reference, cid, markers[reference], markers[cid])
            return results
        def done(results):
            self.extrinsics = results
            self.pairs.setRowCount(len(results))
            for row, (cid, result) in enumerate(results.items()):
                shared = len(set(unique_markers(markers[reference])) & set(unique_markers(markers[cid])))
                values = [cid, str(shared), f"{result['rms_mm']:.3f}" if result.get('success') else '—',
                          '成功' if result.get('success') else '失败']
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(result.get('message', ''))
                    self.pairs.setItem(row, col, item)
                self.camera_grid.card(cid).set_calibration_status('外参已计算' if result.get('success') else '配准失败',
                                                                 bool(result.get('success')))
            self.steps.set_current(2)
            self._refresh_camera_overlays()
            self._changed()
            self.log('离线外参计算完成；结果为各相机到参考相机的毫米变换。',
                     'success' if all(r.get('success') for r in results.values()) else 'warn', task='多相机标定')
        self._run(solve, done, task='离线外参标定')

    def save_extrinsics(self, path):
        if not self.extrinsics or not all(result.get('success') for result in self.extrinsics.values()):
            raise ValueError('请先完成全部相机对的外参计算')
        payload = dict(units='mm', direction='camera_to_reference', reference=self.reference.currentText(),
                       pairs={cid: {key: result[key].tolist() if isinstance(result[key], np.ndarray) else result[key]
                                    for key in ('T', 'rms_mm', 'inlier_ratio', 'outlier_codes') if key in result}
                              for cid, result in self.extrinsics.items()})
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        self.steps.set_current(3)
        self.log('已保存外参：'+str(path), 'success', task='多相机标定')

    def save_extrinsics_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存离线外参', 'extrinsics.json', 'JSON (*.json)')
        if path:
            try:
                self.save_extrinsics(path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, '保存失败', str(exc))

    def new_project(self):
        old = self.session
        super().new_project()
        if self.session is not old:
            self.observations.clear()
            for cid in self.camera_ids:
                self.camera_grid.card(cid).set_thumbnail(None)
                self.camera_grid.card(cid).set_marker_count(None)
            self._invalidate_extrinsics()


class TurntableWorkbench(ModeWorkbench):
    mode_key = 'turntable'
    mode_title = '转台拼接'
    calibration_capture_requested = Signal(int)
    acquisition_settings_changed = Signal(float)

    def __init__(self, parent=None, **kwargs):
        self.calibration_frames = {}
        self.calibration = None
        self.calibration_result = None
        super().__init__(parent, **kwargs)
        self.simulation_group.hide()
        group = QGroupBox('02  转台标定')
        controls = QVBoxLayout(group)
        self.frame_labels = []
        self.load_frame_buttons = []
        self.capture_frame_buttons = []
        for index in range(2):
            row = QHBoxLayout()
            load = QPushButton(f'载入 frame{index}')
            load.clicked.connect(lambda checked=False, slot=index: self.load_calibration_dialog(slot))
            row.addWidget(load)
            capture = QPushButton(f'拍摄 frame{index}')
            capture.setEnabled(False)
            capture.setToolTip('需要连接真实采集控制器')
            capture.clicked.connect(lambda checked=False, slot=index: self.calibration_capture_requested.emit(slot))
            row.addWidget(capture)
            controls.addLayout(row)
            label = QLabel(f'frame{index}：未载入')
            controls.addWidget(label)
            self.frame_labels.append(label)
            self.load_frame_buttons.append(load)
            self.capture_frame_buttons.append(capture)
        self.calibrate_button = QPushButton('计算转台标定')
        self.calibrate_button.clicked.connect(self.calibrate_turntable)
        controls.addWidget(self.calibrate_button)
        self.calibration_label = QLabel('未标定 · 请载入旋转前后的两帧检测JSON')
        self.calibration_label.setWordWrap(True)
        controls.addWidget(self.calibration_label)
        reset = QPushButton('重置标定')
        reset.clicked.connect(self.clear_calibration)
        controls.addWidget(reset)
        controls.addWidget(QLabel('采集间隔（秒）'))
        self.capture_interval = QDoubleSpinBox()
        self.capture_interval.setRange(.1, 60)
        self.capture_interval.setValue(3)
        self.capture_interval.valueChanged.connect(self.acquisition_settings_changed.emit)
        controls.addWidget(self.capture_interval)
        self.parameter_layout.insertWidget(1, group)
        self.device_label.setText('转台方案 · 单相机 · 未连接硬件')
        self._refresh_controls()

    def _refresh_controls(self):
        super()._refresh_controls()
        if not hasattr(self, 'calibrate_button'):
            return
        available = not self._busy and self.session.state not in ('scanning', 'paused')
        ready = len(self.calibration_frames) == 2 and all(len(unique_markers(frame['markers'])) >= 3
                                                       for frame in self.calibration_frames.values())
        self.calibrate_button.setEnabled(available and ready)
        for button in self.load_frame_buttons:
            button.setEnabled(available)
        if self.calibration is None:
            self.scan_button.setEnabled(False)
            self._actions['scan'].setEnabled(False)
            self.scan_button.setToolTip('先完成转台标定；此原型扫描按钮只生成合成点云')

    def set_calibration_frame(self, index, image, markers):
        if index not in (0, 1) or self._busy or self.session.state in ('scanning', 'paused'):
            raise ValueError('标定帧不可在当前状态下更新')
        markers = list(markers)
        if not all(isinstance(m, dict) for m in markers):
            raise ValueError('标记格式错误')
        image = load_image(image)
        self.calibration_frames[index] = dict(image=image, markers=markers)
        self.calibration = self.calibration_result = None
        self.calibration_label.setText('标定帧已更新，需要重新计算')
        self.frame_labels[index].setText(f'frame{index}：{len(unique_markers(markers))} 个有效3D标记')
        self.marker_inspector.set_frame(image, markers, frame_id=f'标定 frame{index}')
        self._changed()
        self._refresh_controls()

    def load_calibration_dialog(self, index):
        path, _ = QFileDialog.getOpenFileName(self, f'载入 frame{index} 检测结果', '', 'JSON (*.json)')
        if path:
            try:
                image, markers = read_observation(path)
                self.set_calibration_frame(index, image, markers)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                QMessageBox.warning(self, '标定帧载入失败', str(exc))

    def calibrate_turntable(self):
        if not self.calibrate_button.isEnabled():
            return
        from core.turntable_calibrator import TurntableCalibrator
        first, second = (unique_markers(self.calibration_frames[i]['markers']) for i in (0, 1))
        common = sorted(set(first) & set(second), key=str)
        if len(common) < 3:
            self.log('转台标定需要至少3个共有有效编码圆。', 'warn')
            return
        p0 = np.asarray([valid_xyz(first[code]) for code in common])
        p1 = np.asarray([valid_xyz(second[code]) for code in common])
        if min(np.linalg.matrix_rank(p0-p0.mean(0)), np.linalg.matrix_rank(p1-p1.mean(0))) < 2:
            self.log('标记点共线，无法标定转台。', 'warn')
            return
        calibration = TurntableCalibrator()
        ok, message, result = calibration.calibrate_from_markers(p0, p1)
        if not ok or not np.isfinite([*result.get('axis', []), *result.get('center', []), result.get('angle_deg', float('nan'))]).all():
            self.calibration_label.setText('标定失败：'+message)
            self.log(message, 'error')
            return
        self.calibration, self.calibration_result = calibration, result
        self.marker_inspector.set_frame(self.calibration_frames[1]['image'], self.calibration_frames[1]['markers'],
            frame_id='标定 frame1', reference_id='标定 frame0', reference_markers=self.calibration_frames[0]['markers'],
            registration_accepted=True)
        self.calibration_label.setText(f"离线标定已计算\n角度 {result['angle_deg']:.3f}° / 约 {result['step_count']} 步\n"
                                       f"轴 {np.round(result['axis'], 4)}\n中心(mm) {np.round(result['center'], 3)}")
        self._changed()
        self.log(message, 'success', task='转台标定')
        self._refresh_controls()

    def start_scan(self):
        if self.calibration is None:
            self.log('请先完成转台标定。', 'warn')
            return
        super().start_scan()

    def clear_calibration(self):
        if self._busy or self.session.state in ('scanning', 'paused'):
            return
        self.calibration_frames.clear()
        self.calibration = self.calibration_result = None
        for index, label in enumerate(self.frame_labels):
            label.setText(f'frame{index}：未载入')
        self.calibration_label.setText('未标定 · 请载入旋转前后的两帧检测JSON')
        self.marker_inspector.set_frame(None, [])
        self._refresh_controls()

    def new_project(self):
        old = self.session
        super().new_project()
        if self.session is not old:
            self.clear_calibration()
