"""Shared offline-capable recognition settings for all industrial workspaces."""
import copy
from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox,
                              QGroupBox, QLabel, QPushButton, QLayout, QScrollArea,
                              QSpinBox, QDoubleSpinBox)
from core.calib_board_detector import DEFAULT_BOARD_SPECS
from ui_common.parameter_slider import ParameterSlider


class RecognitionParameters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = None
        self.mode = None
        self._loaded = None
        self._edited = False
        self._loading = False
        self._revision = 0
        self._search_cancel = None
        self.apply_timer = QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(250)
        self.apply_timer.timeout.connect(self._apply)
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
        circle.setContentsMargins(8, 14, 8, 8)
        circle.setVerticalSpacing(6)
        self.circle_n = QSpinBox()
        self.circle_n.setRange(1, 32)
        self.circle_r1 = QDoubleSpinBox()
        self.circle_r2 = QDoubleSpinBox()
        for spin in (self.circle_r1, self.circle_r2):
            spin.setRange(.01, 20.)
            spin.setDecimals(2)
            spin.setSingleStep(.1)
        for label, spin in (('N', self.circle_n), ('r1 / r0', self.circle_r1), ('r2 / r0', self.circle_r2)):
            spin.setKeyboardTracking(False)
            circle.addRow(label, spin)
            spin.valueChanged.connect(self._changed)
            spin.lineEdit().textEdited.connect(self._validate_input)
        self.circle_n.setToolTip('整数 N：1～32。')
        for spin in (self.circle_r1, self.circle_r2):
            spin.setToolTip('有限正数，最大20；r2/r0 必须大于 r1/r0。')
        self.auto_button = QPushButton('自动识别')
        self.auto_button.setToolTip('在当前原始图像上搜索有限整数候选；按亮度变化前后稳定检出的编码圆数量选择。')
        self.auto_button.clicked.connect(self._auto_detect)
        circle.addRow(self.auto_button)
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
        self.scroll = scroll
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.status = QLabel('识别参数可在未连接相机时设置。')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.marker_type.currentIndexChanged.connect(self._changed)
        self.board_spec.currentIndexChanged.connect(self._changed)
        self.gamma.spin.valueChanged.connect(self._changed)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self._update_groups()
        self.setEnabled(False)

    def bind(self, bridge, mode):
        self._cancel_search()
        self.apply_timer.stop()
        self._revision += 1
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
        self.apply_timer.stop()
        self._cancel_search()
        self._revision += 1
        self._edited = False
        self._loaded = None
        super().hideEvent(event)

    def refresh(self):
        ready = bool(self.bridge and not getattr(self.bridge, '_cleaned', False)
                     and self.bridge._current_mode == self.mode)
        self.setEnabled(ready)
        if not ready:
            self.apply_timer.stop()
            self._cancel_search()
            return
        config = self.bridge.recognition.config(self.mode)
        if config != self._loaded and not self._edited:
            self._load(config)
        idle = self.bridge.can_change_workspace()
        for control in (self.marker_type, self.board_spec, self.gamma,
                        self.circle_n, self.circle_r1, self.circle_r2):
            control.setEnabled(idle and self._search_cancel is None)
        self.auto_button.setEnabled(idle or self._search_cancel is not None)

    def _load(self, config):
        self._loading = True
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
        for spin, value in zip((self.circle_n, self.circle_r1, self.circle_r2), (n, r1, r2)):
            spin.setValue(value)
        self._loaded = copy.deepcopy(config)
        self._edited = False
        self._loading = False
        self._update_groups()
        self.status.setText('修改后自动应用；无需连接相机。')

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
        if self._loading or self._loaded is None:
            return
        self._revision += 1
        self._cancel_search()
        self._edited = True
        self._update_groups()
        self.status.setText('正在等待参数自动应用…')
        self.apply_timer.start()

    def _apply(self):
        if not self.bridge or not self._edited or getattr(self.bridge, '_cleaned', False):
            return
        if not self._validate_input():
            return
        # A change in the legacy controls must not silently overwrite new settings.
        if self.bridge.recognition.config(self.mode) != self._loaded:
            self._edited = False
            self.refresh()
            self.status.setText('识别配置已在其他入口变化，已重新读取；请重新修改。')
            return
        config = self._loaded
        gamma = config['gamma'] if self.gamma.value() == round(config['gamma'], 2) else self.gamma.value()
        circle = [self.circle_n.value(), self.circle_r1.value(), self.circle_r2.value()]
        for index, spin in enumerate((self.circle_r1, self.circle_r2), 1):
            if circle[index] == round(config['circle'][index], spin.decimals()):
                circle[index] = config['circle'][index]
        if self.marker_type.currentData() != 'coded_circle':
            circle = config['circle']
        try:
            self.bridge.recognition.configure(self.mode, self.marker_type.currentData(),
                                              self.board_spec.currentData(), gamma, circle=circle)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._edited = False
        self.refresh()
        self.status.setText('已自动应用；原始帧将按新参数后台识别。')

    def _validate_input(self, *_):
        if self.marker_type.currentData() == 'coded_circle' and not all(
                spin.hasAcceptableInput() for spin in (self.circle_n, self.circle_r1, self.circle_r2)):
            self.apply_timer.stop()
            self.status.setText('输入无效：N 为 1～32 整数，半径比例为 0～20 内的正数。')
            return False
        return True

    def _cancel_search(self):
        if self._search_cancel is not None:
            self._search_cancel.set()
            self._search_cancel = None
        if hasattr(self, 'auto_button'):
            self.auto_button.setText('自动识别')

    def _auto_detect(self):
        if self._search_cancel is not None:
            self._cancel_search()
            self._revision += 1
            self.status.setText('自动识别已取消，手动参数保持不变。')
            return
        if not self.bridge or self._edited:
            self.status.setText('请等待手动参数自动应用，或修正无效参数后重试。')
            return
        revision, mode = self._revision, self.mode
        def done(result, error):
            if revision != self._revision or mode != self.mode:
                return
            self._search_cancel = None
            self.auto_button.setText('自动识别')
            if error:
                self.refresh()
                self.status.setText(str(error))
                return
            self._loading = True
            for spin, value in zip((self.circle_n, self.circle_r1, self.circle_r2), result['circle']):
                spin.setValue(value)
            self._loading = False
            self._changed()
            self.status.setText(f"稳定检出 {result['stable_count']} 个编码圆，整数参数正在自动应用…")
        try:
            self._search_cancel = self.bridge.recognition.search_current(mode, done)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.auto_button.setText('取消自动识别')
        self.status.setText('正在搜索整数参数，比较不同亮度下的稳定检出…')
        self.refresh()
