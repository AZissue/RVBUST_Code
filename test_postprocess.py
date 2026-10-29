"""Offline postprocess geometry, DB lineage and production UI integration (no SDK)."""
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import open3d as o3d
import test_ui_frame_database as fixture
from PySide6.QtCore import Qt, QSignalBlocker, QEvent, QPoint, QPointF
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu
from ui_v2.dialogs import ChineseMessageBox as QMessageBox
from core.postprocess.processing import voxel_downsample, random_downsample, polygon_crop_mask
from core.postprocess.session import CloudLayer, write_cloud
from core.frame_database import STALE_RESULT
from core.session_project import SessionProject


def cloud(points, colors=None):
    result = o3d.geometry.PointCloud()
    result.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=float))
    if colors is not None:
        result.colors = o3d.utility.Vector3dVector(np.asarray(colors, dtype=float))
    return result


class GeometryTests(unittest.TestCase):
    def test_voxel_centroids_and_color_means(self):
        points, colors = voxel_downsample([[.1, 0, 0], [.3, 0, 0], [2, 0, 0]],
                                          [[1, 0, 0], [0, 0, 1], [0, 1, 0]], 1)
        np.testing.assert_allclose(points, [[.2, 0, 0], [2, 0, 0]])
        np.testing.assert_allclose(colors, [[.5, 0, .5], [0, 1, 0]])
        for value in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                voxel_downsample(points, voxel_size=value)

    def test_random_preserves_correspondence_without_duplicates(self):
        points = np.arange(300).reshape(-1, 3)
        sampled, colors, indices = random_downsample(points, points/300, .25, seed=42)
        self.assertEqual(len(indices), 25)
        self.assertEqual(len(set(indices)), 25)
        np.testing.assert_array_equal(sampled, points[indices])
        np.testing.assert_allclose(colors, points[indices]/300)
        np.testing.assert_array_equal(indices, random_downsample(points, ratio=.25, seed=42)[2])
        for ratio in (0, 1.1, float('inf')):
            with self.assertRaises(ValueError):
                random_downsample(points, ratio=ratio)

    def test_projected_polygon_uses_all_depths(self):
        points = [[0, 0, 0], [0, 0, 100], [10, 0, 0]]
        polygon = [(40, 40), (60, 40), (60, 60), (40, 60)]
        view = dict(center=np.zeros(3), rotation_matrix=np.eye(3), extent=10,
                    zoom=1, pan=np.zeros(2), width=100, height=100)
        mask = polygon_crop_mask(points, polygon, **view)
        np.testing.assert_array_equal(mask, [True, True, False])
        np.testing.assert_array_equal(mask, polygon_crop_mask(points, polygon[::-1], **view))

    def test_failed_export_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'cloud.ply'
            target.write_bytes(b'existing data')
            with patch('core.utils.write_point_cloud_atomic', return_value=False):
                with self.assertRaises(OSError):
                    write_cloud(target, [CloudLayer('layer', [[1, 2, 3]])])
            self.assertEqual(target.read_bytes(), b'existing data')

    def test_owned_arrays_are_read_only(self):
        points = np.array([[1., 2, 3], [np.nan, 0, 0]])
        layer = CloudLayer('original', points, [[1, 0, 0], [0, 1, 0]])
        points[0] = 99
        np.testing.assert_array_equal(layer.points, [[1, 2, 3]])
        self.assertFalse(layer.points.flags.writeable)
        self.assertFalse(layer.colors.flags.writeable)

class PostprocessTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    wait = fixture.FrameBrowserTests.wait
    source = fixture.FrameBrowserTests.source

    def setUp(self):
        fixture.FrameBrowserTests.setUp(self)
        self.editor = self.bridge.open_postprocess()
        self.app.processEvents()

    def tearDown(self):
        self.wait(lambda: self.editor._worker is None)
        if not self.editor._closed:
            self.editor.close()
        fixture.FrameBrowserTests.tearDown(self)
        # processEvents alone leaves closed windows queued for DeferredDelete.
        # Drain them before another test applies an application-wide stylesheet.
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_log_entry_history_live_filter_and_close(self):
        panel = self.editor._log_panel
        self.assertFalse(panel.isVisible())
        self.assertTrue(self.editor.status.isVisible())
        self.win.log('后处理日志共享检查', 'warn')
        self.editor._btn_log.click()
        self.app.processEvents()
        self.assertTrue(panel.isVisible())
        self.assertFalse(self.editor.status.isVisible())
        self.assertEqual(panel.records[-1], self.win._log_panel.records[-1])
        from core.utils import logger
        task = threading.Thread(target=lambda: logger.warning('后台线程日志同步检查'))
        task.start()
        task.join()
        self.app.processEvents()
        self.assertEqual(sum(row[-1] == '后台线程日志同步检查' for row in panel.records), 1)
        panel.search.setText('后处理日志共享检查')
        self.assertEqual(len(panel.visible_records()), 1)
        self.editor._set_status('处理失败：日志检查')
        self.assertEqual(panel.records[-1][1], 'error')
        self.assertFalse(self.editor.status.isVisible())
        panel._btn_close.click()
        self.assertFalse(self.editor._btn_log.isChecked())
        self.assertFalse(panel.isVisible())
        self.assertTrue(self.editor.status.isVisible())
        self.assertEqual(self.editor.status.text(), '处理失败：日志检查')
        self.win.log('隐藏时继续记录', 'success')
        self.editor._btn_log.click()
        self.assertEqual(panel.records[-1][-1], '隐藏时继续记录')
        self.assertFalse(self.editor.status.isVisible())
        panel._btn_collapse.click()
        self.assertTrue(self.editor.status.isVisible())
        self.editor._btn_log.click()
        self.assertFalse(self.editor.status.isVisible())
        self.editor._btn_log.click()
        self.assertTrue(self.editor.status.isVisible())

    def test_log_history_and_shutdown_disconnect(self):
        self.editor.close()
        self.win.log('重开前历史', 'info')
        self.editor = self.bridge.open_postprocess()
        self.app.processEvents()
        self.assertEqual(self.editor._log_panel.records[-1][-1], '重开前历史')
        self.editor.shutdown()
        count = len(self.editor._log_panel.records)
        self.win.log('关闭后日志', 'info')
        self.assertEqual(len(self.editor._log_panel.records), count)

    def finish(self):
        self.wait(lambda: self.editor._worker is None and self.editor._pending_load is None)
        self.assertNotIn('失败', self.editor.status.text())

    def load_grid(self):
        uid = self.db.ingest(self.source())
        points = np.array([[x, y, 1] for x in range(10) for y in range(10)], float)
        result = self.db.publish_result(cloud(points, np.tile([.2, .4, .6], (100, 1))), [uid])
        self.editor.source_browser.refresh()
        self.editor.load_selected([result])
        self.finish()
        self.assertEqual(self.editor._display_ids, [result])
        return uid, result, points

    def test_context_delete_moves_result_to_trash_and_recovers_in_both_trees(self):
        raw, source, _ = self.load_grid()
        self.editor.downsample('voxel'); self.finish()
        result = self.editor._display_ids[0]
        browser = self.editor.source_browser
        position = browser.tree.visualItemRect(browser._component_items[result, 'cloud']).center()
        def choose_delete(menu, *_):
            action = next(a for a in menu.actions() if a.text() == '删除选中点云')
            self.assertTrue(action.isEnabled())
            action.trigger()
        class TestMenu(QMenu):
            def exec(self, *_):
                choose_delete(self)
        with patch('ui_v2.postprocess.window.QMenu', TestMenu), patch(
                'ui_v2.postprocess.window.QMessageBox.question', return_value=QMessageBox.Yes):
            self.editor._source_menu(position)
            self.assertFalse(self.editor.actions['open'].isEnabled())
            self.finish()
        self.assertIn(result, self.db.removed)
        self.assertNotIn(result, browser._items)
        self.assertNotIn(result, self.bridge.frame_db.browsers[self.editor.mode]._items)
        self.assertEqual(self.editor._display_ids, [])
        self.assertEqual(self.editor._undo, [])
        self.assertIn(raw, self.db.records)
        self.assertIn(source, self.db.records)
        self.editor._mutate_database(recover=True); self.finish()
        self.assertIn(result, self.db.records)
        self.assertIn(result, browser._items)
        self.assertIn(result, self.bridge.frame_db.browsers[self.editor.mode]._items)

    def test_delete_uses_highlight_not_checks_and_deduplicates_parent_child(self):
        raw, first, points = self.load_grid()
        second = self.db.publish_result(cloud(points), [raw])
        self.editor.source_browser.refresh()
        self.editor.load_selected([raw, first, second]); self.finish()
        browser = self.editor.source_browser
        with QSignalBlocker(browser.tree):
            browser.tree.clearSelection()
            for item in (browser._items[first], browser._items[second], browser._component_items[second, 'cloud']):
                item.setSelected(True)
        with patch('ui_v2.postprocess.window.QMessageBox.question', return_value=QMessageBox.Yes) as question:
            self.editor.delete_selected(); self.finish()
        self.assertIn('2 项点云', question.call_args.args[2])
        self.assertEqual(set(self.db.removed), {first, second})
        self.assertEqual(self.editor._display_ids, [raw])
        self.assertTrue((self.db.directory/'frames'/raw/'image.png').is_file())

    def test_raw_delete_warns_for_image_pair_and_retargets_workflow_paths(self):
        raw, result, _ = self.load_grid()
        frame, _ = self.db.load_frame(raw)
        self.bridge.fixed_workflow.frames_calib['cam0'] = frame
        browser = self.editor.source_browser
        with QSignalBlocker(browser.tree):
            browser.tree.clearSelection()
            browser._items[raw].setSelected(True)
        with patch('ui_v2.postprocess.window.QMessageBox.question', return_value=QMessageBox.Yes) as question:
            self.editor.delete_selected(); self.finish()
        self.assertIn('2D图像一并移除', question.call_args.args[2])
        self.assertIn(raw, self.db.removed)
        self.assertIn(result, self.db.records)
        self.assertIn('.trash', frame.offline_pointmap_path)
        self.assertTrue(Path(frame.offline_pointmap_path).is_file())
        self.assertTrue(Path(frame.offline_image_path).is_file())
        self.editor._mutate_database(recover=True); self.finish()
        self.assertIn(raw, self.db.records)
        self.assertNotIn('.trash', frame.offline_pointmap_path)
        self.assertTrue(Path(frame.offline_image_path).is_file())

    def test_delete_cancel_image_only_busy_and_failure_leave_data_intact(self):
        raw, result, _ = self.load_grid()
        with patch('ui_v2.postprocess.window.QMessageBox.question', return_value=QMessageBox.No):
            self.editor.delete_selected()
        self.assertIn(result, self.db.records)
        self.assertIsNone(self.editor._worker)
        with patch.object(self.bridge, 'can_change_workspace', return_value=False), patch(
                'ui_v2.postprocess.window.QMessageBox.question') as question:
            self.editor.delete_selected()
            question.assert_not_called()
        browser = self.editor.source_browser
        with QSignalBlocker(browser.tree):
            browser.tree.clearSelection()
            browser._component_items[raw, 'image'].setSelected(True)
        self.assertEqual(self.editor._selected_cloud_ids(), [])
        with QSignalBlocker(browser.tree):
            browser.tree.clearSelection()
            browser._items[result].setSelected(True)
        with patch('ui_v2.postprocess.window.QMessageBox.question', return_value=QMessageBox.Yes), patch.object(
                self.db, 'remove', side_effect=OSError('disk failure')):
            self.editor.delete_selected()
            self.wait(lambda: self.editor._worker is None)
        self.assertIn('disk failure', self.editor.status.text())
        self.assertIn(result, self.db.records)
        self.assertEqual(self.editor._display_ids, [result])

    def test_single_db_entry_in_each_mode_and_busy_gate(self):
        self.assertIs(self.bridge.open_postprocess(), self.editor)
        self.assertIs(self.editor.source_browser.database, self.db)
        self.assertFalse(hasattr(self.editor, 'panel'))
        self.assertFalse(hasattr(self.editor, 'tree_tabs'))
        self.assertNotIn('publish', self.editor.actions)
        self.assertNotIn('db', self.editor.actions)
        self.assertFalse(self.editor.viewer.toolbar.isVisible())
        self.assertFalse(getattr(self.bridge, '_sdk_initialized', False))
        self.editor.close()
        self.app.processEvents()
        for mode in ('mobile_chain', 'turntable', 'multi_cam'):
            self.win.set_mode(mode, [])
            self.editor = self.bridge.open_postprocess()
            self.assertEqual(self.editor.mode, mode)
            self.editor.close()
            self.app.processEvents()
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            self.assertIsNone(self.bridge.open_postprocess())

    def test_db_selection_loads_without_import_button_or_duplicate_records(self):
        uid, result, points = self.load_grid()
        self.editor.load_selected([])
        self.editor.source_browser.tree.setCurrentItem(self.editor.source_browser._items[uid])
        self.finish()
        self.assertEqual(self.editor._display_ids, [uid])
        self.assertEqual(len(self.db.records), 2)

    def test_reopened_db_checkbox_keeps_emitting_item_alive(self):
        from shiboken6 import isValid
        _, result, _ = self.load_grid()
        self.editor.close()
        self.app.processEvents()
        self.browser.set_component_checked(result, 'cloud')
        self.wait(lambda: bool(self.win.workspace_multi().viewer()._database_clouds))
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.editor = self.bridge.open_postprocess()
        self.finish()
        browser = self.editor.source_browser
        item = browser._component_items[result, 'cloud']
        with patch.object(browser, 'refresh') as rebuild:
            for visible in (False, True, False, True):
                item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
                self.finish()
                self.assertEqual(bool(self.editor._display_ids), visible)
                self.assertTrue(isValid(item))
                self.assertIs(browser._component_items[result, 'cloud'], item)
            rebuild.assert_not_called()
        self.assertEqual(len(self.db.records), 2)

    def test_load_latest_selection_wins_while_background_read_runs(self):
        uid, result, _ = self.load_grid()
        entered, release = threading.Event(), threading.Event()
        original = self.db.load_frame
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(3)
            return original(*args, **kwargs)
        with patch.object(self.db, 'load_frame', side_effect=delayed):
            self.editor.load_selected([uid])
            self.assertTrue(entered.wait(2))
            self.editor.load_selected([result])
            release.set()
            self.finish()
        self.assertEqual(self.editor._display_ids, [result])

    def test_downsample_automatically_commits_preserves_source_and_view(self):
        _, source, points = self.load_grid()
        original = self.db.directory/'frames'/source/'pointmap.ply'
        before = original.read_bytes()
        self.editor.viewer.canvas.zoom = 1.3
        view = self.editor._view()
        from core.postprocess import processing
        threads = []
        def run(*args):
            threads.append(threading.get_ident())
            return processing.voxel_downsample(*args)
        with patch('ui_v2.postprocess.window.voxel_downsample', side_effect=run):
            self.editor.downsample('voxel', 3)
            self.assertFalse(self.editor.actions['open'].isEnabled())
            self.finish()
        result = self.editor._display_ids[0]
        self.assertNotEqual(result, source)
        self.assertEqual(self.db.records[result].points, 16)
        self.assertEqual(self.db.records[result].source_ids, [source])
        self.assertEqual(self.db.records[result].purpose, '后处理结果')
        self.assertIn(result, self.browser._items)
        self.assertEqual(self.editor.source_browser.checked_components('cloud'), [(result, 'cloud')])
        self.assertNotEqual(threads, [threading.get_ident()])
        self.assertEqual(original.read_bytes(), before)
        for key, value in view.items():
            np.testing.assert_allclose(self.editor._view()[key], value)
        self.assertTrue(self.win._dirty)

    def test_split_publishes_both_branches_and_undo_moves_only_outputs_to_trash(self):
        _, source, _ = self.load_grid()
        original = self.editor._clouds[source]
        self.editor._segment = (source, original, np.arange(100) < 40, self.editor._view())
        self.editor.apply_segment(True)
        self.finish()
        outputs = [uid for uid, _ in self.editor._undo[-1][0]]
        self.assertEqual([self.db.records[uid].points for uid in outputs], [40, 60])
        self.assertEqual(self.editor._display_ids, outputs[:1])
        layers = self.editor._read_records(self.editor.directory, self.editor._undo[-1][0])
        np.testing.assert_array_equal(np.vstack([p.points for p in layers]), original.points)
        np.testing.assert_array_equal(np.vstack([p.colors for p in layers]), original.colors)
        self.assertEqual(len(self.db.records), 4)
        self.assertTrue(all(self.db.records[uid].source_ids == [source] for uid in outputs))
        self.editor.undo()
        self.finish()
        self.assertEqual(self.editor._display_ids, [source])
        self.assertEqual(len(self.db.records), 2)
        self.assertTrue(all(uid in self.db.removed for uid in outputs))
        self.db.restore_last_removal()
        self.assertTrue(all(uid in self.db.records for uid in outputs))

    def test_split_write_failure_rolls_back_all_branches(self):
        _, source, _ = self.load_grid()
        original = self.editor._clouds[source]
        self.editor._segment = (source, original, np.arange(100) < 40, self.editor._view())
        index = (self.db.directory/'index.json').read_bytes()
        before = set(self.db.records)
        from core.utils import write_point_cloud_atomic
        calls = []
        def write(path, data):
            calls.append(path)
            return write_point_cloud_atomic(path, data) if len(calls) == 1 else False
        with patch('core.utils.write_point_cloud_atomic', side_effect=write):
            self.editor.apply_segment(True)
            self.wait(lambda: self.editor._worker is None)
        self.assertIn('写入失败', self.editor.status.text())
        self.assertEqual(set(self.db.records), before)
        self.assertEqual({p.name for p in (self.db.directory/'frames').iterdir()}, before)
        self.assertEqual((self.db.directory/'index.json').read_bytes(), index)
        self.assertIs(self.editor._clouds[source], original)
        self.assertFalse(self.editor._undo)

    def test_grouped_results_refresh_reload_fallback_and_selection(self):
        raw, source, _ = self.load_grid()
        original = self.editor._clouds[source]
        self.editor._segment = (source, original, np.arange(100) < 40, self.editor._view())
        self.editor.apply_segment(True)
        self.finish()
        outputs = [uid for uid, _ in self.editor._undo[-1][0]]
        multi = self.db.publish_result(cloud([[0, 0, 1]]), [raw, source], postprocess=True)
        missing = self.db.publish_result(cloud([[0, 0, 2]]), [], postprocess=True)
        # Emulate an unavailable source without altering the stored session format.
        self.db.records[missing].source_ids = ['0' * 32]
        browser = self.editor.source_browser
        # Reversed snapshots ensure attachment never depends on insertion order.
        sessions, records = self.db.snapshot()
        with patch.object(self.db, 'snapshot', return_value=(sessions, records[::-1])):
            browser.refresh()
        def verify(tree):
            self.assertEqual(set(tree._items), set(self.db.records))
            for uid in outputs:
                frame = tree._items[uid].parent()
                self.assertIs(frame, tree._items[outputs[0]].parent())
                self.assertFalse(frame.data(0, Qt.UserRole))
                self.assertTrue(frame.text(0).startswith('后处理帧 '))
                self.assertIs(frame.parent(), tree._items[source].parent())
                self.assertIs(tree._component_items[uid, 'cloud'], tree._items[uid])
                self.assertEqual(tree._items[uid].childCount(), 0)
            self.assertEqual(tree._items[source].childCount(), 1)
            self.assertEqual([tree._items[uid].text(0) for uid in outputs],
                             ['框内点云 · PLY', '框外点云 · PLY'])
            for uid in (multi, missing):
                self.assertEqual(tree._items[uid].parent().parent().text(0), '拼接结果')
        verify(browser)
        verify(self.browser)
        with QSignalBlocker(browser.tree):
            browser.tree.clearSelection()
            browser._items[source].setSelected(True)
        self.assertEqual(browser.selected_ids(), [source])
        self.assertEqual(self.editor._selected_cloud_ids(), [source])
        checks = browser.checked_components()
        browser.refresh()
        verify(browser)
        self.assertEqual(browser.selected_ids(), [source])
        self.assertEqual(browser.checked_components(), checks)
        self.editor.close()
        self.app.processEvents()
        self.db._save_index()
        self.db.open_project(self.db.directory / 'index.json')
        self.editor = self.bridge.open_postprocess()
        self.finish()
        verify(self.editor.source_browser)

    def test_virtual_frame_selection_delete_restore_and_legacy_metadata(self):
        import json
        raw, source, _ = self.load_grid()
        second = self.source(2)
        second.kind = 'scan'
        raw2 = self.db.ingest(second)
        layer = self.editor._clouds[source]
        self.editor._segment = (source, layer, np.arange(100) < 40, self.editor._view())
        self.editor.apply_segment(True); self.finish()
        outputs = [uid for uid, _ in self.editor._undo[-1][0]]
        operation = self.db.records[outputs[0]].operation_id
        self.assertTrue(operation)
        self.assertEqual(self.db.records[outputs[1]].operation_id, operation)
        for browser in (self.browser, self.editor.source_browser):
            self.assertEqual(browser._items[raw2].parent().text(0), '扫描帧数据')
            frame = browser._items[outputs[0]].parent()
            previews = []
            browser.component_selected.connect(lambda *args: previews.append(args))
            browser.frame_selected.connect(lambda *args: previews.append(args))
            displayed = list(self.editor._display_ids)
            browser.tree.setCurrentItem(frame)
            self.assertEqual(self.editor._display_ids, displayed)
            self.assertIsNone(self.editor._worker)
            self.assertEqual(previews, [])
            self.assertEqual(browser.selected_ids(), outputs)
            self.assertIsNone(browser.export_uid())
            browser._items[outputs[0]].setSelected(True)
            self.assertEqual(browser.selected_ids(), outputs)
            browser.refresh()
            self.assertEqual(browser.selected_ids(), outputs)
            self.assertEqual(browser._items[outputs[0]].parent().childCount(), 2)
        self.assertEqual(self.editor._selected_cloud_ids(), outputs)
        before = {uid: (self.db.directory/'frames'/uid/'pointmap.ply').read_bytes()
                  for uid in (raw, raw2, source)}
        for uid in outputs:
            target = Path(self.temp.name)/(uid+'.ply')
            self.db.export_cloud(uid, target)
            self.assertEqual(target.read_bytes(), (self.db.directory/'frames'/uid/'pointmap.ply').read_bytes())
        self.db.remove(outputs)
        self.db._save_index()
        self.db.open_project(self.db.directory/'index.json')
        self.db.restore_last_removal()
        self.assertEqual([self.db.records[uid].operation_id for uid in outputs], [operation]*2)
        project = SessionProject('multi_cam', save_root=Path(self.temp.name)/'saved-group')
        self.addCleanup(project.dispose)
        project.database = self.db
        saved = project.save({})
        restored, _ = SessionProject.load(saved, 'multi_cam')
        self.addCleanup(restored.dispose)
        from ui_v2.frame_database import FrameBrowser
        restored_browser = FrameBrowser(restored.database)
        self.addCleanup(restored_browser.deleteLater)
        self.assertIs(restored_browser._items[outputs[0]].parent(),
                      restored_browser._items[outputs[1]].parent())
        self.assertEqual(restored.database.records[outputs[0]].output_role, 'inside')
        for uid, data in before.items():
            self.assertEqual((self.db.directory/'frames'/uid/'pointmap.ply').read_bytes(), data)
        # Old readers ignore the optional top-level map; old sessions have none.
        index = self.db.directory/'index.json'
        data = json.loads(index.read_text(encoding='utf-8'))
        self.assertEqual(data['schema'], 1)
        self.assertNotIn('operation_id', data['records'][0])
        data.pop('operations')
        index.write_text(json.dumps(data), encoding='utf-8')
        self.db.open_project(index)
        self.browser.refresh()
        self.assertIsNot(self.browser._items[outputs[0]].parent(),
                         self.browser._items[outputs[1]].parent())
        self.assertEqual(set(self.browser._items), set(self.db.records))

    def test_split_index_failure_rolls_back_both_branches(self):
        _, source, _ = self.load_grid()
        layer = self.editor._clouds[source]
        self.editor._segment = (source, layer, np.arange(100) < 40, self.editor._view())
        before = set(self.db.records)
        index = (self.db.directory / 'index.json').read_bytes()
        with patch.object(self.db, '_save_index', side_effect=OSError('split disk full')):
            self.editor.apply_segment(False)
            self.wait(lambda: self.editor._worker is None)
        self.assertEqual(set(self.db.records), before)
        self.assertEqual((self.db.directory / 'index.json').read_bytes(), index)
        self.assertIs(self.editor._clouds[source], layer)
        self.assertFalse(self.editor._undo)

    def test_index_failure_keeps_previous_preview_and_database(self):
        _, source, _ = self.load_grid()
        before = set(self.db.records)
        with patch.object(self.db, '_save_index', side_effect=OSError('disk full')):
            self.editor.downsample('random')
            self.wait(lambda: self.editor._worker is None)
        self.assertEqual(set(self.db.records), before)
        self.assertEqual(self.editor._display_ids, [source])
        self.assertIn('disk full', self.editor.status.text())
        self.assertTrue(self.editor.actions['open'].isEnabled())

    def test_merge_uses_db_inputs_and_preserves_mixed_colors(self):
        _, source, _ = self.load_grid()
        other = self.db.publish_result(cloud([[20, 20, 20]]), [], postprocess=True)
        self.editor.source_browser.refresh()
        self.editor.load_selected([source, other])
        self.finish()
        original = self.editor._clouds[source]
        self.editor.merge_selected()
        self.finish()
        merged = self.editor._clouds[self.editor._display_ids[0]]
        self.assertEqual(len(merged.points), 101)
        np.testing.assert_allclose(merged.colors[:100], original.colors)
        self.assertEqual(self.db.records[merged.origins[0][0]].source_ids, [source, other])
        self.assertIn(source, self.db.records)
        self.assertIn(other, self.db.records)

    def test_chained_processing_and_undo_restore_direct_db_sources(self):
        _, source, _ = self.load_grid()
        self.editor.downsample('random'); self.finish()
        first = self.editor._display_ids[0]
        self.editor.downsample('random'); self.finish()
        second = self.editor._display_ids[0]
        self.assertEqual(self.db.records[second].source_ids, [first])
        self.editor.undo(); self.finish()
        self.assertEqual(self.editor._display_ids, [first])
        self.editor.undo(); self.finish()
        self.assertEqual(self.editor._display_ids, [source])
        self.assertEqual(len(self.db.records), 2)

    def test_undo_rejects_result_referenced_by_another_branch(self):
        self.load_grid()
        self.editor.downsample('random'); self.finish()
        output = self.editor._display_ids[0]
        self.db.publish_result(cloud([[1, 2, 3]]), [output], postprocess=True)
        self.editor.undo()
        self.wait(lambda: self.editor._worker is None)
        self.assertIn('已有派生数据', self.editor.status.text())
        self.assertIn(output, self.db.records)
        self.assertTrue(self.editor._undo)

    def test_confirmed_polygon_locks_navigation_until_cancel(self):
        self.load_grid()
        editor = self.editor
        canvas = editor.viewer.canvas
        w, h = canvas.width(), canvas.height()
        editor.stage_polygon([(0, 0), (w, 0), (w, h), (0, h)])
        self.finish()
        view = editor._view()
        segment = editor._segment
        self.assertTrue(editor.overlay.view_locked)
        self.assertFalse(editor.overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertFalse(editor.actions['fit'].isEnabled())
        self.assertFalse(editor.properties.isEnabled())
        for target in (canvas, editor.overlay):
            for button in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
                QTest.mousePress(target, button, pos=QPoint(100, 100))
                move = QMouseEvent(QEvent.MouseMove, QPointF(140, 130), QPointF(140, 130),
                                   Qt.NoButton, button, Qt.NoModifier)
                self.app.sendEvent(target, move)
                QTest.mouseRelease(target, button, pos=QPoint(140, 130))
            wheel = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(), QPoint(0, 120),
                                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            self.app.sendEvent(target, wheel)
            QTest.keyClick(target, Qt.Key_F)
            QTest.keyClick(target, Qt.Key_Z)
        self.app.processEvents()
        for key, value in view.items():
            np.testing.assert_array_equal(editor._view()[key], value)
        self.assertIs(editor._segment, segment)
        QTest.keyClick(editor.overlay, Qt.Key_Escape)
        self.assertIsNone(editor._segment)
        self.assertFalse(editor.overlay.view_locked)
        self.assertTrue(editor.actions['fit'].isEnabled())
        self.assertTrue(editor.properties.isEnabled())
        self.app.sendEvent(canvas, wheel)
        self.assertGreater(canvas.zoom, view['zoom'])
        editor.stage_polygon([(0, 0), (w, 0), (w, h), (0, h)])
        self.finish()
        editor.start_polygon()
        self.assertFalse(editor.overlay.view_locked)
        self.assertTrue(editor.actions['fit'].isEnabled())
        editor.overlay.cancel()

    def test_cancel_during_mask_computation_does_not_restore_old_selection(self):
        self.load_grid()
        gate = threading.Event()
        started = threading.Event()
        def slow_mask(*args, **kwargs):
            started.set()
            gate.wait(3)
            return polygon_crop_mask(*args, **kwargs)
        w, h = self.editor.viewer.canvas.width(), self.editor.viewer.canvas.height()
        polygon = [(0, 0), (w, 0), (w, h), (0, h)]
        with patch('ui_v2.postprocess.window.polygon_crop_mask', slow_mask):
            self.editor.stage_polygon(polygon)
            try:
                self.wait(started.is_set)
                self.assertTrue(self.editor.overlay.view_locked)
                self.editor.overlay.cancel()
            finally:
                gate.set()
            self.finish()
        self.assertIsNone(self.editor._segment)
        self.assertFalse(self.editor.overlay.view_locked)
        with patch('ui_v2.postprocess.window.polygon_crop_mask', side_effect=ValueError('mask failure')):
            self.editor.stage_polygon(polygon)
            self.wait(lambda: self.editor._worker is None)
        self.assertIn('mask failure', self.editor.status.text())
        self.assertFalse(self.editor.overlay.view_locked)
        self.assertTrue(self.editor.actions['fit'].isEnabled())

    def test_applying_confirmed_polygon_releases_navigation(self):
        self.load_grid()
        canvas = self.editor.viewer.canvas
        w, h = canvas.width(), canvas.height()
        self.editor.stage_polygon([(0, 0), (w, 0), (w, h), (0, h)])
        self.finish()
        self.editor.apply_segment(True)
        self.finish()
        self.assertFalse(self.editor.overlay.view_locked)
        self.assertFalse(self.editor.overlay.active)
        self.assertTrue(self.editor.actions['fit'].isEnabled())

    def test_stage_view_and_resize_guards(self):
        _, source, _ = self.load_grid()
        layer = self.editor._clouds[source]
        self.editor._segment = (source, layer, np.arange(100)<40, self.editor._view())
        self.editor.viewer.canvas.zoom *= 2
        self.editor.apply_segment(True)
        self.assertIn('重新框选', self.editor.status.text())
        w, h = self.editor.viewer.canvas.width(), self.editor.viewer.canvas.height()
        self.editor.stage_polygon([(-w,-h),(2*w,-h),(2*w,2*h),(-w,2*h)])
        self.finish()
        self.assertEqual(int(self.editor._segment[2].sum()), 100)
        self.editor.resize(1300,800); self.app.processEvents()
        self.assertIsNone(self.editor._segment)
        self.assertFalse(self.editor.overlay.view_locked)
        self.assertEqual(len(self.db.records), 2)

    def test_stale_source_and_project_change_refuse_automatic_commit(self):
        uid, source, _ = self.load_grid()
        self.db.replace_capture(uid, self.source(2))
        self.editor.downsample('random')
        self.wait(lambda: self.editor._worker is None)
        self.assertIn('来源数据', self.editor.status.text())
        self.assertEqual(len(self.db.records), 2)
        directory = self.db.directory
        self.db.directory = directory/'changed'
        try:
            self.editor.downsample('random')
            self.wait(lambda: self.editor._worker is None)
            self.assertIn('项目已切换', self.editor.status.text())
            self.assertEqual(len(self.db.records), 2)
        finally:
            self.db.directory = directory

    def test_external_import_converts_units_and_automatically_joins_db(self):
        from PySide6.QtCore import QTimer
        target = Path(self.temp.name)/'meters.ply'
        o3d.io.write_point_cloud(str(target), cloud([[.1,.2,.3]]))
        source_bytes = target.read_bytes()
        for unit, expected in (('mm', [[.1,.2,.3]]), ('m', [[100,200,300]])):
            def choose():
                dialog = self.app.activeModalWidget()
                dialog.file_unit.setCurrentIndex(dialog.file_unit.findData(unit))
                dialog.execute_button.click()
            QTimer.singleShot(0, choose)
            with patch('ui_v2.postprocess.window.QFileDialog.getOpenFileName', return_value=(str(target),'')):
                self.editor.actions['open'].click(); self.finish()
            uid = self.editor._display_ids[0]
            np.testing.assert_allclose(self.editor._clouds[uid].points, expected)
            self.assertEqual(self.db.records[uid].source_ids, [])
            self.assertIn(uid, self.browser._items)
            self.assertEqual(target.read_bytes(), source_bytes)
            self.editor.undo(); self.finish()
            self.assertFalse(self.db.records)
            self.assertIn(uid, self.db.removed)

    def test_hidden_selected_db_cloud_can_export_full_source(self):
        _, source, _ = self.load_grid()
        self.editor.source_browser.set_component_checked(source, 'cloud', False)
        self.finish()
        self.assertFalse(self.editor._display_ids)
        target = Path(self.temp.name)/'selected.ply'
        with patch('ui_v2.postprocess.window.QFileDialog.getSaveFileName', return_value=(str(target),'')):
            self.editor.export_selected(); self.finish()
        self.assertEqual(len(o3d.io.read_point_cloud(str(target)).points), 100)

    def test_multi_export_cannot_overwrite_db_source_files(self):
        uid, result, _ = self.load_grid()
        self.editor.load_selected([uid, result]); self.finish()
        target = self.db.directory/'frames'/uid/'pointmap.ply'
        before = target.read_bytes()
        with patch('ui_v2.postprocess.window.QFileDialog.getSaveFileName', return_value=(str(target),'')):
            self.editor.export_selected()
            self.wait(lambda:self.editor._worker is None)
        self.assertIn('DB 内部', self.editor.status.text())
        self.assertEqual(target.read_bytes(), before)

    def test_saved_session_contains_automatic_outputs(self):
        uid, source, _ = self.load_grid()
        self.editor.downsample('random'); self.finish()
        result = self.editor._display_ids[0]
        project = SessionProject('multi_cam', save_root=Path(self.temp.name)/'saved')
        self.addCleanup(project.dispose)
        project.database = self.db
        saved = project.save({})
        restored, _ = SessionProject.load(saved, 'multi_cam')
        self.addCleanup(restored.dispose)
        self.assertEqual(restored.database.records[result].source_ids, [source])
        self.assertEqual(len(restored.database.load_frame(result, 'cloud')[1].points), 50)
        self.db.replace_capture(uid,self.source(2))
        self.assertEqual(self.db.records[result].status, STALE_RESULT)

    def test_close_busy_guard_and_shutdown_drop_late_callback(self):
        release = threading.Event()
        completed = []
        self.editor._run(lambda:release.wait(4), completed.append)
        self.editor.reject()
        self.assertFalse(self.editor._closed)
        self.assertIn('等待',self.editor.status.text())
        release.set();self.finish()
        self.editor._run(lambda:release.wait(4),completed.append)
        self.editor.shutdown()
        self.app.processEvents()
        self.wait(lambda:self.editor._worker is None)
        self.assertEqual(len(completed),1)


if __name__ == '__main__':
    unittest.main()
