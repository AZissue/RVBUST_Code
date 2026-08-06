# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration 入口。

启动流程：
  1. 显示启动小窗（LauncherDialog）：选择工作模式 + 搜索/连接设备；
  2. 用户确认后关闭小窗，进入对应模式的主窗口（MainWindowShell）；
  3. 多相机模式复用现有三栏布局；单相机链式模式使用整页新 UI。
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

    # 使用 ui_v2 主题
    from ui_v2 import GLOBAL_QSS, LauncherDialog, MainWindowShell
    from ui_v2.backend_bridge import BackendBridge
    from ui_v2.widgets.device_table import DeviceInfo
    app.setStyleSheet(GLOBAL_QSS)

    # 1. 显示启动小窗
    launcher = LauncherDialog()

    # 创建主窗口（但不显示）
    main_window = MainWindowShell()
    bridge = BackendBridge(main_window)
    bridge.wire_all()

    # 连接启动小窗信号
    def on_refresh():
        """刷新设备列表。"""
        from core.camera_manager import SingleCameraController
        probe = SingleCameraController("probe")
        devices = probe.find_devices()
        device_infos = []
        for i, dev in enumerate(devices):
            try:
                ret, info = dev.GetDeviceInfo()
                if ret:
                    device_infos.append(DeviceInfo(
                        model=info.name,
                        serial=info.sn,
                        ip=getattr(info, 'ip', ''),
                        online=True,
                        backend_ref=i,  # 设备索引
                    ))
            except Exception:
                pass
        launcher.set_devices(device_infos)

    def on_connect(mode: str, devices: list):
        """连接设备。"""
        bridge._on_device_manager_reopened(mode, devices)
        launcher.accept()

    def on_auto_ip(devices: list):
        """自动配置 IP。"""
        indices = [d.backend_ref for d in devices if isinstance(d.backend_ref, int)]
        bridge.camera_manager.auto_configure_network(indices)

    launcher.refresh_requested.connect(on_refresh)
    launcher.connect_requested.connect(on_connect)
    launcher.auto_ip_requested.connect(on_auto_ip)

    # 初始枚举设备
    on_refresh()

    if launcher.exec() != QDialog.Accepted:
        return 0

    # 2. 根据选中的模式设置主窗口
    mode = launcher.selected_mode()
    devices = launcher.selected_devices()
    main_window.set_mode(mode, devices)
    main_window.setWindowTitle(
        f"RVC 拼接工作站 — {LauncherDialog.MODE_NAMES[mode]} {get_version()}")
    main_window.show()

    # 3. 运行
    exit_code = app.exec()

    # 4. 清理资源
    bridge.cleanup()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
