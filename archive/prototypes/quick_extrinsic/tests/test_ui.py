"""Offscreen UI wiring and worker failure recovery, no device initialization."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from quick_extrinsic import Window
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
import numpy as np
from core.frame_data import FrameData


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        families = QFontDatabase.applicationFontFamilies(font)
        if families:
            cls.app.setFont(QFont(families[0], 9))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = Window(self.temp.name)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.window.close)

    def pump(self):
        deadline = time.monotonic() + 5
        while self.window.job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertIsNone(self.window.job)

    def test_worker_success_refreshes_and_reenables(self):
        self.window.run(lambda: 'worker complete')
        self.assertFalse(self.window.controls.isEnabled())
        self.pump()
        self.assertTrue(self.window.controls.isEnabled())
        self.assertIn('worker complete', self.window.log.toPlainText())

    def test_failure_recovers_and_reports(self):
        from unittest.mock import patch
        with patch('quick_extrinsic.QMessageBox.warning') as warning:
            self.window.run(lambda: (_ for _ in ()).throw(ValueError('failure sentinel')))
            self.pump()
            warning.assert_called_once()
        self.assertTrue(self.window.controls.isEnabled())
        self.assertIn('failure sentinel', self.window.log.toPlainText())

    def test_data_population_and_clear(self):
        for cid in ['cam0', 'cam1']:
            points = np.array([[10, 20, 300], [10, 40, 300], [40, 40, 300], [40, 20, 300]], float)
            markers = [dict(code=i, x_2d=float(p[0]), y_2d=float(p[1]),
                            x_3d=float(p[0]), y_3d=float(p[1]), z_3d=float(p[2]), valid_3d=True)
                       for i, p in enumerate(points)]
            frame = FrameData(0, cid, image_np=np.full((100, 100, 3), 220, np.uint8),
                              markers=markers, markers_all=markers)
            self.window.flow.frames['calib'][cid] = frame
            self.window.flow.detected[cid] = {'markers': markers, 'board': None}
        self.window.flow.mode = 'coded_circle'
        self.window.flow.calibrate('cam0')
        self.window.refresh()
        self.assertEqual(self.window.images.count(), 2)
        self.assertEqual(self.window.markers.rowCount(), 8)
        self.assertIn('cam1→cam0', self.window.transforms.toPlainText())
        self.window.flow.clear_frames()
        self.window.refresh()
        self.assertEqual(self.window.images.count(), 0)
        self.assertEqual(self.window.markers.rowCount(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
