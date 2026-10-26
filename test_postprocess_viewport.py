"""Postprocess-only navigation and viewport segmentation command regression."""
import unittest
import threading
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt, QEvent, QPointF, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import test_postprocess as fixture


class ViewportTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp = fixture.PostprocessTests.setUp
    tearDown = fixture.PostprocessTests.tearDown
    wait = fixture.PostprocessTests.wait
    source = fixture.PostprocessTests.source
    finish = fixture.PostprocessTests.finish
    load_grid = fixture.PostprocessTests.load_grid

    def send_drag(self, target, button=Qt.MiddleButton):
        for kind, pos, pressed, buttons in (
                (QEvent.MouseButtonPress, (100, 150), button, button),
                (QEvent.MouseMove, (145, 180), Qt.NoButton, button),
                (QEvent.MouseButtonRelease, (145, 180), button, Qt.NoButton)):
            point = QPointF(*pos)
            event = QMouseEvent(kind, point, point, pressed, buttons, Qt.NoModifier)
            QApplication.sendEvent(target, event)

    def test_middle_drag_pans_without_rotating_or_changing_pivot(self):
        self.load_grid()
        canvas = self.editor.viewer.canvas
        pan, center, rotation = canvas.pan.copy(), canvas.center.copy(), canvas.rotation.matrix.copy()
        self.send_drag(canvas)
        np.testing.assert_allclose(canvas.pan - pan, [45, 30])
        np.testing.assert_array_equal(canvas.center, center)
        np.testing.assert_array_equal(canvas.rotation.matrix, rotation)
        self.assertEqual(canvas._drag_button, Qt.NoButton)
        main_canvas = self.win.workspace_multi().viewer().viewer().canvas
        self.assertFalse(main_canvas.property('postprocessMiddlePan'))

    def test_drawing_allows_middle_pan_and_discards_stale_polygon(self):
        self.load_grid()
        self.editor.start_polygon()
        overlay = self.editor.overlay
        QTest.mouseClick(overlay, Qt.LeftButton, pos=QPoint(100, 100))
        self.assertEqual(overlay.vertex_count, 1)
        canvas = self.editor.viewer.canvas
        before = canvas.pan.copy()
        self.send_drag(overlay)
        np.testing.assert_allclose(canvas.pan - before, [45, 30])
        self.assertFalse(overlay.active)
        self.assertIsNone(self.editor._segment)
        self.assertFalse(self.editor.segment_tools.buttons['inside'].isEnabled())
        self.assertFalse(self.editor._closed)

    def test_toolbar_close_keep_inside_and_undo_updates_db(self):
        _, source, _ = self.load_grid()
        tools = self.editor.segment_tools
        tools.buttons['draw'].click()
        self.assertTrue(tools.buttons['draw'].isChecked())
        self.assertFalse(tools.buttons['close'].isEnabled())
        overlay = self.editor.overlay
        w, h = overlay.width(), overlay.height()
        for point in (QPoint(1, 90), QPoint(w-2, 90), QPoint(w-2, h-2), QPoint(1, h-2)):
            QTest.mouseClick(overlay, Qt.LeftButton, pos=point)
        self.assertTrue(tools.buttons['back'].isEnabled())
        tools.buttons['back'].click()
        self.assertEqual(overlay.vertex_count, 3)
        QTest.mouseClick(overlay, Qt.LeftButton, pos=QPoint(1, h-2))
        tools.buttons['close'].click()
        self.finish()
        self.assertTrue(tools.buttons['inside'].isEnabled())
        self.assertTrue(tools.buttons['outside'].isEnabled())
        tools.buttons['inside'].click()
        self.finish()
        result = self.editor._display_ids[0]
        self.assertNotEqual(source, result)
        self.assertIn(source, self.db.records)
        self.editor.undo(); self.finish()
        self.assertEqual(self.editor._display_ids, [source])

    def test_tools_anchor_resize_and_escape_cancels_without_closing(self):
        self.load_grid()
        for width, height in ((1440, 900), (1050, 650)):
            self.editor.resize(width, height); self.app.processEvents()
            tools = self.editor.segment_tools
            canvas = self.editor.viewer.canvas
            self.assertEqual(tools.y(), 12)
            self.assertLessEqual(tools.geometry().right(), canvas.width()-8)
            self.assertIs(canvas.childAt(tools.geometry().center()), tools.childAt(tools.rect().center()) or tools)
        tools.buttons['draw'].click()
        QTest.keyClick(self.editor, Qt.Key_Escape)
        self.assertFalse(self.editor.overlay.active)
        self.assertFalse(self.editor._closed)

    def test_confirmed_mask_calculation_locks_middle_pan_until_cancel(self):
        self.load_grid()
        entered, release = threading.Event(), threading.Event()
        def delayed(points, polygon, **view):
            entered.set()
            release.wait(4)
            return np.ones(len(points), dtype=bool)
        with patch('ui_v2.postprocess.window.polygon_crop_mask', delayed):
            self.editor.stage_polygon([(10, 10), (500, 10), (500, 500)])
            self.assertTrue(entered.wait(2))
            try:
                before = self.editor.viewer.canvas.pan.copy()
                self.send_drag(self.editor.viewer.canvas)
                np.testing.assert_array_equal(self.editor.viewer.canvas.pan, before)
                self.assertTrue(self.editor.segment_tools.buttons['cancel'].isEnabled())
                self.editor.segment_tools.buttons['cancel'].click()
            finally:
                release.set()
            self.finish()
        self.assertIsNone(self.editor._segment)
        self.assertFalse(self.editor.overlay.active)
        self.assertFalse(self.editor.segment_tools.buttons['inside'].isEnabled())
        self.send_drag(self.editor.viewer.canvas)
        np.testing.assert_allclose(self.editor.viewer.canvas.pan - before, [45, 30])


if __name__ == '__main__':
    unittest.main()
