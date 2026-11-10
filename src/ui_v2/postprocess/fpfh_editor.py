from PySide6.QtWidgets import QToolButton
from .window import PostprocessWindow

class FPFHEditor(PostprocessWindow):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        button=QToolButton();button.setText('FPFH几何匹配');button.clicked.connect(self.open_fpfh)
        self.operation_bar.layout().insertWidget(1,button)
        self.fpfh_button=button
    def request_fpfh(self):
        """Wait for a selected DB preview to finish before opening parameters."""
        from PySide6.QtCore import QTimer
        if self._closed or getattr(self, '_fpfh_pending', False):
            return
        self._fpfh_pending = True
        def ready():
            if self._closed:
                self._fpfh_pending = False
                return
            if self._worker is not None:
                QTimer.singleShot(20, ready)
                return
            self._fpfh_pending = False
            self.open_fpfh()
        QTimer.singleShot(0, ready)

    def open_fpfh(self):
        if not self._parameter_gate():return
        from .fpfh_dialog import FPFHDialog
        dialog=FPFHDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()
