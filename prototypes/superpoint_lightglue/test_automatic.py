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
    def __init__(self):
        self.pairs = []

    def match(self, images, boxes):
        self.pairs.append(tuple(int(image[0, 0, 0]) for image in images))
        pixels = np.array([[x, y] for y in (8, 20, 32) for x in (8, 20, 32)], dtype=float)
        if self.pairs[-1][1] == 0 or self.pairs[-1] == (120, 140):
            pixels = pixels[:0]
        return pixels, pixels


class AutomaticStitchingTests(unittest.TestCase):
    def test_roi_scales_to_each_original_image_size(self):
        from ui_v2.feature_recognition import feature_box

        roi = (.25, .25, .75, .75)
        self.assertEqual(feature_box((1536, 2048, 3), roi), (512, 384, 1536, 1152))
        self.assertEqual(feature_box((768, 1024, 3), roi), (256, 192, 768, 576))
        self.assertEqual(feature_box((768, 1024, 3), None), (0, 0, 1024, 768))

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

            from core.feature_masks import WorkpieceMaskSettings
            first = capture(1, 0, 100)
            second = capture(2, 3, 120)
            self.assertIsNone(service.append(database, first))
            result = service.append(database, second)
            self.assertEqual(database.records[result.uid].source_ids, [first, second])
            self.assertEqual(result.inliers, 9)
            baseline = service.stitch(database, [first, second], workpiece_roi=(.125, .125, .875, .875),
                                      mask_settings=WorkpieceMaskSettings(True, 'bright', 255))
            self.assertEqual(baseline.inliers, 9)
            masked = service.stitch(database, [first, second], workpiece_roi=(.125, .125, .875, .875),
                                    mask_settings=WorkpieceMaskSettings(True, 'bright', 50))
            self.assertEqual(masked.inliers, 9)
            self.assertTrue(all(6 <= x < 42 and 6 <= y < 42
                                for x, y, _ in masked.observations[-1].points))
            rejected = capture(3, 6, 0)
            with self.assertRaisesRegex(ValueError, '有效深度 0'):
                service.append(database, rejected)
            fourth = capture(4, 9, 140)
            result = service.append(database, fourth)
            self.assertIn((120, 140), service.matcher.pairs)
            self.assertIn((100, 140), service.matcher.pairs)
            self.assertEqual(result.links, ((4, 1),))
            self.assertEqual(result.observations[-1].reference_number, 1)
            self.assertEqual(len(result.observations[-1].points), 9)
            row = database.records[result.uid]
            self.assertIn(rejected, database.records)
            self.assertEqual(row.source_ids, [first, second, fourth])
            self.assertEqual(len(result.cloud.points), 3 * x.size)
            fifth = capture(5, 12, 160)
            combined = service.append(database, fifth)
            self.assertEqual(combined.inliers, 27)
            self.assertEqual(database.records[combined.uid].source_ids, [first, second, fourth, fifth])
            # Force a plausible pair fit to an old frame that conflicts with the adjacent link.
            class ConflictingMatcher(SyntheticMatcher):
                def match(self, images, boxes):
                    ref, moving = super().match(images, boxes)
                    if self.pairs[-1][0] in (120, 140):
                        ref = ref + [7, 0]
                    return ref, moving

            service.matcher = ConflictingMatcher()
            sixth = capture(6, 15, 180)
            result = service.append(database, sixth)
            self.assertEqual(result.links, ((6, 5),))
            self.assertEqual(result.references, 1)
            np.testing.assert_allclose(np.asarray(database.records[result.uid].source_transforms[sixth])[:3, 3],
                                       [-15, 0, 0], atol=1e-5)
            np.testing.assert_allclose(np.asarray(row.source_transforms[fourth])[:3, 3], [-9, 0, 0], atol=1e-5)
