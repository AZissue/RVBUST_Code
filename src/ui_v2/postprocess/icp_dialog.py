"""Pairwise ICP parameter entry, sharing industrial styling and wheel guards."""
from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox, QLabel, QDialogButtonBox
from .parameter_guard import ParameterGuard
from ..dialogs import localize_buttons
from core.postprocess.icp_registration import ICPParameters

class ICPDialog(QDialog):
    def __init__(self, inputs, parent=None):
        super().__init__(parent)
        self.setWindowTitle('ICP精配准 · 两项点云')
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.reference = QComboBox()
        for uid, name in inputs:
            self.reference.addItem(name, uid)
        form.addRow('固定参考', self.reference)
        self.distance = QDoubleSpinBox(); self.distance.setRange(.001,1000); self.distance.setDecimals(3); self.distance.setValue(2); self.distance.setSuffix(' mm')
        self.voxel = QDoubleSpinBox(); self.voxel.setRange(.001,1000); self.voxel.setDecimals(3); self.voxel.setValue(1); self.voxel.setSuffix(' mm')
        self.iterations = QSpinBox(); self.iterations.setRange(1,500); self.iterations.setValue(50)
        self.overlap = QDoubleSpinBox(); self.overlap.setRange(1,100); self.overlap.setValue(30); self.overlap.setSuffix(' %')
        for text, control in [('最大对应距离',self.distance),('计算体素',self.voxel),('最大迭代次数',self.iterations),('最小重叠率',self.overlap)]:
            form.addRow(text,control)
        note = QLabel('另一项点云将移动到参考坐标系。两项须已粗略对齐；ICP可能在大平面或重复结构上误配准。计算体素仅用于加速，输出保留全部有效点和颜色。完成后新增移动点云结果，请勾选结果与参考对比，需要时再合并。')
        note.setWordWrap(True); form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        localize_buttons(buttons); buttons.button(QDialogButtonBox.Ok).setText('执行精配准')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); form.addRow(buttons)
        self.guard = ParameterGuard(self)
        for control in (self.reference,self.distance,self.voxel,self.iterations,self.overlap):
            control.installEventFilter(self.guard)

    def parameters(self):
        return self.reference.currentData(), ICPParameters(self.distance.value(),self.voxel.value(),self.iterations.value(),self.overlap.value()/100)
