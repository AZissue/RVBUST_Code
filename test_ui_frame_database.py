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
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
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
        self.assertEqual(self.browser._items[uid].childCount(), 0)
        self.assertIsNone(self.browser._items[uid].parent().parent())
        self.assertFalse(hasattr(self.browser, 'image'))
        viewer = self.win.workspace_multi().viewer()
        merged = o3d.geometry.PointCloud()
        merged.points = o3d.utility.Vector3dVector([[1., 2., 3.]])
        viewer.set_pointcloud_merged(merged)
        self.browser.tree.setCurrentItem(self.browser._items[uid])
        self.wait(lambda: viewer._database_cloud is not None)
        self.assertEqual(len(viewer._database_cloud.points), 4)
        self.assertTrue(np.isfinite(viewer.viewer().canvas._points).all())
        self.assertIs(viewer._merged, merged)
        grid = self.win.workspace_multi().camera_grid()
        self.assertEqual(grid._database_card.current_frame().image_np.shape[1], 2)
        self.assertTrue(grid._database_card.isVisible())
        self.assertIsNone(self.win.workspace_multi()._industrial.inspector)
        self.browser.restore_button.click()
        self.assertIsNone(viewer._database_cloud)
        self.assertIsNone(grid._database_card)
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

    def test_delete_batch_and_recover_keep_workflow_readable_without_reimporting(self):
        frame = self.source()
        uid = self.db.ingest(frame)
        folder = self.db.directory / 'frames' / uid
        # A real camera capture returns these archive-owned paths to workflows.
        frame.offline_pointmap_path = str(folder / 'pointmap.ply')
        frame.offline_image_path = str(folder / 'image.png')
        frame.offline_dir = str(folder)
        self.bridge.fixed_workflow.frames_calib['cam0'] = frame
        second = self.db.ingest(self.source(2))
        session = self.browser.tree.topLevelItem(0)
        session.setSelected(True)
        self.assertEqual(set(self.browser.selected_ids()), {uid, second})
        with patch('ui_v2.frame_database.QMessageBox.question', return_value=QMessageBox.Yes):
            self.browser.delete_button.click()
            self.wait(lambda: '已删除' in self.win._st_hint.text())
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(self.browser.count.text(), '0 帧')
        self.assertTrue(frame.has_pointcloud)
        self.assertTrue(Path(frame.offline_image_path).is_file())
        self.assertIn('.trash', frame.offline_pointmap_path)
        self.bridge.frame_db.archive_context()
        self.bridge.frame_db.synchronize()
        self.assertEqual(len(self.db.records), 0)
        self.bridge.frame_db.recover('multi_cam')
        self.wait(lambda: '已恢复' in self.win._st_hint.text())
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(set(self.db.records), {uid, second})
        self.assertEqual(frame.offline_pointmap_path, str(folder / 'pointmap.ply'))
        self.assertIs(self.bridge.fixed_workflow.frames_calib['cam0'], frame)

    def test_delete_cancel_busy_and_error_leave_archive_unchanged(self):
        uid = self.db.ingest(self.source())
        with patch('ui_v2.frame_database.QMessageBox.question', return_value=QMessageBox.No):
            self.bridge.frame_db.remove('multi_cam', [uid])
        self.assertIn(uid, self.db.records)
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            self.bridge.frame_db.remove('multi_cam', [uid])
        self.assertIn(uid, self.db.records)
        with patch('ui_v2.frame_database.QMessageBox.question', return_value=QMessageBox.Yes), \
             patch.object(self.db, '_save_index', side_effect=OSError('disk full')):
            self.bridge.frame_db.remove('multi_cam', [uid])
            self.wait(lambda: 'DB删除失败' in self.win._st_hint.text())
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertIn(uid, self.db.records)
        self.assertIn('DB删除失败', self.win._st_hint.text())

    def test_multi_selection_and_refresh_preserve_collapsed_batch(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        self.browser._items[first].setSelected(True)
        self.browser._items[second].setSelected(True)
        self.assertEqual(set(self.browser.selected_ids()), {first, second})
        self.browser.tree.topLevelItem(0).setExpanded(False)
        self.browser.refresh()
        self.assertFalse(self.browser.tree.topLevelItem(0).isExpanded())
        self.assertEqual(set(self.browser.selected_ids()), {first, second})

    def test_context_click_can_clear_db_without_loading_a_pointcloud(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        requests = []
        self.browser.delete_requested.connect(lambda ids: requests.append(ids))
        observed = []
        def choose_clear():
            menu = self.app.activePopupWidget()
            actions = {a.text(): a for a in menu.actions()}
            observed.append((list(actions), actions['恢复上次删除'].isEnabled(),
                             any(w.isRunning() for w in self.bridge._workers)))
            try:
                actions['清空当前 DB'].trigger()
            finally:
                menu.close()
        self.app.processEvents()
        position = self.browser.tree.visualItemRect(self.browser._items[first]).center()
        with patch('ui_v2.frame_database.QMessageBox.question', return_value=QMessageBox.No):
            QTimer.singleShot(0, choose_clear)
            self.browser._context_menu(position)
        self.assertIn('删除选中数据', observed[0][0])
        self.assertFalse(observed[0][1])
        self.assertFalse(observed[0][2])
        self.assertEqual(requests, [[first, second]])
        self.assertEqual(self.browser.selected_ids(), [first])


if __name__ == '__main__':
    unittest.main()
