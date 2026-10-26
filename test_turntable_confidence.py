"""Advisory diagnostics detect model problems without changing the solution."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).parent/'src'))
from core.turntable_confidence import assess, report_for
from core.turntable_calibrator import TurntableCalibrator, rodrigues, kabsch_rigid_transform


class ConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.points = np.random.default_rng(31).normal(size=(12, 3))*20 + [250, 300, 500]
        self.center = np.array([200.,300.,500.])

    def solve(self, angle, extra=(0,0,0)):
        rotation = rodrigues(np.array([0.,0.,1.]), np.radians(angle))
        moved = (self.points-self.center) @ rotation.T + self.center + extra
        calib = TurntableCalibrator()
        ok, msg, _ = calib.calibrate_from_markers(self.points, moved)
        self.assertTrue(ok, msg)
        expected_r, expected_t = kabsch_rigid_transform(self.points, moved)
        np.testing.assert_allclose(calib.R_init, expected_r)
        np.testing.assert_allclose(calib.t_init, expected_t)
        return calib

    def states(self, report):
        return {check['key']: check['state'] for check in report['checks']}

    def test_offset_axis_pure_rotation_allows_large_translation_term(self):
        calib = self.solve(30)
        self.assertGreater(np.linalg.norm(calib.t_init), 100)
        self.assertEqual(calib.confidence['state'], 'clear')
        self.assertEqual(self.states(calib.confidence)['axial_shift'], 'clear')

    def test_axial_shift_is_detected_without_altering_transform(self):
        calib = self.solve(30, np.array([0,0,5.]))
        self.assertEqual(self.states(calib.confidence)['axial_shift'], 'warning')
        shift = next(check for check in calib.confidence['checks'] if check['key']=='axial_shift')
        self.assertAlmostEqual(shift['value'], 5.)

    def test_near_translation_has_small_angle_and_far_axis(self):
        calib = self.solve(.2, np.array([50.,0,0]))
        states = self.states(calib.confidence)
        self.assertEqual(states['small_angle'], 'warning')
        self.assertEqual(states['center_distance'], 'warning')

    def test_distance_is_invariant_to_axis_point_and_camera_origin(self):
        first = assess([0,0,1], .5, self.center, translation=[2,3,.1], reference_points=self.points)
        second = assess([0,0,-1], -.5, self.center+[0,0,100000], translation=[2,3,.1], reference_points=self.points)
        shifted = assess([0,0,1], .5, self.center+[10000,20000,30000], translation=[2,3,.1],
                         reference_points=self.points+[10000,20000,30000])
        for report in (second, shifted):
            self.assertAlmostEqual(report['checks'][2]['value'], first['checks'][2]['value'])
        self.assertEqual(first['state'], second['state'])

    def test_history_without_translation_is_unassessed_and_limits_are_explicit(self):
        calib = TurntableCalibrator()
        calib.set_calibration([0,0,1], self.center, 30, 12)
        report = report_for(calib)
        self.assertEqual(report['state'], 'partial')
        self.assertEqual(self.states(report)['axial_shift'], 'unassessed')
        boundary = assess([0,0,1], np.radians(5), [0,0,0], translation=[0,0,1], reference_points=self.points)
        self.assertEqual(self.states(boundary)['small_angle'], 'clear')
        self.assertEqual(self.states(boundary)['axial_shift'], 'clear')
        with self.assertRaises(ValueError):
            assess([0,0,1], .5, self.center, limits=dict(axial_shift_mm=-1))


if __name__ == '__main__':
    unittest.main()
