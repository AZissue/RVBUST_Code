"""Shared worker ownership, GUI delivery, failure and suppressed late callbacks."""
import _bootstrap
import threading
import time
import unittest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication


class TaskTests(unittest.TestCase):
    def test_callback_exception_still_releases_task_and_allows_next_task(self):
        from ui_common.background_task import start_background_task
        app = QApplication.instance() or QApplication([])
        owner, workers, errors = QObject(), [], []
        def callback(*args):
            raise RuntimeError('bad callback')
        start_background_task(owner, lambda: 42, callback, workers=workers,
                              on_callback_error=errors.append)
        deadline=time.monotonic()+3
        while workers and time.monotonic()<deadline:
            app.processEvents()
            time.sleep(.005)
        self.assertFalse(workers)
        self.assertEqual(str(errors[0]), 'bad callback')

    def test_gui_delivery_failure_and_recovery(self):
        from ui_common.background_task import start_background_task
        app = QApplication.instance() or QApplication([])
        owner, workers, events = QObject(), [], []
        main = threading.get_ident()
        def work():
            self.assertNotEqual(main, threading.get_ident())
            raise ValueError('broken')
        worker = start_background_task(owner, work,
            lambda result, error: events.append((threading.get_ident(), error)),
            workers=workers, on_finished=lambda: events.append('finished'))
        deadline = time.monotonic()+3
        while workers and time.monotonic()<deadline:
            app.processEvents()
            time.sleep(.005)
        self.assertFalse(workers)
        self.assertEqual(events[0][0], main)
        self.assertIsInstance(events[0][1], ValueError)
        self.assertEqual(events[-1], 'finished')
        self.assertIsNone(worker._func)

    def test_closed_owner_skips_result_but_releases_worker(self):
        from ui_common.background_task import start_background_task
        app = QApplication.instance() or QApplication([])
        owner, workers, calls = QObject(), [], []
        start_background_task(owner, lambda: 42, lambda *args: calls.append(args),
                              workers=workers, is_active=lambda: False)
        deadline=time.monotonic()+3
        while workers and time.monotonic()<deadline:
            app.processEvents()
            time.sleep(.005)
        self.assertFalse(workers)
        self.assertFalse(calls)
