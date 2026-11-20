"""Raw acquisition, transactional result publication and portable DB results."""

import _bootstrap  # Configure project and sibling-test imports.
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import contextmanager
from PySide6.QtCore import Qt, QSignalBlocker
import unittest

import numpy as np
import cv2
import open3d as o3d
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QMessageBox
import test_ui_frame_database as fixture
from core.session_project import SessionProject


class ExplicitStitchingTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait
    source = fixture.FrameBrowserTests.source

    def test_offline_main_workspace_enters_without_sdk_or_demo_frames(self):
        from core.camera_manager import CameraManager
        with patch.object(CameraManager,'initialize',side_effect=AssertionError('SDK forbidden')):
            with patch.object(self.bridge,'connect_devices',side_effect=AssertionError('connect forbidden')):
                for mode in ('mobile_chain','multi_cam','turntable','robot_stitch'):
                    self.assertTrue(self.bridge.open_offline_workspace(mode))
                    self.assertEqual(self.win.current_mode(),mode)
                    self.assertEqual(self.bridge._current_mode,mode)
                    self.assertFalse(self.bridge.frame_db.databases[mode].records)
        self.assertIsNotNone(self.bridge.mobile_workflow.station_manager)

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

    def test_feature_roi_draws_on_raw_image_and_roundtrips(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        from prototypes.superpoint_lightglue.dialog import RegionPreview
        from ui_v2.feature_recognition import FEATURE_RECOGNITION

        mode = 'mobile_chain'
        self.win.feature_recognition_enabled = True
        self.bridge._current_mode = mode
        self.win.set_mode(mode, [])
        self.bridge.projects.prepare(mode)
        project = self.bridge.projects.projects[mode]
        project.save_root = Path(self.temp.name) / 'sessions'
        frame = self.source()
        frame.image_np = np.zeros((384, 512, 3), dtype=np.uint8)
        project.database.ingest(frame)
        params = self.win.workspace_mobile()._industrial.frame_browser.properties.recognition
        params.refresh()
        params.marker_type.setCurrentIndex(params.marker_type.findData(FEATURE_RECOGNITION))

        def draw(dialog):
            dialog.show()
            self.app.processEvents()
            preview = dialog.findChild(RegionPreview)
            image = preview._image_rect()
            start = QPoint(round(image.left() + .25 * image.width()), round(image.top() + .25 * image.height()))
            end = QPoint(round(image.left() + .75 * image.width()), round(image.top() + .75 * image.height()))
            QTest.mousePress(preview, Qt.LeftButton, pos=start)
            QTest.mouseMove(preview, end)
            QTest.mouseRelease(preview, Qt.LeftButton, pos=end)
            self.assertTrue(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).isEnabled())
            dialog.hide()
            return QDialog.Accepted

        with patch.object(QDialog, 'exec', draw):
            params.draw_roi.click()
        roi = self.bridge.stitching.feature_roi()
        np.testing.assert_allclose(roi, [.25, .25, .75, .75], atol=.005)
        self.assertIn('已框选', params.roi_label.text())
        params.feature_fields['tolerance'].setValue(2.5)
        params.feature_fields['inlier_percent'].setValue(55)
        params.feature_icp_fields['icp_voxel'].setValue(.75)
        params.feature_icp_fields['geometry_neighbors'].setValue(5)
        params.feature_icp_fields['icp_max_correction'].setValue(4.)
        params.geometry_fpfh.setChecked(True)
        self.assertTrue(params.refinement_order.isEnabled())
        params.refinement_order.setCurrentIndex(params.refinement_order.findData(False))
        params.icp_enabled.setChecked(False)
        self.assertFalse(params.refinement_order.isEnabled())
        params.feature_fields['max_keypoints'].setValue(1024)
        self.assertFalse(self.bridge.stitching.feature_settings().icp_enabled)
        self.assertEqual(self.bridge.stitching.feature_settings().tolerance, 2.5)
        saved, _ = SessionProject.load(project.save({}), mode)
        self.addCleanup(saved.dispose)
        self.assertEqual(saved.feature_roi, roi)
        self.assertEqual(saved.feature_settings.inlier_percent, 55)
        self.assertEqual(saved.feature_settings.tolerance, 2.5)
        self.assertFalse(saved.feature_settings.icp_enabled)
        self.assertFalse(saved.feature_settings.icp_after_geometry)
        self.assertEqual(saved.feature_settings.icp_voxel,.75)
        self.assertTrue(saved.feature_settings.geometry_enabled)
        self.assertTrue(saved.feature_settings.geometry_fpfh)
        self.assertEqual(saved.feature_settings.geometry_neighbors,5)
        self.assertEqual(saved.feature_settings.icp_max_correction,4.)
        params.reset_feature_tuning.click()
        self.assertEqual(self.bridge.stitching.feature_settings().tolerance, 2.)
        params.clear_roi.click()
        self.assertIsNone(self.bridge.stitching.feature_roi())

    def test_workpiece_mask_overlay_and_session_settings(self):
        from core.feature_masks import WorkpieceMaskSettings
        from ui_v2.feature_recognition import FEATURE_RECOGNITION

        mode = 'mobile_chain'
        self.win.feature_recognition_enabled = True
        self.bridge._current_mode = mode
        self.win.set_mode(mode, [])
        self.bridge.projects.prepare(mode)
        project = self.bridge.projects.projects[mode]
        project.save_root = Path(self.temp.name) / 'mask_sessions'
        frame = self.source()
        frame.image_np = np.full((96, 128, 3), 20, dtype=np.uint8)
        frame.image_np[30:60, 50:90] = 180
        uid = project.database.ingest(frame)
        frame.database_id = uid
        page = self.win.workspace_mobile()._industrial.frame_browser.properties.recognition
        page.refresh()
        page.marker_type.setCurrentIndex(page.marker_type.findData(FEATURE_RECOGNITION))
        stitch = self.bridge.stitching
        stitch.set_feature_roi((.25, .125, .875, .875))
        stitch.set_workpiece_roi((.375, .25, .8125, .75))
        page.refresh()
        self.assertIn('已框选', page.workpiece_label.text())
        self.bridge.frame_db.display_frame(mode, uid, frame, None, 'image')
        page.mask_threshold.setValue(100)
        page.mask_enabled.setChecked(True)
        page.mask_overlay.setChecked(True)
        inspector = self.win.workspace_mobile()._industrial.inspector
        view = inspector.image_view
        self.assertEqual(len(view.feature_regions), 2)
        self.assertFalse(view.feature_overlay.isNull())
        self.assertEqual(view.feature_overlay.pixelColor(65, 40).green(), 220)
        self.assertEqual(view.feature_overlay.pixelColor(50, 25).red(), 255)
        self.assertEqual(view.feature_overlay.pixelColor(110, 40).alpha(), 0)
        self.assertIn('1,200', inspector.mask_summary.text())
        self.assertIn('已启用纹理增强补充', inspector.mask_summary.text())
        saved, _ = SessionProject.load(project.save({}), mode)
        self.addCleanup(saved.dispose)
        self.assertEqual(saved.workpiece_roi, project.workpiece_roi)
        self.assertEqual(saved.workpiece_mask, WorkpieceMaskSettings(True, 'bright', 100))
        self.assertTrue(saved.show_feature_mask)
        before = stitch.workpiece_mask()
        page.mask_overlay.setChecked(False)
        self.assertTrue(view.feature_overlay.isNull())
        self.assertEqual(stitch.workpiece_mask(), before)
        page.mask_enabled.setChecked(False)
        self.assertEqual(int(frame.image_np[40, 65, 0]), 180)

    def test_feature_capture_continues_while_matching_and_updates_selected_image(self):
        from threading import Event
        from prototypes.superpoint_lightglue.automatic import FeatureStitching
        from prototypes.superpoint_lightglue.test_automatic import SyntheticMatcher
        from ui_v2.feature_recognition import FEATURE_RECOGNITION

        mode = 'mobile_chain'
        self.win.feature_recognition_enabled = True
        self.bridge._current_mode = mode
        self.win.set_mode(mode, [])
        self.bridge.projects.prepare(mode)
        self.db = self.bridge.frame_db.databases[mode]
        config = self.bridge.recognition.config(mode)
        self.bridge.recognition.configure(mode, FEATURE_RECOGNITION, config['boards'], config['gamma'])
        self.bridge.camera_manager.get_connected_ids = lambda: ['cam0']
        started, release = Event(), Event()
        boxes_seen = []
        class DelayedMatcher(SyntheticMatcher):
            def match(self, images, boxes):
                boxes_seen.extend(boxes)
                started.set()
                if not release.wait(5):
                    raise TimeoutError('matching was not released')
                return super().match(images, boxes)

        identifiers = []
        def capture(_camera):
            number = len(identifiers) + 1
            frame = self.source(number)
            y, x = np.indices((48, 48))
            grid = np.stack((x + number * 3, y, 400 + (x % 4) * .1), axis=-1)
            cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(grid.reshape(-1, 3)))
            self.assertTrue(o3d.io.write_point_cloud(frame.offline_pointmap_path, cloud))
            frame.image_np = np.full(x.shape, 100, dtype=np.uint8)
            frame.pointcloud_aligned = True
            frame.database_id = self.db.ingest(frame)
            identifiers.append(frame.database_id)
            return frame

        self.bridge.camera_manager.capture = capture
        stitch = self.bridge.stitching
        stitch.set_feature_roi((.125, .125, .875, .875))
        stitch._feature_stitcher = FeatureStitching(DelayedMatcher())
        inspector = self.win.workspace_mobile()._industrial.inspector
        try:
            stitch.capture_mobile()
            self.wait(self.bridge.can_change_workspace)
            stitch.capture_mobile()
            self.wait(started.is_set)
            self.assertFalse(self.win._overlay.isVisible())
            self.assertTrue(self.win._task_progress.isVisible())
            self.win.workspace_mobile()._btn_capture.click()
            self.wait(lambda: len(identifiers) == 3)
            self.wait(self.bridge.can_change_workspace)
            self.assertFalse(self.win._overlay.isVisible())
            self.assertTrue(self.win._task_progress.isVisible())
            self.assertFalse(any(row.kind == 'result' for row in self.db.records.values()))
        finally:
            release.set()

        self.wait(lambda: not stitch.feature_matching and self.bridge.can_change_workspace())
        self.assertFalse(self.win._task_progress.isVisible())
        self.assertFalse(any(row.kind == 'result' for row in self.db.records.values()))
        self.assertEqual(set(boxes_seen), {(6, 6, 42, 42)})
        before_manual = len(boxes_seen)
        self.assertEqual(len(inspector.image_view.feature_points), 9)
        self.assertEqual({point[2] for point in inspector.image_view.feature_points}, {3})
        self.assertIn('像素匹配', inspector.counts.text())
        stitch.execute()
        self.wait(lambda: self.bridge.can_change_workspace() and any(
            row.source_ids == identifiers for row in self.db.records.values() if row.kind == 'result'))
        self.assertEqual(len(boxes_seen), before_manual, 'manual registration must reuse the 2D cache')
        self.assertIn('已拼接 3 帧', self.win._st_quality.full_text)
        self.assertEqual(self.bridge.frame_db._displayed[mode][0], identifiers[-1])
        self.assertEqual(len(inspector.image_view.feature_points), 9)
        self.assertEqual({point[2] for point in inspector.image_view.feature_points}, {2})
        self.assertIn('SuperPoint + LightGlue', inspector.title.text())
        self.bridge.frame_db.select(mode, identifiers[0], 'image')
        self.wait(lambda: self.bridge.frame_db._displayed[mode][0] == identifiers[0])
        self.assertEqual(len(inspector.image_view.feature_points), 9)

        # A manual request during a new background match waits and reuses that job.
        started.clear()
        release.clear()
        try:
            stitch.capture_mobile()
            self.wait(started.is_set)
            self.wait(lambda: self.bridge.can_change_workspace())
            self.assertTrue(self.win._task_progress.isVisible())
            stitch.execute()
            self.assertIsNotNone(stitch._pending_feature_stitch)
        finally:
            release.set()
        self.wait(lambda: not stitch.feature_busy and not stitch.feature_matching
                  and self.bridge.can_change_workspace())
        self.assertTrue(any(row.source_ids == identifiers for row in self.db.records.values()
                            if row.kind == 'result'))
        self.assertFalse(self.win._task_progress.isVisible())

    def test_stale_background_pixel_matches_do_not_repopulate_overlays(self):
        from threading import Event
        from prototypes.superpoint_lightglue.automatic import FeatureStitching
        from prototypes.superpoint_lightglue.test_automatic import SyntheticMatcher
        from ui_v2.feature_recognition import FEATURE_RECOGNITION

        mode = 'mobile_chain'
        self.win.feature_recognition_enabled = True
        self.bridge._current_mode = mode
        self.win.set_mode(mode, [])
        self.bridge.projects.prepare(mode)
        database = self.bridge.frame_db.databases[mode]
        config = self.bridge.recognition.config(mode)
        self.bridge.recognition.configure(mode, FEATURE_RECOGNITION, config['boards'], config['gamma'])
        identifiers = []
        for number in (1, 2):
            frame = self.source(number)
            frame.image_np = np.full((48, 48), 100, dtype=np.uint8)
            identifiers.append(database.ingest(frame))
        started, release = Event(), Event()
        class DelayedMatcher(SyntheticMatcher):
            def match(self, images, boxes):
                started.set()
                if not release.wait(5):
                    raise TimeoutError('matching was not released')
                return super().match(images, boxes)
        stitch = self.bridge.stitching
        stitch._feature_stitcher = FeatureStitching(DelayedMatcher())
        try:
            stitch._enqueue_feature_capture(database, identifiers[1])
            self.wait(started.is_set)
            self.assertTrue(self.bridge.can_change_workspace())
            database.records[identifiers[1]].revision += 1
        finally:
            release.set()
        self.wait(lambda: not stitch.feature_matching)
        self.assertIsNone(stitch.feature_observation(mode, identifiers[1]))
        self.assertFalse(self.win._task_progress.isVisible())
        self.assertFalse(any(row.kind == 'result' for row in database.records.values()))

    def test_mobile_and_turntable_plane_filter_roundtrip_and_preserve_raw(self):
        from core.frame_database import FrameDatabase
        from core.postprocess.source_poses import load_stitch_source

        for mode in ('mobile_chain', 'turntable'):
            with self.subTest(mode=mode):
                self.win.set_mode(mode, [])
                self.bridge._current_mode = mode
                db = self.bridge.frame_db.databases[mode]
                frames, original = [], {}
                for number in (1, 2):
                    frame = self.source(number)
                    frame.markers = [
                        dict(code=index, x_2d=1, y_2d=1, x_3d=x, y_3d=y, z_3d=200)
                        for index, (x, y) in enumerate(((-30,-30), (30,-30), (30,30), (-30,30)))
                    ]
                    points = [[1, 3, 193], [1, 3, 198.8], [1.3, 3, 199.2],
                              [1.9, 3, 199.2], [1, 3, 199.7], [1, 3, 208]]
                    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
                    self.assertTrue(o3d.io.write_point_cloud(frame.offline_pointmap_path, cloud))
                    uid = db.ingest(frame)
                    original[uid] = (db.directory/'frames'/uid/'pointmap.ply').read_bytes()
                    frames.append(frame)
                if mode == 'turntable':
                    session = self.win.workspace_turntable().session
                    session.apply_calibration([0,0,1], [0,0,0], 90, 4)
                    session.sequence = frames
                    session.sequence_pcds = [cloud, cloud]
                    session.sequence_markers = [frame.markers for frame in frames]
                def accept_filter(dialog):
                    active, bottom = dialog.findChildren(QCheckBox)
                    self.assertFalse(bottom.isEnabled())
                    active.setChecked(True)
                    self.assertTrue(bottom.isEnabled())
                    self.assertFalse(bottom.isChecked())
                    bottom.setChecked(True)
                    height, lower, _ = dialog.findChildren(QDoubleSpinBox)
                    ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
                    lower.setValue(height.value())
                    self.assertFalse(ok.isEnabled())
                    lower.setValue(.5)
                    self.assertTrue(ok.isEnabled())
                    return QDialog.Accepted
                filter_button = self.win._industrial_ribbon.commands[(mode, 'plane_filter')]
                with patch.object(QDialog, 'exec', accept_filter):
                    filter_button.click()
                self.assertIn('开', filter_button.text())
                self.run_mode(mode)
                results = [row for row in db.records.values() if row.kind == 'result']
                self.assertEqual(len(results), 1, self.win._st_hint.text())
                result = results[0]
                self.assertEqual(result.points, 6)
                self.assertEqual(set(result.source_planes), set(original))
                reopened = FrameDatabase(mode)
                reopened.open_project(db.directory/'index.json')
                restored = reopened.records[result.uid]
                self.assertEqual(restored.source_planes, result.source_planes)
                for uid, expected in original.items():
                    self.assertEqual((db.directory/'frames'/uid/'pointmap.ply').read_bytes(), expected)
                    np.testing.assert_allclose(np.asarray(load_stitch_source(reopened, restored, uid).points),
                                               points[:3])

    def test_ring_recognition_settings_and_three_frame_stitch(self):
        self.bridge._current_mode = 'mobile_chain'
        self.win.set_mode('mobile_chain', [])
        self.db = self.bridge.frame_db.databases['mobile_chain']
        self.bridge.projects.prepare('mobile_chain')
        props = self.win.workspace_mobile()._industrial.frame_browser.properties
        props.tabs.setCurrentWidget(props.recognition)
        self.app.processEvents()
        page = props.recognition
        page.marker_type.setCurrentIndex(page.marker_type.findData('unencoded_circle'))
        page.dot_polarity.setCurrentIndex(page.dot_polarity.findData('light'))
        page.dot_threshold.setValue(170)
        page._apply()
        self.assertEqual(self.bridge.recognition.config('mobile_chain')['unencoded']['polarity'], 'light')
        self.bridge.recognition.enabled = True

        ids = []
        yy, xx = np.mgrid[:120, :180]
        for number in range(3):
            frame = self.source(number + 1)
            frame.image_np = np.full((120, 180, 3), 20, np.uint8)
            for x, y in ((25, 24), (140, 31), (58, 90), (121, 87)):
                cv2.circle(frame.image_np, (x + number, y), 8, (230, 230, 230), -1)
                cv2.circle(frame.image_np, (x + number, y), 6, (120, 120, 120), -1)
            xyz = np.stack((xx - number * 5., yy, np.full_like(xx, 400)), axis=-1)
            cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz.reshape(-1, 3)))
            self.assertTrue(o3d.io.write_point_cloud(frame.offline_pointmap_path, cloud))
            ids.append(self.db.ingest(frame))
        self.execute()
        self.wait(lambda: self.bridge.mobile_workflow._chain_stitcher is not None)
        self.assertEqual(sum(row.kind == 'result' for row in self.db.records.values()), 1)
        chain = self.bridge.mobile_workflow._chain_stitcher
        self.assertEqual(len(chain.edges), 3)
        self.assertTrue(all(edge.point_pairs is not None for edge in chain.edges))
        self.assertTrue(all(self.db.records[uid].recognition['marker_type'] == 'unencoded_circle' for uid in ids))
        for i, node in enumerate(chain.nodes.values()):
            np.testing.assert_allclose(node.T_world[:3, 3], [i * 4., 0., 0.], atol=1e-8)
        project = self.bridge.projects.projects['mobile_chain']
        project.save_root = Path(self.temp.name) / 'saved-rings'
        saved = project.save(self.bridge.projects.describe('mobile_chain', True), include_raw=True)
        loaded, data = SessionProject.load(saved, 'mobile_chain', project.save_root)
        try:
            workflow, _ = self.bridge.projects.prepare_loaded(loaded, data)
            self.assertTrue(workflow.optimize_global()[0])
            self.assertEqual(len(workflow._marker_constraints()), 3)
            self.assertEqual(workflow.match_triangle(ids[0]),
                             self.bridge.mobile_workflow.match_triangle(ids[0]))
            self.assertEqual(len(workflow.match_triangle(ids[0])), 3)
        finally:
            loaded.dispose()

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
        self.bridge.camera_manager._cameras = {'cam0': SimpleNamespace(is_connected=True, sn='MOCK', device_info=SimpleNamespace(name='Mock camera'),
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
        self.bridge.camera_manager._cameras = {'cam0': SimpleNamespace(is_connected=True, sn='MOCK', device_info=SimpleNamespace(name='Mock camera'),
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
                target.calib.last_stitch_transforms = [np.eye(4), np.eye(4)]
            with patch.object(self.bridge.calibration_engine, 'get_transform', return_value=np.eye(4)), \
                    patch.object(target, 'stitch', return_value=returned) as stitch:
                self.win._industrial_ribbon.commands[(mode, 'stitch')].click()
                self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
                stitch.assert_called_once()
            results = [row for row in database.records.values() if row.kind == 'result']
            self.assertEqual(len(results), 1, self.win._st_hint.text())
            self.assertEqual(results[0].source_ids, [frame.database_id for frame in frames])

    def test_large_turntable_uses_isolated_job_and_publishes_transform_provenance(self):
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        database = self.bridge.frame_db.databases['turntable']
        frames = [self.source(i) for i in (1,2)]
        ids = [database.ingest(frame) for frame in frames]
        for uid in ids:
            database.records[uid].points = 1_000_000
        session = self.win.workspace_turntable().session
        session.apply_calibration([0,0,1], [0,0,0], 90, 4)
        session.sequence = frames
        cloud = frames[0].load_pointcloud_o3d()
        transforms = [np.eye(4).tolist(), np.eye(4).tolist()]
        with patch('core.turntable_stitch_job.run_job', return_value=(cloud, dict(transforms=transforms, counts=[4,4]))) as job:
            self.win._industrial_ribbon.commands[('turntable','stitch')].click()
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
            job.assert_called_once()
        result = next(row for row in database.records.values() if row.kind=='result')
        self.assertEqual(result.source_ids, ids)
        self.assertEqual(set(result.source_transforms), set(ids))

    def check_clouds(self, mode, ids):
        browser = self.bridge.frame_db.browsers[mode]
        for uid in ids:
            browser.set_component_checked(uid, 'cloud')
        viewer = self.win._stack.currentWidget().viewer
        panel = viewer() if callable(viewer) else viewer
        self.wait(lambda: len(panel._database_clouds) == len(ids) and
                  not any(w.isRunning() for w in self.bridge._workers))

    def run_mode(self, mode):
        self.win._industrial_ribbon.commands[(mode, 'stitch')].click()
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))

    def test_checked_mobile_subset_overrides_row_selection_and_publishes_only_inputs(self):
        self.mobile()
        first, second = list(self.db.records)
        third = self.source(3)
        third.markers = [dict(m, x_3d=m['x_3d']+20) for m in self.db.records[first].markers]
        third.markers_all = third.markers
        last = self.db.ingest(third)
        self.select_raw(second)
        self.check_clouds('mobile_chain', [first, last])
        with self.assertLogs('core.utils', level='INFO') as captured:
            self.run_mode('mobile_chain')
        messages = '\n'.join(captured.output)
        self.assertIn('参与拼接的原始点云：帧001、帧003', messages)
        self.assertIn('标定 帧003→帧001', messages)
        self.assertIn('参考相机自动设为: 帧001', messages)
        self.assertIn('机位 帧003 配准成功', messages)
        self.assertNotIn('station_2', messages)
        chain = self.bridge.mobile_workflow._chain_stitcher
        self.assertEqual(list(chain.nodes), ['station_1', 'station_2'])
        self.assertEqual(chain.edges[0].from_id, 'station_2')
        self.assertEqual(chain.edges[0].to_id, 'station_1')
        self.assertIn(('station_1', 'station_2'), chain.calibration_engine.pair_results)
        saved_calibration = chain.calibration_engine.to_dict()
        self.assertEqual(saved_calibration['reference_id'], 'station_1')
        self.assertIn('station_1|station_2', saved_calibration['pairs'])
        self.assertEqual(type(chain.calibration_engine)().display_name('cam0'), 'cam0')
        result = next(row for row in self.db.records.values() if row.kind == 'result')
        self.assertEqual(result.source_ids, [first, last])
        self.assertEqual(len(self.bridge.mobile_workflow.get_station_evaluations()), 2)
        self.assertEqual(self.bridge.frame_db.browsers['mobile_chain'].checked_components('cloud'), [])
        self.check_clouds('mobile_chain', [first, result.uid])
        self.run_mode('mobile_chain')
        self.assertEqual(sum(row.kind == 'result' for row in self.db.records.values()), 1)
        self.assertIn('仅勾选原始点云', self.win._st_hint.text())

    def test_selected_nonconsecutive_frame_failure_uses_db_number(self):
        self.mobile()
        first = next(iter(self.db.records))
        third = self.source(3)
        third.markers = self.db.records[first].markers
        third.markers_all = third.markers
        last = self.db.ingest(third)
        browser = self.bridge.frame_db.browsers['mobile_chain']
        with QSignalBlocker(browser.tree):
            browser.tree.clearSelection()
            browser._items[first].setSelected(True)
            browser._items[last].setSelected(True)
        from core.chain_stitcher import ChainStitcher
        original = ChainStitcher.add_frame
        def reject_third(chain, frame, **kwargs):
            if frame.camera_name == 'station_2':
                return False, '共有标记不足', None
            return original(chain, frame, **kwargs)
        with patch.object(ChainStitcher, 'add_frame', reject_third):
            self.run_mode('mobile_chain')
        self.assertIn('帧003：共有标记不足', self.win._st_hint.text())
        self.assertNotIn('原始帧 2', self.win._st_hint.text())
        self.assertFalse(any(row.kind == 'result' for row in self.db.records.values()))

    def test_checked_turntable_db_frames_register_without_internal_sequence(self):
        self.mobile()
        frames = [self.db.load_frame(uid)[0] for uid in self.db.records]
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        database = self.bridge.frame_db.databases['turntable']
        ids = [database.ingest(frame) for frame in frames]
        session = self.win.workspace_turntable().session
        self.assertEqual(session.get_all_frames(), [])
        self.check_clouds('turntable', ids)
        self.run_mode('turntable')
        results = [row for row in database.records.values() if row.kind == 'result']
        self.assertEqual(len(results), 1, self.win._st_hint.text())
        self.assertEqual(results[0].source_ids, ids)
        self.assertEqual(session.get_all_frames(), [])

    def test_checked_turntable_nonconsecutive_steps_use_original_angles(self):
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        ws = self.win.workspace_turntable()
        ws.spin_voxel.setValue(0)
        ws.chk_icp_refine.setChecked(False)
        ws.session.apply_calibration([0,0,1], [0,0,0], 90, 4)
        database = self.bridge.frame_db.databases['turntable']
        frames = [self.source(i) for i in (1,2,3)]
        ids = [database.ingest(frame) for frame in frames]
        ws.session.sequence = frames
        self.check_clouds('turntable', [ids[0], ids[2]])
        self.run_mode('turntable')
        result = next(row for row in database.records.values() if row.kind == 'result')
        self.assertEqual(result.source_ids, [ids[0], ids[2]])
        merged = np.asarray(database.load_frame(result.uid)[1].points)
        from core.point_cloud_processor import PointCloudProcessor
        raw = np.asarray(PointCloudProcessor._filter_valid(frames[0].load_pointcloud_o3d())[0].points)
        expected = np.vstack([raw, raw * [-1,-1,1]])
        np.testing.assert_allclose(merged, expected, atol=1e-5)
        self.assertEqual(ws.session.sequence, frames)

    def test_checked_multicam_uses_db_frames_and_extrinsics_not_scan_cache(self):
        database = self.bridge.frame_db.databases['multi_cam']
        ids = [database.ingest(self.source(i+1), camera=f'cam{i}') for i in range(3)]
        self.check_clouds('multi_cam', ids[:2])
        self.run_mode('multi_cam')
        self.assertTrue(all(row.kind == 'raw' for row in database.records.values()))
        self.assertIn('有效外参标定', self.win._st_hint.text())
        transform = np.eye(4)
        transform[0,3] = 10
        self.bridge.calibration_engine.pair_results[('cam0','cam1')] = dict(
            success=True, T=transform, rms_mm=.1, inlier_ratio=1.)
        self.bridge.fixed_workflow._reference_id = 'cam0'
        self.bridge.calibration_engine.reference_id = 'cam0'
        self.assertEqual(self.bridge.fixed_workflow.frames_scan, {})
        self.check_clouds('multi_cam', ids[:2])
        self.run_mode('multi_cam')
        result = next(row for row in database.records.values() if row.kind == 'result')
        self.assertEqual(result.source_ids, ids[:2])
        self.assertEqual(self.bridge.fixed_workflow.frames_scan, {})
        from core.point_cloud_processor import PointCloudProcessor
        source = database.load_frame(ids[0])[1]
        raw = np.asarray(PointCloudProcessor._filter_valid(source)[0].points)
        merged = np.asarray(database.load_frame(result.uid)[1].points)
        np.testing.assert_allclose(merged, np.vstack([raw, raw+[10,0,0]]), atol=1e-5)

    def test_checked_multicam_composes_chain_through_unselected_intermediate_camera(self):
        database = self.bridge.frame_db.databases['multi_cam']
        ids = [database.ingest(self.source(i+1), camera=f'cam{i}') for i in range(3)]
        engine = self.bridge.calibration_engine
        engine.reference_id = self.bridge.fixed_workflow._reference_id = 'cam0'
        engine.topology = 'chain'
        engine.required_cameras = ['cam0', 'cam1', 'cam2']
        for ref, cam, distance in [('cam0', 'cam1', 10), ('cam1', 'cam2', 20)]:
            transform = np.eye(4)
            transform[0, 3] = distance
            engine.pair_results[ref, cam] = dict(success=True, T=transform, rms_mm=.1, inlier_ratio=1.)
        self.check_clouds('multi_cam', [ids[0], ids[2]])
        self.run_mode('multi_cam')
        result = next(row for row in database.records.values() if row.kind == 'result')
        self.assertEqual(result.source_ids, [ids[0], ids[2]])
        from core.point_cloud_processor import PointCloudProcessor
        raw = np.asarray(PointCloudProcessor._filter_valid(database.load_frame(ids[0])[1])[0].points)
        merged = np.asarray(database.load_frame(result.uid)[1].points)
        np.testing.assert_allclose(merged, np.vstack([raw, raw+[30,0,0]]), atol=1e-5)

    def test_single_checked_frame_does_not_silently_stitch_all(self):
        self.mobile()
        self.check_clouds('mobile_chain', [next(iter(self.db.records))])
        self.run_mode('mobile_chain')
        self.assertTrue(all(row.kind == 'raw' for row in self.db.records.values()))
        self.assertIn('至少需要两帧', self.win._st_hint.text())


if __name__ == '__main__':
    unittest.main()
