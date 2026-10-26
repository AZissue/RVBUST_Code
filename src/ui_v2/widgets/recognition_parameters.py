"""Shared offline-capable recognition settings for all industrial workspaces."""
import copy
from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox,
                              QGroupBox, QLabel, QPushButton, QLayout, QScrollArea)
from core.calib_board_detector import DEFAULT_BOARD_SPECS
from ui_common.parameter_slider import ParameterSlider


class RecognitionParameters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = None
        self.mode = None
        self._loaded = None
        self._edited = False
        self._catalog = copy.deepcopy(DEFAULT_BOARD_SPECS)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(8)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(6)
        self.marker_type = QComboBox()
        self.marker_type.addItem('编码圆', 'coded_circle')
        self.marker_type.addItem('非对称圆标定板', 'asymmetric_grid')
        form.addRow('识别类型', self.marker_type)
        layout.addLayout(form)
        self.circle_group = QGroupBox('编码圆')
        circle = QFormLayout(self.circle_group)
        self.circle_values = QLabel()
        self.circle_values.setWordWrap(True)
        circle.addRow('当前参数', self.circle_values)
        layout.addWidget(self.circle_group)
        self.board_group = QGroupBox('非对称圆标定板')
        board = QFormLayout(self.board_group)
        board.setContentsMargins(8, 14, 8, 8)
        board.setVerticalSpacing(6)
        board.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.board_spec = QComboBox()
        self.board_spec.setMinimumContentsLength(10)
        self.board_spec.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.board_spec.setToolTip('优先选择板上实际行列数；自动模式会逐一尝试全部规格。')
        self.board_details = QLabel()
        self.board_details.setWordWrap(True)
        self.gamma = ParameterSlider(decimals=2)
        self.gamma.set_range(.1, 10.)
        self.gamma.setMinimumHeight(32)
        self.gamma.setToolTip('优先使用此 Gamma 检测；失败后自动尝试其他亮度，以适应曝光变化。')
        board.addRow('规格', self.board_spec)
        board.addRow(self.board_details)
        board.addRow('Gamma', self.gamma)
        self.board_group.setToolTip('规格按行 × 列显示；圆心间距由三维数据自动估计。Gamma 优先应用，失败时尝试其他亮度。')
        layout.addWidget(self.board_group)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.apply_button = QPushButton('应用识别参数')
        self.apply_button.setMinimumHeight(32)
        self.apply_button.setStyleSheet('min-height:32px;')
        root.addWidget(self.apply_button)
        self.status = QLabel('识别参数可在未连接相机时设置。')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.marker_type.currentIndexChanged.connect(self._changed)
        self.board_spec.currentIndexChanged.connect(self._changed)
        self.gamma.spin.valueChanged.connect(self._changed)
        self.apply_button.clicked.connect(self._apply)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self._update_groups()
        self.setEnabled(False)

    def bind(self, bridge, mode):
        self.bridge = bridge if hasattr(bridge, 'recognition') else None
        self.mode = mode
        self._loaded = None
        self._edited = False
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self):
        ready = bool(self.bridge and not getattr(self.bridge, '_cleaned', False)
                     and self.bridge._current_mode == self.mode)
        self.setEnabled(ready)
        if not ready:
            return
        config = self.bridge.recognition.config(self.mode)
        if config != self._loaded and not self._edited:
            self._load(config)
        self.apply_button.setEnabled(self.bridge.can_change_workspace())

    def _load(self, config):
        for spec in config['boards']:
            if spec not in self._catalog:
                self._catalog.append(copy.deepcopy(spec))
        with QSignalBlocker(self.marker_type), QSignalBlocker(self.board_spec):
            self.marker_type.setCurrentIndex(self.marker_type.findData(config['marker_type']))
            self.board_spec.clear()
            self.board_spec.addItem('自动识别全部规格', copy.deepcopy(self._catalog))
            for spec in self._catalog:
                self.board_spec.addItem(f"{spec['rows']} × {spec['cols']}", [copy.deepcopy(spec)])
            selected = next((i for i in range(self.board_spec.count())
                             if self.board_spec.itemData(i) == config['boards']), None)
            if selected is None:
                self.board_spec.addItem('当前配置的规格组合', copy.deepcopy(config['boards']))
                selected = self.board_spec.count() - 1
            self.board_spec.setCurrentIndex(selected)
            self.gamma.set_value(config['gamma'])
        n, r1, r2 = config['circle']
        self.circle_values.setText(f'N = {n}\nr1 / r0 = {r1:g}\nr2 / r0 = {r2:g}')
        self._loaded = copy.deepcopy(config)
        self._edited = False
        self._update_groups()
        self.status.setText('当前识别参数；修改后点击应用。')

    def _update_groups(self):
        board = self.marker_type.currentData() == 'asymmetric_grid'
        self.circle_group.setVisible(not board)
        self.board_group.setVisible(board)
        specs = self.board_spec.currentData() or []
        details = '\n'.join(f"{spec['rows']} × {spec['cols']} · {spec['rows'] * spec['cols']} 圆心" for spec in specs)
        self.board_details.setToolTip(details)
        self.board_details.setText(details if len(specs) == 1 else
                                   f"自动尝试 {len(specs)} 种规格：" + ' / '.join(
                                       f"{s['rows']}×{s['cols']}" for s in specs))

    def _changed(self, *_):
        self._edited = True
        self._update_groups()
        self.status.setText('参数尚未应用。')

    def _apply(self):
        if not self.bridge:
            return
        # A change in the legacy controls must not silently overwrite new settings.
        if self.bridge.recognition.config(self.mode) != self._loaded:
            self._edited = False
            self.refresh()
            self.status.setText('识别配置已在其他入口变化，已重新读取，请确认后应用。')
            return
        config = self._loaded
        gamma = config['gamma'] if self.gamma.value() == round(config['gamma'], 2) else self.gamma.value()
        try:
            self.bridge.recognition.configure(self.mode, self.marker_type.currentData(),
                                              self.board_spec.currentData(), gamma)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._edited = False
        self.refresh()
        self.status.setText('已应用；原始帧将按新参数后台识别。')
