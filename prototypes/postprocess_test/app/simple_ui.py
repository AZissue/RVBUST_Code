# -*- coding: utf-8 -*-
"""
后处理原型独立运行入口。

使用方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/postprocess_test/app/simple_ui.py
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

# 让原型能引用 src/ 下的模块
_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if os.path.join(_SRC_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_SRC_ROOT, "src"))

from ui_v2.theme import GLOBAL_QSS
from postprocess_workspace import PostprocessWorkspace


class PostprocessWindow(QMainWindow):
    """独立运行外壳。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("点云后处理原型（ui_v2 工作区）")
        self.resize(1500, 950)

        central = QWidget()
        self.setCentralWidget(central)
        lo = QVBoxLayout(central)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self.workspace = PostprocessWorkspace()
        lo.addWidget(self.workspace)

        # 居中
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    win = PostprocessWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
