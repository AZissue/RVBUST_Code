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
from PySide6.QtGui import QFontDatabase, QContextMenuEvent
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
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
        # Ordinary DB tests isolate recognition; its own tests opt in with a mock detector.
        self.bridge.recognition.enabled = False
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

    def test_calibration_and_scan_labels_have_independent_display_numbers(self):
        identifiers=[]
        for number, purpose in ((1,'标定数据'), (2,'标定数据'), (3,'扫描数据'), (4,'扫描数据')):
            identifiers.append(self.db.ingest(self.source(number), purpose=purpose))
        self.browser.refresh()
        expected=['标定帧 001 · cam0','标定帧 002 · cam0','拼接帧 001 · cam0','拼接帧 002 · cam0']
        self.assertEqual([self.browser._items[uid].text(0) for uid in identifiers],expected)
        self.assertEqual([self.db.records[uid].frame_id for uid in identifiers],[1,2,3,4])
        self.browser.refresh()
        self.assertEqual([self.browser._items[uid].text(0) for uid in identifiers],expected)
        editor=self.bridge.open_postprocess()
        self.assertEqual([editor.source_browser._items[uid].text(0) for uid in identifiers],expected)
        editor.close();self.app.processEvents()

    def test_selected_frame_shows_matching_2d_and_raw_cloud_without_replacing_workflow(self):
        frame = self.source()
        uid = self.db.ingest(frame)
        self.assertEqual(self.browser.count.text(), '1 帧')
        self.assertEqual(self.browser._items[uid].childCount(), 2)
        self.assertEqual(self.browser._items[uid].parent().text(0), '标定会话数据')
        self.assertIsNone(self.browser._items[uid].parent().parent().parent())
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
        self.win._industrial_ribbon.commands[('multi_cam', 'restore')].click()
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
        self.bridge.camera_manager._cameras = {'cam0': SimpleNamespace(is_connected=True, sn='MOCK', device_info=SimpleNamespace(name='MOCK'),
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

    def test_component_selection_is_independent_and_refresh_keeps_child_selection(self):
        first = self.db.ingest(self.source(1))
        second = self.db.ingest(self.source(2))
        viewer = self.win.workspace_multi().viewer()
        grid = self.win.workspace_multi().camera_grid()
        cloud_item = self.browser._component_items[(first, 'cloud')]
        self.browser.tree.setCurrentItem(cloud_item)
        self.wait(lambda: viewer._database_cloud is not None)
        self.assertIsNone(grid._database_card)
        original_cloud = viewer._database_cloud
        canvas = viewer.viewer().canvas
        canvas.zoom = 2.
        image_item = self.browser._component_items[(second, 'image')]
        with patch.object(FrameData, 'load_pointcloud_o3d', side_effect=AssertionError('2D selection loaded PLY')):
            self.browser.tree.setCurrentItem(image_item)
            self.wait(lambda: '的2D图像' in self.win._st_hint.text())
        self.assertIs(viewer._database_cloud, original_cloud)
        self.assertEqual(canvas.zoom, 2.)
        self.assertTrue(grid._database_card.isVisible())
        self.assertIs(self.browser.tree.currentItem(), image_item)
        self.assertEqual(self.browser.selected_ids(), [second])
        self.browser.refresh()
        self.assertTrue(self.browser._component_items[(second, 'image')].isSelected())
        self.browser.restore_button.click()
        self.assertIsNone(grid._database_card)

    def test_image_only_preview_restores_without_a_database_cloud(self):
        uid = self.db.ingest(self.source())
        viewer = self.win.workspace_multi().viewer()
        grid = self.win.workspace_multi().camera_grid()
        self.browser.tree.setCurrentItem(self.browser._component_items[(uid, 'image')])
        self.wait(lambda: '的2D图像' in self.win._st_hint.text())
        self.assertIsNone(viewer._database_cloud)
        self.assertTrue(grid._database_card.isVisible())
        self.browser.restore_button.click()
        self.assertIsNone(grid._database_card)

    def test_raw_cloud_marks_only_valid_centers_and_image_selection_keeps_geometry(self):
        frame = self.source()
        frame.markers_all = [dict(code=37, x_2d=1, y_2d=1, x_3d=10., y_3d=20., z_3d=30., valid_3d=True),
                             dict(code=13, x_2d=0, y_2d=0, valid_3d=False),
                             dict(code=23, x_2d=0, y_2d=1, x_3d=float('nan'), y_3d=0., z_3d=1.)]
        uid = self.db.ingest(frame)
        viewer = self.win.workspace_multi().viewer()
        self.browser.tree.setCurrentItem(self.browser._component_items[(uid, 'cloud')])
        self.wait(lambda: viewer._database_cloud is not None)
        canvas = viewer.viewer().canvas
        self.assertEqual(len(canvas._cloud_markers), 1)
        self.assertEqual(canvas._cloud_markers[0][0], 37)
        np.testing.assert_allclose(canvas._cloud_markers[0][1][0], [10, 20, 30])
        count = canvas.total_points
        # Marker annotations are now off by default; explicitly enable them
        # before testing their geometry and rendered colors.
        action = next(a for a in viewer.viewer().options_button.menu().actions() if a.text() == '编码圆圆心与编号')
        action.setChecked(True)
        canvas.center = np.array([10., 20., 30.])
        canvas._notify_view_changed()
        self.app.processEvents()
        image = canvas._rotation_overlay.grab().toImage()
        colors = {image.pixelColor(x, y).name() for x in range(image.width()//2-10, image.width()//2+11)
                  for y in range(image.height()//2-10, image.height()//2+11)}
        self.assertIn('#4ee887', colors)
        action.setChecked(False)
        self.assertFalse(canvas.marker_centers)
        action.setChecked(True)
        self.assertEqual(canvas.total_points, count)
        self.wait(self.bridge.can_change_workspace)
        self.browser.tree.setCurrentItem(self.browser._component_items[(uid, 'image')])
        self.wait(lambda: '的2D图像' in self.win._st_hint.text())
        self.assertEqual(len(canvas._cloud_markers), 1)
        self.browser.restore_button.click()
        self.assertEqual(canvas._cloud_markers, [])

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
            self.browser.delete_selected()
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
            QTest.mouseClick(self.browser.tree.viewport(), Qt.RightButton, Qt.NoModifier, position)
            QTimer.singleShot(0, choose_clear)
            self.app.sendEvent(self.browser.tree.viewport(), QContextMenuEvent(
                QContextMenuEvent.Mouse, position, self.browser.tree.viewport().mapToGlobal(position)))
        self.assertIn('删除选中数据', observed[0][0])
        self.assertFalse(observed[0][1])
        self.assertFalse(observed[0][2])
        self.assertEqual(requests, [[first, second]])
        self.assertEqual(self.browser.selected_ids(), [first])

    def test_right_click_targets_never_request_frame_or_component_preview(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        tree = self.browser.tree
        frames, components = [], []
        self.browser.frame_selected.connect(frames.append)
        self.browser.component_selected.connect(lambda *args: components.append(args))
        targets = [self.browser._items[second],
                   self.browser._component_items[(second, 'cloud')],
                   self.browser._component_items[(second, 'image')],
                   self.browser._items[second].parent()]
        with patch.object(self.bridge.frame_db, 'select') as preview:
            for target in targets:
                tree.setCurrentItem(self.browser._items[first])
                preview.reset_mock()
                frames.clear(); components.clear()
                tree.scrollToItem(target)
                self.app.processEvents()
                position = tree.visualItemRect(target).center()
                QTest.mousePress(tree.viewport(), Qt.RightButton, Qt.NoModifier, position)
                self.assertIs(tree.currentItem(), target)
                self.assertEqual(tree.selectedItems(), [target])
                self.assertTrue(self.browser.selected_ids())
                QTest.mouseRelease(tree.viewport(), Qt.RightButton, Qt.NoModifier, position)
                self.assertEqual(frames, [])
                self.assertEqual(components, [])
                preview.assert_not_called()

    def test_right_click_selected_row_preserves_multi_selection_and_current_item(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        tree = self.browser.tree
        with patch.object(self.bridge.frame_db, 'select') as preview:
            tree.setCurrentItem(self.browser._items[first])
            self.browser._items[second].setSelected(True)
            preview.reset_mock()
            position = tree.visualItemRect(self.browser._items[second]).center()
            QTest.mouseClick(tree.viewport(), Qt.RightButton, Qt.NoModifier, position)
            self.assertIs(tree.currentItem(), self.browser._items[first])
            self.assertEqual(self.browser.selected_ids(), [first, second])
            preview.assert_not_called()

    def test_left_click_still_requests_frame_and_component_previews(self):
        uid = self.db.ingest(self.source())
        tree = self.browser.tree
        with patch.object(self.bridge.frame_db, 'select') as preview:
            for target, component in [(self.browser._items[uid], None),
                                     (self.browser._component_items[(uid, 'cloud')], 'cloud'),
                                     (self.browser._component_items[(uid, 'image')], 'image')]:
                tree.scrollToItem(target)
                self.app.processEvents()
                QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier,
                                 tree.visualItemRect(target).center())
                if component:
                    preview.assert_called_once_with('multi_cam', uid, component)
                else:
                    preview.assert_called_once_with('multi_cam', uid)
                preview.reset_mock()

    def test_delete_confirmation_has_chinese_buttons_and_defaults_to_no(self):
        uid = self.db.ingest(self.source())
        observed = []
        def dismiss():
            box = self.app.activeModalWidget()
            observed.append((box.button(QMessageBox.Yes).text(),
                             box.button(QMessageBox.No).text(),
                             box.defaultButton() is box.button(QMessageBox.No)))
            box.button(QMessageBox.No).click()
        QTimer.singleShot(0, dismiss)
        self.bridge.frame_db.remove('multi_cam', [uid])
        self.assertEqual(observed, [('是', '否', True)])
        self.assertIn(uid, self.db.records)


class LocalizedDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_standard_dialogs_keep_button_results_and_default_focus(self):
        from ui_v2.dialogs import ChineseMessageBox
        cases = [
            ('question', QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
             {QMessageBox.Yes: '是', QMessageBox.No: '否'}),
            ('warning', QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save,
             {QMessageBox.Save: '保存', QMessageBox.Discard: '放弃修改', QMessageBox.Cancel: '取消'}),
            ('information', QMessageBox.Ok, QMessageBox.Ok, {QMessageBox.Ok: '确定'}),
            ('critical', QMessageBox.Ok, QMessageBox.Ok, {QMessageBox.Ok: '确定'}),
        ]
        for method, buttons, default, expected in cases:
            with self.subTest(method=method):
                observed = []
                def dismiss():
                    box = self.app.activeModalWidget()
                    observed.append(({flag: box.button(flag).text() for flag in expected},
                                     box.defaultButton() is box.button(default)))
                    box.button(default).click()
                QTimer.singleShot(0, dismiss)
                result = getattr(ChineseMessageBox, method)(None, '测试', '提示', buttons, default)
                self.assertEqual(result, default)
                self.assertEqual(observed, [(expected, True)])


if __name__ == '__main__':
    unittest.main()
