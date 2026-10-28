"""Independent parameter dialog for postprocess downsampling."""
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
)

from ..dialogs import localize_buttons
from .parameter_guard import ParameterGuard


class DownsampleDialog(QDialog):
    """Collect parameters only; the owner retains the existing commit pipeline."""

    parameters_changed = Signal(dict)

    def __init__(self, layer_name='', point_count=0, state=None, parent=None):
        super().__init__(parent)
        self.point_count = int(point_count)
        self.setWindowTitle('下采样参数设置')
        self.setModal(True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(410)

        form = QFormLayout(self)
        self.method = QComboBox()
        self.method.addItem('体素下采样', 'voxel')
        self.method.addItem('随机抽样', 'random')
        form.addRow('下采样方法', self.method)
        self.voxel = QDoubleSpinBox()
        self.voxel.setRange(.01, 100000)
        self.voxel.setValue(2)
        self.voxel.setSuffix(' mm')
        self.voxel.setSingleStep(.1)
        form.addRow('体素尺寸', self.voxel)
        self.ratio = QDoubleSpinBox()
        self.ratio.setRange(.1, 100)
        self.ratio.setValue(50)
        self.ratio.setSuffix(' %')
        self.ratio.setSingleStep(1)
        form.addRow('随机保留', self.ratio)
        self.inputs = QLabel(f'输入：{layer_name or "未选择点云"}，{self.point_count:,} 点')
        self.inputs.setWordWrap(True)
        form.addRow(self.inputs)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        form.addRow('参数回显', self.summary)
        self.validation = QLabel()
        self.validation.setWordWrap(True)
        self.validation.setStyleSheet('color: #e58b8b;')
        form.addRow(self.validation)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        localize_buttons(self.buttons)
        self.execute_button = self.buttons.button(QDialogButtonBox.Ok)
        self.execute_button.setText('执行下采样')
        self.execute_button.setAutoDefault(False)
        self.cancel_button = self.buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

        self._parameter_guard = ParameterGuard(self)
        for control in (self.voxel, self.ratio):
            control.setFocusPolicy(Qt.StrongFocus)
            control.installEventFilter(self._parameter_guard)
            control.valueChanged.connect(self._parameters_updated)
        self.method.currentIndexChanged.connect(self._parameters_updated)
        if state:
            index = self.method.findData(state.get('method', 'voxel'))
            self.method.setCurrentIndex(max(0, index))
            self.voxel.setValue(state.get('voxel', 2))
            self.ratio.setValue(state.get('ratio', 50))
        self._parameters_updated()

    def parameters(self):
        return {
            'method': self.method.currentData(),
            'voxel': self.voxel.value(),
            'ratio': self.ratio.value(),
        }

    def _parameters_updated(self, *_):
        method = self.method.currentData()
        self.voxel.setEnabled(method == 'voxel')
        self.ratio.setEnabled(method == 'random')
        error = ''
        if not self.point_count:
            error = '当前没有可下采样的点云。'
        elif method == 'voxel':
            value = self.voxel.value()
            if not math.isfinite(value) or not .01 <= value <= 100000:
                error = '体素尺寸必须在 0.01–100000 mm 范围内。'
            else:
                self.summary.setText(f'体素尺寸：{value:g} mm；结果点数以下采样计算为准。')
        else:
            value = self.ratio.value()
            if not math.isfinite(value) or not .1 <= value <= 100:
                error = '随机保留比例必须在 0.1–100% 范围内。'
            else:
                count = int(round(self.point_count * value / 100))
                self.summary.setText(f'随机保留：{value:g} %；预计输出：{count:,} 点。')
                if count < 1:
                    error = '预计输出为 0 点，请提高随机保留比例。'
        self.validation.setText(error)
        self.execute_button.setEnabled(not error)
        self.parameters_changed.emit(self.parameters())
