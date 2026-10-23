"""Shared capture settings, loaded from the camera when first displayed."""
from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox,
                              QGroupBox, QLabel, QPushButton, QHBoxLayout,
                              QScrollArea, QLayout)
from ui_common.parameter_slider import ParameterSlider


class CaptureParameters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('captureParameters')
        self.bridge = None
        self._pending = False
        self._loaded = None
        self._read_values = {}
        self._auto_needed = True
        self._generation = 0
        self._source = None
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)
        header = QHBoxLayout()
        self.camera = QComboBox()
        self.camera.setPlaceholderText('未连接相机')
        self.camera.currentIndexChanged.connect(self._invalidate)
        self.read_button = QPushButton('重新读取')
        self.read_button.clicked.connect(lambda: self._request(False))
        header.addWidget(QLabel('目标相机'))
        header.addWidget(self.camera, 1)
        header.addWidget(self.read_button)
        root.addLayout(header)
        self.camera.setToolTip('目标在线相机；打开页面或切换相机时自动读取机内参数')
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSizeConstraint(QLayout.SetMinimumSize)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(0)
        self.scroll.setWidget(body)
        root.addWidget(self.scroll, 1)
        self.controls, self.sliders, self.rows, self.groups = {}, {}, {}, {}
        self._build_groups(body_layout)
        body_layout.addStretch(1)
        self.apply_button = QPushButton('应用到当前相机')
        self.apply_button.clicked.connect(lambda: self._request(True))
        root.addWidget(self.apply_button)
        self.status = QLabel('未连接相机；连接后自动读取机内参数。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        root.addWidget(self.status)
        self.apply_button.setToolTip('拖动滑块或输入数值后点击应用，仅影响后续拍摄。\n更多型号专用参数可在顶部“参数调试”中设置。')
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self._show_unloaded()
        self.refresh()

    def _build_groups(self, body_layout):
        """Keep the field inventory and construction separate from page state."""
        specs = (
            ('拍摄', [('拍摄模式', 'capture_mode', 'choice')]),
            ('2D 图像', [('曝光', 'exposure_time_2d', 'int'), ('增益', 'gain_2d', 'float'),
                         ('Gamma', 'gamma_2d', 'float'),
                         ('使用光机', 'use_projector_capturing_2d_image', 'bool'),
                         ('点云对应 2D', 'correspond2d', 'bool')]),
            ('3D 点云', [('曝光', 'exposure_time_3d', 'int'), ('增益', 'gain_3d', 'float')]),
            ('投影', [('亮度', 'projector_brightness', 'int'), ('颜色', 'projector_color', 'choice')]))
        for title, fields in specs:
            group = QGroupBox(title)
            form = QFormLayout(group)
            form.setSizeConstraint(QLayout.SetMinimumSize)
            form.setContentsMargins(7, 10, 7, 6)
            form.setSpacing(4)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            self.groups[title] = (group, [])
            for label, key, kind in fields:
                if kind in ('bool', 'choice'):
                    row = control = QComboBox()
                    if kind == 'bool':
                        control.addItem('否', False)
                        control.addItem('是', True)
                else:
                    row = ParameterSlider(decimals=3 if kind == 'float' else 0,
                                          suffix=' ms' if key.startswith('exposure') else '')
                    control = row.spin
                    self.sliders[key] = row
                self.controls[key] = control
                self.rows[key] = (form, row)
                self.groups[title][1].append(key)
                form.addRow(label, row)
                form.labelForField(row).setFixedWidth(70)
            body_layout.addWidget(group)

    def bind(self, bridge):
        candidate = bridge if (hasattr(bridge, 'camera_manager') and
                                callable(getattr(bridge, 'capture_parameters', None))) else None
        if candidate is not self.bridge:
            self.bridge = candidate
            self._invalidate()
        if self.bridge:
            self.timer.start()
        else:
            self.timer.stop()
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh)

    def _invalidate(self):
        self._generation += 1
        self._loaded = None
        self._read_values = {}
        self._auto_needed = True
        self._show_unloaded()
        self.status.setText('等待自动读取相机参数…')
        self._enable()

    def refresh(self, allow_auto=True):
        manager = self.bridge.camera_manager if self.bridge else None
        ids = manager.get_connected_ids() if manager else []
        previous = [self.camera.itemText(i) for i in range(self.camera.count())]
        current = self.camera.currentText()
        if ids != previous:
            with QSignalBlocker(self.camera):
                self.camera.clear()
                self.camera.addItems(ids)
                if current in ids:
                    self.camera.setCurrentText(current)
                elif ids:
                    self.camera.setCurrentIndex(0)
        source = (manager.capture_parameter_source(self.camera.currentText())
                  if manager and self.camera.count() else None)
        if source != self._source:
            self._source = source
            self._invalidate()
        if not ids:
            self.status.setText('未连接相机；离线数据不支持设置拍摄参数。')
        self._enable()
        if allow_auto and self.isVisible() and self._auto_needed and self.read_button.isEnabled():
            self._request(False)

    def _show_fields(self, keys):
        for key, (form, row) in self.rows.items():
            form.setRowVisible(row, key in keys)
        for group, members in self.groups.values():
            group.setVisible(any(key in keys for key in members))

    def _show_unloaded(self):
        """Keep the settings discoverable without presenting invented values."""
        for key, control in self.controls.items():
            if key in self.sliders:
                self.sliders[key].set_unloaded()
            else:
                control.clear()
                control.addItem('待读取', None)
        self._show_fields(set(self.controls))

    def _enable(self):
        ready = bool(self.bridge and self.camera.count() and not self._pending
                     and self.bridge.can_change_workspace())
        self.camera.setEnabled(bool(self.camera.count()) and not self._pending)
        self.read_button.setEnabled(ready)
        self.apply_button.setEnabled(ready and self._loaded == self.camera.currentText())
        self.apply_button.setText('应用到 ' + self.camera.currentText() if self.camera.count() else '应用到当前相机')
        for key, (_, row) in self.rows.items():
            row.setEnabled(ready and key in self._read_values and self._loaded == self.camera.currentText())

    def _value(self, key):
        if key in self.sliders:
            return self.sliders[key].value()
        return self.controls[key].currentData()

    def _values_to_apply(self):
        # Preserve SDK precision for untouched fields rounded by the display.
        values = {}
        for key, (original, shown) in self._read_values.items():
            current = self._value(key)
            values[key] = original if current == shown else current
        return values

    def _display_result(self, result):
        """Populate supported controls without reading or writing a device."""
        for key, value in result['values'].items():
            if key in self.sliders:
                editor = self.sliders[key]
                editor.set_range(*result['ranges'][key])
                editor.set_value(value)
            else:
                control = self.controls[key]
                choices = result['choices'].get(key, [('否', False), ('是', True)])
                control.clear()
                for label, option in choices:
                    control.addItem(label, option)
                control.setCurrentIndex(control.findData(value))
        self._show_fields(set(result['values']))
        self._read_values = {key: (value, self._value(key))
                             for key, value in result['values'].items()}

    def _request(self, apply):
        self.refresh(False)
        if not self.read_button.isEnabled() or (apply and not self.apply_button.isEnabled()):
            return
        self._auto_needed = False
        generation = self._generation
        camera_id = self.camera.currentText()
        values = self._values_to_apply() if apply else None
        self._pending = True
        self._enable()
        self.status.setText('正在应用参数…' if apply else '正在读取机内参数…')

        def done(result, error):
            self._pending = False
            self.refresh(False)
            if generation != self._generation or camera_id != self.camera.currentText():
                return
            if error:
                self.status.setText(str(error) + '\n可点击“重新读取”重试。')
            else:
                self._display_result(result)
                self._loaded = camera_id
                text = '已应用，后续拍摄生效。' if apply else '已读取相机内保存的参数。'
                if result['hdr']:
                    text += '\nHDR 已开启，3D 曝光与亮度还受分档参数控制。'
                self.status.setText(text)
            self._enable()

        self.bridge.capture_parameters(camera_id, values, done)
