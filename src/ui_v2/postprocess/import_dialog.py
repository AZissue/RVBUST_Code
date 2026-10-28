"""Import units are collected before the existing file chooser."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QLabel, QDialogButtonBox


class ImportDialog(QDialog):
    unit_changed = Signal(str)

    def __init__(self, unit='mm', parent=None):
        super().__init__(parent)
        self.setWindowTitle('导入点云参数设置')
        self.setModal(True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(410)
        form = QFormLayout(self)
        self.file_unit = QComboBox()
        self.file_unit.addItem('毫米 mm', 'mm')
        self.file_unit.addItem('米 m（载入后转为 mm）', 'm')
        self.file_unit.setCurrentIndex(max(0, self.file_unit.findData(unit)))
        form.addRow('源文件单位', self.file_unit)
        hint = QLabel('确认源文件单位后选择文件。支持 PLY、PCD、XYZ、PTS；导入生成独立 DB 结果，保留源文件。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.execute_button = self.buttons.button(QDialogButtonBox.Ok)
        self.execute_button.setText('选择文件…')
        self.execute_button.setAutoDefault(False)
        self.cancel_button = self.buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setText('取消')
        self.cancel_button.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.file_unit.currentIndexChanged.connect(lambda: self.unit_changed.emit(self.unit()))

    def unit(self):
        return self.file_unit.currentData()
