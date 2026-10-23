"""Shared DB metadata inspector and controls for the current 3D renderer."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLabel,
    QTabWidget, QScrollArea, QComboBox, QSpinBox, QPushButton, QCheckBox, QLayout,
    QStackedWidget, QSizePolicy)


class DbProperties(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('dbProperties')
        self.setStyleSheet('''
            QWidget#dbProperties QComboBox, QWidget#dbProperties QSpinBox,
            QWidget#dbProperties QDoubleSpinBox {
                min-height:24px; padding:2px 6px;
            }
            QWidget#dbProperties QPushButton { min-height:24px; padding:2px 6px; }
        ''')
        self._renderer = None
        self._connections = []
        self.values = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(QLabel('属性'))
        self.tabs = QTabWidget()
        self.tabs.setObjectName('propertyTabs')
        self.tabs.setStyleSheet("QTabBar::tab {font-size:11px;padding:6px 5px;}")
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        root.addWidget(self.tabs, 1)
        self.data = QWidget()
        self.form = QFormLayout(self.data)
        self.form.setSizeConstraint(QLayout.SetMinimumSize)
        self.form.setContentsMargins(8, 6, 8, 6)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.object_pages = QStackedWidget()
        self.data_scroll = self._scroll(self.data)
        self.object_pages.addWidget(self.data_scroll)
        self._object_pages = {}
        self.tabs.addTab(self.object_pages, '数据属性')
        self.display = QWidget()
        form = QFormLayout(self.display)
        form.setSizeConstraint(QLayout.SetMinimumSize)
        form.setContentsMargins(8, 6, 8, 6)
        self.view_preset = QComboBox()
        self.quality = QComboBox()
        self.color_mode = QComboBox()
        self.point_size = QSpinBox()
        self.point_size.setRange(1, 10)
        self.point_size.setValue(2)
        for label, control, options in (
                ('标准视角', self.view_preset, ['等轴测', '顶视', '正视', '右视']),
                ('显示质量', self.quality, ['流畅', '均衡', '细节']),
                ('点云颜色', self.color_mode, ['原始颜色', '高度着色', '统一颜色'])):
            control.addItems(options)
            form.addRow(label, control)
        form.addRow('点大小', self.point_size)
        self.options = {}
        for label, name in [('参考网格', 'grid'), ('坐标轴', 'axes'), ('编码圆圆心与编号', 'marker_centers')]:
            check = QCheckBox(label)
            self.options[name] = check
            form.addRow(check)
            check.toggled.connect(lambda value, key=name: self._option(key, value))
        self.fit_button = QPushButton('适配视图')
        self.fit_button.clicked.connect(lambda: self._renderer and self._renderer.reset_view())
        form.addRow(self.fit_button)
        self.max_button = QPushButton('最大化视图（Esc 恢复）')
        self.max_button.setCheckable(True)
        self.max_button.toggled.connect(lambda value: self._renderer and self._renderer.max_button.setChecked(value))
        form.addRow(self.max_button)
        hint = QLabel('显示设置作用于当前3D视图，不修改原始数据。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self._page(self.display, '3D 显示')
        from .capture_parameters import CaptureParameters
        self.capture = CaptureParameters()
        self.tabs.addTab(self.capture, '拍摄参数')
        from .recognition_parameters import RecognitionParameters
        self.recognition = RecognitionParameters()
        self.tabs.addTab(self.recognition, '识别参数')
        for control, name in [(self.view_preset, 'view_preset'), (self.quality, 'quality'), (self.color_mode, 'color_mode')]:
            control.currentTextChanged.connect(lambda value, key=name: self._combo(key, value))
        self.point_size.valueChanged.connect(lambda value: self._renderer and self._renderer.point_size_control.setValue(value))
        self.display.setEnabled(False)
        self.show_values({'提示': '请选择 DB 树中的数据'})

    def _page(self, content, title):
        scroll = self._scroll(content)
        self.tabs.addTab(scroll, title)
        return scroll

    def _scroll(self, content):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def register_object_page(self, kind, content):
        page = self._scroll(content)
        self._object_pages[kind] = page
        self.object_pages.addWidget(page)

    def show_values(self, values, *, object_type=None):
        self.values = dict(values)
        page = self._object_pages.get(object_type, self.data_scroll)
        self.object_pages.setCurrentWidget(page)
        if page is not self.data_scroll:
            self.tabs.setCurrentIndex(0)
        while self.form.rowCount():
            self.form.removeRow(0)
        for key, value in self.values.items():
            label = QLabel(str(value))
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setToolTip(str(value))
            self.form.addRow(key, label)

    def _combo(self, name, value):
        if self._renderer:
            getattr(self._renderer, name).setCurrentText(value)

    def _option(self, name, value):
        if self._renderer:
            self._renderer.display_actions[name].setChecked(value)

    def bind_renderer(self, renderer):
        if renderer is self._renderer:
            return
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self._renderer = renderer if hasattr(renderer, 'display_actions') else None
        self.display.setEnabled(self._renderer is not None)
        if self._renderer is None:
            return
        for name in ('view_preset', 'quality', 'color_mode'):
            source, target = getattr(renderer, name), getattr(self, name)
            self._mirror(source.currentTextChanged, target, target.setCurrentText, source.currentText())
        source = renderer.point_size_control
        self._mirror(source.valueChanged, self.point_size, self.point_size.setValue, source.value())
        self._mirror(renderer.max_button.toggled, self.max_button, self.max_button.setChecked, renderer.max_button.isChecked())
        for name, action in renderer.display_actions.items():
            target = self.options[name]
            self._mirror(action.toggled, target, target.setChecked, action.isChecked())

    def _mirror(self, signal, target, setter, value):
        def update(value):
            with QSignalBlocker(target):
                setter(value)
        update(value)
        signal.connect(update)
        self._connections.append((signal, update))
