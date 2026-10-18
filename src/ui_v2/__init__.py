"""MCC v2 presentation. Public exports are lazy to keep theme/config imports light.

ui_common owns renderers, image conversion, icons and worker primitives.
ui_v2 owns application layouts and semantic wiring; it never imports legacy ui.
PyInstaller explicitly collects ui_v2 and ui_common for lazy factory imports.
"""

from importlib import import_module as _import_module

# 对外名 -> 定义模块（相对包名）
_LAZY_EXPORTS = {
    "GLOBAL_QSS": ".theme",
    "LauncherDialog": ".launcher_dialog",
    "MainWindowShell": ".main_window",
    "UiComposition": ".composition",
    "WorkspaceFactories": ".composition",
    "UiComponents": ".components",
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
