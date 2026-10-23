"""Raw acquisition, transactional result publication and portable DB results."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import contextmanager
from PySide6.QtCore import Qt
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

    def test_three_frames_add_cross_constraints_and_run_global_optimization(self):
        self.mobile()
        frame = self.source(3)
        frame.markers = [dict(marker, x_3d=marker['x_3d']+20)
                         for marker in next(iter(self.db.records.values())).markers]
        frame.markers_all = frame.markers
        self.db.ingest(frame)
        self.execute()
        workflow = self.bridge.mobile_workflow
        chain = workflow._chain_stitcher
        self.assertEqual(len(chain.nodes), 3, self.win._st_hint.text())
        self.assertEqual(len(chain.edges), 3)
        self.assertEqual(len(chain.pose_graph.edges), 3)
        self.assertIn(frozenset(('station_2', 'station_3')),
            {frozenset((edge.from_id, edge.to_id)) for edge in chain.edges})
        self.assertTrue(all(np.isfinite(node.T_world).all() for node in chain.nodes.values()))
        rms = workflow.get_error_report()['global_marker_rms_mm']
        card = self.win.workspace_mobile()._eval_card
        self.assertIn('全局标记误差', card.summary())
        self.assertEqual(card._rms.text(), f'{rms:.3f}mm')
        card.set_evaluation(4, 1., .24, 'ok', '下一步')
        self.assertIn('本步误差 0.24mm', card.summary())
        result = next(row for row in self.db.records.values() if row.kind == 'result')
        self.assertEqual(result.logical_name, '拼接帧 001')
        self.assertEqual(chain.add_cross_frame_constraints(), 0)
        self.assertEqual(len(chain.edges), 3)
        # Retrying global optimization does not duplicate edges, and rejected
        # extra constraints must not enter either graph representation.
        from core.chain_stitcher import ChainEdge
        third = chain.edges.pop()
        chain.pose_graph.edges.pop()
        rejected = ChainEdge(third.from_id, third.to_id, third.T, 10., .1, 8)
        with patch.object(chain, '_try_register', return_value=rejected):
            self.assertEqual(chain.add_cross_frame_constraints(), 0)
        self.assertEqual(len(chain.edges), 2)
        for row in self.win.workspace_mobile()._industrial.frame_browser._items.values():
            self.assertNotIn('000', row.text(0))

    def test_db_preview_selection_is_silent_but_errors_still_log(self):
        self.mobile()
        browser = self.bridge.frame_db.browsers['mobile_chain']
        uid = next(iter(self.db.records))
        with patch.object(self.win, 'log') as log:
            for _ in range(3):
                self.bridge.frame_db.select('mobile_chain', uid)
                self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
            log.assert_not_called()
            self.assertIn('原始帧 001', self.win._st_hint.text())
        with patch.object(self.db, 'load_frame', side_effect=IOError('missing raw')), patch.object(self.win, 'log') as log:
            self.bridge.frame_db.select('mobile_chain', uid)
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
            self.assertIn('missing raw', log.call_args.args[0])
            self.assertEqual(log.call_args.args[1], 'error')

    def test_ui_log_keeps_important_events_when_diagnostics_are_enabled(self):
        import logging
        from ui_common.activity_log import ActivityLogPanel
        panel = ActivityLogPanel()
        logger = logging.getLogger('mcc_test_diagnostic_filter')
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        try:
            panel.attach_logger(logger)
            logger.debug('diagnostic shape and file path')
            logger.info('registration complete')
            logger.warning('quality warning')
            self.app.processEvents()
            messages = [row[4] for row in panel.records]
            self.assertEqual(messages, ['registration complete', 'quality warning'])
        finally:
            panel.detach_loggers()
            panel.close()
            panel.deleteLater()

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

    def select_raw(self, uid, component=None):
        browser = self.bridge.frame_db.browsers['mobile_chain']
        browser.tree.clearSelection()
        browser.tree.setCurrentItem(browser._component_items[(uid, component)] if component else browser._items[uid])
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))

    @contextmanager
    def camera(self, value=211):
        from test_frame_database import PLY
        sdk = SimpleNamespace(PointMapUnitEnum=SimpleNamespace(Millimeter=1),
            PointMap=SimpleNamespace(Destroy=Mock()), Image=SimpleNamespace(Destroy=Mock()))
        pm = Mock()
        def save(path, *args):
            Path(path).write_bytes(PLY.replace(b'1 2 3', b'7 8 9'))
            return True
        pm.SaveWithImage.side_effect = save
        self.bridge.camera_manager._cameras = {'cam0': SimpleNamespace(is_connected=True, sn='MOCK',
            capture_3d=lambda options: (np.full((2,2,3),value,np.uint8), pm, object(), 'ok'))}
        self.bridge.stitching.update_mobile_actions()
        with patch('core.frame_database._import_rvc', return_value=sdk), \
             patch('core.frame_data._import_rvc', return_value=sdk):
            yield sdk

    def test_selected_raw_retake_overwrites_same_pair_and_discards_stale_registration(self):
        from core.frame_database import STALE_RESULT
        ws = self.mobile()
        raw = list(self.db.records)
        self.execute()
        result = next(uid for uid,row in self.db.records.items() if row.kind=='result')
        before = list(self.db.records)
        first_bytes = (self.db.directory/'frames'/raw[0]/'pointmap.ply').read_bytes()
        self.select_raw(raw[1], 'image')
        with self.camera() as sdk:
            button = self.win._industrial_ribbon.commands[('mobile_chain','recapture')]
            self.assertTrue(button.isEnabled())
            self.assertIn('002', button.toolTip())
            self.select_raw(raw[0])
            self.assertIn('001', button.toolTip())
            self.select_raw(raw[1], 'image')
            self.assertIn('002', button.toolTip())
            button.click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
            sdk.PointMap.Destroy.assert_called_once()
        self.assertEqual(list(self.db.records), before)
        self.assertEqual(self.db.records[raw[1]].frame_id, 2)
        self.assertEqual(self.db.records[raw[1]].revision, 1)
        self.assertEqual(self.db.records[result].status, STALE_RESULT)
        self.assertIn('需重新拼接', ws._industrial.frame_browser._items[result].text(0))
        self.assertEqual(self.db.records[raw[1]].markers, [])
        self.assertEqual((self.db.directory/'frames'/raw[0]/'pointmap.ply').read_bytes(), first_bytes)
        frame,_ = self.db.load_frame(raw[1])
        np.testing.assert_array_equal(frame.image_np, np.full((2,2,3),211,np.uint8))
        self.assertIn(b'7 8 9', Path(frame.offline_pointmap_path).read_bytes())
        self.assertEqual(self.bridge.mobile_workflow.get_station_evaluations(), [])
        self.assertEqual(ws._station_count, 0)
        self.assertNotEqual(self.db.records[raw[0]].status, '已入链')
        self.assertEqual(ws._industrial.frame_browser.selected_ids(), [raw[1]])
        self.assertEqual(ws._industrial.frame_browser.selected_ids(), [raw[1]])
        self.assertIsNotNone(ws.viewer()._database_cloud)
        self.assertIsNone(ws.viewer()._merged)
        self.assertTrue(self.win._industrial_ribbon.commands[('mobile_chain','export')].isEnabled())
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=('', '')) as dialog:
            self.bridge.stitching.export()
            dialog.assert_called_once()

    def test_retake_can_register_again_and_publish_a_new_exportable_result(self):
        from core.frame_database import STALE_RESULT
        self.mobile()
        raw = list(self.db.records)
        markers = [dict(marker) for marker in self.db.records[raw[1]].markers]
        self.execute()
        old = next(uid for uid,row in self.db.records.items() if row.kind == 'result')
        self.select_raw(raw[1])
        with self.camera():
            self.win._industrial_ribbon.commands[('mobile_chain','recapture')].click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        with patch.object(self.bridge.marker_detector, 'detect_3d', return_value=markers) as detect:
            self.execute()
            detect.assert_called_once()
        results = [row for row in self.db.records.values() if row.kind == 'result' and row.status != STALE_RESULT]
        self.assertEqual(len(results), 1, self.win._st_hint.text())
        self.assertEqual(results[0].source_ids, raw)
        self.assertEqual(self.db.records[old].status, STALE_RESULT)
        self.assertEqual(len(self.bridge.mobile_workflow.get_station_evaluations()), 2)
        self.assertTrue(self.win._industrial_ribbon.commands[('mobile_chain','export')].isEnabled())

    def test_unregistered_frame_can_be_retaken_and_undo_targets_db_last_not_selected(self):
        ws = self.mobile()
        first, second = list(self.db.records)
        self.select_raw(first)
        with self.camera(), patch('ui_v2.explicit_stitching.QMessageBox.question', side_effect=AssertionError('no chain reset prompt')):
            self.win._industrial_ribbon.commands[('mobile_chain','recapture')].click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(list(self.db.records), [first,second])
        self.assertEqual(self.db.records[first].revision, 1)
        self.select_raw(first)
        with patch('ui_v2.explicit_stitching.QMessageBox.question', return_value=QMessageBox.Yes):
            self.win._industrial_ribbon.commands[('mobile_chain','undo')].click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertIn(first, self.db.records)
        self.assertNotIn(second, self.db.records)
        self.assertIsNone(ws.viewer()._database_cloud)
        self.assertIsNone(ws.viewer()._merged)

    def test_failed_retake_preserves_selected_record_chain_and_capture_target_clears(self):
        ws = self.mobile()
        raw = list(self.db.records)
        self.execute()
        chain = self.bridge.mobile_workflow._chain_stitcher
        self.select_raw(raw[0])
        before = (self.db.directory/'index.json').read_bytes()
        with self.camera():
            with patch.object(self.bridge.camera_manager, 'capture', return_value=None):
                self.win._industrial_ribbon.commands[('mobile_chain','recapture')].click()
                self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
            self.assertEqual((self.db.directory/'index.json').read_bytes(), before)
            self.assertIs(self.bridge.mobile_workflow._chain_stitcher, chain)
            self.assertEqual(self.db.records[raw[0]].revision, 0)
            self.bridge.stitching.capture_mobile()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(sum(row.kind=='raw' for row in self.db.records.values()), 3)
        self.assertEqual([row.frame_id for row in self.db.records.values() if row.kind=='raw'], [1,2,3])
        self.assertEqual(self.db.records[raw[0]].revision, 0)

    def test_db_edit_buttons_follow_raw_selection_and_delete_undo_move_corresponding_pairs(self):
        from core.frame_database import STALE_RESULT
        ws = self.mobile()
        raw = list(self.db.records)
        self.execute()
        result = next(uid for uid,row in self.db.records.items() if row.kind=='result')
        ribbon = self.win._industrial_ribbon.commands
        self.assertFalse(ribbon[('mobile_chain','recapture')].isEnabled())
        self.assertFalse(ribbon[('mobile_chain','delete')].isEnabled())
        self.select_raw(raw[0], 'cloud')
        self.assertTrue(ribbon[('mobile_chain','delete')].isEnabled())
        self.assertFalse(ribbon[('mobile_chain','recapture')].isEnabled())
        with patch('ui_v2.explicit_stitching.QMessageBox.question', return_value=QMessageBox.No):
            ribbon[('mobile_chain','delete')].click()
        self.assertIn(raw[0], self.db.records)
        with patch('ui_v2.explicit_stitching.QMessageBox.question', return_value=QMessageBox.Yes):
            ribbon[('mobile_chain','delete')].click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertNotIn(raw[0], self.db.records)
        self.assertIn(raw[0], self.db.removed)
        self.assertIn(raw[1], self.db.records)
        self.assertEqual(self.db.records[result].status, STALE_RESULT)
        self.assertEqual(ws._station_count, 0)
        with patch('ui_v2.explicit_stitching.QMessageBox.question', return_value=QMessageBox.Yes):
            ribbon[('mobile_chain','undo')].click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertNotIn(raw[1], self.db.records)
        self.assertIn(raw[1], self.db.removed)
        self.assertFalse(ribbon[('mobile_chain','undo')].isEnabled())
        self.bridge.frame_db.recover('mobile_chain')
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertIn(raw[1], self.db.records)
        self.assertTrue(ribbon[('mobile_chain','undo')].isEnabled())

    def test_group_mixed_and_multiple_selection_cannot_silently_retake_latest_frame(self):
        self.mobile()
        raw = list(self.db.records)
        self.execute()
        browser = self.bridge.frame_db.browsers['mobile_chain']
        with self.camera(), patch.object(self.bridge.camera_manager,'capture') as capture:
            self.select_raw(raw[0])
            browser._items[raw[1]].setSelected(True)
            self.bridge.stitching.recapture_mobile()
            capture.assert_not_called()
            browser.tree.clearSelection()
            browser.tree.setCurrentItem(browser._items[raw[0]].parent())
            self.bridge.stitching.recapture_mobile()
            capture.assert_not_called()
            self.assertFalse(self.win._industrial_ribbon.commands[('mobile_chain','recapture')].isEnabled())

    def test_online_capture_stores_raw_without_registration(self):
        ws = self.mobile()
        frame = self.source(3)
        fake_sdk = SimpleNamespace(PointMapUnitEnum=SimpleNamespace(Millimeter=1),
            PointMap=SimpleNamespace(Destroy=Mock()), Image=SimpleNamespace(Destroy=Mock()))
        pm = Mock()
        pm.SaveWithImage.side_effect = lambda path, *args: Path(path).write_bytes(Path(frame.offline_pointmap_path).read_bytes()) or True
        self.bridge.camera_manager._cameras = {'cam0': SimpleNamespace(is_connected=True, sn='MOCK',
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
