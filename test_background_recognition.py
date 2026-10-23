"""No hardware: background scheduling, cache provenance, and preview priority."""
import copy
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
import numpy as np
import test_ui_frame_database as fixture
from core import frame_recognition
from core.frame_database import FrameDatabase
from core.marker_detector import MarkerDetector, MARKER_TYPE_CODED_CIRCLE
from core.frame_data import FrameData


def result(config, markers=None, **extra):
    return dict(state='done', key=frame_recognition.fingerprint(config), markers=markers or [],
                marker_type=config['marker_type'], **extra)


class BackgroundTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    source = fixture.FrameBrowserTests.source
    wait = fixture.FrameBrowserTests.wait

    def setUp(self):
        fixture.FrameBrowserTests.setUp(self)
        self.recognition = self.bridge.recognition
        self.recognition.timer.stop()
        self.recognition.enabled = True
        self.events = []
        self.detector = patch('core.frame_recognition.detect', side_effect=lambda frame, config: result(config)).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        for event in self.events:
            event.set()
        fixture.FrameBrowserTests.tearDown(self)

    def settle(self, condition=None):
        def ready():
            self.recognition.tick()
            return (condition() if condition else not self.recognition.jobs)
        self.wait(ready)

    def blocked(self):
        started, release = threading.Event(), threading.Event()
        self.events.append(release)
        threads = []
        def detect(frame, config):
            threads.append(threading.get_ident())
            started.set()
            release.wait(5)
            return result(config, [dict(code=7, x_2d=1, y_2d=1, valid_3d=False)])
        self.detector.side_effect = detect
        return started, release, threads

    def test_pool_is_bounded_and_does_not_block_preview_or_gate(self):
        started, release, threads = self.blocked()
        ids = [self.db.ingest(self.source(i)) for i in (1, 2, 3)]
        with patch.object(self.win, 'show_loading') as loading:
            self.recognition.tick()
            self.assertTrue(started.wait(2))
            self.assertEqual(len(self.recognition.jobs), 2)
            self.assertTrue(self.bridge.can_change_workspace())
            self.assertTrue(all(value != threading.get_ident() for value in threads))
            loading.assert_not_called()
        self.browser.component_selected.emit(ids[0], 'image')
        self.wait(lambda: not self.bridge._workers)
        self.assertEqual(self.bridge.frame_db._displayed['multi_cam'][0], ids[0])
        release.set()
        self.settle(lambda: all(row.recognition.get('state') == 'done' for row in self.db.records.values()))
        self.assertEqual(self.db.records[ids[0]].markers[0]['code'], 7)

    def test_empty_result_is_cached_retry_is_explicit_and_config_changes_invalidate(self):
        uid = self.db.ingest(self.source())
        self.settle()
        self.assertEqual(self.db.records[uid].recognition['state'], 'done')
        for _ in range(5):
            self.recognition.tick()
        self.assertEqual(self.detector.call_count, 1)
        self.recognition.retry('multi_cam', [uid])
        self.settle()
        self.assertEqual(self.detector.call_count, 2)
        self.bridge.marker_detector.set_params(9, 2., 3.)
        self.settle()
        self.assertEqual(self.detector.call_count, 3)

    def test_delete_and_project_switch_discard_late_results(self):
        started, release, _ = self.blocked()
        uid = self.db.ingest(self.source())
        self.recognition.tick()
        self.assertTrue(started.wait(2))
        self.db.remove([uid])
        release.set()
        self.settle()
        self.assertNotIn(uid, self.db.records)
        self.assertNotIn('markers', self.db.removed[uid]['record']['recognition'])
        started, release, _ = self.blocked()
        uid = self.db.ingest(self.source(2))
        self.recognition.tick()
        self.assertTrue(started.wait(2))
        self.db.directory = Path(self.temp.name) / 'replacement'
        self.db.records.clear()
        release.set()
        self.settle()
        self.assertFalse(self.db.records)

    def test_retake_rejects_old_revision_and_detects_new_data(self):
        started, release, _ = self.blocked()
        uid = self.db.ingest(self.source())
        self.recognition.tick()
        self.assertTrue(started.wait(2))
        self.db.replace_capture(uid, self.source(2))
        self.assertEqual(self.db.records[uid].revision, 1)
        release.set()
        self.detector.side_effect = lambda frame, config: result(config, [dict(code=99)])
        self.settle(lambda: self.db.records[uid].recognition.get('state') == 'done')
        self.assertEqual(self.db.records[uid].markers, [dict(code=99)])

    def test_error_is_visible_and_retry_recovers(self):
        uid = self.db.ingest(self.source())
        self.detector.side_effect = RuntimeError('detector failed')
        self.settle()
        self.assertEqual(self.db.records[uid].recognition['state'], 'error')
        self.recognition.tick()
        self.assertEqual(self.detector.call_count, 1)
        self.assertFalse(self.recognition.ensure('multi_cam', [uid], Mock()))
        self.detector.side_effect = lambda frame, config: result(config)
        self.recognition.retry('multi_cam', [uid])
        self.settle()
        self.assertEqual(self.db.records[uid].recognition['state'], 'done')

    def test_retry_clears_stale_visible_markers_until_new_result_arrives(self):
        uid = self.db.ingest(self.source())
        self.detector.side_effect = lambda frame, config: result(config, [dict(code=3, valid_3d=False, x_2d=1, y_2d=1)])
        self.settle()
        frame, _ = self.db.load_frame(uid, 'image')
        self.bridge.frame_db.display_frame('multi_cam', uid, frame, None, 'image')
        self.assertEqual(frame.markers_all[0]['code'], 3)
        started, release, _ = self.blocked()
        self.recognition.retry('multi_cam', [uid])
        self.recognition.tick()
        self.assertTrue(started.wait(2))
        self.assertEqual(frame.markers_all, [])
        self.assertIsNone(frame.recognition_key)
        release.set()
        self.settle()
        self.assertEqual(frame.markers_all[0]['code'], 7)

    def test_board_metadata_roundtrip_and_old_live_frame_cannot_erase_cache(self):
        frame = self.source()
        uid = self.db.ingest(frame)
        self.detector.side_effect = lambda frame, config: result(config, [dict(code=1)],
            board_pose=np.eye(4).tolist(), board_pattern=[4, 11], board_pattern_name='4x11', board_rms_mm=.2)
        self.settle()
        self.db.annotate(frame)  # Frame held before recognition has no cache key.
        self.assertEqual(len(self.db.records[uid].markers), 1)
        restored = FrameDatabase('multi_cam')
        restored.open_project(self.db.directory / 'index.json')
        loaded, cloud = restored.load_frame(uid, 'image')
        self.assertIsNone(cloud)
        np.testing.assert_array_equal(loaded.board_pose, np.eye(4))
        self.assertEqual(loaded.board_pattern, (4, 11))
        self.assertEqual(loaded.board_rms_mm, .2)
        self.assertTrue(loaded.recognition_key)

    def test_cache_is_additive_and_trash_roundtrips_without_changing_legacy_records(self):
        uid = self.db.ingest(self.source())
        self.settle()
        index = json.loads((self.db.directory / 'index.json').read_text(encoding='utf-8'))
        self.assertNotIn('recognition', index['records'][0])
        self.assertEqual(index['recognition'][uid]['state'], 'done')
        self.db.remove([uid])
        index = json.loads((self.db.directory / 'index.json').read_text(encoding='utf-8'))
        self.assertNotIn('recognition', index['removed'][uid]['record'])
        loaded = FrameDatabase('multi_cam')
        loaded.open_project(self.db.directory / 'index.json')
        self.assertEqual(loaded.removed[uid]['record']['recognition']['state'], 'done')
        loaded.restore_last_removal()
        self.assertEqual(loaded.records[uid].recognition['state'], 'done')

    def test_stitch_waits_asynchronously_then_reuses_cached_markers(self):
        self.win.set_mode('mobile_chain', [])
        self.bridge._current_mode = 'mobile_chain'
        self.db = self.bridge.frame_db.databases['mobile_chain']
        xyz = np.random.default_rng(42).normal(size=(8, 3))*100
        def detect(frame, config):
            markers = [dict(code=i, x_2d=1, y_2d=1, valid_3d=True,
                x_3d=float(point[0]+frame.frame_id*10), y_3d=float(point[1]), z_3d=float(point[2]))
                       for i, point in enumerate(xyz)]
            return result(config, markers)
        self.detector.side_effect = detect
        for i in (1, 2):
            self.db.ingest(self.source(i))
        with patch.object(self.bridge.marker_detector, 'detect_3d', side_effect=AssertionError('stitch re-detected')):
            self.bridge.stitching.execute()
            self.assertEqual(len(self.recognition.waiters), 1)
            self.settle(lambda: any(row.kind == 'result' for row in self.db.records.values()) and not self.bridge._workers)
        self.assertEqual(self.detector.call_count, 2)
        self.assertEqual(len([row for row in self.db.records.values() if row.kind == 'result']), 1)

    def test_empty_cache_does_not_redetect_during_stitch(self):
        self.win.set_mode('mobile_chain', [])
        self.bridge._current_mode = 'mobile_chain'
        self.db = self.bridge.frame_db.databases['mobile_chain']
        for i in (1, 2):
            self.db.ingest(self.source(i))
        self.settle(lambda: all(row.recognition.get('state') == 'done' for row in self.db.records.values()))
        with patch.object(self.bridge.marker_detector, 'detect_3d', side_effect=AssertionError('empty cache re-detected')):
            self.bridge.stitching.execute()
            self.wait(lambda: not self.bridge._workers)
        self.assertEqual(self.detector.call_count, 2)
        self.assertFalse(any(row.kind == 'result' for row in self.db.records.values()))

    def test_foreground_load_has_priority_and_waiter_cancels_after_input_changes(self):
        uid = self.db.ingest(self.source())
        with patch.object(self.bridge, '_workers', [SimpleNamespace(isRunning=lambda: True)]):
            self.recognition.tick()
        self.assertFalse(self.recognition.jobs)
        callback = Mock()
        self.recognition.ensure('multi_cam', [uid], callback)
        self.db.remove([uid])
        self.assertFalse(self.recognition.ensure('multi_cam', [uid], Mock()))
        self.recognition.tick()
        self.assertFalse(self.recognition.waiters)
        callback.assert_not_called()

    def test_capture_previews_cloud_before_dispatch_and_allows_next_capture(self):
        self.win.set_mode('mobile_chain', [])
        self.bridge._current_mode = 'mobile_chain'
        self.db = self.bridge.frame_db.databases['mobile_chain']
        frame = self.source()
        uid = self.db.ingest(frame)
        started, release, _ = self.blocked()
        with patch.object(self.bridge.camera_manager, 'get_connected_ids', return_value=['cam0']), \
                patch.object(self.bridge.camera_manager, 'capture', return_value=frame):
            self.bridge.stitching.capture_mobile()
            self.wait(lambda: not self.bridge._workers)
        self.assertEqual(self.bridge.frame_db._displayed['mobile_chain'][0], uid)
        self.assertIsNotNone(self.win.workspace_mobile().viewer()._database_cloud)
        self.recognition.tick()
        self.assertTrue(started.wait(2))
        self.assertTrue(self.bridge.can_change_workspace())
        release.set()
        self.settle()

    def test_multi_camera_cloud_loading_stays_off_ui_thread(self):
        self.bridge.fixed_workflow.start_calibration('cam0')
        frame = self.source()
        threads = []
        original = FrameData.load_pointcloud_o3d
        def load(value):
            threads.append(threading.get_ident())
            return original(value)
        with patch.object(self.bridge.camera_manager, 'is_connected', return_value=True), \
                patch.object(self.bridge.camera_manager, 'capture', return_value=frame), \
                patch.object(FrameData, 'load_pointcloud_o3d', load):
            self.bridge._on_card_capture('cam0')
            self.wait(lambda: not self.bridge._workers)
        self.assertTrue(threads)
        self.assertTrue(all(value != threading.get_ident() for value in threads))
        self.assertIsNotNone(self.win.workspace_multi().viewer().viewer())
        self.assertEqual(self.detector.call_count, 0)
        self.settle()
        self.assertEqual(self.detector.call_count, 1)

    def test_turntable_capture_returns_before_marker_recognition(self):
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        self.db = self.bridge.frame_db.databases['turntable']
        ws = self.win.workspace_turntable()
        ws.cam_mgr = self.bridge.camera_manager
        ws.marker_detector = self.bridge.marker_detector
        frame = self.source()
        with patch.object(ws, '_is_connected', return_value=True), \
                patch.object(self.bridge.camera_manager, 'capture', return_value=frame), \
                patch.object(self.bridge.marker_detector, 'detect_3d', side_effect=AssertionError('capture waited for detection')):
            ws._on_capture_frame0()
            self.wait(lambda: not self.bridge._workers)
        self.assertIs(ws.current_frame0, frame)
        self.assertEqual(self.detector.call_count, 0)
        self.settle()
        self.assertEqual(self.detector.call_count, 1)

    def test_cached_metadata_refresh_does_not_reload_cloud_or_reset_view(self):
        uid = self.db.ingest(self.source())
        self.browser.set_component_checked(uid, 'cloud')
        viewer = self.win.workspace_multi().viewer()
        self.wait(lambda: bool(viewer._database_clouds) and not self.bridge._workers)
        self.detector.side_effect = lambda frame, config: result(config, [dict(
            code=7, x_2d=1., y_2d=1., valid_3d=True, x_3d=1., y_3d=2., z_3d=3.)])
        with patch.object(viewer, 'show_database_clouds', wraps=viewer.show_database_clouds) as show, \
                patch.object(viewer, 'reset_view') as reset:
            self.settle()
        show.assert_not_called()
        reset.assert_not_called()
        self.assertEqual(viewer._cloud_markers[0][0], 7)

    def test_turntable_results_update_calibration_and_sequence_without_modal_detection(self):
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        self.db = self.bridge.frame_db.databases['turntable']
        ws = self.win.workspace_turntable()
        frame = self.source()
        uid = self.db.ingest(frame)
        ws.current_frame0 = frame
        ws.session.frame0 = frame
        ws.session.markers0 = []
        ws.session.sequence = [frame]
        ws.session.sequence_markers = [[]]
        self.detector.side_effect = lambda frame, config: result(config, [dict(code=4, valid_3d=True,
            x_2d=1, y_2d=1, x_3d=1, y_3d=2, z_3d=3)])
        with patch.object(self.win, 'show_loading') as loading:
            self.settle()
        loading.assert_not_called()
        self.assertEqual(ws.current_markers0[0]['code'], 4)
        self.assertEqual(ws.session.markers0, ws.session.sequence_markers[0])
        self.assertTrue(self.db.records[uid].recognition['key'])

    def test_recognition_commit_rolls_back_on_disk_failure(self):
        uid = self.db.ingest(self.source())
        before = copy.deepcopy(vars(self.db.records[uid]))
        with patch.object(self.db, '_save_index', side_effect=IOError('disk full')):
            with self.assertRaises(IOError):
                self.db.set_recognition(uid, 0, self.db.directory, dict(state='done', markers=[dict(code=8)]))
        self.assertEqual(vars(self.db.records[uid]), before)

    def test_failed_metadata_write_stops_retries_until_requested(self):
        uid = self.db.ingest(self.source())
        with patch.object(self.db, '_save_index', side_effect=IOError('disk full')) as write:
            self.recognition.tick()
            self.recognition.tick()
            self.assertEqual(write.call_count, 1)
        self.assertFalse(self.recognition.jobs)
        self.recognition.retry('multi_cam', [uid])
        self.settle()
        self.assertEqual(self.db.records[uid].recognition['state'], 'done')


class DetectorSnapshotTests(unittest.TestCase):
    def test_background_sdk_errors_are_distinct_from_zero_detections(self):
        source = MarkerDetector()
        source.raise_errors = True
        source._coded_marker_type = None
        with self.assertRaisesRegex(RuntimeError, 'PyRVC'):
            source.detect(np.zeros((2, 2, 3), np.uint8))

    def test_independent_detector_and_board_metadata(self):
        source = MarkerDetector()
        config = frame_recognition.configuration(source, MARKER_TYPE_CODED_CIRCLE)
        detector = Mock()
        detector.detect_3d.return_value = [dict(code=3, valid_3d=False)]
        detector.last_board_result = dict(T_board_in_cam=np.eye(4), pattern_size=(4, 11), pattern_name='4x11', rms_mm=.1)
        with patch('core.frame_recognition.MarkerDetector', return_value=detector):
            outcome = frame_recognition.detect(SimpleNamespace(image_np=None, offline_pointmap_path='raw.ply'), config)
        detector.set_params.assert_called_once_with(*config['circle'])
        self.assertEqual(outcome['board_pattern'], [4, 11])
        self.assertEqual(outcome['markers'][0]['valid_3d'], False)


if __name__ == '__main__':
    unittest.main()
