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


class StitchJobTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
