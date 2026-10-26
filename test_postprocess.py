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
from core.postprocess.session import CloudLayer, PostProcessSession, write_cloud
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

    def test_owned_arrays_and_bounded_undo(self):
        points = np.array([[1., 2, 3], [np.nan, 0, 0]])
        layer = CloudLayer('original', points, [[1, 0, 0], [0, 1, 0]])
        points[0] = 99
        np.testing.assert_array_equal(layer.points, [[1, 2, 3]])
        self.assertFalse(layer.points.flags.writeable)
        self.assertFalse(layer.colors.flags.writeable)
        session = PostProcessSession([layer])
        for i in range(12):
            session.snapshot()
            session.layers = [CloudLayer(str(i), [[i, 0, 0]])]
        self.assertEqual(len(session._undo), 8)
        self.assertTrue(session.undo())
        self.assertEqual(session.layers[0].name, '10')


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
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                self.editor.close()
        fixture.FrameBrowserTests.tearDown(self)

    def finish(self):
        self.wait(lambda: self.editor._worker is None)
        self.assertNotIn('失败', self.editor.status.text())

    def load_grid(self):
        uid = self.db.ingest(self.source())
        points = np.array([[x, y, 1] for x in range(10) for y in range(10)], float)
        colors = np.tile([.2, .4, .6], (100, 1))
        result = self.db.publish_result(cloud(points, colors), [uid])
        self.editor.load_selected([result])
        self.finish()
        self.assertEqual(len(self.editor.session.layers), 1)
        return uid, result, points

    def select(self, *indices):
        tree = self.editor.panel.tree
        tree.clearSelection()
        tree.setCurrentItem(self.editor.panel._items[indices[0]])
        for index in indices:
            self.editor.panel._items[index].setSelected(True)

    def test_entry_reuses_window_and_shared_db_without_reset(self):
        self.assertIs(self.bridge.open_postprocess(), self.editor)
        self.assertIs(self.editor.source_browser.database, self.db)
        self.assertFalse(self.editor.viewer.toolbar.isVisible())
        self.assertTrue(self.win._industrial_ribbon.postprocess_button.isVisible())
        self.assertFalse(getattr(self.bridge, '_sdk_initialized', False))
        self.editor.close()
        self.app.processEvents()
        self.assertIsNone(self.bridge._postprocess_window)

    def test_entry_in_each_mode_and_busy_gate(self):
        self.editor.close()
        self.app.processEvents()
        for mode in ('mobile_chain', 'turntable', 'multi_cam'):
            self.win.set_mode(mode, [])
            self.editor = self.bridge.open_postprocess()
            self.assertEqual(self.editor.mode, mode)
            self.assertIs(self.editor.database, self.bridge.frame_db.databases[mode])
            self.editor.close()
            self.app.processEvents()
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            self.assertIsNone(self.bridge.open_postprocess())

    def test_external_file_units_and_failed_processing_preserve_layer(self):
        target = Path(self.temp.name)/'meters.ply'
        o3d.io.write_point_cloud(str(target), cloud([[.1, .2, .3]]))
        self.editor.file_unit.setCurrentIndex(1)
        with patch('ui_v2.postprocess.window.QFileDialog.getOpenFileName', return_value=(str(target), '')):
            self.editor.open_file()
            self.finish()
        layer = self.editor.session.layers[0]
        np.testing.assert_allclose(layer.points, [[100, 200, 300]])
        with patch('ui_v2.postprocess.window.voxel_downsample', side_effect=ValueError('test rejection')):
            self.editor.downsample('voxel')
            self.wait(lambda: self.editor._worker is None)
        self.assertIs(self.editor.session.layers[0], layer)
        self.assertFalse(self.editor.session.can_undo)
        self.assertTrue(self.editor.actions['publish'].isEnabled())
        self.assertIn('test rejection', self.editor.status.text())

    def test_visibility_on_reopened_db_keeps_emitting_tree_item_alive(self):
        from shiboken6 import isValid
        _, result, _ = self.load_grid()
        self.editor.close()
        self.app.processEvents()
        self.browser.set_component_checked(result, 'cloud')
        self.wait(lambda: bool(self.win.workspace_multi().viewer()._database_clouds))
        self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
        self.editor = self.bridge.open_postprocess()
        self.finish()
        panel = self.editor.panel
        item = panel._items[0]
        root = item.parent()
        original = self.editor.session.layers[0].points.copy()
        # A no-op mock makes regression fail safely instead of deleting the
        # QTreeWidgetItem from inside its native setData notification stack.
        with patch.object(panel, 'refresh') as rebuild:
            for visible in (False, True, False, True):
                item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
                self.app.processEvents()
                self.assertEqual(self.editor.session.layers[0].visible, visible)
                self.assertEqual(len(self.editor.viewer._layers), int(visible))
                self.assertTrue(isValid(item))
                self.assertIs(panel._items[0], item)
                self.assertIs(item.parent(), root)
            rebuild.assert_not_called()
        np.testing.assert_array_equal(self.editor.session.layers[0].points, original)
        self.assertEqual(len(self.db.records), 2)

    def test_load_and_downsample_are_background_and_original_unchanged(self):
        uid, result, points = self.load_grid()
        raw = self.db.directory/'frames'/result/'pointmap.ply'
        before = raw.read_bytes()
        layer = self.editor.session.layers[0]
        np.testing.assert_allclose(layer.points, points)
        self.assertEqual(layer.origins, ((result, self.db.records[result].revision),))
        from core.postprocess import processing
        threads = []
        def run(*args):
            threads.append(threading.get_ident())
            return processing.voxel_downsample(*args)
        self.editor.viewer.canvas.zoom = 1.3
        view = self.editor._view()
        self.editor.voxel.setValue(3)
        with patch('ui_v2.postprocess.window.voxel_downsample', side_effect=run):
            self.editor.downsample('voxel')
            self.assertFalse(self.editor.actions['publish'].isEnabled())
            self.finish()
        self.assertNotEqual(threads, [threading.get_ident()])
        self.assertEqual(len(self.editor.session.layers[0].points), 16)
        for key, value in view.items():
            np.testing.assert_allclose(self.editor._view()[key], value)
        self.assertEqual(raw.read_bytes(), before)
        self.editor.undo()
        self.assertIs(self.editor.session.layers[0], layer)
        self.assertEqual(len(self.db.records), 2)

    def test_polygon_split_conserves_points_colors_and_undo(self):
        self.load_grid()
        original = self.editor.session.layers[0]
        view = self.editor._view()
        mask = np.arange(100) < 40
        self.editor._segment = (0, original, mask, view)
        self.editor.apply_segment(True)
        self.finish()
        kept, branch = self.editor.session.layers
        self.assertEqual([len(kept.points), len(branch.points)], [40, 60])
        np.testing.assert_array_equal(np.vstack([kept.points, branch.points]), original.points)
        np.testing.assert_array_equal(np.vstack([kept.colors, branch.colors]), original.colors)
        self.assertEqual(branch.origins, original.origins)
        self.editor.undo()
        self.assertEqual(len(self.editor.session.layers), 1)
        self.assertIs(self.editor.session.layers[0], original)

    def test_staged_polygon_rejects_changed_view(self):
        self.load_grid()
        original = self.editor.session.layers[0]
        self.editor._segment = (0, original, np.arange(100) < 40, self.editor._view())
        self.editor.viewer.canvas.zoom *= 2
        self.editor.apply_segment(True)
        self.assertIsNone(self.editor._worker)
        self.assertIn('重新框选', self.editor.status.text())
        self.assertIs(self.editor.session.layers[0], original)

    def test_stage_polygon_and_merge_recycle(self):
        self.load_grid()
        view = self.editor._view()
        w, h = view['width'], view['height']
        self.editor.stage_polygon([(-w, -h), (2*w, -h), (2*w, 2*h), (-w, 2*h)])
        self.finish()
        self.assertIsNotNone(self.editor._segment)
        self.assertEqual(int(self.editor._segment[2].sum()), 100)
        self.assertNotIn('正在后台', self.editor.status.text())
        self.editor.resize(1300, 800)
        self.app.processEvents()
        self.assertIsNone(self.editor._segment)
        original = self.editor.session.layers[0]
        self.editor.session.layers.append(CloudLayer('uncolored', [[20, 20, 20]]))
        self.editor._refresh()
        self.select(0, 1)
        self.editor.merge_selected()
        self.finish()
        merged = self.editor.session.layers[0]
        self.assertEqual(len(merged.points), 101)
        np.testing.assert_allclose(merged.colors[:100], original.colors)
        self.assertEqual(merged.origins, original.origins)
        self.editor.remove_layers([0])
        self.assertFalse(self.editor.session.can_undo)
        self.assertEqual(len(self.editor.session.layers), 0)
        self.editor.restore_removed()
        self.assertIs(self.editor.session.layers[0], merged)
        self.assertEqual(len(self.db.records), 2)

    def test_publish_branch_export_and_reopen_saved_session(self):
        uid, stitched, _ = self.load_grid()
        self.editor.ratio.setValue(50)
        self.editor.downsample('random')
        self.finish()
        self.editor.publish_selected()
        self.finish()
        result = list(self.db.records)[-1]
        record = self.db.records[result]
        self.assertEqual(record.purpose, '后处理结果')
        self.assertEqual(record.source_ids, [stitched])
        self.assertEqual(record.points, 50)
        self.assertEqual(self.browser._items[result].parent().text(0), '后处理结果')
        self.assertTrue(self.win._dirty)
        target = Path(self.temp.name)/'export.ply'
        self.db.export_cloud(result, target)
        self.assertEqual(len(o3d.io.read_point_cloud(str(target)).points), 50)
        # Public session storage is compatible without any new format or schema.
        project = SessionProject('multi_cam', save_root=Path(self.temp.name)/'saved')
        self.addCleanup(project.dispose)
        project.database = self.db
        saved = project.save({})
        restored, data = SessionProject.load(saved, 'multi_cam')
        self.addCleanup(restored.dispose)
        self.assertEqual(restored.database.records[result].source_ids, [stitched])
        self.assertEqual(len(restored.database.load_frame(result, 'cloud')[1].points), 50)
        derived = self.db.publish_result(cloud([[1, 2, 3]]), [result], postprocess=True)
        self.db.replace_capture(uid, self.source(2))
        for key in (stitched, result, derived):
            self.assertEqual(self.db.records[key].status, STALE_RESULT)

    def test_replaced_source_refuses_publish_and_stale_load(self):
        uid, stitched, _ = self.load_grid()
        self.db.replace_capture(uid, self.source(2))
        self.editor.publish_selected()
        self.wait(lambda: self.editor._worker is None)
        self.assertIn('来源数据', self.editor.status.text())
        self.assertEqual(len(self.db.records), 2)
        self.editor.load_selected([stitched])
        self.wait(lambda: self.editor._worker is None)
        self.assertEqual(len(self.editor.session.layers), 1)
        self.assertIn('来源数据', self.editor.status.text())

    def test_external_result_and_atomic_failure(self):
        self.editor.session.layers.append(CloudLayer('external', [[1, 2, 3]]))
        self.editor._refresh(select=0)
        before = set(self.db.records)
        with patch('core.utils.write_point_cloud_atomic', return_value=False):
            self.editor.publish_selected()
            self.wait(lambda: self.editor._worker is None)
        self.assertIn('写入失败', self.editor.status.text())
        self.assertEqual(set(self.db.records), before)
        self.assertFalse(list((self.db.directory/'frames').iterdir()))
        self.editor.publish_selected()
        self.finish()
        record = next(iter(self.db.records.values()))
        self.assertEqual(record.source_ids, [])
        self.assertEqual(record.purpose, '后处理结果')

    def test_export_selection_ignores_hidden_and_other_layers(self):
        self.load_grid()
        layer = self.editor.session.layers[0]
        layer.visible = False
        self.editor.session.layers.append(CloudLayer('not selected', [[100, 200, 300]]))
        self.editor._refresh(select=0)
        target = Path(self.temp.name)/'selected.ply'
        with patch('ui_v2.postprocess.window.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            self.editor.export_selected()
            self.finish()
        actual = o3d.io.read_point_cloud(str(target))
        self.assertEqual(len(actual.points), 100)
        np.testing.assert_allclose(actual.points, layer.points)

    def test_shutdown_waits_for_work_and_drops_late_callback(self):
        release = threading.Event()
        completed = []
        self.editor._run(lambda: release.wait(4), completed.append)
        timer = threading.Timer(.02, release.set)
        timer.start()
        self.editor.shutdown()
        timer.join()
        self.app.processEvents()
        self.wait(lambda: self.editor._worker is None)
        self.assertEqual(completed, [])
        self.assertFalse(self.bridge._workers)

    def test_close_and_escape_cannot_bypass_busy_or_unsaved_guard(self):
        release = threading.Event()
        try:
            self.editor._run(lambda: release.wait(4), lambda _: None)
            self.editor.reject()
            self.assertFalse(self.editor._closed)
            self.assertIn('等待', self.editor.status.text())
        finally:
            release.set()
        self.finish()
        self.editor.session.layers.append(CloudLayer('unsaved', [[1, 2, 3]]))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question:
            self.editor.reject()
            question.assert_called_once()
            self.assertFalse(self.editor._closed)


if __name__ == '__main__':
    unittest.main()
