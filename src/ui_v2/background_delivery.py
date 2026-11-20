"""Compatibility adapter; production tasks use ui_common.background_task."""
from ui_common.background_task import TaskDelivery


class BackgroundDelivery(TaskDelivery):
    def __init__(self, bridge, worker, callback):
        super().__init__(bridge, worker, callback, bridge._workers,
                         bridge._on_worker_thread_finished,
                         lambda: not getattr(bridge, '_cleaned', False), None)
