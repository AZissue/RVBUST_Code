import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtWidgets import QApplication, QComboBox, QLabel
from PySide6.QtCore import QTimer
from ui_v2 import MainWindowShell
from ui_v2.backend_bridge import BackendBridge
from ui_v2.widgets.device_table import DeviceInfo
from core.offline_session import OfflineSession
from test_multi_camera_topology import fixture


class CaptureSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindowShell()
        self.bridge = BackendBridge(self.window)
        self.bridge.wire_all()
        self.window.set_mode('multi_cam', [DeviceInfo(model='Camera', serial=f'SERIAL-{i}', backend_ref=i) for i in range(2)])
        self.window.set_presentation('industrial')
        self.ws = self.window.workspace_multi()
        _, self.frames = fixture(2)
        self.bridge.fixed_workflow.start_calibration('cam0')
        for frame in self.frames.values():
            self.bridge.fixed_workflow.add_calibration_frame(frame)
        self.bridge.camera_manager.get_connected_ids = Mock(return_value=list(self.frames))

    def tearDown(self):
        self.bridge.cleanup()
        self.window._dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_dialog_reference_and_timing_are_applied_to_real_workflow(self):
        def choose():
            dialog = self.app.activeModalWidget()
            dialog.findChild(QComboBox, 'calibrationReference').setCurrentIndex(1)
            dialog.findChild(QComboBox, 'calibrationTiming').setCurrentIndex(1)
            self.assertTrue(any('SERIAL-1' in label.text() for label in dialog.findChildren(QLabel)))
            dialog.accept()
        QTimer.singleShot(20, choose)
        self.ws._choose_topology()
        wf = self.bridge.fixed_workflow
        self.assertEqual(wf.reference_id, 'cam1')
        self.assertIs(wf.frames_calib['cam0'], self.frames['cam0'])
        self.assertFalse(self.ws._rb_sync.isChecked())
        self.assertTrue(wf.calibrate()[0])
        self.assertEqual(self.bridge.calibration_engine.reference_id, 'cam1')
        with patch.object(self.bridge, '_run_background') as runner, \
                patch.object(self.bridge.camera_manager, 'capture_all', return_value={}) as capture:
            self.bridge._on_multi_capture(self.ws._rb_sync.isChecked())
            runner.call_args.args[0]()
            capture.assert_called_once_with(sync=False)
            capture.reset_mock()
            self.bridge._on_multi_capture_scan()
            runner.call_args.args[0]()
            capture.assert_called_once_with(sync=True)

    def test_uncomputed_settings_roundtrip_and_reference_change_invalidates_results(self):
        self.bridge._on_multi_settings_changed('chain', 'cam1', False)
        data = self.bridge.projects.describe('multi_cam', include_raw=False)
        self.assertEqual(data['calibration_reference'], 'cam1')
        self.assertFalse(data['capture_synchronous'])
        session = OfflineSession()
        session._meta.update(data)
        self.bridge._load_fixed_session(session, {cid: [frame] for cid, frame in self.frames.items()})
        self.assertEqual(self.bridge.fixed_workflow.reference_id, 'cam1')
        self.assertEqual(self.ws._calibration_reference, 'cam1')
        self.assertFalse(self.ws._rb_sync.isChecked())
        self.bridge.fixed_workflow.calibrate()
        self.bridge.fixed_workflow.start_scanning()
        self.bridge._on_multi_settings_changed('chain', 'cam0', False)
        self.assertFalse(self.bridge.calibration_engine.pair_results)
        self.assertFalse(self.ws._btn_scan_capture.isEnabled())

    def test_missing_reference_frame_never_silently_changes_selection(self):
        self.ws.reset_camera_grid(['cam0', 'cam1', 'cam2'])
        self.bridge._on_multi_settings_changed('star', 'cam2', True)
        self.assertEqual(self.bridge.fixed_workflow.reference_id, 'cam2')
        self.assertFalse(self.ws._btn_calibrate.isEnabled())
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            self.bridge._on_multi_settings_changed('star', 'cam0', True)
        self.assertEqual(self.bridge.fixed_workflow.reference_id, 'cam2')


if __name__ == '__main__':
    unittest.main()
