"""GUI-owned delivery for bridge tasks, including queued shutdown completions."""
from PySide6.QtCore import QObject, Slot, Qt


class BackgroundDelivery(QObject):
    """Keep callback ownership explicit until QThread has really finished.

    A Python lambda connected to finished can retain an entire closed workspace.
    Bound QObject slots give queued events a GUI receiver and let us drop those
    closures deterministically, rather than leaving Qt wrappers in GC cycles.
    """

    def __init__(self, bridge, worker, callback):
        super().__init__(bridge)
        self._bridge = bridge
        self._worker = worker
        self._callback = callback
        worker.result_ready.connect(self.result, Qt.QueuedConnection)
        worker.finished.connect(self.finished, Qt.QueuedConnection)

    @Slot(object, object)
    def result(self, value, error):
        if self._callback is not None and not getattr(self._bridge, '_cleaned', False):
            self._callback(value, error)

    @Slot()
    def finished(self):
        worker = self._worker
        if worker is None:
            return
        # QThread.finished is emitted before native thread-local cleanup ends.
        # Join before releasing callable closures and scheduling Qt destruction.
        worker.wait()
        try:
            self._bridge._on_worker_thread_finished(worker)
        finally:
            self._callback = None
            self._worker = None
            worker._func = None
            worker._args = ()
            worker._kwargs = {}
            worker._delivery = None
            self.deleteLater()
