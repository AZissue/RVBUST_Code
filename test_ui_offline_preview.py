"""Offline entrance, hardware isolation and failure recovery (small fixtures)."""
import os
import sys
import unittest
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import open3d as o3d

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QSignalSpy
from PySide6.QtCore import QTimer
import cv2
from core.camera_manager import CameraManager
from core.frame_data import FrameData
from ui_v2 import MainWindowShell, LauncherDialog
from ui_v2.backend_bridge import BackendBridge
from core.offline_fixture import load_stool


class OfflinePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')

    def setUp(self):
        self.hardware = patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK used'))
        self.hardware.start()
        self.win = MainWindowShell()
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        for mode, database in self.win._frame_databases.items():
            database.directory = Path(self.storage.name) / mode
        self.bridge = BackendBridge(self.win)
        self.bridge.wire_all()
        self.win.set_backend_bridge(self.bridge)
        self.bridge._run_background = self.synchronous

    def synchronous(self, work, done, **kwargs):
        try:
            result = work()
        except Exception as error:
            done(None, error)
        else:
            done(result, None)

    def tearDown(self):
        self.bridge.cleanup()
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()
        self.hardware.stop()

    def records(self):
        records = []
        for i in range(2):
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(np.arange(30).reshape(10, 3).astype(float))
            source = Path(self.storage.name) / f'input_{i}.ply'
            image = Path(self.storage.name) / f'input_{i}.png'
            o3d.io.write_point_cloud(str(source), cloud)
            cv2.imwrite(str(image), np.zeros((20, 30, 3), np.uint8))
            frame = FrameData(i + 1, f'cam{i}', image_np=np.zeros((20, 30, 3), np.uint8),
                              is_offline=True, kind='calib', markers=[], markers_all=[],
                              offline_pointmap_path=str(source), offline_image_path=str(image))
            records.append((frame, cloud))
        return records

    def test_launcher_offline_requires_no_devices_and_obeys_busy_gate(self):
        dlg = LauncherDialog()
        spy = QSignalSpy(dlg.offline_requested)
        for mode in dlg.MODE_NAMES:
            dlg._set_mode(mode, 'industrial')
            self.assertFalse(dlg._btn_connect.isEnabled())
            dlg._btn_offline.click()
            self.assertEqual(spy.at(spy.count() - 1)[0], mode)
        count = spy.count()
        dlg.set_busy(True)
        dlg._btn_offline.click()
        self.assertEqual(spy.count(), count)
        dlg.set_busy(False)
        dlg.reject()

    def test_multicam_loads_real_frames_without_marking_cameras_connected(self):
        with patch('ui_v2.offline_preview.load_stool', side_effect=self.records):
            self.bridge.open_offline_preview('multi_cam')
        self.assertTrue(self.bridge.offline_preview)
        self.assertEqual(len(self.bridge.fixed_workflow.frames_calib), 2)
        self.assertEqual(self.bridge.camera_manager.get_connected_ids(), [])
        ws = self.win.workspace_multi()
        self.assertEqual(len(ws.viewer()._clouds), 2)
        self.assertFalse(ws._btn_capture.isEnabled())
        self.assertTrue(ws._btn_detect.isEnabled())
        self.assertIn('离线', self.win._st_devices.text())

    def test_turntable_has_two_calibration_frames_but_no_hardware_capture(self):
        with patch('ui_v2.offline_preview.load_stool', side_effect=self.records):
            self.bridge.open_offline_preview('turntable')
        ws = self.win.workspace_turntable()
        self.assertIsNotNone(ws.current_frame0)
        self.assertIsNotNone(ws.current_frame1)
        self.assertFalse(ws.btn_capture_frame0.isEnabled())
        self.assertFalse(ws.btn_capture_frame1.isEnabled())
        self.assertFalse(ws.session.is_calibrated())

    def test_mobile_offline_load_only_archives_raw_frames(self):
        with patch('ui_v2.offline_preview.load_stool', side_effect=self.records), \
             patch('core.mobile_chain_workflow.MobileChainWorkflow.load_session_dir', side_effect=AssertionError('load must not stitch')):
            self.bridge.open_offline_preview('mobile_chain')
        database = self.bridge.frame_db.databases['mobile_chain']
        self.assertEqual(len(database.records), 2)
        self.assertTrue(all(row.kind == 'raw' for row in database.records.values()))
        self.assertEqual(self.bridge.mobile_workflow.get_station_evaluations(), [])
        self.assertIsNone(self.win.workspace_mobile().viewer()._merged)
        self.assertIsNotNone(self.win.workspace_mobile().viewer()._database_cloud)
        self.assertTrue(self.win._industrial_ribbon.commands[('mobile_chain', 'stitch')].isEnabled())

    def test_missing_data_reports_failure_and_retains_previous_workspace(self):
        before = self.win.current_mode()
        result = []
        with patch('ui_v2.offline_preview.load_stool', side_effect=FileNotFoundError('fixture missing')):
            self.bridge.open_offline_preview('turntable', lambda *args: result.append(args))
        self.assertFalse(result[0][0])
        self.assertIn('fixture missing', result[0][1])
        self.assertEqual(self.win.current_mode(), before)
        self.assertFalse(self.bridge.offline_preview)

    def test_device_manager_switches_offline_modes_without_enumeration(self):
        class OfflineLauncher(LauncherDialog):
            def exec(dialog):
                dialog._set_mode('turntable', 'industrial')
                QTimer.singleShot(0, dialog._btn_offline.click)
                return super().exec()
        self.win._launcher_factory = OfflineLauncher
        with patch('ui_v2.offline_preview.load_stool', side_effect=self.records), \
             patch.object(self.bridge, 'enumerate_devices', side_effect=AssertionError('enumeration used')):
            self.bridge.open_offline_preview('multi_cam')
            self.win.open_device_manager()
        self.assertEqual(self.win.current_mode(), 'turntable')
        self.assertIsNotNone(self.win.workspace_turntable().current_frame1)

    def test_archive_checksum_and_display_filter_preserve_original_ply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ply = (b'ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\n'
                   b'property float y\nproperty float z\nend_header\n0 0 0\n1 2 3\n4 5 6\n')
            png = cv2.imencode('.png', np.zeros((2, 2, 3), np.uint8))[1].tobytes()
            entries = []
            for i in (1, 2):
                with zipfile.ZipFile(root / f'{i}.zip', 'w') as archive:
                    archive.writestr(f'{i}.ply', ply)
                    archive.writestr(f'{i}.png', png)
                entries.append(dict(id=i, archive=f'{i}.zip', markers=[],
                    sha256={key: hashlib.sha256(value).hexdigest() for key, value in [('ply', ply), ('png', png)]}))
            (root / 'manifest.json').write_text(json.dumps(dict(units='mm', frames=entries)))
            records = load_stool(root)
            self.assertEqual(len(records[0][1].points), 2)
            self.assertEqual((root / '.cache' / '1.ply').read_bytes(), ply)
            (root / '.cache' / '1.ply').write_bytes(b'damaged')
            load_stool(root)
            self.assertEqual((root / '.cache' / '1.ply').read_bytes(), ply)
            entries[0]['sha256']['ply'] = 'invalid checksum'
            (root / 'manifest.json').write_text(json.dumps(dict(units='mm', frames=entries)))
            with self.assertRaisesRegex(ValueError, '校验失败'):
                load_stool(root)


if __name__ == '__main__':
    unittest.main()
