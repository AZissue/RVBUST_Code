"""Raw acquisition, transactional result publication and portable DB results."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import numpy as np
from PySide6.QtWidgets import QMessageBox
import test_ui_frame_database as fixture
from core.session_project import SessionProject


class ExplicitStitchingTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait
    source = fixture.FrameBrowserTests.source

    def mobile(self):
        self.win.set_mode('mobile_chain', [])
        self.bridge._current_mode = 'mobile_chain'
        self.db = self.bridge.frame_db.databases['mobile_chain']
        self.bridge.mobile_workflow.start_chaining()
        self.bridge.projects.prepare('mobile_chain')
        for i in (1, 2):
            frame = self.source(i)
            xyz = np.random.default_rng(42).normal(size=(8, 3))*100
            frame.markers = [dict(code=j, x_2d=1, y_2d=1, valid_3d=True,
                x_3d=float(v[0]+i*10), y_3d=float(v[1]), z_3d=float(v[2])) for j, v in enumerate(xyz)]
            frame.markers_all = frame.markers
            self.db.ingest(frame)
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        return self.win.workspace_mobile()

    def execute(self):
        self.win._industrial_ribbon.commands[('mobile_chain', 'stitch')].click()
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))

    def test_manual_result_leaves_sources_intact_and_roundtrips_with_session(self):
        ws = self.mobile()
        self.assertEqual(self.bridge.mobile_workflow.get_station_evaluations(), [])
        self.assertIsNone(ws.viewer()._merged)
        raw = list(self.db.records)
        digest = lambda uid: hashlib.sha256((self.db.directory/'frames'/uid/'pointmap.ply').read_bytes()).hexdigest()
        before = {uid: digest(uid) for uid in raw}
        self.execute()
        result_ids = [uid for uid, row in self.db.records.items() if row.kind == 'result']
        self.assertEqual(len(result_ids), 1, self.win._st_hint.text())
        uid = result_ids[0]
        self.assertEqual(self.db.records[uid].source_ids, raw)
        self.assertEqual(before, {key: digest(key) for key in raw})
        self.assertEqual(len(self.bridge.mobile_workflow.get_station_evaluations()), 2)
        self.assertIn('拼接帧', ws._industrial.frame_browser._items[uid].text(0))
        self.assertTrue(ws.viewer().viewer().mode.isHidden())
        self.assertIsNotNone(ws.viewer()._database_cloud)
        self.assertFalse(ws._industrial.inspector.isVisible())
        project = self.bridge.projects.projects['mobile_chain']
        project.save_root = Path(self.temp.name)/'saved'
        saved = project.save(self.bridge.projects.describe('mobile_chain', True), include_raw=True)
        loaded, data = SessionProject.load(saved, 'mobile_chain', project.save_root)
        try:
            self.assertEqual(loaded.database.records[uid].source_ids, raw)
            frame, cloud = loaded.database.load_frame(uid)
            self.assertIsNone(frame.image_np)
            self.assertGreater(len(cloud.points), 0)
        finally:
            loaded.dispose()
        self.execute()
        self.assertEqual(sum(row.kind == 'result' for row in self.db.records.values()), 2)
        exported = Path(self.temp.name)/'result.ply'
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=(str(exported), '')):
            self.win._industrial_ribbon.commands[('mobile_chain', 'export')].click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertTrue(exported.is_file())
        self.assertEqual(sum(row.kind == 'result' for row in self.db.records.values()), 2)
        browser = ws._industrial.frame_browser
        browser.tree.clearSelection()
        browser.tree.setCurrentItem(browser._items[uid])
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        with patch('ui_v2.frame_database.QMessageBox.question', return_value=QMessageBox.Yes):
            self.bridge.frame_db.remove('mobile_chain', [uid])
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertNotIn(uid, self.db.records)
        self.assertIsNone(ws.viewer()._merged)
        self.bridge.frame_db.recover('mobile_chain')
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertIn(uid, self.db.records)

    def test_registration_failure_keeps_existing_chain_and_creates_no_result(self):
        self.mobile()
        original = self.bridge.mobile_workflow
        with patch('core.chain_stitcher.ChainStitcher.add_frame', return_value=(False, 'no common markers', None)):
            self.execute()
        self.assertIs(self.bridge.mobile_workflow, original)
        self.assertTrue(all(row.kind == 'raw' for row in self.db.records.values()))
        self.assertIn('no common markers', self.win._st_hint.text())

    def test_invalid_raw_slots_do_not_become_valid_after_pose_translation(self):
        import open3d as o3d
        from core.chain_stitcher import ChainNode
        self.mobile()
        original = o3d.geometry.PointCloud()
        original.points = o3d.utility.Vector3dVector([[0., 0., 0.], [float('nan'), 1., 2.], [1., 2., 3.]])
        frame = self.source()
        transform = np.eye(4)
        transform[0, 3] = 10
        with patch.object(frame, 'load_pointcloud_o3d', return_value=original):
            valid = self.bridge.mobile_workflow._chain_stitcher._cache_node_pcd(ChainNode('x', frame, [], transform))
        np.testing.assert_array_equal(np.asarray(valid.points), [[11., 2., 3.]])
        self.assertEqual(len(original.points), 3)

    def test_online_capture_stores_raw_without_registration(self):
        ws = self.mobile()
        frame = self.source(3)
        fake_sdk = SimpleNamespace(PointMapUnitEnum=SimpleNamespace(Millimeter=1),
            PointMap=SimpleNamespace(Destroy=Mock()), Image=SimpleNamespace(Destroy=Mock()))
        pm = Mock()
        pm.SaveWithImage.side_effect = lambda path, *args: Path(path).write_bytes(Path(frame.offline_pointmap_path).read_bytes()) or True
        self.bridge.camera_manager._cameras = {'cam0': SimpleNamespace(is_connected=True,
            capture_3d=lambda options: (frame.image_np, pm, object(), 'ok'))}
        with patch('core.frame_database._import_rvc', return_value=fake_sdk), \
             patch('core.frame_data._import_rvc', return_value=fake_sdk), \
             patch('core.chain_stitcher.ChainStitcher.add_frame', side_effect=AssertionError('capture must not register')):
            self.bridge._on_mobile_capture_station()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(len(self.db.records), 3)
        self.assertTrue(all(row.kind == 'raw' for row in self.db.records.values()))
        self.assertEqual(self.bridge.mobile_workflow.get_station_evaluations(), [])
        self.assertIsNone(ws.viewer()._merged)
        self.assertIsNotNone(ws.viewer()._database_cloud)
        fake_sdk.PointMap.Destroy.assert_called_once()

    def test_failed_result_write_publishes_nothing_and_preserves_previous_workflow(self):
        self.mobile()
        original = self.bridge.mobile_workflow
        with patch('core.utils.write_point_cloud_atomic', return_value=False):
            self.execute()
        self.assertIs(self.bridge.mobile_workflow, original)
        self.assertEqual(len(self.db.records), 2)
        self.assertEqual(len(list((self.db.directory/'frames').iterdir())), 2)

    def test_multi_and_turntable_execution_publish_independent_results(self):
        for mode in ('multi_cam', 'turntable'):
            self.win.set_mode(mode, [])
            self.bridge._current_mode = mode
            database = self.bridge.frame_db.databases[mode]
            frames = [self.source(i) for i in (1, 2)]
            for frame in frames:
                database.ingest(frame)
            cloud = frames[0].load_pointcloud_o3d()
            if mode == 'multi_cam':
                workflow = self.bridge.fixed_workflow
                workflow._frames_scan = {f'cam{i}': frame for i, frame in enumerate(frames)}
                target, returned = workflow, (True, 'ok', cloud)
            else:
                target = self.win.workspace_turntable().session
                target.sequence = frames
                returned = (cloud, 'ok')
            with patch.object(target, 'stitch', return_value=returned) as stitch:
                self.win._industrial_ribbon.commands[(mode, 'stitch')].click()
                self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
                stitch.assert_called_once()
            results = [row for row in database.records.values() if row.kind == 'result']
            self.assertEqual(len(results), 1, self.win._st_hint.text())
            self.assertEqual(results[0].source_ids, [frame.database_id for frame in frames])


if __name__ == '__main__':
    unittest.main()
