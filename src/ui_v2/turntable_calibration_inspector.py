"""Turntable snapshots adapted to the shared read-only calibration dialog."""
import copy
import numpy as np
from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QSignalBlocker
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QLabel, QPushButton, QSlider, QHBoxLayout, QWidget, QScrollArea, QTabWidget, QLayout
from core.turntable_calibrator import rotation_direction, transform_matrix
from ui_common.calibration_result import CalibrationResultDialog, CAMERA_COLOR, valid_transform
from .calibration_inspector import load_calibration_clouds


class TurntableCalibrationInspector(CalibrationResultDialog):
    def __init__(self, calib, snapshot, parent=None):
        self.calibration = copy.deepcopy(calib)
        snapshot = copy.deepcopy(snapshot or {})
        result = snapshot.get('result', {})
        super().__init__({('初始帧', '旋转帧'): result}, parent,
                         title='转台标定结果与误差', loading=True)
        self.resize(1040, 740)
        self.setMinimumSize(760, 620)
        self.error_filter.setCurrentIndex(1)
        direction = rotation_direction(calib.axis, calib.angle_rad)
        self.model_info = QLabel(f'旋转方向：{direction} · 从相机沿 +Z 看向场景（初始帧 → 旋转帧）\n'
            '两帧按小于180°的单步旋转解释；方向不等同于转台俯视方向。\n'
            '显示旋转帧按转轴模型回到初始帧的误差；未进行内点分类，质量门禁未评估。')
        self.model_info.setWordWrap(True)
        self.layout().insertWidget(0, self.model_info)
        self.viewer.set_rotation_geometry(calib.axis, calib.center)
        self.matrix.setObjectName('turntableTransform')
        self.matrix.setFont(QFont('Consolas', 10))
        self.matrix.setHorizontalHeaderLabels(['X', 'Y', 'Z', 't / mm'])
        self.matrix.setVerticalHeaderLabels(['X', 'Y', 'Z', 'w'])
        self.matrix.verticalHeader().setFixedWidth(26)
        self.matrix.horizontalHeader().setFixedHeight(30)
        self.matrix.verticalHeader().setDefaultSectionSize(38)
        self.matrix.setFixedHeight(184)
        self.matrix.setStyleSheet('''
            QTableWidget#turntableTransform {background:#22282f;border:1px solid #424c58;
                border-radius:4px;gridline-color:#36414d;selection-background-color:#354c60;}
            QTableWidget#turntableTransform::item {padding:5px;}
            QTableWidget#turntableTransform QHeaderView::section {background:#303943;
                color:#b9c5d2;border:0;border-bottom:1px solid #485461;padding:4px;font-size:11px;}
            QTableWidget#turntableTransform QTableCornerButton::section {background:#303943;border:0;}
        ''')
        matrix_layout = self.matrix.parentWidget().layout()
        legend = QLabel('R · 旋转（无量纲）      t · 平移（mm）')
        legend.setStyleSheet('color:#9aabba;padding:4px 0;')
        matrix_layout.insertWidget(1, legend)
        matrix_note = QLabel('末行 w 为齐次坐标；悬停数值可查看完整精度。')
        matrix_note.setWordWrap(True)
        matrix_note.setStyleSheet('color:#82909f;padding-top:4px;')
        matrix_layout.insertWidget(3, matrix_note)
        matrix_page = self.matrix.parentWidget()
        matrix_layout.setSizeConstraint(QLayout.SetMinimumSize)
        for tabs in self.findChildren(QTabWidget):
            index = tabs.indexOf(matrix_page)
            if index >= 0:
                title = tabs.tabText(index)
                tabs.removeTab(index)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                scroll.setFrameShape(QScrollArea.NoFrame)
                scroll.setWidget(matrix_page)
                tabs.insertTab(index, scroll, title)
                break
        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(33)
        self.animation_timer.timeout.connect(self._advance)
        self._elapsed = QElapsedTimer()
        self._fit_after_prepare = False
        self.animation_bar = QWidget()
        self.animation_bar.setObjectName('turntablePlayback')
        self.animation_bar.setStyleSheet('''
            QWidget#turntablePlayback {background:#252d36;border:1px solid #414d5b;border-radius:6px;}
            QWidget#turntablePlayback QPushButton {background:#343f4b;color:#e1e8ef;
                border:1px solid #536171;border-radius:4px;padding:4px 10px;min-height:24px;}
            QWidget#turntablePlayback QPushButton:hover {background:#445467;border-color:#7c96af;}
            QWidget#turntablePlayback QPushButton:pressed {background:#263f50;}
            QWidget#turntablePlayback QPushButton:disabled {color:#707f8e;background:#2b333c;border-color:#3b4652;}
            QWidget#turntablePlayback QPushButton#playTransform {background:#28546b;border-color:#3e829e;color:#edfaff;}
            QWidget#turntablePlayback QPushButton#playTransform:hover {background:#336c86;}
            QWidget#turntablePlayback QPushButton#playTransform:disabled {background:#2b3540;color:#707f8e;border-color:#3b4652;}
            QWidget#turntablePlayback QSlider::groove:horizontal {height:6px;background:#424d5a;border-radius:3px;}
            QWidget#turntablePlayback QSlider::sub-page:horizontal {background:#39acd0;border-radius:3px;}
            QWidget#turntablePlayback QSlider::handle:horizontal {width:14px;margin:-5px 0;
                background:#dceff7;border:2px solid #399fc2;border-radius:8px;}
            QWidget#turntablePlayback QSlider::handle:horizontal:hover {background:#ffffff;border-color:#67d3f3;}
            QWidget#turntablePlayback QSlider::handle:horizontal:focus {border-color:#92e3fa;}
            QWidget#turntablePlayback QSlider::sub-page:horizontal:disabled {background:#52616e;}
            QWidget#turntablePlayback QSlider::handle:horizontal:disabled {background:#7a8792;border-color:#52616e;}
            QLabel#playbackPercent {color:#bdeaff;background:#203e50;border:1px solid #41677e;
                border-radius:4px;padding:5px 6px;font-family:Consolas;font-weight:600;}
            QLabel#playbackPercent:disabled {color:#7e909d;background:#2b3540;border-color:#3c4854;}
        ''')
        bar = QHBoxLayout(self.animation_bar)
        bar.setContentsMargins(10, 6, 10, 6)
        bar.setSpacing(10)
        self.play_button = QPushButton('播放变换')
        self.play_button.setObjectName('playTransform')
        self.play_button.setMinimumWidth(78)
        self.replay_button = QPushButton('重播')
        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.setValue(1000)
        self.progress.setToolTip('0%：旋转帧原始位置；100%：绕标定转轴回转后的对齐结果')
        self.progress_label = QLabel('100%')
        self.progress_label.setObjectName('playbackPercent')
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setMinimumWidth(48)
        for widget in (self.play_button, self.replay_button, self.progress, self.progress_label):
            bar.addWidget(widget, 1 if widget is self.progress else 0)
        self.layout().insertWidget(3, self.animation_bar)
        self.animation_hint = QLabel('0% 原始位置 → 100% 回转对齐；方向与采集相反，误差/矩阵显示终态。')
        self.animation_hint.setWordWrap(True)
        self.layout().insertWidget(4, self.animation_hint)
        self.play_button.clicked.connect(self._toggle_play)
        self.replay_button.clicked.connect(self._replay)
        self.progress.valueChanged.connect(self._seek)
        self.refresh()

    def refresh(self, *_):
        if hasattr(self, 'animation_timer'):
            self._pause()
        super().refresh()
        matrix_transform = valid_transform(self.pairs.get(self.pair_choice.currentData(), {}).get('T'))
        for row in range(4):
            for column in range(4):
                item = self.matrix.item(row, column)
                if item is None:
                    continue
                text = item.text()
                try:
                    value = float(matrix_transform[row, column]) if matrix_transform is not None else float(text)
                    text = (f'{value:.0f}' if row == 3 else
                            f'{value:.3f}' if column == 3 else f'{value:.4f}')
                    if len(text) > 9:
                        text = f'{value:.2e}'
                    if float(text) == 0:
                        text = text.lstrip('-')
                    item.setToolTip(f'{value:.15g}' + (' mm' if column == 3 and row < 3 else ''))
                except ValueError:
                    pass
                item.setText(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setForeground(QColor('#8492a0' if row == 3 else '#efbd78' if column == 3 else '#9edce9'))
                if row == 3:
                    item.setBackground(QColor('#272e36'))
        if not hasattr(self, 'animation_timer'):
            return
        result = self.pairs[('初始帧', '旋转帧')]
        transform = valid_transform(result.get('T'))
        available = (self.view_choice.currentIndex() == 0 and self.show_camera.isChecked()
                     and all(len(self.clouds.get(name, [])) for name in ('初始帧', '旋转帧'))
                     and transform is not None and np.allclose(transform, self.calibration.get_transform_for_step(1)))
        self.animation_bar.setEnabled(bool(available))
        if available:
            self._draw_progress(self.progress.value())
        else:
            with QSignalBlocker(self.progress):
                self.progress.setValue(1000)
            self.progress_label.setText('100%')

    def _select_row(self):
        if hasattr(self, 'animation_timer') and self.table.selectedItems():
            self._pause()
            self.progress.setValue(1000)
        super()._select_row()

    def _draw_progress(self, value):
        if not self.active or not self.animation_bar.isEnabled():
            return
        import open3d as o3d
        fraction = value / 1000.
        transform = transform_matrix(self.calibration.axis, -self.calibration.angle_rad*fraction,
                                     self.calibration.center)
        points = self.clouds['旋转帧']
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(points @ transform[:3, :3].T + transform[:3, 3])
        cloud.paint_uniform_color(CAMERA_COLOR)
        self.viewer.set_cloud_markers([])
        self.viewer.set_pointcloud('旋转帧', cloud)
        self.progress_label.setText(f'{value/10:.0f}%')

    def _seek(self, value):
        self._pause()
        self._draw_progress(value)

    def _pause(self):
        self.animation_timer.stop()
        self.play_button.setText('播放变换')

    def _fit_motion(self):
        low = self.clouds['初始帧'].min(axis=0)
        high = self.clouds['初始帧'].max(axis=0)
        for fraction in np.linspace(0, 1, 9):
            transform = transform_matrix(self.calibration.axis, -self.calibration.angle_rad*fraction,
                                         self.calibration.center)
            points = self.clouds['旋转帧'] @ transform[:3, :3].T + transform[:3, 3]
            low, high = np.minimum(low, points.min(axis=0)), np.maximum(high, points.max(axis=0))
        canvas = self.viewer.canvas
        canvas.center = (low+high)/2
        canvas.extent = max(float(np.linalg.norm(high-low))*1.1, 10.)
        canvas.zoom = 1.
        canvas.pan[:] = 0
        canvas._notify_view_changed()

    def _toggle_play(self):
        if not self.active or not self.animation_bar.isEnabled():
            return
        if self.animation_timer.isActive():
            self._pause()
            return
        if self.progress.value() == 1000:
            self.progress.setValue(0)
            self._fit_after_prepare = True
        self._start_progress = self.progress.value()
        self._elapsed.start()
        self.play_button.setText('暂停')
        self.animation_timer.start()

    def _replay(self):
        if not self.animation_bar.isEnabled():
            return
        self._pause()
        self.progress.setValue(0)
        self._fit_after_prepare = True
        self._toggle_play()

    def _advance(self):
        if not self.active or not self.animation_bar.isEnabled():
            self._pause()
            return
        if self.viewer.canvas.is_busy:
            return
        if self._fit_after_prepare:
            self._fit_motion()
            self._fit_after_prepare = False
        value = min(1000, self._start_progress + int(self._elapsed.elapsed()/3))
        with QSignalBlocker(self.progress):
            self.progress.setValue(value)
        self._draw_progress(value)
        if value == 1000:
            self._pause()

    def _finish(self, *_):
        if hasattr(self, 'animation_timer'):
            self._pause()
        super()._finish()


def open_inspector(bridge):
    workspace = bridge.shell.workspace_turntable()
    if not bridge.can_change_workspace():
        bridge.shell.log('请先等待当前任务完成，再查看标定可视化。', 'warn')
        return
    if not workspace.session.is_calibrated():
        bridge.shell.log('尚无转台标定结果，请先计算转轴。', 'warn')
        return
    previous = getattr(bridge, '_turntable_calibration_inspector', None)
    if previous is not None and previous.active:
        previous.raise_()
        previous.activateWindow()
        return
    snapshot = copy.deepcopy(workspace.session.calibration_result)
    dialog = TurntableCalibrationInspector(workspace.session.calib, snapshot, bridge.shell)
    bridge._turntable_calibration_inspector = dialog
    database = bridge.frame_db.databases['turntable']
    paths = {}
    source_warnings = []
    for name, uid in zip(('初始帧', '旋转帧'), (snapshot or {}).get('source_ids', [])):
        if uid in database.records:
            saved_revision = snapshot.get('source_revisions', {}).get(uid)
            if saved_revision is not None and database.records[uid].revision != saved_revision:
                source_warnings.append(f'{name}：原始帧已被替换，不叠加已改变的点云；匹配点仍来自标定快照。')
            else:
                paths[name] = str(database.directory / 'frames' / uid / 'pointmap.ply')
    dialog.open()

    def done(result, error):
        if not dialog.active:
            return
        if error:
            dialog.set_clouds({}, ['读取标定点云失败：' + str(error)])
        else:
            clouds, warnings = result
            warnings.extend(source_warnings)
            if not snapshot:
                warnings.append('历史标定未保存两帧来源和误差明细；仅展示转轴与中心，请重新标定以生成完整可视化。')
            dialog.set_clouds(clouds, warnings)

    bridge._run_background(lambda: load_calibration_clouds(paths), done, name='calibration_inspection')
