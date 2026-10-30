"""Raw DB overlays remain isolated from calibration and workflow geometry."""
import threading
import unittest
from unittest.mock import patch
import numpy as np
import test_ui_frame_database as fixtures


class OverlayTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.FrameBrowserTests.setUpClass.__func__)
    setUp = fixtures.FrameBrowserTests.setUp
    tearDown = fixtures.FrameBrowserTests.tearDown
    source = fixtures.FrameBrowserTests.source
    wait = fixtures.FrameBrowserTests.wait

    def panel(self):
        return self.win.workspace_multi().viewer()

    def test_latest_capture_replaces_visible_frame_and_survives_renderer_switch(self):
        panel = self.panel()
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        a = self.db.load_frame(first, 'cloud')[1]
        b = self.db.load_frame(second, 'cloud')[1]
        panel.set_pointcloud('frame0', a)
        panel.set_pointcloud('frame1', b)
        self.assertEqual([layer.name for layer in panel.viewer()._layers], ['frame1'])
        panel.set_pointcloud_merged(a)
        panel.set_pointcloud('frame0', b)
        self.assertEqual([layer.name for layer in panel.viewer()._layers], ['frame0'])
        panel.set_industrial(False)
        panel.set_industrial(True)
        self.assertEqual([layer.name for layer in panel.viewer()._layers], ['frame0'])
        self.assertEqual(set(panel._clouds), {'frame0', 'frame1'})

    def test_unchecking_overlay_returns_to_latest_capture(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        panel = self.panel()
        panel.set_pointcloud('frame0', self.db.load_frame(first, 'cloud')[1])
        panel.set_pointcloud('frame1', self.db.load_frame(second, 'cloud')[1])
        self.browser.set_component_checked(first, 'cloud')
        self.browser.set_component_checked(second, 'cloud')
        self.wait(lambda: len(panel._database_clouds) == 2)
        self.assertEqual(len(panel.viewer()._layers), 2)
        self.browser.set_component_checked(first, 'cloud', False)
        self.assertEqual(len(panel.viewer()._layers), 1)
        self.browser.set_component_checked(second, 'cloud', False)
        self.assertEqual([layer.name for layer in panel.viewer()._layers], ['frame1'])

    def test_two_checked_raw_clouds_use_original_coordinates_and_cache(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        original = {uid: np.asarray(self.db.load_frame(uid, 'cloud')[1].points).copy() for uid in (first, second)}
        self.panel().set_pointcloud('工作点云', self.db.load_frame(first, 'cloud')[1])
        workflow = self.panel()._clouds.copy()
        with patch.object(self.db, 'load_frame', wraps=self.db.load_frame) as load:
            self.browser.set_component_checked(first, 'cloud')
            self.browser.set_component_checked(second, 'cloud')
            self.wait(lambda: len(self.panel()._database_clouds) == 2)
            self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
            self.assertEqual(load.call_count, 2)
            for uid in (first, second):
                cloud = next(cloud for key, cloud in self.panel()._database_clouds.items() if uid in key)
                np.testing.assert_array_equal(np.asarray(cloud.points), original[uid])
            self.browser.tree.setCurrentItem(self.browser._component_items[first, 'cloud'])
            self.assertEqual(len(self.panel()._database_clouds), 2)
            self.browser.set_component_checked(first, 'cloud', False)
            self.wait(lambda: len(self.panel()._database_clouds) == 1)
            self.assertEqual(load.call_count, 2)
        self.assertEqual(self.panel()._clouds, workflow)
        self.assertEqual(len(self.panel().viewer()._layers), 1)
        self.assertIn('未应用标定变换', self.win._st_hint.text())
        self.browser.tree.setCurrentItem(self.browser._component_items[second, 'image'])
        self.wait(lambda: '的2D图像' in self.win._st_hint.text())
        self.assertEqual(len(self.panel()._database_clouds), 1)
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        tree = self.browser.tree
        QTest.mouseClick(tree.viewport(), Qt.LeftButton,
                         pos=QPoint(15, tree.viewport().height()-10))
        self.assertIsNone(tree.currentItem())
        self.assertEqual(len(self.panel()._database_clouds), 1)
        self.assertEqual(self.browser.checked_components('cloud'), [(second, 'cloud')])
        self.browser.set_component_checked(second, 'cloud', False)
        self.assertEqual(self.panel()._database_clouds, {})
        self.assertFalse(self.browser.checked_components('cloud'))
        self.assertEqual(self.panel().viewer().mode.currentData(), None)
        self.assertEqual(len(self.panel().viewer()._layers), 1)
        np.testing.assert_array_equal(self.panel().viewer()._layers[0].points, original[first])

    def test_clear_checks_while_reading_drops_late_result(self):
        uid = self.db.ingest(self.source())
        entered, release = threading.Event(), threading.Event()
        load = self.db.load_frame
        def delayed(*args):
            entered.set()
            release.wait(5)
            return load(*args)
        try:
            with patch.object(self.db, 'load_frame', delayed):
                self.browser.set_component_checked(uid, 'cloud')
                self.wait(entered.is_set)
                self.browser.set_component_checked(uid, 'cloud', False)
                release.set()
                self.wait(lambda: not self.bridge.frame_db.overlay._running)
                self.assertEqual(self.panel()._database_clouds, {})
                self.assertEqual(self.browser.checked_components('cloud'), [])
        finally:
            release.set()

    def test_fast_changes_coalesce_and_keep_only_latest_checked_frames(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        entered, release = threading.Event(), threading.Event()
        load = self.db.load_frame
        def delayed(*args):
            if args[0] == first:
                entered.set()
                release.wait(5)
            return load(*args)
        try:
            with patch.object(self.db, 'load_frame', delayed):
                self.browser.set_component_checked(first, 'cloud')
                self.wait(entered.is_set)
                self.browser.set_component_checked(second, 'cloud')
                self.browser.set_component_checked(first, 'cloud', False)
                release.set()
                self.wait(lambda: any(second in key for key in self.panel()._database_clouds))
                self.assertEqual(len(self.panel()._database_clouds), 1)
                self.assertFalse(any(first in key for key in self.panel()._database_clouds))
        finally:
            release.set()

    def test_missing_cloud_is_unchecked_and_other_cloud_remains(self):
        first = self.db.ingest(self.source())
        second = self.db.ingest(self.source(2))
        load = self.db.load_frame
        def fail_one(uid, component):
            if uid == second:
                raise IOError('missing test PLY')
            return load(uid, component)
        with patch.object(self.db, 'load_frame', fail_one):
            self.browser.set_component_checked(first, 'cloud')
            self.browser.set_component_checked(second, 'cloud')
            self.wait(lambda: bool(self.panel()._database_clouds))
            self.wait(lambda: not self.bridge.frame_db.overlay._running)
            self.assertEqual(self.browser.checked_components('cloud'), [(first, 'cloud')])
            self.assertEqual(len(self.panel()._database_clouds), 1)

    def test_restore_and_presentation_switch_clear_overlay_checks(self):
        uid = self.db.ingest(self.source())
        self.browser.set_component_checked(uid, 'cloud')
        self.wait(lambda: bool(self.panel()._database_clouds))
        self.bridge.frame_db.restore('multi_cam')
        self.assertEqual(self.browser.checked_components('cloud'), [])
        self.assertEqual(self.panel()._database_clouds, {})
        self.browser.set_component_checked(uid, 'cloud')
        self.wait(lambda: bool(self.panel()._database_clouds))
        self.win.set_presentation('classic')
        self.assertEqual(self.browser.checked_components('cloud'), [])
        self.win.set_presentation('industrial')
        self.assertEqual(self.panel()._database_clouds, {})

    def test_record_revision_refresh_reloads_checked_cloud(self):
        uid = self.db.ingest(self.source())
        with patch.object(self.db, 'load_frame', wraps=self.db.load_frame) as load:
            self.browser.set_component_checked(uid, 'cloud')
            self.wait(lambda: bool(self.panel()._database_clouds))
            self.wait(lambda: not self.bridge.frame_db.overlay._running)
            old = self.panel()._database_cloud
            self.db.records[uid].revision += 1
            self.bridge.frame_db._changed('multi_cam')
            self.wait(lambda: self.panel()._database_cloud is not None and self.panel()._database_cloud is not old)
            self.assertEqual(load.call_count, 2)
            self.assertEqual(self.browser.checked_components('cloud'), [(uid, 'cloud')])

    def test_mode_switch_during_read_cannot_write_into_new_workspace(self):
        uid = self.db.ingest(self.source())
        entered, release = threading.Event(), threading.Event()
        load = self.db.load_frame
        def delayed(*args):
            entered.set()
            release.wait(5)
            return load(*args)
        try:
            with patch.object(self.db, 'load_frame', delayed):
                self.browser.set_component_checked(uid, 'cloud')
                self.wait(entered.is_set)
                self.win.set_mode('mobile_chain', [])
                release.set()
                self.wait(lambda: not self.bridge.frame_db.overlay._running)
                self.assertEqual(self.panel()._database_clouds, {})
                self.assertEqual(self.win.workspace_mobile().viewer()._database_clouds, {})
                self.assertEqual(self.browser.checked_components('cloud'), [])
        finally:
            release.set()

    def test_shared_overlay_works_in_all_three_modes(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            self.bridge._current_mode = mode
            self.win.set_mode(mode, [])
            self.win.set_presentation('industrial')
            workspace = self.win._stack.currentWidget()
            panel = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
            browser = workspace._industrial.frame_browser
            database = self.bridge.frame_db.databases[mode]
            frame = self.source()
            frame.markers = [dict(code=17, x_2d=1, y_2d=1, x_3d=10, y_3d=20, z_3d=30)]
            uid = database.ingest(frame)
            browser.set_component_checked(uid, 'cloud')
            self.wait(lambda: any(uid in key for key in panel._database_clouds))
            self.assertEqual(len(panel.viewer()._layers), 1)
            self.assertEqual(panel.viewer().canvas._cloud_markers, [(17, ((10., 20., 30.), '#4ee887'))])
            self.bridge.frame_db.restore(mode)
            self.assertEqual(panel._database_clouds, {})
            self.assertEqual(panel.viewer().canvas._cloud_markers, [])

    def test_turntable_checked_markers_follow_clouds_not_image_selection(self):
        self.bridge._current_mode = 'turntable'
        self.win.set_mode('turntable', [])
        workspace = self.win.workspace_turntable()
        panel = workspace.viewer
        browser = workspace._industrial.frame_browser
        database = self.bridge.frame_db.databases['turntable']
        first, second = self.source(), self.source(2)
        def marker(code, xyz, **extra):
            return dict(code=code, x_2d=1, y_2d=1,
                        x_3d=xyz[0], y_3d=xyz[1], z_3d=xyz[2], **extra)
        first.markers_all = [marker(17, (10, 20, 30)), marker(21, (0, 0, 0)),
                             marker(25, (1, 2, 3), valid_3d=False), marker(29, (1, 2, float('nan')))]
        second.markers_all = [marker(17, (40, 50, 60))]
        first_id, second_id = database.ingest(first), database.ingest(second)
        browser.tree.setCurrentItem(browser._component_items[first_id, 'cloud'])
        self.wait(lambda: panel._database_cloud is not None)
        expected = [(17, ((10., 20., 30.), '#4ee887'))]
        self.assertEqual(panel._cloud_markers, expected)
        browser.set_component_checked(first_id, 'cloud')
        self.wait(lambda: any(first_id in key for key in panel._database_clouds))
        self.assertEqual(panel._cloud_markers, expected)
        browser.tree.setCurrentItem(browser._component_items[second_id, 'image'])
        self.wait(lambda: '的2D图像' in self.win._st_hint.text())
        self.assertEqual(panel._cloud_markers, expected)
        browser.set_component_checked(second_id, 'cloud')
        self.wait(lambda: len(panel._database_clouds) == 2)
        self.assertEqual(panel._cloud_markers, expected + [(17, ((40., 50., 60.), '#4ee887'))])
        browser.set_component_checked(first_id, 'cloud', False)
        self.assertEqual(panel._cloud_markers, [(17, ((40., 50., 60.), '#4ee887'))])
        database.records[second_id].markers = [marker(31, (70, 80, 90))]
        database.records[second_id].revision += 1
        self.bridge.frame_db._changed('turntable')
        self.wait(lambda: panel._cloud_markers == [(31, ((70., 80., 90.), '#4ee887'))])
        browser.properties.options['marker_centers'].setChecked(False)
        self.assertFalse(panel.viewer().canvas.marker_centers)
        browser.properties.options['marker_centers'].setChecked(True)
        self.assertTrue(panel.viewer().canvas.marker_centers)
        database.records[second_id].kind = 'result'
        database.records[second_id].revision += 1
        self.bridge.frame_db._changed('turntable')
        self.wait(lambda: bool(panel._database_clouds) and not panel._cloud_markers)
        browser.set_component_checked(second_id, 'cloud', False)
        self.assertEqual(panel._cloud_markers, [])

    def test_cleanup_before_debounce_does_not_start_a_new_worker(self):
        from PySide6.QtTest import QTest
        uid = self.db.ingest(self.source())
        with patch.object(self.db, 'load_frame', wraps=self.db.load_frame) as load:
            self.browser.set_component_checked(uid, 'cloud')
            self.bridge.cleanup()
            QTest.qWait(80)
            self.app.processEvents()
            load.assert_not_called()
            self.assertFalse(self.bridge.frame_db.overlay._running)

    def test_blank_click_invalidates_late_single_preview_selection(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        uid = self.db.ingest(self.source())
        entered, release = threading.Event(), threading.Event()
        load = self.db.load_frame
        def delayed(*args):
            entered.set()
            release.wait(5)
            return load(*args)
        try:
            with patch.object(self.db, 'load_frame', delayed):
                tree = self.browser.tree
                tree.setCurrentItem(self.browser._component_items[uid, 'cloud'])
                self.wait(entered.is_set)
                QTest.mouseClick(tree.viewport(), Qt.LeftButton,
                                 pos=QPoint(15, tree.viewport().height()-10))
                release.set()
                self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
                self.assertIsNone(tree.currentItem())
                self.assertEqual(tree.selectedItems(), [])
                self.assertIsNone(self.panel()._database_cloud)
        finally:
            release.set()
