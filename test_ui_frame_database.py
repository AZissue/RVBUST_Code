"""DB first, paired preview, workflow isolation and retained capture history."""
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import open3d as o3d

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from core.camera_manager import CameraManager
from core.frame_data import FrameData
from ui_v2 import MainWindowShell
from ui_v2.backend_bridge import BackendBridge
from ui_v2.widgets.device_table import DeviceInfo
from test_frame_database import PLY


class FrameBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.win = MainWindowShell()
        for mode, database in self.win._frame_databases.items():
            database.directory = Path(self.temp.name) / mode
        with patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK initialize forbidden')):
            self.bridge = BackendBridge(self.win)
            self.bridge.wire_all()
        self.win.set_backend_bridge(self.bridge)
        self.win.set_mode('multi_cam', [DeviceInfo(serial='MOCK', backend_ref=0)])
        self.win.set_presentation('industrial')
        self.browser = self.win.workspace_multi()._industrial.frame_browser
        self.db = self.bridge.frame_db.databases['multi_cam']
        self.win.show()
        self.app.processEvents()

    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate():
            self.app.processEvents()
            if time.monotonic() > deadline:
                self.fail('DB operation timed out')
            time.sleep(.005)
        self.app.processEvents()

    def tearDown(self):
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.bridge.cleanup()
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def source(self, number=1):
        path = Path(self.temp.name) / f'input{number}.ply'
        path.write_bytes(PLY)
        return FrameData(number, 'cam0', image_np=np.zeros((2, 2, 3), np.uint8),
                         is_offline=True, offline_pointmap_path=str(path), kind='calib')

    def test_selected_frame_shows_matching_2d_and_raw_cloud_without_replacing_workflow(self):
        frame = self.source()
        uid = self.db.ingest(frame)
        self.assertEqual(self.browser.count.text(), '1 帧')
        self.assertEqual(self.browser._items[uid].childCount(), 2)
        viewer = self.win.workspace_multi().viewer()
        merged = o3d.geometry.PointCloud()
        merged.points = o3d.utility.Vector3dVector([[1., 2., 3.]])
        viewer.set_pointcloud_merged(merged)
        self.browser.tree.setCurrentItem(self.browser._items[uid].child(1))
        self.wait(lambda: viewer._database_cloud is not None)
        self.assertEqual(len(viewer._database_cloud.points), 4)
        self.assertTrue(np.isfinite(viewer.viewer().canvas._points).all())
        self.assertIs(viewer._merged, merged)
        self.assertFalse(self.browser.image._pixmap.isNull())
        self.assertEqual(self.browser.image._pixmap.size().width(), 2)
        self.browser.restore_button.click()
        self.assertIsNone(viewer._database_cloud)
        self.assertEqual(viewer.viewer().mode.currentData(), '__merged__')
        self.assertEqual(len(self.db.records), 1)
        self.bridge.frame_db.restore('multi_cam')
        self.assertEqual(viewer.viewer().mode.currentData(), '__merged__')

    def test_successful_capture_is_in_db_tree_before_business_preview_and_handles_are_freed(self):
        pm = Mock()
        def save(path, image, unit, ordered):
            Path(path).write_bytes(PLY)
            return True
        pm.SaveWithImage.side_effect = save
        fake_sdk = SimpleNamespace(PointMapUnitEnum=SimpleNamespace(Millimeter=1),
            PointMap=SimpleNamespace(Destroy=Mock()), Image=SimpleNamespace(Destroy=Mock()))
        self.bridge.camera_manager._cameras = {'cam0': SimpleNamespace(is_connected=True,
            capture_3d=lambda options: (np.zeros((2, 2, 3), np.uint8), pm, object(), 'ok'))}
        self.bridge.fixed_workflow.start_calibration('cam0')
        ws = self.win.workspace_multi()
        original = ws.on_capture_done
        observed = []
        def preview(*args, **kwargs):
            observed.append(len(self.browser._items))
            self.assertEqual(len(self.db.records), 1)
            return original(*args, **kwargs)
        with patch('core.frame_database._import_rvc', return_value=fake_sdk), \
             patch('core.frame_data._import_rvc', return_value=fake_sdk), \
             patch.object(ws, 'on_capture_done', side_effect=preview):
            self.bridge._on_multi_capture(True)
            self.wait(lambda: bool(observed))
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(observed, [1])
        frame = self.bridge.fixed_workflow.frames_calib['cam0']
        self.assertTrue(frame.is_offline)
        self.assertIsNone(frame.pointmap)
        self.assertIn(frame.database_id, self.db.records)
        fake_sdk.PointMap.Destroy.assert_called_once_with(pm)
        fake_sdk.Image.Destroy.assert_called_once()

    def test_workflow_reset_and_classic_switch_do_not_delete_archived_frames(self):
        frame = self.source()
        uid = self.db.ingest(frame)
        self.bridge.fixed_workflow.reset()
        self.win.set_presentation('classic')
        self.assertIn(uid, self.db.records)
        self.win.set_presentation('industrial')
        self.assertIn(uid, self.browser._items)
        self.assertTrue((self.db.directory / 'index.json').exists())

    def test_read_failure_keeps_work_view_and_reports_error(self):
        uid = self.db.ingest(self.source())
        (self.db.directory / 'frames' / uid / 'pointmap.ply').unlink()
        self.browser.tree.setCurrentItem(self.browser._items[uid])
        self.wait(lambda: 'DB单帧读取失败' in self.win._st_hint.text())
        self.assertIsNone(self.win.workspace_multi().viewer()._database_cloud)


if __name__ == '__main__':
    unittest.main()
