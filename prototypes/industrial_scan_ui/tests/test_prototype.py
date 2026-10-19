"""Offline regressions; direct unittest script, never initializes camera hardware."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))
from industrial_scan_ui.core.session import CloudLayer, ScanSession, demo_cloud, crop_background, read_cloud, write_cloud
from industrial_scan_ui.app.window import ScanWorkbench
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest


class PrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = ScanWorkbench()

    def tearDown(self):
        self.win._timer.stop()
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def wait_job(self):
        deadline = time.monotonic() + 20
        while self.win._busy:
            self.assertLess(time.monotonic(), deadline, 'background task timeout')
            self.app.processEvents()
            time.sleep(.01)

    def test_scan_pause_resume_finish_and_no_duplicate_completion(self):
        model = ScanSession()
        self.assertTrue(model.start())
        self.assertFalse(model.start())
        self.assertIsNone(model.advance(40))
        self.assertTrue(model.pause())
        self.assertIsNone(model.advance(60))
        self.assertEqual(model.progress, 40)
        with self.assertRaises(ValueError):
            model.finish()
        model.start()
        self.assertIsNotNone(model.advance(60))
        self.assertIsNone(model.advance(100))
        self.assertEqual(len(model.layers), 1)
        model.finish()
        self.assertEqual(model.state, 'finished')

    def test_ribbon_buttons_drive_demo_and_pause_gate(self):
        self.win._actions['scan'].click()
        self.assertEqual(self.win.current_state(), 'scanning')
        self.assertFalse(self.win._actions['export'].isEnabled())
        self.win._tick()
        self.win._actions['pause'].click()
        progress = self.win.session.progress
        self.win._tick()
        self.assertEqual(self.win.session.progress, progress)
        self.win.scan_button.click()
        for _ in range(30):
            self.win._tick()
        self.assertEqual(len(self.win.session.layers), 2)
        self.assertEqual(self.win.current_state(), 'captured')
        self.win._actions['finish'].click()
        self.assertEqual(self.win.current_state(), 'finished')

    def test_visibility_crop_undo_and_delete(self):
        root = self.win.tree.topLevelItem(0)
        item = root.child(0)
        item.setCheckState(0, Qt.Unchecked)
        self.assertEqual(self.win.canvas.total_points, 0)
        self.assertFalse(self.win._actions['export'].isEnabled())
        item.setCheckState(0, Qt.Checked)
        original = self.win.session.layers[0].points.copy()
        self.win._actions['crop'].click()
        self.assertLess(len(self.win.session.layers[0].points), len(original))
        self.assertTrue((self.win.session.layers[0].points[:, 2] > 5).all())
        self.win.undo()
        np.testing.assert_array_equal(self.win.session.layers[0].points, original)
        self.win.delete_layer()
        self.assertEqual(self.win.canvas.total_points, 0)
        self.win.undo()
        self.assertEqual(self.win.canvas.total_points, len(original))

    def test_invalid_crop_is_non_destructive(self):
        layer = self.win.session.layers[0]
        self.win.z_cut.setValue(100000)
        self.win.remove_background()
        self.assertIs(self.win.session.layers[0], layer)
        self.assertEqual(len(self.win._undo), 0)

    def test_real_import_unit_conversion_and_export_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'metres.ply'
            destination = Path(directory) / 'millimetres.ply'
            layer = CloudLayer('fixture', np.array([[.01, .02, .03], [.04, .05, .06]]))
            write_cloud(source, [layer])
            self.win.import_file(source, 'm')
            self.wait_job()
            np.testing.assert_allclose(self.win.session.layers[-1].points,
                                       [[10, 20, 30], [40, 50, 60]])
            self.win.session.layers[0].visible = False
            self.win.export_file(destination)
            self.wait_job()
            actual = read_cloud(destination)
            self.assertEqual(len(actual.points), 2)
            np.testing.assert_allclose(actual.points, [[10, 20, 30], [40, 50, 60]])
            self.assertIsNone(self.win._worker)

    def test_empty_and_nonfinite_cloud_handling(self):
        with self.assertRaises(ValueError):
            CloudLayer('empty', np.empty((0, 3)))
        layer = CloudLayer('partial', [[1, 2, 3], [np.nan, 0, 0]], [[1, 0, 0], [0, 1, 0]])
        self.assertEqual(len(layer.points), 1)
        np.testing.assert_array_equal(layer.colors, [[1, 0, 0]])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                write_cloud(Path(directory) / 'none.ply', [])

    def test_preview_budget_across_layers_and_no_data_loss(self):
        layer = demo_cloud(spacing=.5)
        layers = [layer] * 8
        self.win.canvas.set_layers(layers, fit=True)
        self.assertLessEqual(len(self.win.canvas._points), self.win.canvas.MAX_PREVIEW)
        self.assertEqual(self.win.canvas.total_points, len(layer.points) * 8)
        self.assertGreater(self.win.canvas.total_points, len(self.win.canvas._points))

    def test_compatibility_interaction_lod_restores_without_editing_source(self):
        canvas = self.win.canvas
        original = self.win.session.layers[0].points.copy()
        full = canvas.displayed_points
        QTest.mousePress(canvas, Qt.LeftButton, pos=QPoint(200, 200))
        self.assertLessEqual(canvas.displayed_points, 3000)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=QPoint(200, 200))
        QTest.qWait(260)
        self.assertEqual(canvas.displayed_points, full)
        np.testing.assert_array_equal(self.win.session.layers[0].points, original)
        self.assertIn('兼容', canvas.backend_name)
        self.assertFalse(self.win.render_quality.isEnabled())

    def test_display_controls_and_mouse_navigation(self):
        self.win.grid_toggle.setChecked(False)
        self.win.axes_toggle.setChecked(False)
        self.win.point_size.setValue(4)
        self.win.color_mode.setCurrentText('高度着色')
        canvas = self.win.canvas
        self.assertFalse(canvas.grid)
        self.assertFalse(canvas.axes)
        self.assertEqual(canvas.point_size, 4)
        self.assertEqual(canvas.color_mode, '高度着色')
        canvas.resize(800, 500)
        before = canvas.yaw
        QTest.mousePress(canvas, Qt.LeftButton, pos=QPoint(200, 200))
        move = QMouseEvent(QMouseEvent.MouseMove, QPointF(240, 220), QPointF(240, 220),
                           Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(canvas, move)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=QPoint(240, 220))
        self.assertNotEqual(canvas.yaw, before)
        canvas.set_view('顶视')
        self.assertEqual(canvas.pitch, 0)
        # Exercise all paint branches with a headless image.
        self.assertFalse(canvas.grab().isNull())

    def test_integration_hooks_never_connect_hardware(self):
        self.win.set_devices([object(), object()])
        self.assertIn('2', self.win.device_label.text())
        self.win.set_state('captured')
        self.assertEqual(self.win.current_state(), 'captured')
        called = []
        def runner(func, callback):
            called.append(True)
            callback(func(), None)
        self.win.set_background_runner(runner)
        with tempfile.TemporaryDirectory() as directory:
            self.win.export_file(Path(directory) / 'hook.ply')
        self.assertEqual(called, [True])
        self.assertFalse(self.win._busy)

    def test_failed_import_preserves_layers_and_releases_worker(self):
        layers = list(self.win.session.layers)
        with patch('industrial_scan_ui.app.window.QMessageBox.warning') as warning:
            self.win.import_file('file_that_does_not_exist.ply')
            self.wait_job()
            warning.assert_called_once()
        self.assertEqual(self.win.session.layers, layers)
        self.assertIsNone(self.win._worker)
        self.assertTrue(self.win._actions['import'].isEnabled())

    def test_compact_window_and_task_close_gate(self):
        from PySide6.QtGui import QCloseEvent
        self.win.resize(1000, 660)
        self.win.show()
        self.app.processEvents()
        self.assertGreaterEqual(self.win.canvas.width(), 360)
        self.assertGreaterEqual(self.win.canvas.height(), 300)
        self.assertFalse(self.win.grab().isNull())
        self.win._busy = True
        event = QCloseEvent()
        self.win.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.win._busy = False


if __name__ == '__main__':
    unittest.main(verbosity=2)
