
import _bootstrap  # Configure project and sibling-test imports.
import sys
import unittest
from pathlib import Path

import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from core.turntable_calibrator import OnlineTurntableSession, TurntableCalibrator, match_markers_pair


class UnencodedTurntableTests(unittest.TestCase):
    def setUp(self):
        points = np.array([[4, 8, 100], [22, 10, 100], [9, 41, 100], [57, 22, 100]])
        center = np.array([6, 7, 100])
        rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
        rotated = (points - center) @ rotation.T + center
        def markers(positions):
            return [dict(code=i, marker_type='unencoded_circle', valid_3d=True,
                         x_3d=x, y_3d=y, z_3d=z)
                    for i, (x, y, z) in enumerate(positions)]
        self.first = markers(points)
        self.second = markers(rotated[[2, 0, 3, 1]])

    def test_calibration_uses_geometry_despite_shuffled_local_numbers(self):
        session = OnlineTurntableSession()
        session.markers0 = self.first
        session.markers1 = self.second
        ok, message, info = session.calibrate()
        self.assertTrue(ok, message)
        self.assertAlmostEqual(info['angle_deg'], 90)
        self.assertEqual(len(session.calibration_result['result']['details']), 4)

    def test_scans_match_using_geometry_before_calibrated_fallback(self):
        clouds = []
        for rows in (self.first, self.second):
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector([
                [row[key] for key in ('x_3d', 'y_3d', 'z_3d')] for row in rows])
            clouds.append(cloud)
        calibrator = TurntableCalibrator()
        calibrator.set_calibration([0, 0, 1], [6, 7, 100], 80, 4)
        result, message = calibrator.stitch_pointclouds(clouds, markers=[self.first, self.second])
        self.assertIn('普通圆点几何匹配', message)
        np.testing.assert_allclose(np.asarray(result.points)[4:], np.asarray(clouds[0].points)[[2, 0, 3, 1]])

    def test_mixed_types_do_not_match_by_local_number(self):
        for row in self.second:
            row.pop('marker_type')
        self.assertIsNone(match_markers_pair(self.first, self.second)[0])


if __name__ == '__main__':
    unittest.main()
