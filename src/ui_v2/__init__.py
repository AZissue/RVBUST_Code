# -*- coding: utf-8 -*-
"""
ui_v2 —— 拼接软件新 UI 空壳（Shell）。

定位：
  - 仅包含 UI 层：窗口、布局、控件、信号与状态接口；
  - **不含任何业务逻辑**，所有与 src/core、Workflow、PyRVC 的交互点
    均以 Qt 信号 + ``# TODO(BACKEND):`` 标记留出接口；
  - 可完全离线运行（无相机、无 PyRVC、无 OpenGL），便于先评审交互与视觉。

对外入口（对外名不变，但自 Phase 0 起为**惰性导出**）：
  - theme.GLOBAL_QSS                 全局 QSS
  - launcher_dialog.LauncherDialog   启动小窗（模式选择 + 设备管理）
  - main_window.MainWindowShell      主窗口（工作区 QStackedWidget 框架）

⚠️ Phase 0（原型 UI 复用主程序拆分批）：原先的 eager 重导出会让
`from ui_v2.theme import GLOBAL_QSS` 连带拉起 launcher_dialog → main_window
→ workspaces → ui.viewer_3d（open3d）整条链（2057 模块 / ~2.1s）。
现改 PEP 562 `__getattr__` 惰性导出：`from ui_v2 import GLOBAL_QSS` 对外行为不变。

⚠️ PyInstaller：`__getattr__` 对静态分析不安全（详见旧 UI 解耦方案 v2），
`MultiCameraCalibration.spec` 已同步补 `collect_submodules('ui')` / `collect_submodules('ui_v2')`。
新增导出名时**两处都要改**。
"""

from importlib import import_module as _import_module

# 对外名 -> 定义模块（相对包名）
_LAZY_EXPORTS = {
    "GLOBAL_QSS": ".theme",
    "LauncherDialog": ".launcher_dialog",
    "MainWindowShell": ".main_window",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name):
    """惰性导出：首次访问时才导入定义模块，并缓存到本模块 globals。"""
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
