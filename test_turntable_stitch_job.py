"""Sparse surfaces survive default stitching and native work is isolated."""
import sys
from pathlib import Path
import tempfile
import unittest
import numpy as np
import open3d as o3d
sys.path.insert(0, str(Path(__file__).parent/'src'))
from core.turntable_calibrator import TurntableCalibrator
from core.turntable_stitch_job import run_job
from core.marker_plane import fit_marker_plane, filter_source_cloud


class StitchJobTests(unittest.TestCase):
    def test_marker_plane_retains_camera_side_and_preserves_attributes(self):
        xyz = np.array([[x, y, 200 + x/5] for x in (-30, 0, 30) for y in (-30, 30)])
        markers = [dict(zip(('x_3d', 'y_3d', 'z_3d'), point)) for point in xyz]
        markers.append(dict(x_3d=5, y_3d=5, z_3d=280))
        plane = fit_marker_plane(markers, 1)
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
            [[10, 0, 192], [10, 0, 202], [10, 0, 210], [0, 0, 0], [np.nan, 1, 1]]))
        cloud.paint_uniform_color([.2, .3, .4])
        filtered, valid = filter_source_cloud(cloud, plane)
        self.assertEqual(valid, 3)
        np.testing.assert_array_equal(np.asarray(filtered.points), [[10, 0, 192]])
        np.testing.assert_allclose(np.asarray(filtered.colors), [[.2, .3, .4]])
        self.assertEqual(len(cloud.points), 5)
        with self.assertRaisesRegex(ValueError, '平面'):
            fit_marker_plane([dict(x_3d=x, y_3d=0, z_3d=200) for x in range(6)], 1)

    def test_sparse_surface_and_invalid_slots_before_translation(self):
        points = np.vstack([np.random.default_rng(7).normal(size=(150,3)), [[60,60,80], [0,0,0], [np.nan,1,2]]])
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(points)
        calib = TurntableCalibrator()
        calib.set_calibration([0,0,1], [10,20,30], 90, 4)
        merged, _ = calib.stitch_pointclouds([cloud, cloud])
        self.assertEqual(len(merged.points), 302)
        np.testing.assert_allclose(np.asarray(merged.points)[150], [60,60,80])
        self.assertEqual(len(cloud.points), 153)

    def test_child_preserves_sources_and_reports_each_transform(self):
        with tempfile.TemporaryDirectory() as folder:
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector([[1,2,3],[3,4,5],[40,50,60]])
            paths = [Path(folder)/f'{i}.ply' for i in range(2)]
            for path in paths:
                o3d.io.write_point_cloud(str(path), cloud)
            before = [p.read_bytes() for p in paths]
            merged, metadata = run_job(paths, dict(axis=[0,0,1],center=[0,0,0],angle_deg=90,step_count=4), [[],[]], [0,2])
            self.assertEqual(len(merged.points), 6)
            self.assertEqual(metadata['counts'], [3,3])
            np.testing.assert_allclose(np.asarray(merged.points)[3:], np.asarray(cloud.points)*[-1,-1,1], atol=1e-5)
            self.assertEqual([p.read_bytes() for p in paths], before)
            filtered, metadata = run_job(paths,
                dict(axis=[0,0,1], center=[0,0,0], angle_deg=90, step_count=4),
                [[], []], [0, 2], planes=[[0, 0, -1, 4]] * 2)
            self.assertEqual(len(filtered.points), 2)
            self.assertIn('6 → 2 点', metadata['message'])
            self.assertEqual([p.read_bytes() for p in paths], before)

            edge = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
                [[1, 2, 3.8], [1, 2, 4.2], [1.8, 2, 4.2], [1, 2, 4.7]]))
            for path in paths:
                o3d.io.write_point_cloud(str(path), edge)
            filtered, metadata = run_job(paths,
                dict(axis=[0,0,1], center=[0,0,0], angle_deg=90, step_count=4),
                [[], []], [0, 2],
                planes=[dict(plane=[0, 0, -1, 4], bottom_band_mm=.5, radius_mm=.75)] * 2)
            self.assertEqual(len(filtered.points), 4)
            self.assertIn('8 → 4 点', metadata['message'])
            np.testing.assert_allclose(np.asarray(filtered.points)[:2], np.asarray(edge.points)[:2])


if __name__ == '__main__':
    unittest.main()
