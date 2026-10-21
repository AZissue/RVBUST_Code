"""Turntable calibration geometry, session lifecycle and DB category regressions."""
import unittest
from dataclasses import replace
import numpy as np
from scipy.spatial.transform import Rotation
import test_ui_frame_database as fixtures
from core.turntable_calibrator import estimate_rotation_center


class RotationCenterTests(unittest.TestCase):
    def test_small_angle_center_uses_axis_gauge_without_numeric_explosion(self):
        axis = np.array([.381, -.778, -.499])
        axis /= np.linalg.norm(axis)
        expected = np.array([120., -30., 400.])
        anchor = np.array([20., 30., 500.])
        for angle in (.02, 15., 90.):
            rotation = Rotation.from_rotvec(axis * np.radians(angle)).as_matrix()
            translation = expected - rotation @ expected
            actual = estimate_rotation_center(rotation, translation, anchor)
            perpendicular = actual - expected
            perpendicular -= axis * np.dot(perpendicular, axis)
            self.assertLess(np.linalg.norm(perpendicular), 1e-6)
            self.assertLess(abs(np.dot(actual-anchor, axis)), 1e-6)
            np.testing.assert_allclose((rotation-np.eye(3)) @ actual, -translation, atol=1e-9)


class TurntablePresentationTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.FrameBrowserTests.setUpClass.__func__)
    setUp = fixtures.FrameBrowserTests.setUp
    tearDown = fixtures.FrameBrowserTests.tearDown
    wait = fixtures.FrameBrowserTests.wait
    source = fixtures.FrameBrowserTests.source
    def test_calibration_panel_updates_toggles_and_clears_with_session(self):
        self.win.set_mode('turntable', [])
        workspace = self.win.workspace_turntable()
        panel = workspace._industrial.calibration_panel
        self.assertTrue(panel.isVisible())
        self.assertTrue(workspace._industrial.sidebar.isHidden())
        workspace.session.calib.set_calibration([0, 0, 1], [10, 20, 30], 30., 12)
        workspace.session.calibrated = True
        workspace._update_online_ui()
        canvas = workspace.viewer.viewer().canvas
        self.assertIn('30.0000°', panel.values.text())
        np.testing.assert_allclose(canvas._rotation_geometry[1], [10, 20, 30])
        count = canvas.total_points
        panel.show_geometry.setChecked(False)
        self.assertIsNone(canvas._rotation_geometry)
        panel.show_geometry.setChecked(True)
        panel.locate.click()
        np.testing.assert_allclose(canvas.center, [10, 20, 30])
        self.assertEqual(count, canvas.total_points)
        self.app.processEvents()
        image = canvas._rotation_overlay.grab().toImage()
        colors = {image.pixelColor(x, y).name() for x in range(image.width()//2-12, image.width()//2+13)
                  for y in range(image.height()//2-12, image.height()//2+13)}
        self.assertIn('#ff8c7e', colors)
        workspace.session.calib.set_calibration([0, 0, 1], [10, 20, 30], .02, 18000)
        workspace._update_online_ui()
        self.assertIn('转角过小', panel.warning.text())
        workspace.session.calib.set_calibration([0, 0, 1], [1e13, 20, 30], .02, 18000)
        workspace._update_online_ui()
        self.assertIsNone(canvas._rotation_geometry)
        self.assertFalse(panel.locate.isEnabled())
        workspace._reset_online_state()
        self.assertIn('未标定', panel.status.text())
        self.assertIsNone(canvas._rotation_geometry)
        self.assertEqual(workspace.lbl_online_calib.text(), '未标定')

    def test_categories_select_only_their_frames_and_remain_collapsed(self):
        first = self.source(1)
        second = self.source(2)
        first_id = self.db.ingest(first, purpose='标定数据')
        second_id = self.db.ingest(second, purpose='扫描数据')
        category = self.browser._items[first_id].parent()
        self.assertEqual(category.text(0), '标定帧')
        self.assertEqual(self.browser._items[second_id].parent().text(0), '扫描原始帧')
        self.browser.tree.clearSelection()
        category.setSelected(True)
        self.assertEqual(self.browser.selected_ids(), [first_id])
        category.setExpanded(False)
        self.browser.refresh()
        self.assertFalse(self.browser._items[first_id].parent().isExpanded())
        self.db.records[second_id] = replace(self.db.records[second_id], kind='result', source_ids=(first_id,))
        self.browser.refresh()
        self.assertEqual(self.browser._items[second_id].parent().text(0), '拼接结果')
        self.assertEqual(self.browser._items[first_id].parent().text(0), '标定帧')
