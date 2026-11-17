"""Verify automatic publication, failure retention, and return to the last accepted frame."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import open3d as o3d

from core.frame_data import FrameData
from core.frame_database import FrameDatabase
from prototypes.superpoint_lightglue.automatic import FeatureStitching


class SyntheticMatcher:
    def match(self, images, boxes):
        pixels = np.array([[x, y] for y in (8, 20, 32) for x in (8, 20, 32)], dtype=float)
        if images[1][0, 0, 0] == 0:
            pixels = pixels[:0]
        return pixels, pixels


class AutomaticStitchingTests(unittest.TestCase):
    def test_rejected_capture_does_not_become_the_next_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = FrameDatabase('mobile_chain')
            database.directory = root / 'db'
            service = FeatureStitching(SyntheticMatcher())
            y, x = np.indices((48, 48))

            def capture(number, shift, texture):
                cloud = o3d.geometry.PointCloud()
                grid = np.stack((x + shift, y, 400 + (x % 4) * .1), axis=-1)
                cloud.points = o3d.utility.Vector3dVector(grid.reshape(-1, 3))
                path = root / f'{number}.ply'
                self.assertTrue(o3d.io.write_point_cloud(str(path), cloud))
                frame = FrameData(number, 'cam0', image_np=np.full(x.shape, texture, dtype=np.uint8),
                                  offline_pointmap_path=str(path), pointcloud_aligned=True)
                return database.ingest(frame)

            first = capture(1, 0, 100)
            self.assertIsNone(service.append(database, first))
            second = capture(2, 3, 100)
            result = service.append(database, second)
            self.assertEqual(database.records[result.uid].source_ids, [first, second])
            self.assertEqual(result.inliers, 9)
            rejected = capture(3, 6, 0)
            with self.assertRaisesRegex(ValueError, '有效深度 0'):
                service.append(database, rejected)
            fourth = capture(4, 9, 100)
            result = service.append(database, fourth)
            row = database.records[result.uid]
            self.assertIn(rejected, database.records)
            self.assertEqual(row.source_ids, [first, second, fourth])
            self.assertEqual(len(result.cloud.points), 3 * x.size)
            np.testing.assert_allclose(np.asarray(row.source_transforms[fourth])[:3, 3], [-9, 0, 0], atol=1e-8)
