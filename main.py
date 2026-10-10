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

# 原生层崩溃（如 SDK 堆损坏 0xc0000374）导致进程终止时，把全部线程的
# Python 栈写入专用文件，为事后定位保留完整现场（控制台输出易丢失，
# 因此始终写文件；stderr 可用时同时输出）。
try:
    import faulthandler
    _faulthandler_file = open("faulthandler_crash.log", "a", buffering=1)
    faulthandler.enable(_faulthandler_file)
    if sys.stderr is not None:
        faulthandler.enable()
except Exception:
    pass


# 保证 src 包可导入（兼容开发环境与 PyInstaller 打包环境）
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后，src 已作为包被包含，无需额外添加路径
    pass
else:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def main():
    from version import get_version

    try:
        from PySide6.QtCore import QPropertyAnimation
        from PySide6.QtWidgets import QApplication, QDialog
    except ImportError:
        print("[ERROR] PySide6 未安装，仅 core 模块可用（python test_core.py）")
        return 1

    from core.utils import logger
    logger.info(f"MultiCameraCalibration 启动，版本: {get_version()}")

    app = QApplication(sys.argv)
    app.setApplicationName("MultiCameraCalibration")

    # 使用 ui_v2 主题
    from ui_v2 import GLOBAL_QSS, LauncherDialog, MainWindowShell
    from ui_v2.backend_bridge import BackendBridge
    app.setStyleSheet(GLOBAL_QSS)

    # 1. 显示启动小窗
    launcher = LauncherDialog()

    # 创建主窗口（但不显示）
    main_window = MainWindowShell()
    bridge = BackendBridge(main_window)
    bridge.wire_all()
    main_window.set_backend_bridge(bridge)

    # 连接启动小窗信号
    def on_refresh():
        """刷新设备列表。"""
        launcher.set_devices(bridge.enumerate_devices())

    def on_connect(mode: str, devices: list):
        """连接设备。

        在启动小窗上显示遮罩，后台连接相机；连接完成后平滑切换到主窗口。
        """
        launcher.show_connection_overlay("正在连接相机...")
        ordered = BackendBridge.get_ordered_devices(devices)
        bridge._on_device_manager_reopened(mode, ordered, show_loading=False)

    def on_connection_finished(success: bool, message: str):
        """相机连接完成：先渲染主窗口，再让小窗淡出关闭。"""
        # 设备管理重连时，bridge 会再次发射 connection_finished；
        # 这里只响应初始启动小窗的连接结果，避免旧回调把模式刷回初始状态。
        if not launcher.isVisible():
            return
        if not success:
            launcher.hide_connection_overlay()
            return
        mode = launcher.selected_mode()
        devices = BackendBridge.get_ordered_devices(launcher.selected_devices())
        main_window.set_mode(mode, devices)
        main_window.setWindowTitle(
            f"RVC 拼接工作站 — {LauncherDialog.MODE_NAMES[mode]} {get_version()}")

        # 主窗口从透明淡入，同时直接关闭启动小窗，避免小窗淡出时闪一下
        main_window.setWindowOpacity(0.0)
        main_window.show()
        fade_in = QPropertyAnimation(main_window, b"windowOpacity")
        fade_in.setDuration(200)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.start()
        # 保持动画引用，防止被 Python GC 销毁
        main_window._fade_in_animation = fade_in
        launcher.accept()

    def on_auto_ip(devices: list):
        """自动配置 IP（后台执行，防止 UI 卡住）。"""
        launcher.set_auto_ip_busy(True)

        def on_finished(_results, _error):
            if not launcher.isVisible():
                return
            launcher.set_auto_ip_busy(False)
            # IP 可能已变化，刷新列表
            launcher.set_devices(bridge.enumerate_devices())

        bridge.auto_configure_network(devices, on_finished=on_finished)

    launcher.refresh_requested.connect(on_refresh)
    launcher.connect_requested.connect(on_connect)
    launcher.auto_ip_requested.connect(on_auto_ip)
    bridge.connection_finished.connect(on_connection_finished)
    # 事件循环退出前统一收口清理（此时事件循环仍可处理线程退出信号）
    app.aboutToQuit.connect(bridge.cleanup)

    # 初始枚举设备
    on_refresh()

    exit_code = 0
    try:
        if launcher.exec() != QDialog.Accepted:
            return 0  # 取消小窗的早退路径：finally 仍会跑 cleanup

        # 2. 工作区切换与小窗关闭已在 on_connection_finished 中完成

        # 3. 运行
        exit_code = app.exec()
        return exit_code
    finally:
        # 4. 清理资源。cleanup 幂等（aboutToQuit 可能已跑过）；
        # pending 非空 = 有 A 类任务超时未结束：warning 已落盘，os._exit 直接
        # 终止进程（不受 return 影响），避免 QThread 运行中析构 __fastfail。
        if bridge.cleanup():
            os._exit(exit_code)


if __name__ == "__main__":
    sys.exit(main())
