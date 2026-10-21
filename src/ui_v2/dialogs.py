"""Chinese labels independent of the host Qt/system language."""
from PySide6.QtWidgets import QMessageBox as QtMessageBox


def localize_buttons(box):
    enum = QtMessageBox if isinstance(box, QtMessageBox) else type(box)
    for name, text in dict(Save='保存', Discard='放弃修改', Cancel='取消',
            Ok='确定', Yes='是', No='否', Close='关闭', Retry='重试').items():
        flag = getattr(enum, name, None)
        button = box.button(flag) if flag is not None else None
        if button:
            button.setText(text)


class ChineseMessageBox(QtMessageBox):
    @staticmethod
    def _show(icon, parent, title, text, buttons, default):
        box = ChineseMessageBox(icon, title, text, buttons, parent)
        localize_buttons(box)
        if default != QtMessageBox.NoButton:
            box.setDefaultButton(default)
        return QtMessageBox.StandardButton(box.exec())

    @staticmethod
    def warning(parent, title, text, buttons=QtMessageBox.Ok, defaultButton=QtMessageBox.NoButton):
        return ChineseMessageBox._show(QtMessageBox.Warning, parent, title, text, buttons, defaultButton)

    @staticmethod
    def question(parent, title, text, buttons=QtMessageBox.Yes | QtMessageBox.No, defaultButton=QtMessageBox.NoButton):
        return ChineseMessageBox._show(QtMessageBox.Question, parent, title, text, buttons, defaultButton)

    @staticmethod
    def information(parent, title, text, buttons=QtMessageBox.Ok, defaultButton=QtMessageBox.NoButton):
        return ChineseMessageBox._show(QtMessageBox.Information, parent, title, text, buttons, defaultButton)

    @staticmethod
    def critical(parent, title, text, buttons=QtMessageBox.Ok, defaultButton=QtMessageBox.NoButton):
        return ChineseMessageBox._show(QtMessageBox.Critical, parent, title, text, buttons, defaultButton)
