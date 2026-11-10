from PySide6.QtWidgets import QToolButton
from ui_v2.postprocess.window import PostprocessWindow

class FPFHEditor(PostprocessWindow):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        button=QToolButton();button.setText('FPFH几何匹配');button.clicked.connect(self.open_fpfh)
        self.operation_bar.layout().insertWidget(1,button)
        self.fpfh_button=button
    def open_fpfh(self):
        if not self._parameter_gate():return
        from .dialog import FPFHDialog
        dialog=FPFHDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()
