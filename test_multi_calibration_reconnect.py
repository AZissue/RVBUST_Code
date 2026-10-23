"""Connecting devices must retain archived calibration inputs and restore action gates."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtWidgets import QApplication
from core.frame_data import FrameData
from ui_v2 import MainWindowShell
from ui_v2.backend_bridge import BackendBridge
from ui_v2.widgets.device_table import DeviceInfo


class ReconnectCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindowShell()
        self.bridge = BackendBridge(self.window)
        self.bridge.wire_all()
        self.window.set_mode('multi_cam', [])
        self.window.set_presentation('industrial')
        self.ws = self.window.workspace_multi()
        self.devices = [DeviceInfo(serial=str(i), backend_ref=i) for i in range(2)]

    def tearDown(self):
        self.bridge.cleanup()
        self.window._dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def load_frames(self, detected=True):
        self.bridge.fixed_workflow.start_calibration('cam0')
        frames = {}
        for index in range(2):
            cid = f'cam{index}'
            points = [(0, 0, 0), (20, 0, 0), (0, 20, 0), (10, 10, 10)]
            markers = [dict(code=code, x_3d=x+index*100, y_3d=y, z_3d=z)
                       for code, (x, y, z) in enumerate(points)] if detected else []
            frame = FrameData(index, cid, is_offline=True, kind='calib', markers=markers)
            self.bridge.fixed_workflow.add_calibration_frame(frame)
            frames[cid] = frame
        self.bridge.offline_preview = True
        self.ws.set_state('detected' if detected else 'captured')
        return frames

    def reconnect(self):
        with patch.object(self.bridge, '_ensure_sdk', return_value=True), \
                patch.object(self.bridge, '_run_background') as runner:
            self.bridge._on_device_manager_reopened('multi_cam', self.devices, show_loading=False)
            runner.call_args.args[1]([('cam0', True, 'ok'), ('cam1', True, 'ok')], None)
        # The launcher's actual successful-connection path.
        self.window.set_mode('multi_cam', self.devices, preserve_state=True)

    def test_detected_offline_frames_survive_connect_and_compute_real_extrinsics(self):
        frames = self.load_frames()
        self.reconnect()
        self.assertFalse(self.bridge.offline_preview)
        for cid, frame in frames.items():
            self.assertIs(self.bridge.fixed_workflow.frames_calib[cid], frame)
        self.assertEqual(self.ws.current_state(), 'detected')
        self.assertTrue(self.window._industrial_ribbon.commands['multi_cam', 'calibrate'].isEnabled())
        ok, message = self.bridge.fixed_workflow.calibrate()
        self.assertTrue(ok, message)
        self.assertAlmostEqual(self.bridge.calibration_engine.pair_results['cam0', 'cam1']['rms_mm'], 0, places=8)

    def test_undetected_inputs_require_detection_and_empty_workspace_stays_connected(self):
        frames = self.load_frames(detected=False)
        self.reconnect()
        self.assertEqual(self.ws.current_state(), 'captured')
        self.assertTrue(self.ws._btn_detect.isEnabled())
        self.assertFalse(self.ws._btn_calibrate.isEnabled())
        self.assertEqual(self.bridge.fixed_workflow.frames_calib, frames)
        self.bridge.fixed_workflow.reset()
        self.reconnect()
        self.assertEqual(self.ws.current_state(), 'connected')
        self.assertFalse(self.ws._btn_calibrate.isEnabled())

    def test_scanning_reconnect_keeps_inputs_but_requires_recomputing_extrinsics(self):
        frames = self.load_frames()
        self.assertTrue(self.bridge.fixed_workflow.calibrate()[0])
        self.bridge.fixed_workflow.start_scanning()
        self.ws.set_state('locked')
        self.reconnect()
        self.assertEqual(self.bridge.fixed_workflow.frames_calib, frames)
        self.assertFalse(self.bridge.calibration_engine.pair_results)
        self.assertFalse(self.bridge.fixed_workflow.frames_scan)
        self.assertEqual(self.ws.current_state(), 'detected')
        self.assertFalse(self.ws._btn_scan_capture.isEnabled())


if __name__ == '__main__':
    unittest.main()
