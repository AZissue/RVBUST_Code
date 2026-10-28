"""GUI delivery and shutdown regressions, private DB fixtures, SDK forbidden."""
import sys
import threading
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch
import test_ui_frame_database as fixture
from PySide6.QtCore import QEvent, QThread
from shiboken6 import isValid


class BackgroundLifecycleTests(fixture.FrameBrowserTests):
    # Only the dedicated lifecycle tests are collected below.
    def tearDown(self):
        if isValid(self.win):
            super().tearDown()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_shutdown_drops_queued_ui_callbacks_after_window_deletion(self):
        entered, release = threading.Event(), threading.Event()
        calls, errors = [], []
        target = Path(self.temp.name)/'must-finish.txt'
        def work():
            entered.set()
            release.wait(3)
            target.write_text('completed', encoding='utf-8')
            return 7
        self.bridge._run_background(work, lambda *args: calls.append(args),
                                    must_finish=True, name='project_export_cloud')
        self.assertTrue(entered.wait(2))
        release.set()
        self.bridge.cleanup()
        self.assertEqual(target.read_text(encoding='utf-8'), 'completed')
        self.win._dirty = False
        self.win.close(); self.win.deleteLater()
        with patch.object(sys, 'excepthook', lambda *args: errors.append(args)):
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
        self.assertFalse(isValid(self.win))
        self.assertEqual(calls, [], 'Queued UI completion must not outlive cleanup')
        self.assertEqual(errors, [], 'Finished callbacks must not access deleted widgets')
        self.assertEqual(self.bridge._workers, [])

    def test_finished_job_releases_captured_payload_on_gui_thread(self):
        class Payload:
            pass
        payload = Payload()
        captured = weakref.ref(payload)
        calls = []
        def work(value=payload):
            return 7
        def done(value, error, context=payload):
            calls.append((value, error, QThread.currentThread() == self.app.thread()))
        self.bridge._run_background(work, done, name='db_frame_preview')
        worker = self.bridge._workers[-1]
        del payload, work, done
        self.wait(lambda: not self.bridge._workers)
        self.assertEqual(calls, [(7, None, True)])
        self.assertIsNone(captured(), 'Finished task must release callable closures even while its wrapper is retained')
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(worker))

    def test_cleanup_prevents_new_dispatch(self):
        self.bridge.cleanup()
        calls = []
        self.bridge._run_background(lambda: calls.append('work'), lambda *args: calls.append('done'),
                                    name='db_frame_preview')
        self.app.processEvents()
        self.assertEqual(calls, [])
        self.assertEqual(self.bridge._workers, [])


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name in ('test_shutdown_drops_queued_ui_callbacks_after_window_deletion',
                 'test_finished_job_releases_captured_payload_on_gui_thread',
                 'test_cleanup_prevents_new_dispatch'):
        suite.addTest(BackgroundLifecycleTests(name))
    return suite


if __name__ == '__main__':
    unittest.main()
