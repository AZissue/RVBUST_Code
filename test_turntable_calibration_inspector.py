"""Turntable result snapshots, direction conventions and read-only inspection."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import open3d as o3d
import test_ui_frame_database as fixtures
from core.turntable_calibrator import rotation_direction, rodrigues
from core.session_project import SessionProject


class DirectionTests(unittest.TestCase):
    def test_camera_view_direction_and_axis_sign_equivalence(self):
        self.assertEqual(rotation_direction([0, 0, 1], .5), '顺时针')
        self.assertEqual(rotation_direction([0, 0, -1], .5), '逆时针')
        self.assertEqual(rotation_direction([0, 0, -1], -.5), '顺时针')
        self.assertIn('侧视', rotation_direction([1, 0, 0], .5))
        self.assertEqual(rotation_direction([0, 0, 1], 0), '无法判定')
        self.assertIn('180°', rotation_direction([0, 0, 1], np.pi))


class TurntableInspectorTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.FrameBrowserTests.setUpClass.__func__)
    setUp = fixtures.FrameBrowserTests.setUp
    source = fixtures.FrameBrowserTests.source
    wait = fixtures.FrameBrowserTests.wait

    def tearDown(self):
        dialog = getattr(self.bridge, '_turntable_calibration_inspector', None)
        if dialog is not None and dialog.active:
            dialog.reject()
        fixtures.FrameBrowserTests.tearDown(self)

    def calibrate(self, angle_deg=30., extra=(0, 0, 0)):
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        ws = self.win.workspace_turntable()
        database = self.bridge.frame_db.databases['turntable']
        points = np.random.default_rng(23).normal(size=(8, 3))*30 + [10, 20, 500]
        rotation = rodrigues(np.array([0., 0., 1.]), np.radians(angle_deg))
        center = np.array([10., -20., 500.])
        moved = (points-center) @ rotation.T + center + np.asarray(extra)
        for index, xyz in enumerate((points, moved)):
            frame = self.source(index+1)
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(xyz)
            o3d.io.write_point_cloud(frame.offline_pointmap_path, cloud)
            frame.markers = [dict(code=i+10, x_2d=1, y_2d=1, x_3d=p[0], y_3d=p[1], z_3d=p[2])
                             for i, p in enumerate(xyz)]
            frame.markers_all = frame.markers
            database.ingest(frame, purpose=f'转台标定 frame{index}')
            getattr(ws.session, f'set_frame{index}')(frame, frame.markers, cloud)
        ok, message, _ = ws.session.calibrate()
        self.assertTrue(ok, message)
        ws.session.calibration_result['source_revisions'] = {uid: row.revision for uid, row in database.records.items()}
        ws._update_online_ui()
        return ws, database, points, moved

    def open(self, ws):
        ws.calibration_visualization_requested.emit()
        dialog = self.bridge._turntable_calibration_inspector
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        return dialog

    def test_result_survives_frame_release_aligns_clouds_and_roundtrips(self):
        ws, database, points, moved = self.calibrate()
        snapshot = copy.deepcopy(ws.session.calibration_result)
        self.assertIsNone(ws.session.frame0)
        self.assertEqual(len(snapshot['result']['details']), 8)
        self.assertLess(snapshot['result']['rms_all_mm'], 1e-8)
        self.assertIn('顺时针', ws._industrial.calibration_panel.values.text())
        before = {uid: (database.directory/'frames'/uid/'pointmap.ply').read_bytes() for uid in database.records}
        dialog = self.open(ws)
        self.assertEqual(dialog.table.rowCount(), 8)
        np.testing.assert_allclose(np.asarray(dialog.viewer._pcds['旋转帧'].points), points, atol=1e-5)
        self.assertIsNotNone(dialog.viewer.canvas._rotation_geometry)
        self.assertIn('+Z', dialog.model_info.text())
        self.assertEqual(before, {uid: (database.directory/'frames'/uid/'pointmap.ply').read_bytes() for uid in database.records})
        project = self.bridge.projects.projects['turntable']
        project.save_root = Path(self.temp.name)/'saved'
        saved = project.save(self.bridge.projects.describe('turntable', True), include_raw=True)
        loaded, data = SessionProject.load(saved, 'turntable', project.save_root)
        try:
            session, _ = self.bridge.projects.prepare_loaded(loaded, data)
            self.assertEqual(session.calibration_result, snapshot)
            self.assertEqual(rotation_direction(session.calib.axis, session.calib.angle_rad), '顺时针')
        finally:
            loaded.dispose()
        ws.session.reset()
        ws._update_online_ui()
        self.assertFalse(ws._industrial.calibration_panel.visualize.isEnabled())

    def test_old_result_and_changed_source_are_explicit_and_busy_is_blocked(self):
        ws, database, _, _ = self.calibrate()
        uid = next(iter(database.records))
        database.records[uid].revision += 1
        dialog = self.open(ws)
        self.assertNotIn('初始帧', dialog.clouds)
        self.assertIn('已被替换', dialog.status.text())
        dialog.reject()
        self.app.processEvents()
        ws.session.calibration_result = None
        dialog = self.open(ws)
        self.assertIn('历史标定', dialog.status.text())
        self.assertEqual(dialog.table.rowCount(), 0)
        self.assertIsNotNone(dialog.viewer.canvas._rotation_geometry)
        dialog.reject()
        self.app.processEvents()
        with patch.object(self.bridge, 'can_change_workspace', return_value=False), \
                patch.object(self.bridge, '_run_background') as run:
            ws.calibration_visualization_requested.emit()
            run.assert_not_called()
        with patch.object(self.bridge, '_run_background', side_effect=lambda work, done, **kw: done(None, 'test load error')):
            ws.calibration_visualization_requested.emit()
            dialog = self.bridge._turntable_calibration_inspector
            self.assertIn('读取标定点云失败', dialog.status.text())

    def test_closed_dialog_ignores_late_cloud_callback(self):
        ws, _, _, _ = self.calibrate()
        callbacks = []
        with patch.object(self.bridge, '_run_background', side_effect=lambda work, done, **kw: callbacks.append(done)):
            ws.calibration_visualization_requested.emit()
        dialog = self.bridge._turntable_calibration_inspector
        dialog.reject()
        callbacks[0](({'初始帧': np.ones((4,3))}, []), None)
        self.assertEqual(dialog.clouds, {})

    def test_animation_follows_axis_arc_preserves_inputs_and_stops_on_close(self):
        from PySide6.QtWidgets import QPushButton
        from core.turntable_calibrator import transform_matrix
        ws, database, points, moved = self.calibrate()
        self.assertIsInstance(ws._industrial.calibration_panel.visualize, QPushButton)
        original = copy.deepcopy(ws.session.calibration_result)
        dialog = self.open(ws)
        self.assertTrue(dialog.animation_bar.isEnabled())
        raw = dialog.clouds['旋转帧'].copy()
        reference = np.asarray(dialog.viewer._pcds['初始帧'].points).copy()
        canvas = dialog.viewer.canvas
        center, zoom = canvas.center.copy(), canvas.zoom
        for progress in (0, 500, 1000):
            dialog.progress.setValue(progress)
            calib = ws.session.calib
            transform = transform_matrix(calib.axis, -calib.angle_rad*progress/1000, calib.center)
            expected = raw @ transform[:3,:3].T + transform[:3,3]
            np.testing.assert_allclose(np.asarray(dialog.viewer._pcds['旋转帧'].points), expected, atol=1e-8)
            np.testing.assert_allclose(dialog.viewer._pcds['初始帧'].points, reference)
            np.testing.assert_allclose(canvas.center, center)
            self.assertEqual(canvas.zoom, zoom)
        dialog.play_button.click()
        self.assertTrue(dialog.animation_timer.isActive())
        self.wait(lambda: dialog.progress.value() > 0)
        dialog.play_button.click()
        self.assertFalse(dialog.animation_timer.isActive())
        paused = dialog.progress.value()
        self.assertGreater(paused, 0)
        dialog.replay_button.click()
        self.assertEqual(dialog.progress.value(), 0)
        self.assertTrue(dialog.animation_timer.isActive())
        dialog.progress.setValue(500)
        self.assertFalse(dialog.animation_timer.isActive())
        dialog.error_filter.setCurrentIndex(1)
        dialog.table.selectRow(0)
        self.assertEqual(dialog.progress.value(), 1000)
        dialog.view_choice.setCurrentIndex(1)
        self.assertFalse(dialog.animation_bar.isEnabled())
        dialog.view_choice.setCurrentIndex(0)
        self.assertTrue(dialog.animation_bar.isEnabled())
        dialog.replay_button.click()
        self.wait(lambda: dialog.progress.value() == 1000 and not dialog.animation_timer.isActive())
        np.testing.assert_allclose(dialog.viewer._pcds['旋转帧'].points, points, atol=1e-5)
        dialog.replay_button.click()
        dialog.reject()
        self.assertFalse(dialog.animation_timer.isActive())
        self.assertEqual(ws.session.calibration_result, original)
        np.testing.assert_array_equal(dialog.clouds['旋转帧'], raw)

    def test_animation_disabled_with_missing_source_and_recovers_on_load(self):
        ws, _, _, _ = self.calibrate()
        dialog = self.open(ws)
        clouds = dict(dialog.clouds)
        dialog.set_clouds({'初始帧': clouds['初始帧']})
        self.assertFalse(dialog.animation_bar.isEnabled())
        dialog._toggle_play()
        self.assertFalse(dialog.animation_timer.isActive())
        dialog.set_clouds(clouds)
        self.assertTrue(dialog.animation_bar.isEnabled())

    def test_confidence_warnings_are_visible_without_blocking_visualization(self):
        from PySide6.QtWidgets import QLabel
        ws, _, _, _ = self.calibrate(.2, (50, 0, 5))
        panel = ws._industrial.calibration_panel
        self.assertIn('建议复核', panel.status.text())
        self.assertTrue(panel.visualize.isEnabled())
        for name in ('小角度', '轴向位移', '轴心距离'):
            self.assertIn(name, panel.warning.text())
        dialog = self.open(ws)
        self.assertEqual(dialog.confidence_report['state'], 'warning')
        texts = '\n'.join(label.text() for label in dialog.confidence_page.findChildren(QLabel))
        for name in ('小角度', '轴向位移', '轴心距离', '不阻断拼接'):
            self.assertIn(name, texts)
        self.assertIn('需复核', dialog.model_info.text())


if __name__ == '__main__':
    unittest.main()
