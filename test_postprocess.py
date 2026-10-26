"""Offline postprocess geometry, DB lineage and production UI integration (no SDK)."""
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import open3d as o3d
import test_ui_frame_database as fixture
from PySide6.QtCore import Qt
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
        self.editor.voxel.setValue(3)
        from core.postprocess import processing
        threads = []
        def run(*args):
            threads.append(threading.get_ident())
            return processing.voxel_downsample(*args)
        with patch('ui_v2.postprocess.window.voxel_downsample', side_effect=run):
            self.editor.downsample('voxel')
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
        target = Path(self.temp.name)/'meters.ply'
        o3d.io.write_point_cloud(str(target), cloud([[.1,.2,.3]]))
        self.editor.file_unit.setCurrentIndex(1)
        with patch('ui_v2.postprocess.window.QFileDialog.getOpenFileName', return_value=(str(target),'')):
            self.editor.open_file(); self.finish()
        uid = self.editor._display_ids[0]
        np.testing.assert_allclose(self.editor._clouds[uid].points, [[100,200,300]])
        self.assertEqual(self.db.records[uid].source_ids, [])
        self.assertIn(uid, self.browser._items)
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
