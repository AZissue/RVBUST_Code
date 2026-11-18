import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from prototypes.superpoint_lightglue.pipeline import lift_pixels, estimate_pose


class RegistrationTest(unittest.TestCase):
    def test_rotated_crop_pixels_return_to_original_sensor_axes(self):
        from prototypes.superpoint_lightglue.pipeline import original_crop_pixels

        image = np.arange(48).reshape(6, 8)
        y, x = np.indices(image.shape)
        for turns in (1, 2, 3):
            rotated = np.rot90(image, turns)
            v, u = np.indices(rotated.shape)
            points = np.column_stack((u.ravel(), v.ravel())) + .0
            recovered = original_crop_pixels(points, 8, 6, turns).astype(int)
            np.testing.assert_array_equal(x.ravel()[rotated.ravel()], recovered[:, 0])
            np.testing.assert_array_equal(y.ravel()[rotated.ravel()], recovered[:, 1])

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

    def test_configured_consensus_accepts_only_when_support_clears_gate(self):
        rng = np.random.default_rng(4)
        target = rng.uniform(-100, 100, size=(20, 3))
        source = target + [7, 3, -2]
        source[10:] += rng.uniform(30, 90, size=(10, 3))
        with self.assertRaisesRegex(ValueError, r'10/20.*至少 12'):
            estimate_pose(source, target, 2.)
        pose, mask, _ = estimate_pose(source, target, 2., min_ratio=.45)
        self.assertEqual(mask.sum(), 10)
        np.testing.assert_allclose(pose[:3, 3], [-7, -3, 2], atol=1e-8)
