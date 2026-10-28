"""Guard numeric parameters against accidental wheel and unfocused key edits."""
from PySide6.QtCore import QObject, QEvent, Qt


class ParameterGuard(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            event.accept()
            return True
        if (event.type() == QEvent.KeyPress and not watched.hasFocus()
                and event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown)):
            event.accept()
            return True
        return False
