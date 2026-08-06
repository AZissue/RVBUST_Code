# -*- coding: utf-8 -*-
"""
ui_v2 —— 拼接软件新 UI 空壳（Shell）。

定位：
  - 仅包含 UI 层：窗口、布局、控件、信号与状态接口；
  - **不含任何业务逻辑**，所有与 src/core、Workflow、PyRVC 的交互点
    均以 Qt 信号 + ``# TODO(BACKEND):`` 标记留出接口；
  - 可完全离线运行（无相机、无 PyRVC、无 OpenGL），便于先评审交互与视觉。

对外入口：
  - launcher_dialog.LauncherDialog   启动小窗（模式选择 + 设备管理）
  - main_window.MainWindowShell      主窗口（双工作区 QStackedWidget 框架）
  - run_shell.py                     离线演示入口（mock 设备数据）

接入说明见同目录 README.md。
"""

from .theme import GLOBAL_QSS
from .launcher_dialog import LauncherDialog
from .main_window import MainWindowShell

__all__ = ["GLOBAL_QSS", "LauncherDialog", "MainWindowShell"]
