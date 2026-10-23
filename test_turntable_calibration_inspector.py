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

    def calibrate(self):
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        ws = self.win.workspace_turntable()
        database = self.bridge.frame_db.databases['turntable']
        points = np.random.default_rng(23).normal(size=(8, 3))*30 + [10, 20, 500]
        rotation = rodrigues(np.array([0., 0., 1.]), np.radians(30))
        center = np.array([10., -20., 500.])
        moved = (points-center) @ rotation.T + center
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


if __name__ == '__main__':
    unittest.main()
