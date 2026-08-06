# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration 入口。

启动流程：
  1. 显示启动小窗口（LauncherWindow）：选择工作模式 + 搜索/连接设备；
  2. 用户确认后关闭小窗口，进入对应模式的主窗口；
  3. 多相机模式复用现有 MainWindow；单相机链式模式使用专用 UI。
"""

import os
import sys

# 保证 src 包可导入（兼容开发环境与 PyInstaller 打包环境）
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后，src 已作为包被包含，无需额外添加路径
    pass
else:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def main():
    from version import get_version

    try:
        from PySide6.QtWidgets import QApplication, QDialog
    except ImportError:
        print("[ERROR] PySide6 未安装，仅 core 模块可用（python test_core.py）")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("MultiCameraCalibration")

    from ui.main_window import MainWindow, STYLESHEET
    from ui.launcher_window import LauncherWindow
    app.setStyleSheet(STYLESHEET)

    # 1. 显示启动小窗口
    launcher = LauncherWindow()
    # 连接启动窗口信号到主窗口设备操作
    main_window = MainWindow()
    launcher.search_requested.connect(main_window._on_refresh_devices)
    launcher.connect_requested.connect(
        lambda indices: (main_window._on_add_cameras(indices), launcher.accept()))
    launcher.auto_ip_requested.connect(
        lambda: main_window._on_auto_configure_network(launcher.selected_devices()))

    # 枚举设备并填充到启动窗口
    main_window._on_refresh_devices()
    launcher.set_devices(main_window._device_descs)

    if launcher.exec() != QDialog.Accepted:
        return 0

    # 2. 根据选中的模式设置主窗口
    mode = launcher.selected_mode()
    if mode == LauncherWindow.MODE_MOBILE_CHAIN:
        # 单相机链式拼接：切换到移动链式页面
        main_window.left_tabs.setCurrentIndex(2)
        main_window.setWindowTitle(
            f"MultiCameraCalibration — 单相机移动链式拼接 {get_version()}")
    else:
        # 多相机模式：默认页面
        main_window.left_tabs.setCurrentIndex(0)
        main_window.setWindowTitle(
            f"MultiCameraCalibration — 多相机外参标定与点云拼接 {get_version()}")

    main_window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
