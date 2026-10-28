"""Slow SDK regression: the launcher event loop must remain responsive."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication
from ui_v2.backend_bridge import BackendBridge
from ui_v2.launcher_dialog import LauncherDialog
from core.device_status import DeviceStatus


class LauncherRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def exercise(self, fail=False):
        bridge = BackendBridge.__new__(BackendBridge)
        QObject.__init__(bridge)
        bridge._workers = []
        bridge.shell = NS(_presentation='classic', log=Mock(), workspace_robot=lambda: Mock())
        bridge.can_change_workspace = lambda: not any(w.isRunning() for w in bridge._workers)
        bridge._ensure_sdk = Mock(return_value=True)
        entered, release = threading.Event(), threading.Event()
        gui_thread = threading.get_ident()
        worker_threads = []
        def poll():
            worker_threads.append(threading.get_ident())
            entered.set()
            if not release.wait(4):
                raise RuntimeError('test timeout')
            if fail:
                raise RuntimeError('SDK test failure')
            return [DeviceStatus(serial='SLOW', status='idle')]
        bridge.camera_manager = NS(poll_device_statuses=poll)
        dialog = LauncherDialog()
        dialog.show()
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(5)
        try:
            start = time.perf_counter()
            self.assertTrue(bridge.refresh_launcher_devices(dialog))
            self.assertLess(time.perf_counter() - start, .5)
            deadline = time.perf_counter() + 3
            while (not entered.is_set() or len(ticks) < 5) and time.perf_counter() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.assertTrue(entered.is_set())
            self.assertGreaterEqual(len(ticks), 5)
            self.assertNotEqual(worker_threads, [gui_thread])
            self.assertTrue(dialog._busy)
            self.assertFalse(bridge.refresh_launcher_devices(dialog))
            self.assertEqual(len(bridge._workers), 1)
        finally:
            release.set()
            deadline = time.perf_counter() + 5
            while bridge._workers and time.perf_counter() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            timer.stop()
        self.assertFalse(bridge._workers)
        self.assertFalse(dialog._busy)
        if fail:
            self.assertTrue(bridge.shell.log.called)
        else:
            self.assertEqual(dialog._table.devices()[0].serial, 'SLOW')
        dialog.close()
        bridge.deleteLater()
        self.app.processEvents()

    def test_slow_poll_keeps_gui_responsive(self):
        self.exercise()

    def test_failed_poll_releases_busy_gate(self):
        self.exercise(fail=True)


if __name__ == '__main__':
    unittest.main()
