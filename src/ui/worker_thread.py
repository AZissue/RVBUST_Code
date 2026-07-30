# -*- coding: utf-8 -*-
"""
后台工作线程（WorkerThread）—— 把耗时操作放到后台执行，避免阻塞 UI。

使用方式：
    def _on_heavy(self):
        self._show_loading("处理中...")
        self._worker = WorkerThread(self._heavy_impl)
        self._worker.finished.connect(self._on_heavy_done)
        self._worker.start()

    def _on_heavy_done(self, result, error):
        self._hide_loading()
        if error:
            self._log(f"[ERROR] {error}")
        else:
            ...
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal


class WorkerThread(QThread):
    """通用后台工作线程。"""

    finished = Signal(object, object)  # (result, error)

    def __init__(self, func: Callable, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result, None)
        except Exception as e:
            self.finished.emit(None, e)


def run_in_background(parent, func: Callable, on_done: Callable,
                      *args, **kwargs) -> WorkerThread:
    """便捷方法：在后台执行 func，完成后调用 on_done(result, error)。

    on_done 签名: on_done(result, error)
    """
    worker = WorkerThread(func, *args, **kwargs)
    worker.finished.connect(on_done)
    worker.start()
    return worker
