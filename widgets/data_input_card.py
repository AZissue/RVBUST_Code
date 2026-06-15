"""
单个数据输入卡片组件。
紧凑单行布局：状态指示灯 + 标签 + 输入框 + 复制按钮。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QApplication,
    QSizePolicy,
)

import resources as res


class DataInputCard(QWidget):
    """数据输入卡片：标签和输入框在同一行的紧凑控件"""

    value_changed = pyqtSignal(str)

    def __init__(self, card_id, label_text, hint_text, parent=None):
        super().__init__(parent)
        self._card_id = card_id

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(f"""
            DataInputCard {{
                background-color: {res.BG_CARD};
                border-radius: 4px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # 状态指示灯
        self._dot = QLabel()
        self._dot.setFixedSize(6, 6)
        self._dot.setStyleSheet(f"""
            background-color: {res.BORDER_DEFAULT};
            border-radius: 3px;
            border: none;
        """)
        layout.addWidget(self._dot, alignment=Qt.AlignVCenter)

        # 标签
        self._label = QLabel(label_text)
        self._label.setFixedWidth(130)
        self._label.setStyleSheet(
            f"font-size: {res.FONT_BODY}px; font-weight: 600; "
            f"color: {res.TEXT_TITLE}; border: none;"
        )
        layout.addWidget(self._label, alignment=Qt.AlignVCenter)

        # 输入框
        self._input = QLineEdit()
        self._input.setPlaceholderText(hint_text)
        self._input.setStyleSheet(res.input_style())
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input, 1)

        # 复制按钮
        btn_copy = QPushButton("复制")
        btn_copy.setFixedSize(40, 24)
        btn_copy.setStyleSheet(f"""
            QPushButton {{
                background-color: {res.BG_MAIN};
                color: {res.PRIMARY};
                border: 1px solid {res.PRIMARY};
                border-radius: 4px;
                font-size: {res.FONT_HINT}px;
            }}
            QPushButton:hover {{
                background-color: {res.PRIMARY_LIGHT};
            }}
        """)
        btn_copy.clicked.connect(self._on_copy)
        layout.addWidget(btn_copy, alignment=Qt.AlignVCenter)

    def _on_text_changed(self, text):
        self.set_status("ok" if text.strip() else "empty")
        self.value_changed.emit(text)

    def _on_copy(self):
        QApplication.clipboard().setText(self._input.text())

    def set_value(self, text):
        self._input.blockSignals(True)
        self._input.setText(text)
        self._input.blockSignals(False)

    def get_value(self):
        return self._input.text().strip()

    def set_status(self, status):
        colors = {"empty": res.BORDER_DEFAULT, "ok": res.SUCCESS, "error": res.ERROR}
        self._dot.setStyleSheet(f"""
            background-color: {colors.get(status, res.BORDER_DEFAULT)};
            border-radius: 3px;
            border: none;
        """)
        if status == "error":
            self._input.setStyleSheet(res.input_error_style())
        else:
            self._input.setStyleSheet(res.input_style())

    def set_visible(self, visible):
        self.setVisible(visible)

    def card_id(self):
        return self._card_id
