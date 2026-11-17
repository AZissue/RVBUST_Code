import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from prototypes.superpoint_lightglue.pipeline import lift_pixels, estimate_pose


class RegistrationTest(unittest.TestCase):
    def test_lifting_rejects_depth_edges_and_missing_samples(self):
        y, x = np.indices((9, 9))
        grid = np.stack((x, y, np.full_like(x, 500)), axis=-1).astype(float)
        grid[:, 5:, 2] += 30
        grid[1, 1] = np.nan
        xyz, valid = lift_pixels(grid, [[2.5, 5.5], [4, 4], [1, 1], [-1, 3]], 4)
        np.testing.assert_array_equal(valid, [True, False, False, False])
        np.testing.assert_allclose(xyz[0], [2.5, 5.5, 500])

    def test_pose_maps_moving_into_reference_with_outliers(self):
        moving = np.random.default_rng(14).uniform(-20, 20, (24, 3))
        rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
        reference = moving @ rotation.T + [10, 30, -15]
        reference[-4:] += 50
        pose, mask, errors = estimate_pose(moving, reference, 1)
        self.assertEqual(mask.sum(), 20)
        np.testing.assert_allclose(pose[:3, :3], rotation, atol=1e-9)
        np.testing.assert_allclose(pose[:3, 3], [10, 30, -15], atol=1e-9)
        self.assertLess(errors[mask].max(), 1e-8)
        with self.assertRaises(ValueError):
            estimate_pose(moving[:5], reference[:5], 1)
