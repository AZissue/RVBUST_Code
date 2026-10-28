"""Independent colour parameters; no algorithm or DB side effects."""
from dataclasses import asdict
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QWidget, QScrollArea, QFormLayout,
    QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QDialogButtonBox)
from core.postprocess.color_correction import ColorParameters
from .parameter_guard import ParameterGuard


class ColorDialog(QDialog):
    parameters_changed = Signal(dict)

    def __init__(self, inputs, active_uid=None, state=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('颜色统一参数设置')
        self.setModal(True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(460)
        self.resize(490, 560)
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        form = QFormLayout(panel)
        scroll.setWidget(panel)
        root.addWidget(scroll, 1)
        self.color_inputs = QLabel('预计输入：0 层')
        self.color_inputs.setWordWrap(True)
        form.addRow(self.color_inputs)
        self.color_reference = QComboBox()
        form.addRow('多云参考层', self.color_reference)
        self.color_scale = QDoubleSpinBox()
        self.color_scale.setRange(.01, 1000000)
        self.color_scale.setValue(30)
        self.color_scale.setSuffix(' mm')
        self.color_distance = QDoubleSpinBox()
        self.color_distance.setRange(.001, 10000)
        self.color_distance.setDecimals(3)
        self.color_distance.setValue(2)
        self.color_distance.setSuffix(' mm')
        self.color_strength = QDoubleSpinBox()
        self.color_strength.setRange(0, 100)
        self.color_strength.setValue(60)
        self.color_strength.setSuffix(' %')
        self.color_gain = QDoubleSpinBox()
        self.color_gain.setRange(1, 2)
        self.color_gain.setValue(1.5)
        self.color_samples = QSpinBox()
        self.color_samples.setRange(24, 100000)
        self.color_samples.setValue(20000)
        for label, control in (('单云空间尺度', self.color_scale), ('多云重叠距离', self.color_distance),
                ('校正强度', self.color_strength), ('增益上限（下限为倒数）', self.color_gain),
                ('估计样本上限/层', self.color_samples)):
            form.addRow(label, control)
        self.color_aligned = QCheckBox('多云已处于同一坐标系')
        form.addRow(self.color_aligned)
        hint = QLabel('单云：低频颜色场；多云：重叠区估计。原始未配准多帧请先拼接。\n'
                      '无色/混合输入拒绝；不覆盖来源，不改变XYZ。\n'
                      '仅缓和可估计色差，可能影响真实材质；不是摄影测量级真彩还原。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        form.addRow('参数回显', self.summary)
        self.validation = QLabel()
        self.validation.setWordWrap(True)
        self.validation.setStyleSheet('color: #e58b8b;')
        form.addRow(self.validation)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.execute_button = self.buttons.button(QDialogButtonBox.Ok)
        self.execute_button.setText('执行颜色统一')
        self.execute_button.setAutoDefault(False)
        self.cancel_button = self.buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setText('取消')
        self.cancel_button.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        state = dict(state or {})
        for uid, name, count in inputs:
            self.color_reference.addItem(name, uid)
        preferred = state.get('reference')
        if preferred not in [entry[0] for entry in inputs]:
            preferred = active_uid
        self.color_reference.setCurrentIndex(max(0, self.color_reference.findData(preferred)))
        self.color_inputs.setText(f'预计输入：{len(inputs)} 层，{sum(x[2] for x in inputs):,} 点 · ' +
                                 ('单云空间校正' if len(inputs) == 1 else '多云重叠匹配'))
        self.color_reference.setEnabled(len(inputs) > 1)
        self.color_aligned.setEnabled(len(inputs) > 1)
        self.color_scale.setEnabled(len(inputs) == 1)
        self.color_distance.setEnabled(len(inputs) > 1)
        self.color_aligned.setChecked(state.get('aligned', False))
        self._guard = ParameterGuard(self)
        for key, control in (('scale', self.color_scale), ('overlap_distance', self.color_distance),
                ('strength', self.color_strength), ('max_gain', self.color_gain), ('sample_limit', self.color_samples)):
            if key in state:
                control.setValue(state[key] * 100 if key == 'strength' else state[key])
            control.setFocusPolicy(Qt.StrongFocus)
            control.installEventFilter(self._guard)
            control.valueChanged.connect(self._updated)
        self.color_gain.setSingleStep(.05)
        self.color_samples.setSingleStep(1000)
        self.color_reference.currentIndexChanged.connect(self._updated)
        self.color_aligned.toggled.connect(self._updated)
        self._input_count = len(inputs)
        self._updated()

    def parameters(self):
        return dict(scale=self.color_scale.value(), strength=self.color_strength.value()/100,
            max_gain=self.color_gain.value(), sample_limit=self.color_samples.value(),
            overlap_distance=self.color_distance.value(), reference=self.color_reference.currentData(),
            aligned=self.color_aligned.isChecked())

    def _updated(self, *_):
        state = self.parameters()
        params = ColorParameters(**{key: state[key] for key in asdict(ColorParameters()) if key in state})
        self.summary.setText(f'尺度={params.scale:g}mm，强度={params.strength:.0%}，上限={params.max_gain:g}，'
                             f'样本上限={params.sample_limit}，重叠距离={params.overlap_distance:g}mm')
        error = ''
        try:
            params.validate()
            if not self._input_count:
                error = '请先显示至少一项有色点云。'
            elif self._input_count > 1 and not state['aligned']:
                error = '请确认多云已处于同一坐标系。'
        except ValueError as exc:
            error = str(exc)
        self.validation.setText(error)
        self.execute_button.setEnabled(not error)
        self.parameters_changed.emit(state)

    def accept(self):
        self._updated()
        if self.execute_button.isEnabled():
            super().accept()
