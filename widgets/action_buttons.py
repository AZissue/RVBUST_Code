"""
操作按钮栏组件。
包含四个操作按钮：拍照、识别、保存、清除上一组。
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSizePolicy

import resources as res


class ActionButtons(QWidget):
    """底部操作按钮栏"""

    capture_clicked = pyqtSignal()   # 拍照按钮
    detect_clicked = pyqtSignal()    # 识别按钮
    save_clicked = pyqtSignal()      # 保存按钮
    undo_clicked = pyqtSignal()      # 清除上一组按钮
    load_test_clicked = pyqtSignal() # 加载测试数据（临时）按钮

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addStretch()

        self._btn_load_test = QPushButton("加载测试")
        self._btn_load_test.setStyleSheet(f"""
            QPushButton {{
                background-color: {res.BG_MAIN};
                color: {res.WARNING};
                border: 1px dashed {res.WARNING};
                border-radius: {res.BORDER_RADIUS}px;
                padding: 0 16px;
                font-size: {res.FONT_HINT}px;
                height: 32px;
            }}
        """)
        self._btn_load_test.clicked.connect(self.load_test_clicked.emit)
        layout.addWidget(self._btn_load_test)

        self._btn_capture = QPushButton("拍照")
        self._btn_capture.setStyleSheet(res.primary_button_style())
        self._btn_capture.clicked.connect(self.capture_clicked.emit)
        layout.addWidget(self._btn_capture)

        self._btn_detect = QPushButton("识别")
        self._btn_detect.setStyleSheet(res.secondary_emphasis_button_style())
        self._btn_detect.clicked.connect(self.detect_clicked.emit)
        layout.addWidget(self._btn_detect)

        self._btn_save = QPushButton("保存")
        self._btn_save.setStyleSheet(res.secondary_button_style())
        self._btn_save.clicked.connect(self.save_clicked.emit)
        layout.addWidget(self._btn_save)

        self._btn_undo = QPushButton("清除上一组")
        self._btn_undo.setStyleSheet(res.danger_button_style())
        self._btn_undo.clicked.connect(self.undo_clicked.emit)
        layout.addWidget(self._btn_undo)

        layout.addStretch()

    def set_detect_enabled(self, enabled):
        self._btn_detect.setEnabled(enabled)

    def set_save_enabled(self, enabled):
        self._btn_save.setEnabled(enabled)

    def set_undo_enabled(self, enabled):
        self._btn_undo.setEnabled(enabled)
