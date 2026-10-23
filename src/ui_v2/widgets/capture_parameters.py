"""Shared capture settings, loaded from the camera when first displayed."""
from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox,
                              QGroupBox, QLabel, QPushButton, QHBoxLayout,
                              QScrollArea, QLayout, QToolButton, QSizePolicy)
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
        self._populating = False
        self._writing = False
        self._dirty = False
        self._edit_revision = 0
        self._ranges = {}
        self.apply_timer = QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(250)
        self.apply_timer.timeout.connect(self._flush)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)
        header = QHBoxLayout()
        self.camera = QComboBox()
        self.camera.setPlaceholderText('未连接相机')
        self.camera.currentIndexChanged.connect(self._invalidate)
        self.camera.setMinimumWidth(0)
        self.camera.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.camera.setStyleSheet('font-size:11px;')
        self.camera.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.read_button = QToolButton()
        from ui_common.symbols import apply
        apply(self.read_button, 'refresh', size=16)
        self.read_button.setFixedSize(28, 28)
        self.read_button.setStyleSheet('QToolButton {padding:2px;border:1px solid #414141;} QToolButton:hover {background:#414141;}')
        self.read_button.setToolTip('重新读取相机参数')
        self.read_button.setAccessibleName('重新读取相机参数')
        self.read_button.clicked.connect(lambda: self._request(False))
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
        self.status = QLabel('未连接相机；连接后自动读取机内参数。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        root.addWidget(self.status)
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
            ('3D 点云', [('曝光', 'exposure_time_3d', 'int'),
                         ('单行曝光', 'line_scanner_exposure_time_us', 'int'), ('增益', 'gain_3d', 'float')]),
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
                                          suffix=' µs' if key == 'line_scanner_exposure_time_us' else ' ms' if key.startswith('exposure') else '')
                    control = row.spin
                    self.sliders[key] = row
                self.controls[key] = control
                signal = control.currentIndexChanged if isinstance(control, QComboBox) else control.valueChanged
                signal.connect(self._changed)
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
        self.apply_timer.stop()
        self._dirty = False
        self._generation += 1
        self._loaded = None
        self._read_values = {}
        self._ranges = {}
        self._auto_needed = True
        self._show_unloaded()
        self.status.setText('等待自动读取相机参数…')
        self._enable()

    def refresh(self, allow_auto=True):
        manager = self.bridge.camera_manager if self.bridge and not getattr(self.bridge, '_cleaned', False) else None
        ids = manager.get_connected_ids() if manager else []
        previous = [self.camera.itemData(i) for i in range(self.camera.count())]
        current = self.camera.currentData()
        if ids != previous:
            with QSignalBlocker(self.camera):
                self.camera.clear()
                labels = manager.capture_parameter_labels() if manager else {}
                for cid in ids:
                    self.camera.addItem(labels.get(cid, cid), cid)
                    self.camera.setItemData(self.camera.count() - 1, labels.get(cid, cid), Qt.ToolTipRole)
                if current in ids:
                    self.camera.setCurrentIndex(self.camera.findData(current))
                elif ids:
                    self.camera.setCurrentIndex(0)
        if manager:
            for cid, label in manager.capture_parameter_labels().items():
                index = self.camera.findData(cid)
                with QSignalBlocker(self.camera):
                    self.camera.setItemText(index, label)
                    self.camera.setItemData(index, label, Qt.ToolTipRole)
            self.camera.setToolTip(self.camera.currentText())
        source = (manager.capture_parameter_source(self.camera.currentData())
                  if manager and self.camera.count() else None)
        if source != self._source:
            self._source = source
            self._invalidate()
        if not ids:
            self.status.setText('未连接相机；离线数据不支持设置拍摄参数。')
        self._enable()
        if allow_auto and self.isVisible() and self._auto_needed and self.read_button.isEnabled():
            self._request(False)
        if self._dirty and not self._pending and not self.apply_timer.isActive():
            self.apply_timer.start()

    def _changed(self, *_):
        if self._populating or self._loaded != self.camera.currentData() or not self._read_values:
            return
        self._dirty = True
        self._edit_revision += 1
        self.status.setText('正在等待参数生效…')
        if not self.apply_timer.isActive():
            self.apply_timer.start()

    def _flush(self):
        if not self._dirty or self._pending:
            return
        self._request(True)

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
        connected = bool(self.bridge and not getattr(self.bridge, '_cleaned', False) and self.camera.count())
        idle = connected and self.bridge.can_change_workspace()
        self.camera.setEnabled(connected and not self._pending)
        self.read_button.setEnabled(idle and not self._pending)
        editable = idle or connected and self._pending and self._writing
        for key, (_, row) in self.rows.items():
            row.setEnabled(bool(editable and key in self._read_values
                                and self._loaded == self.camera.currentData()))

    def _value(self, key):
        if key in self.sliders:
            return self.sliders[key].value()
        return self.controls[key].currentData()

    def _values_to_apply(self):
        # Preserve SDK precision for untouched fields rounded by the display.
        values = {}
        for key, (original, shown) in self._read_values.items():
            current = self._value(key)
            valid_original = key not in self._ranges or self._ranges[key][0] <= original <= self._ranges[key][1]
            values[key] = original if current == shown and valid_original else current
        return values

    def _display_result(self, result):
        """Populate supported controls without reading or writing a device."""
        self._populating = True
        try:
            self._populate(result)
        finally:
            self._populating = False

    def _populate(self, result):
        self._ranges = dict(result['ranges'])
        for key, value in result['values'].items():
            if key in self.sliders:
                editor = self.sliders[key]
                editor.set_range(*result['ranges'][key])
                low, high = result['ranges'][key]
                unqueried = key in result.get('unqueried_ranges', [])
                editor.slider.setVisible(not unqueried)
                editor.spin.setFixedWidth(145 if unqueried else 91)
                editor.setToolTip('单行曝光，单位微秒；SDK 未提供独立范围查询，以设备校验为准'
                                  if unqueried else f'相机允许范围：{low:g}～{high:g}；调整后自动生效')
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
        if self._pending or not self.bridge or getattr(self.bridge, '_cleaned', False) or not self.bridge.can_change_workspace() or not self.camera.count():
            return
        if apply and self._loaded != self.camera.currentData():
            return
        self.apply_timer.stop()
        self._auto_needed = False
        generation = self._generation
        revision = self._edit_revision
        camera_id = self.camera.currentData()
        values = self._values_to_apply() if apply else None
        shown = {key: self._value(key) for key in self._read_values} if apply else {}
        self._pending = True
        self._writing = apply
        self._enable()
        self.status.setText('正在更新拍摄参数…' if apply else '正在读取机内参数…')

        def done(result, error):
            self._pending = False
            self._writing = False
            self.refresh(False)
            if generation != self._generation or camera_id != self.camera.currentData():
                return
            newer_edits = apply and self._edit_revision != revision
            if result and set(result['values']) != set(self._read_values):
                newer_edits = False
            self._dirty = newer_edits
            if error:
                self.status.setText(str(error) + '\n可修改参数或点击刷新按钮重试。')
                if not newer_edits:
                    self.apply_timer.stop()
            else:
                if newer_edits:
                    # Retain the newer controls; acknowledge only the values sent.
                    self._read_values = {key: (value, shown[key]) for key, value in result['values'].items()}
                else:
                    self._display_result(result)
                self._loaded = camera_id
                text = '已实时生效，取景中可查看效果。' if apply else '已读取机内参数，调整后自动生效。'
                if result['hdr']:
                    text += '\nHDR 已开启，3D 曝光与亮度还受分档参数控制。'
                self.status.setText('正在等待最新参数生效…' if newer_edits else text)
            self._enable()
            if self._dirty:
                self.apply_timer.start()

        self.bridge.capture_parameters(camera_id, values, done)
