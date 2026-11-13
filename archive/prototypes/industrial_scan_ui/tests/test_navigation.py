"""Regression for the old Euler/clamped-pitch dead zones and mouse lifecycle."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys, unittest
import numpy as np
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]/'src'))
from industrial_scan_ui.core.trackball import Trackball
from industrial_scan_ui.app.canvas import CloudCanvas
from industrial_scan_ui.core.session import demo_cloud
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest


class TrackballTests(unittest.TestCase):
    def test_one_pixel_motion_changes_every_tested_viewport_region(self):
        for view in ('顶视', '正视', '右视', '等轴测'):
            for x, y in [(600, 350), (1, 1), (1197, 1), (1, 697), (1197, 697),
                         (600, 1), (1, 350), (1197, 350), (600, 697)]:
                for dx, dy in [(1, 0), (0, 1), (-1, 0), (0, -1)]:
                    ball = Trackball()
                    ball.set_view(view)
                    before = ball.matrix.copy()
                    self.assertTrue(ball.drag((x, y), (x+dx, y+dy), 1200, 700, (600, 350)))
                    self.assertGreater(np.linalg.norm(ball.matrix-before), 1e-7, (view, x, y, dx, dy))

    def test_continuous_rotations_do_not_stop_at_old_pitch_limit(self):
        ball = Trackball()
        for i in range(2000):
            before = ball.matrix.copy()
            ball.drag((600., 350.), (600., 355.), 1200, 700, (600, 350))
            self.assertGreater(np.linalg.norm(ball.matrix-before), 1e-4)
        np.testing.assert_allclose(ball.matrix.T @ ball.matrix, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(ball.matrix), 1., places=12)

    def test_reverse_drag_restores_orientation_without_jump(self):
        ball = Trackball()
        before = ball.matrix.copy()
        for start, end in [((600, 350), (800, 450)), ((800, 450), (1100, 650)),
                           ((1100, 650), (800, 450)), ((800, 450), (600, 350))]:
            ball.drag(start, end, 1200, 700, (600, 350))
        np.testing.assert_allclose(ball.matrix, before, atol=1e-12)

    def test_sphere_hyperbola_join_is_continuous(self):
        radius = 700*.45
        x = 600 + np.sqrt(.5)*radius
        a = Trackball.project((x-1e-4, 350), 1200, 700, (600, 350))
        b = Trackball.project((x+1e-4, 350), 1200, 700, (600, 350))
        self.assertLess(np.linalg.norm(a-b), 1e-5)


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = CloudCanvas()
        self.view.resize(1200, 700)
        self.view.set_layers([demo_cloud()], fit=True)

    def tearDown(self):
        self.view.shutdown()
        self.view.deleteLater()
        self.app.processEvents()

    def move(self, point, buttons, modifiers=Qt.NoModifier):
        event = QMouseEvent(QEvent.MouseMove, QPointF(*point), QPointF(*point),
                            Qt.NoButton, buttons, modifiers)
        QApplication.sendEvent(self.view, event)

    def test_former_corner_click_region_now_rotates(self):
        before = self.view.rotation.matrix.copy()
        QTest.mousePress(self.view, Qt.LeftButton, pos=QPoint(1170, 30))
        self.move((1171, 31), Qt.LeftButton)
        self.assertFalse(np.allclose(before, self.view.rotation.matrix))
        self.assertTrue(self.view._moving)
        QTest.mouseRelease(self.view, Qt.LeftButton, pos=QPoint(1171, 31))
        QTest.qWait(260)
        self.assertFalse(self.view._moving)

    def test_pan_is_pixel_exact_and_does_not_change_rotation(self):
        before = self.view.rotation.matrix.copy()
        for button in (Qt.RightButton,):
            pan = self.view.pan.copy()
            QTest.mousePress(self.view, button, pos=QPoint(500, 300))
            self.move((512, 309), button)
            np.testing.assert_allclose(self.view.pan, pan+[12, 9])
            QTest.mouseRelease(self.view, button, pos=QPoint(512, 309))
        np.testing.assert_allclose(self.view.rotation.matrix, before)

    def test_middle_pick_keeps_static_detail_and_does_not_drag(self):
        full = self.view.displayed_points
        center = self.view._points[len(self.view._points)//2].copy()
        calls = []
        def pick(position):
            calls.append(self.view.displayed_points)
            self.assertFalse(self.view._moving)
            return center
        self.view.pick_pivot = pick
        QTest.mousePress(self.view, Qt.MiddleButton, pos=QPoint(500, 300))
        np.testing.assert_array_equal(self.view.center, center)
        pan = self.view.pan.copy()
        rotation = self.view.rotation.matrix.copy()
        self.move((520, 320), Qt.MiddleButton)
        QTest.mouseRelease(self.view, Qt.MiddleButton, pos=QPoint(520, 320))
        self.assertEqual(calls, [full])
        self.assertEqual(self.view.displayed_points, full)
        np.testing.assert_array_equal(self.view.pan, pan)
        np.testing.assert_array_equal(self.view.rotation.matrix, rotation)
        self.assertFalse(self.view._restore.isActive())

    def test_middle_pick_restores_detail_before_pending_drag_timeout(self):
        full = self.view.displayed_points
        QTest.mousePress(self.view, Qt.LeftButton, pos=QPoint(500, 300))
        QTest.mouseRelease(self.view, Qt.LeftButton, pos=QPoint(500, 300))
        self.assertLess(self.view.displayed_points, full)
        seen = []
        self.view.pick_pivot = lambda point: seen.append(self.view.displayed_points)
        QTest.mouseClick(self.view, Qt.MiddleButton, pos=QPoint(500, 300))
        self.assertEqual(seen, [full])
        self.assertFalse(self.view._moving)

    def test_middle_background_preserves_view(self):
        self.view.pan[:] = [24, 37]
        center = self.view.center.copy()
        self.view.pick_pivot = lambda point: None
        QTest.mouseClick(self.view, Qt.MiddleButton, pos=QPoint(30, 30))
        np.testing.assert_array_equal(self.view.center, center)
        np.testing.assert_array_equal(self.view.pan, [24, 37])

    def test_left_double_click_no_longer_picks(self):
        calls = []
        self.view.pick_pivot = lambda point: calls.append(point)
        QTest.mouseDClick(self.view, Qt.LeftButton, pos=QPoint(500, 300))
        QTest.mouseRelease(self.view, Qt.LeftButton, pos=QPoint(500, 300))
        self.assertEqual(calls, [])

    def test_focus_loss_cancels_drag_and_next_press_responds(self):
        QTest.mousePress(self.view, Qt.LeftButton, pos=QPoint(500, 300))
        QApplication.sendEvent(self.view, QEvent(QEvent.WindowDeactivate))
        self.assertIsNone(self.view._last)
        QTest.qWait(260)
        self.assertFalse(self.view._moving)
        before = self.view.rotation.matrix.copy()
        QTest.mousePress(self.view, Qt.LeftButton, pos=QPoint(500, 300))
        self.move((501, 300), Qt.LeftButton)
        self.assertFalse(np.allclose(before, self.view.rotation.matrix))

    def test_new_pivot_preserves_scene_projection(self):
        points = self.view._points[::100].copy()
        before, _ = self.view.project(points)
        self.view.set_pivot(points[0])
        after, _ = self.view.project(points)
        np.testing.assert_allclose(before, after, atol=1e-9)

    def test_background_double_click_does_not_reset_view(self):
        self.view.pan[:] = [24, 37]
        original_center = self.view.center.copy()
        self.view.pick_pivot = lambda point: None
        QTest.mouseDClick(self.view, Qt.LeftButton, pos=QPoint(30, 30))
        np.testing.assert_array_equal(self.view.center, original_center)
        np.testing.assert_array_equal(self.view.pan, [24, 37])
        QTest.keyClick(self.view, Qt.Key_F)
        np.testing.assert_array_equal(self.view.pan, [0, 0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
