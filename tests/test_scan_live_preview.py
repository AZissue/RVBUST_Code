"""Scan toolbar delegates to production multi-camera 2D preview and capture interlock."""

import _bootstrap  # Configure project and sibling-test imports.
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
import unittest
import threading
import time
from unittest.mock import Mock, patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication
from core.frame_data import FrameData
from ui_v2 import MainWindowShell
from ui_v2.backend_bridge import BackendBridge
from ui_v2.widgets.device_table import DeviceInfo


class ScanPreviewTests(unittest.TestCase):
    def wait(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate())

    def test_slow_capture_runs_off_gui_and_paused_results_are_discarded(self):
        started, release = threading.Event(), threading.Event()
        main_thread = threading.get_ident()
        def capture(cid):
            self.assertNotEqual(threading.get_ident(), main_thread)
            started.set()
            release.wait(2)
            return self.frames[cid]
        self.bridge.camera_manager.capture_2d_preview.side_effect = capture
        self.button.click()
        self.bridge._card_preview_timer.stop()
        try:
            self.bridge._on_card_preview_tick()
            self.wait(started.is_set)
            self.bridge._pause_card_preview()
        finally:
            release.set()
        self.wait(lambda: self.bridge._card_capture is None)
        self.assertIsNone(self.ws.camera_grid().card('cam0').current_frame())
        self.assertIsNone(self.ws.camera_grid().card('cam1').current_frame())

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindowShell()
        self.bridge = BackendBridge(self.window)
        self.bridge.wire_all()
        self.window.set_mode('multi_cam', [DeviceInfo(serial=str(i), backend_ref=i) for i in range(2)])
        self.window.set_presentation('industrial')
        self.ws = self.window.workspace_multi()
        self.button = self.window._industrial_ribbon.commands['multi_cam', 'scan_preview']
        self.connected = {'cam0', 'cam1'}
        self.bridge.camera_manager.is_connected = Mock(side_effect=lambda cid: cid in self.connected)
        self.frames = {cid: FrameData(99, cid, image_np=np.full((32, 48, 3), 80, np.uint8))
                       for cid in self.connected}
        self.bridge.camera_manager.capture_2d_preview = Mock(side_effect=self.frames.get)

    def tearDown(self):
        self.bridge.cleanup()
        self.window._dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_preview_updates_all_live_images_without_creating_scan_data(self):
        p = self.ws._industrial
        p.set_multi_view('3d')
        p.preview_toggle.setChecked(False)
        self.button.click()
        self.assertEqual(self.bridge._card_preview_active, self.connected)
        self.assertTrue(self.button.isChecked())
        self.assertEqual(p._multi_view, '2d')
        self.assertTrue(p.preview_toggle.isChecked())
        self.bridge._card_preview_timer.stop()
        self.bridge._on_card_preview_tick()
        self.wait(lambda: all(self.ws.camera_grid().card(cid).current_frame() is self.frames[cid]
                              for cid in self.connected))
        for cid in self.connected:
            self.assertIs(self.ws.camera_grid().card(cid).current_frame(), self.frames[cid])
        self.assertFalse(self.bridge.fixed_workflow.frames_scan)
        p.preview_stop.click()
        self.assertFalse(self.button.isChecked())
        self.assertFalse(self.bridge._card_preview_active)
        self.assertFalse(self.bridge._card_preview_timer.isActive())

    def test_scan_capture_pauses_and_restores_preview_on_success_and_failure(self):
        self.button.click()
        self.bridge.fixed_workflow.add_scan_frame = Mock(return_value=(True, 'ok'))
        for error in ('模拟拍摄失败', None):
            with patch.object(self.bridge, '_run_background') as run:
                self.bridge._on_multi_capture_scan()
                self.assertFalse(self.bridge._card_preview_active)
                self.assertFalse(self.button.isChecked())
                self.assertFalse(self.bridge._card_preview_timer.isActive())
                run.call_args.args[1](self.frames if error is None else None, error)
                self.assertEqual(self.bridge._card_preview_active, self.connected)
                self.assertTrue(self.button.isChecked())
        self.assertEqual(self.bridge.fixed_workflow.add_scan_frame.call_count, 2)

    def test_disconnect_and_per_camera_toggles_update_toolbar(self):
        card = self.ws.camera_grid().card('cam0')
        card._btn_preview.click()
        self.assertTrue(self.button.isChecked())
        self.button.click()
        self.assertFalse(self.bridge._card_preview_active)
        self.button.click()
        self.connected.clear()
        self.bridge._on_card_preview_tick()
        self.assertFalse(self.button.isChecked())
        self.assertFalse(self.bridge._card_preview_timer.isActive())
        self.ws.reset_camera_grid(['cam0'], enable_controls=False)
        self.assertFalse(self.button.isEnabled())


if __name__ == '__main__':
    unittest.main()
