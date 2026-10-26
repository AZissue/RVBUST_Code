"""Small standard grids, diagnostics and registration gates without hardware."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.calib_board_detector import CalibBoardDetector
from core.marker_detector import MarkerDetector
from core.frame_data import FrameData
from core import frame_recognition


class BoardRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ply = Path(self.temp.name) / 'points.ply'
        self.ply.touch()
        self.image = np.zeros((1080, 1440), np.uint8)
        # 3px radius dots were rejected by the old ~90px area threshold.
        for row in range(11):
            for col in range(7):
                cv2.circle(self.image, (500 + (2*col + row % 2)*8, 500 + row*8), 3, 255, -1)
        yy, xx = np.mgrid[:1080, :1440]
        self.points = np.column_stack((xx.ravel()*.5, yy.ravel()*.5, np.full(xx.size, 500.)))

    def detect(self, points=None, include_invalid=True):
        detector = MarkerDetector('asymmetric_grid')
        with patch.object(CalibBoardDetector, '_read_ply_points', return_value=self.points if points is None else points):
            markers = detector.detect_3d(self.image, offline_ply_path=str(self.ply), include_invalid=include_invalid)
        return detector, markers

    def test_small_standard_grid_and_depth_reconstruct_rigid_pose(self):
        detector, markers = self.detect()
        board = detector.last_board_result
        self.assertIsNotNone(board)
        self.assertEqual(board['pattern_name'], '7x11')
        self.assertEqual(len(markers), 77)
        self.assertTrue(all(m['valid_3d'] for m in markers))
        self.assertLess(board['rms_mm'], .05)
        self.assertAlmostEqual(board['spacing_mm'], 4., places=2)

    def test_missing_or_unorganized_depth_preserves_2d_with_reason(self):
        for points in (np.empty((0, 3)), self.points[:100], np.zeros_like(self.points)):
            detector, markers = self.detect(points)
            self.assertIsNone(detector.last_board_result)
            self.assertEqual(len(markers), 77)
            self.assertTrue(all(not m['valid_3d'] for m in markers))
            self.assertTrue(detector.last_board_diagnostic['message'])
            _, registration = self.detect(points, include_invalid=False)
            self.assertEqual(registration, [])

    def test_gamma_is_first_attempt_and_empty_grid_explains_configuration(self):
        detector = CalibBoardDetector(gamma=1.73)
        with patch.object(detector, '_detect_pattern_robust', return_value=None) as run:
            result = detector.detect(self.image)
        self.assertEqual(run.call_args.args[1][0], 1.73)
        self.assertIn('2D 网格未检出', result['message'])
        self.assertIn('7×11', result['message'])

    def test_failed_pose_keeps_diagnostic_depth_out_of_registration(self):
        detector = MarkerDetector('asymmetric_grid')
        config = frame_recognition.configuration(detector, 'asymmetric_grid')
        frame = FrameData(1, 'offline', image_np=self.image, offline_pointmap_path=str(self.ply))
        # Distorted depths have finite XYZ but cannot pass a rigid board fit.
        points = self.points.copy()
        points[:, 2] += 30*np.sin(points[:, 0])
        with patch.object(CalibBoardDetector, '_read_ply_points', return_value=points):
            result = frame_recognition.detect(frame, config)
        self.assertFalse(result['board_success'])
        self.assertIn('RMS', result['message'])
        frame_recognition.apply(frame, result)
        self.assertEqual(len(frame.markers_all), 77)
        self.assertEqual(frame.markers, [])
        self.assertIsNone(frame.board_pose)
        self.assertEqual(frame.recognition_message, result['message'])


if __name__ == '__main__':
    unittest.main()
