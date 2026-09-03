# -*- coding: utf-8 -*-
"""
CloudCompare-Like 后处理原型 — 独立运行入口。

使用方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/cloudcompare_like/app/main.py
"""

from __future__ import annotations

import os
import sys

# 让原型能引用 src/ 下的模块
_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if os.path.join(_SRC_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_SRC_ROOT, "src"))

from ui_v2.theme import GLOBAL_QSS
from cc_workspace import CloudCompareWindow

from PySide6.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    win = CloudCompareWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
