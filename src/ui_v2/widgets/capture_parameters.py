"""Shared capture parameter page for the industrial workspaces."""
from PySide6.QtCore import QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QFormLayout, QComboBox, QSpinBox,
                              QDoubleSpinBox, QLabel, QPushButton)


class CaptureParameters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = None
        self._pending = False
        self._loaded = None
        self._read_values = {}
        form = QFormLayout(self)
        form.setContentsMargins(8, 6, 8, 6)
        self.camera = QComboBox()
        self.camera.currentIndexChanged.connect(self._invalidate)
        form.addRow('目标相机', self.camera)
        self.read_button = QPushButton('读取相机参数')
        self.read_button.clicked.connect(lambda: self._request(False))
        form.addRow(self.read_button)
        self.controls = {}
        for label, key in [('2D 曝光', 'exposure_time_2d'),
                           ('3D 曝光', 'exposure_time_3d'),
                           ('2D 增益', 'gain_2d'), ('3D 增益', 'gain_3d'),
                           ('投影亮度', 'projector_brightness')]:
            control = QDoubleSpinBox() if key.startswith('gain') else QSpinBox()
            if key.startswith('gain'):
                control.setDecimals(3)
                control.setSingleStep(0.1)
            elif key.startswith('exposure'):
                control.setSuffix(' ms')
            control.setKeyboardTracking(False)
            self.controls[key] = control
            form.addRow(label, control)
        self.apply_button = QPushButton('应用到当前相机')
        self.apply_button.clicked.connect(lambda: self._request(True))
        form.addRow(self.apply_button)
        self.status = QLabel('请连接相机后读取拍摄参数。')
        self.status.setWordWrap(True)
        form.addRow(self.status)
        hint = QLabel('仅作用于目标在线相机的后续拍摄，不修改已入库数据。\n高级参数仍可通过顶部“参数调试”设置。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def bind(self, bridge):
        # Presentation-only hosts/test adapters may have no camera service.
        self.bridge = bridge if (hasattr(bridge, 'camera_manager') and
                                 callable(getattr(bridge, 'capture_parameters', None))) else None
        if self.bridge:
            self.timer.start()
        else:
            self.timer.stop()
        self.refresh()

    def _invalidate(self):
        self._loaded = None
        self._read_values = {}
        self.status.setText('请读取目标相机的当前参数。')
        self._enable()

    def refresh(self):
        ids = self.bridge.camera_manager.get_connected_ids() if self.bridge else []
        previous = [self.camera.itemText(i) for i in range(self.camera.count())]
        if ids != previous:
            current = self.camera.currentText()
            with QSignalBlocker(self.camera):
                self.camera.clear()
                self.camera.addItems(ids)
                if current in ids:
                    self.camera.setCurrentText(current)
            self._invalidate()
            if not ids:
                self.status.setText('未连接相机；离线数据不支持设置拍摄参数。')
        self._enable()

    def _enable(self):
        ready = bool(self.bridge and self.camera.count() and not self._pending
                     and self.bridge.can_change_workspace())
        self.camera.setEnabled(not self._pending)
        self.read_button.setEnabled(ready)
        self.apply_button.setEnabled(ready and self._loaded == self.camera.currentText())
        for control in self.controls.values():
            control.setEnabled(ready and self._loaded == self.camera.currentText())

    def _request(self, apply):
        self.refresh()
        if not self.read_button.isEnabled() or (apply and not self.apply_button.isEnabled()):
            return
        camera_id = self.camera.currentText()
        # Preserve SDK precision for fields the operator has not changed.
        values = {key: (self._read_values[key][0]
                        if control.value() == self._read_values[key][1] else control.value())
                  for key, control in self.controls.items()} if apply else None
        self._pending = True
        self._enable()
        self.status.setText('正在应用参数…' if apply else '正在读取参数…')

        def done(result, error):
            self._pending = False
            self.refresh()
            if camera_id != self.camera.currentText():
                return
            if error:
                self.status.setText(str(error))
            else:
                for key, control in self.controls.items():
                    control.setRange(*result['ranges'][key])
                    control.setValue(result['values'][key])
                self._read_values = {key: (result['values'][key], control.value())
                                     for key, control in self.controls.items()}
                self._loaded = camera_id
                text = '已应用，后续拍摄生效。' if apply else '已读取，可修改后应用。'
                if result['hdr']:
                    text += '\n当前启用 HDR；3D 曝光与亮度还受 HDR 分档参数控制。'
                self.status.setText(text)
            self._enable()

        self.bridge.capture_parameters(camera_id, values, done)
