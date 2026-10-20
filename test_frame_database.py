"""Raw DB ownership, capture ordering, rollback and portable reopening."""
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.camera_manager import CameraManager
from core.frame_data import FrameData
from core.frame_database import FrameDatabase

PLY = (b'ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\n'
       b'property float y\nproperty float z\nend_header\n0 0 0\n1 2 3\n4 5 6\nnan nan nan\n')


class FrameDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
        self.source = self.root / 'source.ply'
        self.source.write_bytes(PLY)
        self.db = FrameDatabase('multi_cam', self.root / 'db')

    def frame(self, camera='cam0'):
        return FrameData(1, camera, image_np=self.image.copy(), is_offline=True,
                         offline_pointmap_path=str(self.source))

    def test_archive_owns_pair_after_source_mutation_and_deletion(self):
        frame = self.frame()
        uid = self.db.ingest(frame)
        original = self.image.copy()
        frame.image_np[:] = 255
        frame.markers.clear()
        self.source.unlink()
        loaded, cloud = self.db.load_frame(uid)
        np.testing.assert_array_equal(loaded.image_np, original)
        self.assertEqual((self.db.directory / 'frames' / uid / 'pointmap.ply').read_bytes(), PLY)
        self.assertEqual(self.db.records[uid].points, 4)
        self.assertEqual(len(cloud.points), 4)

    def test_same_frame_deduplicates_but_new_capture_with_same_number_does_not(self):
        frame = self.frame()
        first = self.db.ingest(frame)
        self.assertEqual(self.db.ingest(frame), first)
        second = self.db.ingest(self.frame())
        self.assertNotEqual(second, first)
        self.assertEqual(len(self.db.records), 2)

    def test_project_can_move_and_reopen_with_stable_identifiers(self):
        uid = self.db.ingest(self.frame())
        moved = self.root / 'moved'
        shutil.copytree(self.db.directory, moved)
        other = FrameDatabase('multi_cam', self.root / 'empty')
        other.open_project(moved / 'index.json')
        self.assertEqual(list(other.records), [uid])
        np.testing.assert_array_equal(other.load_frame(uid)[0].image_np, self.image)
        wrong = FrameDatabase('turntable', self.root / 'wrong')
        with self.assertRaisesRegex(ValueError, '不匹配'):
            wrong.open_project(moved / 'index.json')

    def test_incomplete_or_uncommitted_data_never_appears_in_db(self):
        frame = self.frame()
        with patch.object(self.db, '_save_index', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.db.ingest(frame)
        self.assertEqual(len(self.db.records), 0)
        self.assertIsNone(frame.database_id)
        self.assertEqual(list((self.db.directory / 'frames').iterdir()), [])
        frame.offline_pointmap_path = 'missing.ply'
        with self.assertRaises(FileNotFoundError):
            self.db.ingest(frame)
        self.assertEqual(len(self.db.records), 0)

    def test_parallel_cameras_are_archived_before_capture_returns(self):
        manager = CameraManager()
        sdk = SimpleNamespace(PointMapUnitEnum=SimpleNamespace(Millimeter=1))
        events = []
        def make_camera(name):
            def capture(options):
                events.append(('capture', name))
                pm = Mock()
                def save(path, image, unit, ordered):
                    Path(path).write_bytes(PLY)
                    events.append(('stored', name))
                    return True
                pm.SaveWithImage.side_effect = save
                return self.image.copy(), pm, object(), 'ok'
            return SimpleNamespace(is_connected=True, capture_3d=capture)
        manager._cameras = {name: make_camera(name) for name in ('cam0', 'cam1')}
        manager.capture_sink = self.db.ingest
        with patch('core.frame_database._import_rvc', return_value=sdk):
            result = manager.capture_all(sync=True)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(self.db.records), 2)
        for name, frame in result.items():
            self.assertIn(frame.database_id, self.db.records)
            self.assertLess(events.index(('capture', name)), events.index(('stored', name)))
        self.assertEqual(len({f.frame_id for f in result.values()}), 1)

    def test_capture_failure_cannot_return_an_unarchived_frame(self):
        manager = CameraManager()
        manager._cameras = {'cam0': SimpleNamespace(is_connected=True,
            capture_3d=lambda options: (self.image.copy(), None, None, 'ok'))}
        manager.capture_sink = Mock(side_effect=OSError('archive failed'))
        with patch.object(FrameData, 'release_rvc') as release:
            with self.assertRaisesRegex(OSError, 'archive failed'):
                manager.capture('cam0')
            release.assert_called_once()

    def test_remove_and_recover_batch_survives_reopening_and_never_deletes_source(self):
        first = self.frame()
        uid = self.db.ingest(first)
        second = self.db.ingest(self.frame('cam1'))
        moves = self.db.remove([uid, second])
        self.assertEqual(self.db.records, {})
        self.assertTrue(self.source.is_file())
        self.assertTrue(all((new / 'image.png').is_file() for old, new in moves.values()))
        with self.assertRaisesRegex(ValueError, '已从DB移除'):
            self.db.ingest(first)
        other = FrameDatabase('multi_cam', self.root / 'other')
        other.open_project(self.db.directory / 'index.json')
        other.restore_last_removal()
        self.assertEqual(set(other.records), {uid, second})
        np.testing.assert_array_equal(other.load_frame(uid)[0].image_np, self.image)
        self.assertEqual(other.removed, {})

    def test_remove_and_restore_failures_roll_back_files_and_index(self):
        uid = self.db.ingest(self.frame())
        with patch.object(self.db, '_save_index', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.db.remove([uid])
        self.assertIn(uid, self.db.records)
        self.assertNotIn(uid, self.db.removed)
        self.assertTrue((self.db.directory / 'frames' / uid / 'pointmap.ply').exists())
        self.db.remove([uid])
        with patch.object(self.db, '_save_index', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.db.restore_last_removal()
        self.assertNotIn(uid, self.db.records)
        self.assertIn(uid, self.db.removed)
        self.db.restore_last_removal()
        self.assertIn(uid, self.db.records)

    def test_partial_missing_file_rollback_and_latest_batch_restore(self):
        one = self.db.ingest(self.frame())
        two = self.db.ingest(self.frame())
        (self.db.directory / 'frames' / two).rename(self.root / 'missing')
        with self.assertRaises(OSError):
            self.db.remove([one, two])
        self.assertIn(one, self.db.records)
        self.assertTrue((self.db.directory / 'frames' / one / 'image.png').is_file())
        (self.root / 'missing').rename(self.db.directory / 'frames' / two)
        self.db.remove([one])
        self.db.remove([two])
        self.db.restore_last_removal()
        self.assertEqual(set(self.db.records), {two})
        self.db.restore_last_removal()
        self.assertEqual(set(self.db.records), {one, two})

    def test_raw_organized_cloud_render_cache_has_finite_bounds_without_changing_source(self):
        from ui_common.industrial_scene.render_cache import FrameRenderCache, FrameSource, RenderPolicy
        points = np.array([[0., 0., 0.], [1., 2., 3.], [4., 5., 6.], [np.nan]*3])
        original = points.copy()
        cache = FrameRenderCache()
        source = FrameSource(points, None)
        scene = cache.prepare([source], RenderPolicy(10, 1))
        self.assertEqual(scene.original_points, 4)
        self.assertEqual(scene.counts, (2,))
        self.assertTrue(np.isfinite(scene.bounds).all())
        self.assertTrue(np.isfinite(scene.frames[0].packed['position']).all())
        np.testing.assert_array_equal(points, original)
        again = cache.prepare([source], RenderPolicy(10, 1))
        self.assertEqual(again.builds, 0)
        self.assertIs(scene.frames[0].packed, again.frames[0].packed)


if __name__ == '__main__':
    unittest.main()
