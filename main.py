# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration 入口。

Phase 3：启动完整 UI（QApplication + MainWindow）。
core 模块可独立测试：python test_core.py；UI 测试：python test_ui.py。
"""

import os
import sys

# 保证 src 包可导入
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def main():
    from version import get_version

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("[ERROR] PySide6 未安装，仅 core 模块可用（python test_core.py）")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("MultiCameraCalibration")

    from ui.main_window import MainWindow, STYLESHEET
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.setWindowTitle(
        f"MultiCameraCalibration — 多相机外参标定与点云拼接 {get_version()}")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
