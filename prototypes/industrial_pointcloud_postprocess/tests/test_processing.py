"""Pure-numpy processing tests; direct unittest script, no Qt, no hardware."""
from pathlib import Path
import sys
import unittest
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))
from industrial_pointcloud_postprocess.core.processing import (
    ortho_project, point_in_polygon, polygon_crop_mask, voxel_downsample, random_downsample)


class PointInPolygonTests(unittest.TestCase):
    def test_square(self):
        square = np.array([[0., 0.], [10., 0.], [10., 10.], [0., 10.]])
        xy = np.array([[5., 5.], [15., 5.], [-1., 5.], [5., -1.], [5., 15.], [0.5, 9.5]])
        result = point_in_polygon(xy, square)
        np.testing.assert_array_equal(result, [True, False, False, False, False, True])

    def test_concave(self):
        concave = np.array([[0., 0.], [10., 0.], [10., 4.], [4., 4.], [4., 10.], [0., 10.]])
        xy = np.array([[2., 2.], [7., 2.], [7., 7.], [2., 7.], [12., 2.]])
        result = point_in_polygon(xy, concave)
        np.testing.assert_array_equal(result, [True, True, False, True, False])

    def test_boundary_neighborhood(self):
        square = np.array([[0., 0.], [10., 0.], [10., 10.], [0., 10.]])
        eps = 1e-9
        xy = np.array([[eps, 5.], [-eps, 5.], [10. - eps, 5.], [10. + eps, 5.],
                       [5., eps], [5., -eps], [5., 10. - eps], [5., 10. + eps]])
        result = point_in_polygon(xy, square)
        np.testing.assert_array_equal(result, [True, False, True, False, True, False, True, False])

    def test_rejects_invalid_polygon(self):
        with self.assertRaises(ValueError):
            point_in_polygon(np.array([[1., 1.]]), np.array([[0., 0.], [1., 1.]]))


class OrthoProjectTests(unittest.TestCase):
    def test_identity_rotation_known_values(self):
        width, height, extent = 800, 600, 340.
        scale = min(width, height) * 1.65 / extent
        points = np.array([[0., 0., 0.], [10., -5., 3.], [-20., 8., -7.]])
        xy, depth = ortho_project(points, center=np.zeros(3), rotation_matrix=np.eye(3),
                                  extent=extent, zoom=1., pan=np.zeros(2),
                                  width=width, height=height)
        expected = np.array([[width / 2, height / 2],
                             [width / 2 + scale * 10, height / 2 + scale * 5],
                             [width / 2 - scale * 20, height / 2 - scale * 8]])
        np.testing.assert_allclose(xy, expected)
        np.testing.assert_allclose(depth, [0., 3., -7.])

    def test_zoom_and_pan(self):
        width, height, extent = 400, 400, 100.
        scale = 400 * 1.65 / extent * 2.
        xy, _ = ortho_project(np.array([[5., 5., 0.]]), center=np.zeros(3), rotation_matrix=np.eye(3),
                              extent=extent, zoom=2., pan=np.array([7., -3.]),
                              width=width, height=height)
        np.testing.assert_allclose(xy[0], [200 + scale * 5 + 7, 200 - scale * 5 - 3])

    def test_crop_mask_matches_projection(self):
        rng = np.random.default_rng(1)
        points = rng.uniform(-100, 100, (2000, 3))
        polygon = [(300., 200.), (500., 200.), (500., 400.), (300., 400.)]
        mask = polygon_crop_mask(points, polygon, center=np.zeros(3), rotation_matrix=np.eye(3),
                                 extent=340., zoom=1., pan=np.zeros(2), width=800, height=600)
        xy, _ = ortho_project(points, np.zeros(3), np.eye(3), 340., 1., np.zeros(2), 800, 600)
        np.testing.assert_array_equal(mask, point_in_polygon(xy, polygon))
        self.assertTrue(0 < mask.sum() < len(points))


class VoxelDownsampleTests(unittest.TestCase):
    def test_reduces_and_averages(self):
        x, y = np.meshgrid(np.arange(10.), np.arange(10.))
        points = np.column_stack((x.ravel(), y.ravel(), np.zeros(100)))
        out, _ = voxel_downsample(points, None, 2.0)
        self.assertEqual(len(out), 25)
        self.assertLess(len(out), len(points))

    def test_voxel_mean(self):
        points = np.array([[0., 0., 0.], [0.5, 0.5, 0.5], [5., 5., 5.]])
        out, _ = voxel_downsample(points, None, 2.0)
        self.assertEqual(len(out), 2)
        self.assertTrue(any(np.allclose(row, [0.25, 0.25, 0.25]) for row in out))
        self.assertTrue(any(np.allclose(row, [5., 5., 5.]) for row in out))

    def test_colors_averaged_in_sync(self):
        points = np.array([[0., 0., 0.], [0.5, 0.5, 0.5], [5., 5., 5.]])
        colors = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
        _, out_colors = voxel_downsample(points, colors, 2.0)
        self.assertTrue(any(np.allclose(row, [0.5, 0.5, 0.]) for row in out_colors))
        self.assertTrue(any(np.allclose(row, [0., 0., 1.]) for row in out_colors))

    def test_invalid_voxel_size(self):
        points = np.array([[0., 0., 0.]])
        for bad in (0., -1., np.nan, np.inf):
            with self.assertRaises(ValueError):
                voxel_downsample(points, None, bad)

    def test_empty_result_raises(self):
        with self.assertRaises(ValueError):
            voxel_downsample(np.empty((0, 3)), None, 1.0)


class RandomDownsampleTests(unittest.TestCase):
    def test_count_and_unique_indices(self):
        points = np.arange(3000, dtype=float).reshape(1000, 3)
        out, _, indices = random_downsample(points, None, 0.3, seed=7)
        self.assertEqual(len(out), 300)
        self.assertEqual(len(np.unique(indices)), 300)
        np.testing.assert_array_equal(out, points[indices])

    def test_seed_reproducible(self):
        points = np.random.default_rng(0).normal(size=(500, 3))
        _, _, a = random_downsample(points, None, 0.5, seed=42)
        _, _, b = random_downsample(points, None, 0.5, seed=42)
        np.testing.assert_array_equal(a, b)

    def test_colors_follow_indices(self):
        points = np.arange(300, dtype=float).reshape(100, 3)
        colors = points.copy()
        out, out_colors, indices = random_downsample(points, colors, 0.5, seed=3)
        np.testing.assert_array_equal(out_colors, colors[indices])
        np.testing.assert_array_equal(out, points[indices])

    def test_invalid_ratio(self):
        points = np.zeros((10, 3))
        for bad in (0., -0.5, 1.5, np.nan):
            with self.assertRaises(ValueError):
                random_downsample(points, None, bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
