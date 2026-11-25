from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    progress = Signal(str, int)
    result = Signal(str, object)
    error = Signal(str, str)
    finished = Signal(str)


class Worker(QRunnable):
    def __init__(self, task_id: str, function: Callable, *args, **kwargs) -> None:
        super().__init__()
        self.task_id = task_id
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.function(*self.args, progress=lambda value: self.signals.progress.emit(self.task_id, value), **self.kwargs)
            self.signals.result.emit(self.task_id, result)
        except Exception:
            self.signals.error.emit(self.task_id, traceback.format_exc())
        finally:
            self.signals.finished.emit(self.task_id)


@dataclass
class TaskRecord:
    task_id: str
    name: str
    kind: str
    status: str = "PENDING"
    progress: int = 0


class TaskManager(QObject):
    task_added = Signal(object)
    task_updated = Signal(object)
    log_message = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(4)
        self.records: dict[str, TaskRecord] = {}
        self._workers: dict[str, Worker] = {}

    def submit(self, name: str, kind: str, function: Callable, *args, on_result: Callable | None = None, **kwargs) -> str:
        task_id = uuid.uuid4().hex[:12]
        record = TaskRecord(task_id, name, kind, "RUNNING")
        self.records[task_id] = record
        worker = Worker(task_id, function, *args, **kwargs)
        self._workers[task_id] = worker
        worker.signals.progress.connect(self._progress)
        worker.signals.result.connect(lambda ident, result: self._result(ident, result, on_result))
        worker.signals.error.connect(self._error)
        worker.signals.finished.connect(self._finished)
        self.task_added.emit(record)
        self.log_message.emit("INFO", f"任务已启动：{name}")
        self.pool.start(worker)
        return task_id

    def _progress(self, task_id: str, value: int) -> None:
        record = self.records[task_id]
        record.progress = value
        self.task_updated.emit(record)

    def _result(self, task_id: str, result, callback: Callable | None) -> None:
        record = self.records[task_id]
        record.status = "COMPLETED"
        record.progress = 100
        if callback:
            callback(result)
        self.task_updated.emit(record)
        self.log_message.emit("INFO", f"任务完成：{record.name}")

    def _error(self, task_id: str, details: str) -> None:
        record = self.records[task_id]
        record.status = "FAILED"
        self.task_updated.emit(record)
        self.log_message.emit("ERROR", f"任务失败：{record.name}\n{details}")

    def _finished(self, task_id: str) -> None:
        self._workers.pop(task_id, None)

    def shutdown(self) -> None:
        self.pool.waitForDone(3000)
