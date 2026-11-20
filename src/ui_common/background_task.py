"""GUI-owned task delivery and deterministic native-thread lifetime."""
from PySide6.QtCore import QObject, Slot, Qt
from core.utils import logger
from .worker_thread import WorkerThread


class TaskDelivery(QObject):
    def __init__(self, owner, worker, callback, workers, on_finished, is_active, on_callback_error):
        super().__init__(owner)
        self.worker = worker
        self.callback = callback
        self.workers = workers
        self.on_finished = on_finished
        self.is_active = is_active
        self.on_callback_error = on_callback_error
        worker.result_ready.connect(self.result, Qt.QueuedConnection)
        worker.finished.connect(self.finished, Qt.QueuedConnection)

    @Slot(object, object)
    def result(self, value, error):
        if self.callback is not None and (self.is_active is None or self.is_active()):
            try:
                self.callback(value, error)
            except Exception as exc:
                logger.exception('后台任务结果回填异常')
                if self.on_callback_error is not None:
                    try:
                        self.on_callback_error(exc)
                    except Exception:
                        logger.exception('后台任务失败提示异常')

    @Slot()
    def finished(self):
        worker = self.worker
        if worker is None:
            return
        worker.wait()
        try:
            if worker in self.workers:
                self.workers.remove(worker)
            if self.on_finished is not None:
                self.on_finished()
        except Exception:
            logger.exception('后台任务收尾异常')
        finally:
            worker._func = None
            worker._args = ()
            worker._kwargs = {}
            worker._delivery = None
            worker.deleteLater()
            self.worker = self.callback = self.on_finished = self.is_active = self.on_callback_error = None
            self.workers = None
            self.deleteLater()


def start_background_task(owner, work, callback, *, workers, on_finished=None,
                          is_active=None, name='task', must_finish=False, on_callback_error=None):
    """Start work off-thread, deliver on GUI thread, then join and release closures.

    The caller owns busy/progress presentation and optional project archival.
    is_active suppresses late GUI results without skipping worker cleanup.
    """
    worker = WorkerThread(work)
    worker._task_name = name
    worker._must_finish = must_finish
    workers.append(worker)
    worker._delivery = TaskDelivery(owner, worker, callback, workers, on_finished, is_active, on_callback_error)
    worker.start()
    return worker
