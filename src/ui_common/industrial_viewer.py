"""Production renderer adapter for the prototype's portable GPU scene.

Keeps original Open3D geometry alive; sampling affects only display buffers.
"""
from dataclasses import dataclass
import numpy as np
from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QSpinBox, QLabel, QApplication, QToolButton, QMenu)


@dataclass
class DisplayLayer:
    name: str
    points: object
    colors: object = None
    visible: bool = True


class IndustrialViewer(QWidget):
    status_changed = Signal(str)
    collapse_toggled = Signal(bool)
    maximize_toggled = Signal(bool)
    canvas_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pcds = {}
        self._merged = None
        self._database_cloud = None
        self._database_previous_mode = None
        self._reference = None
        self._highlights = {}
        self._collapsed = False
        self._maximized = False
        self._retired = []
        self._layers = []
        self._closed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem('全部相机', None)
        self.mode.addItem('拼接结果', '__merged__')
        self.mode.currentIndexChanged.connect(self._refresh)
        # DB tree owns data selection. Retain the model only for existing APIs.
        self.mode.setParent(self)
        self.mode.hide()
        self.view_preset = QComboBox()
        self.view_preset.addItems(['等轴测', '顶视', '正视', '右视'])
        self.view_preset.currentTextChanged.connect(lambda value: self.canvas.set_view(value))
        self.view_preset.setToolTip('标准视角')
        row.addWidget(self.view_preset)
        self.quality = QComboBox()
        self.quality.addItems(['流畅', '均衡', '细节'])
        self.quality.setCurrentText('均衡')
        self.quality.currentTextChanged.connect(self._quality)
        self.quality.setToolTip('显示质量（不改变原始数据）')
        row.addWidget(self.quality)
        self.color_mode = QComboBox()
        self.color_mode.addItems(['原始颜色', '高度着色', '统一颜色'])
        self.color_mode.currentTextChanged.connect(self._color)
        row.addWidget(self.color_mode)
        size = QSpinBox()
        size.setRange(1, 10)
        size.setValue(2)
        size.setPrefix('点大小 ')
        size.valueChanged.connect(self.set_point_size)
        row.addWidget(size)
        row.addStretch(1)
        self.max_button = QPushButton('最大化')
        self.max_button.setCheckable(True)
        self.max_button.toggled.connect(self._maximize)
        row.addWidget(self.max_button)
        self.options_button = QToolButton()
        self.options_button.setText('显示选项')
        self.options_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.options_button)
        for label, attribute in (('参考网格', 'grid'), ('坐标轴', 'axes'), ('编码圆圆心与编号', 'marker_centers')):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda value, attr=attribute: self._display_option(attr, value))
        self.options_button.setMenu(menu)
        row.addWidget(self.options_button)
        root.addLayout(row)
        self.canvas = self._create_canvas()
        root.addWidget(self.canvas, 1)
        self.status = QLabel()
        root.addWidget(self.status)
        self._bind_canvas()
        QTimer.singleShot(400, self._check_context)

    def _create_canvas(self, software=False):
        if software or QApplication.platformName().lower() in ('offscreen','minimal'):
            from .industrial_scene.canvas import CloudCanvas
            return CloudCanvas(self)
        from .industrial_scene.gpu_canvas import GpuCloudCanvas
        return GpuCloudCanvas(self)

    def _bind_canvas(self):
        self.canvas.status_changed.connect(self._status)
        if hasattr(self.canvas, 'render_failed'):
            self.canvas.render_failed.connect(self._fallback)
        self._status()

    def _check_context(self):
        if self.isVisible() and hasattr(self.canvas, 'isValid') and not self.canvas.isValid():
            self._fallback('无法建立 OpenGL 3.3 上下文')

    def _fallback(self, message):
        if self._closed or not hasattr(self.canvas, 'render_failed'):
            return
        old = self.canvas
        old.shutdown()
        self._retired.append(old)
        old.hide()
        self.canvas = self._create_canvas(software=True)
        self.layout().replaceWidget(old, self.canvas)
        self._bind_canvas()
        self.canvas.set_layers(self._layers, fit=True)
        geometry = getattr(old, '_rotation_geometry', None)
        self.canvas.set_rotation_geometry(*(geometry or (None, None)))
        self.canvas.set_cloud_markers(getattr(old, '_cloud_markers', []))
        self.canvas.marker_centers = getattr(old, 'marker_centers', True)
        self.canvas_changed.emit(self.canvas)
        self.status_changed.emit(str(message) + '；已切换软件兼容预览，显示点数受限。')

    def _quality(self, value):
        self.canvas.set_policy(value)

    def _color(self, value):
        self.canvas.color_mode = value
        self.canvas.update()

    def _display_option(self, name, value):
        setattr(self.canvas, name, value)
        self.canvas._rotation_overlay.update()
        self.canvas.update()

    def _status(self):
        text = f'{self.canvas.backend_name} | 原始 {self.canvas.total_points:,} / 显示 {self.canvas.displayed_points:,} 点'
        self.status.setText(text)

    def _refresh(self, *_, fit=False):
        selected = self.mode.currentData()
        clouds = {'__merged__':self._merged} if selected == '__merged__' else self._pcds
        if selected == '__db_frame__':
            clouds = {'DB原始单帧 / 相机坐标': self._database_cloud}
        elif selected not in (None,'__merged__'):
            clouds = {selected:self._pcds.get(selected)}
        layers = []
        for key, cloud in clouds.items():
            if cloud is None or not len(cloud.points):
                continue
            # Array views keep the actual source geometry; no raw-point decimation.
            colors = np.asarray(cloud.colors) if cloud.has_colors() else None
            if self._highlights.get(key):
                colors = np.array(colors if colors is not None else np.broadcast_to([.66,.81,.91], (len(cloud.points),3)), copy=True)
                ids = np.asarray(self._highlights[key], dtype=int)
                ids = ids[(ids >= 0) & (ids < len(colors))]
                colors[ids] = [1., .3, .3]
            layers.append(DisplayLayer(key, np.asarray(cloud.points), colors))
        self._layers = layers
        self.canvas.set_layers(layers, fit=fit or self.canvas.total_points == 0)

    def set_pointcloud(self, camera_id, pcd):
        if pcd is None:
            self._pcds.pop(camera_id, None)
            index = self.mode.findData(camera_id)
            if index >= 0:
                self.mode.removeItem(index)
        else:
            self._pcds[camera_id] = pcd
            if self.mode.findData(camera_id) < 0:
                self.mode.addItem(camera_id, camera_id)
        self._refresh()

    def set_pointcloud_merged(self, pcd):
        self._merged = pcd
        self.mode.setCurrentIndex(1)
        self._refresh()

    def remove_camera(self, camera_id):
        self.set_pointcloud(camera_id, None)

    def clear_all(self):
        self.canvas.set_cloud_markers([])
        self._pcds.clear()
        self._merged = None
        self._database_cloud = None
        self._highlights.clear()
        self.mode.blockSignals(True)
        while self.mode.count() > 2:
            self.mode.removeItem(2)
        self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)
        self._refresh()

    def reset_view(self):
        self.canvas.fit_view()

    def show_database_frame(self, cloud):
        self.mode.blockSignals(True)
        if cloud is not None:
            if self.mode.currentData() != '__db_frame__':
                self._database_previous_mode = self.mode.currentData()
            self._database_cloud = cloud
            if self.mode.findData('__db_frame__') < 0:
                self.mode.addItem('DB原始单帧 / 相机坐标', '__db_frame__')
            self.mode.setCurrentIndex(self.mode.findData('__db_frame__'))
        else:
            self._database_cloud = None
            restore_mode = self._database_previous_mode if self.mode.currentData() == '__db_frame__' else self.mode.currentData()
            index = self.mode.findData('__db_frame__')
            if index >= 0:
                self.mode.removeItem(index)
            index = self.mode.findData(restore_mode)
            self.mode.setCurrentIndex(max(0, index))
        self.mode.blockSignals(False)
        self._refresh(fit=True)

    def set_view_preset(self, name):
        self.canvas.set_view({'iso':'等轴测','top':'顶视','front':'正视','side':'右视','right':'右视'}.get(name,name))

    def set_point_size(self, size):
        self.canvas.point_size = size
        self.canvas.update()

    def set_reference(self, camera_id):
        self._reference = camera_id
        self._refresh()

    def set_rotation_geometry(self, axis=None, center=None):
        self.canvas.set_rotation_geometry(axis, center)

    def set_cloud_markers(self, points):
        self.canvas.set_cloud_markers(points)

    def set_highlight(self, camera_id, indices=None):
        self._highlights[camera_id] = list(indices or [])
        self._refresh()

    def clear_highlight(self):
        self._highlights.clear()
        self._refresh()

    def is_collapsed(self):
        return self._collapsed

    def set_collapsed(self, collapsed):
        self._collapsed = collapsed
        self.canvas.setVisible(not collapsed)
        self.collapse_toggled.emit(not collapsed)

    def _maximize(self, enabled):
        self._maximized = enabled
        self.maximize_toggled.emit(enabled)

    def set_maximized(self, enabled):
        self.max_button.setChecked(enabled)

    def shutdown(self):
        self._closed = True
        for canvas in [self.canvas, *self._retired]:
            canvas.shutdown()
            worker = getattr(canvas, '_worker', None)
            if worker is not None and worker.isRunning():
                worker.wait()

    def is_busy(self):
        return any(canvas.is_busy for canvas in [self.canvas, *self._retired])
