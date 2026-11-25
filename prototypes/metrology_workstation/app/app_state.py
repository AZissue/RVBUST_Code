from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AppState(QObject):
    module_changed = Signal(str)
    mode_changed = Signal(str)
    project_changed = Signal(str)
    save_state_changed = Signal(bool)

    MODULES = ("项目", "数据采集", "三维重建", "模型封装", "CAD 对比", "尺寸测量", "检测报告")

    def __init__(self) -> None:
        super().__init__()
        self.current_module = "项目"
        self.mode = "工作站"
        self.project_name = "PRJ-2026-0148"
        self.project_path = ""
        self.saved = True

    def set_module(self, module: str) -> None:
        if module not in self.MODULES or module == self.current_module:
            return
        self.current_module = module
        self.module_changed.emit(module)

    def set_mode(self, mode: str) -> None:
        if mode not in ("工作站", "工程师") or mode == self.mode:
            return
        self.mode = mode
        self.mode_changed.emit(mode)

    def set_project(self, name: str, path: str = "") -> None:
        self.project_name = name
        self.project_path = path
        self.saved = True
        self.project_changed.emit(name)
        self.save_state_changed.emit(True)

    def mark_saved(self, saved: bool) -> None:
        if saved == self.saved:
            return
        self.saved = saved
        self.save_state_changed.emit(saved)
