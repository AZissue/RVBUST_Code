"""ROI preview compatibility with the shared QImage canvas."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .dialog import FeatureMatchDialog, RegionPreview


class RegionPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_loaded_cleared_and_zoomed_roi(self):
        view = RegionPreview()
        self.addCleanup(view.close)
        view.resize(640, 480)
        view.show()
        self.app.processEvents()
        view.paintEvent(None)
        self.assertTrue(view._image_rect().isEmpty())
        view.reset(np.zeros((480, 640, 3), np.uint8))
        view.paintEvent(None)
        rect = view._image_rect()
        QTest.mousePress(view, Qt.LeftButton, pos=QPoint(round(rect.left()+rect.width()/4),
                                                       round(rect.top()+rect.height()/4)))
        QTest.mouseRelease(view, Qt.LeftButton, pos=QPoint(round(rect.left()+rect.width()*3/4),
                                                         round(rect.top()+rect.height()*3/4)))
        np.testing.assert_allclose(view.pixel_box(), (160, 120, 480, 360), atol=1)
        view.zoom = 2
        view.pan = QPointF(10, 20)
        center = view._image_rect().center()
        np.testing.assert_allclose((view._normalized(center).x(), view._normalized(center).y()), (.5, .5))
        view.paintEvent(None)
        view.reset()
        view.paintEvent(None)
        self.assertIsNone(view.pixel_box())

    def test_match_result_uses_current_image_dimensions(self):
        views = (RegionPreview(), RegionPreview())
        for view in views:
            self.addCleanup(view.close)
            view.reset(np.zeros((120, 200, 3), np.uint8))
        target = SimpleNamespace(views=views, report=Mock(), refresh=Mock(), rms=None, snapshot=None)
        result = SimpleNamespace(inliers=np.array([True]), valid=np.array([True]),
            pixels=(np.array([[100., 60.]]), np.array([[50., 30.]])),
            pose=np.eye(4), errors=np.array([.1]), reason='')
        FeatureMatchDialog.show_result(target, result, 'temporary', (), ())
        self.assertIsNotNone(target.snapshot)
        self.assertEqual(len(views[0].display.rows), 1)
