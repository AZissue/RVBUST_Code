"""Pixel matching must stay independent from XYZ and be reusable by manual registration."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np
import open3d as o3d

from core.feature_settings import FeatureSettings
from core.frame_data import FrameData
from core.frame_database import FrameDatabase
from .automatic import FeatureStitching
from .test_automatic import SyntheticMatcher


class PixelCacheTests(TestCase):
    def test_prepare_reads_no_point_cloud_and_cache_keys_track_only_2d_inputs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = FrameDatabase('mobile_chain')
            db.directory = root / 'db'
            matcher = SyntheticMatcher()
            service = FeatureStitching(matcher)
            y, x = np.indices((48, 48))
            ids = []
            for number in (1, 2):
                cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
                    np.stack((x+3*(number-1), y, 400+(x%4)*.1), axis=-1).reshape(-1, 3)))
                path = root / f'{number}.ply'
                self.assertTrue(o3d.io.write_point_cloud(str(path), cloud))
                frame = FrameData(number, 'cam0', image_np=np.full(x.shape, 100, np.uint8),
                                  offline_pointmap_path=str(path), pointcloud_aligned=True)
                ids.append(db.ingest(frame))
            with patch('prototypes.superpoint_lightglue.automatic.read_frame', side_effect=AssertionError('XYZ read')), \
                    patch.object(db, 'publish_result', side_effect=AssertionError('automatic publication')):
                observations = service.prepare(db, ids[1])
                self.assertEqual(observations[-1].stage, 'matching')
                self.assertEqual(len(observations[-1].points), 9)
                service.prepare(db, ids[1])
            self.assertEqual(len(matcher.pairs), 1)
            service.stitch(db, ids)
            self.assertEqual(len(matcher.pairs), 1)
            settings = replace(FeatureSettings(), tolerance=1., inlier_percent=65)
            service.prepare(db, ids[1], settings=settings)
            self.assertEqual(len(matcher.pairs), 1)
            settings = replace(settings, max_keypoints=1024)
            service.prepare(db, ids[1], settings=settings)
            self.assertEqual(len(matcher.pairs), 2)
            db.records[ids[1]].revision += 1
            service.prepare(db, ids[1], settings=settings)
            self.assertEqual(len(matcher.pairs), 3)

            # Replacing a capture while its PNG is being read must not stamp old pixels
            # with the new exposure revision.
            from .pipeline import frame_image
            def replace_during_read(directory, row):
                image = frame_image(directory, row)
                if row.uid == ids[1]:
                    db.records[row.uid].revision += 1
                return image
            with patch('prototypes.superpoint_lightglue.automatic.frame_image', side_effect=replace_during_read):
                service.prepare(db, ids[1], settings=settings)
            calls = len(matcher.pairs)
            service.prepare(db, ids[1], settings=settings)
            self.assertEqual(len(matcher.pairs), calls+1)


    def test_mask_enhancement_keeps_original_matches_and_only_adds_unique_pairs(self):
        from types import SimpleNamespace
        from core.feature_masks import WorkpieceMaskSettings
        from .matching import PixelMatchCache

        image = np.full((64, 64, 3), 20, dtype=np.uint8)
        image[25:50, 25:50] = 180
        original = image.copy()
        baseline = np.array([[10., 10.], [30., 30.]])
        class TwoPassMatcher:
            calls = 0
            def match(self, images, boxes):
                self.calls += 1
                if self.calls == 1:
                    return baseline.copy(), baseline.copy()
                # A near duplicate and two conflicting endpoints must not inflate support.
                ref = np.array([[30.1, 30.1], [40., 40.], [30., 30.], [45., 45.]])
                mov = np.array([[30.1, 30.1], [40., 40.], [35., 35.], [40., 40.]])
                return ref, mov
        class Database:
            directory = 'test'
            records = {key: SimpleNamespace(uid=key, revision=1) for key in ('a', 'b')}
        db = Database()
        matcher = TwoPassMatcher()
        cache = PixelMatchCache(matcher)
        rows = tuple(db.records.values())
        settings = FeatureSettings()
        raw = cache.pair(db, rows, (image, image), None, settings, None, WorkpieceMaskSettings())
        result = cache.pair(db, rows, (image, image), None, settings, None,
                            WorkpieceMaskSettings(True, 'bright', 100))
        self.assertEqual(matcher.calls, 2, 'enabling enhancement must reuse original inference')
        for points in result:
            np.testing.assert_array_equal(points[:2], baseline)
            np.testing.assert_array_equal(points[2:], [[40., 40.]])
        np.testing.assert_array_equal(image, original)
        empty = cache.pair(db, rows, (image, image), None, settings, None,
                           WorkpieceMaskSettings(True, 'bright', 255))
        for points in empty:
            np.testing.assert_array_equal(points, baseline)
        self.assertEqual(matcher.calls, 2)
