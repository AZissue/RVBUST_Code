"""Explicit snapshots, portable data, save failure and disk cleanup semantics."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.session_project import SessionProject, safe_name, disk_usage
from core.frame_data import FrameData
from core.station_manager import StationManager
from test_frame_database import PLY


class SessionProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = SessionProject('mobile_chain', '工件A', self.root / 'sessions')
        self.addCleanup(self.project.dispose)
        self.source = self.root / 'source.ply'
        self.source.write_bytes(PLY)

    def ingest(self):
        frame = FrameData(1, 'cam0', image_np=np.zeros((2, 2, 3), np.uint8),
            is_offline=True, offline_pointmap_path=str(self.source))
        return self.project.database.ingest(frame)

    def test_startup_has_no_persistent_directory_and_save_updates_one_project(self):
        self.assertFalse(self.project.directory.exists())
        self.assertFalse(self.project.save_root.exists())
        uid = self.ingest()
        saved = self.project.save(dict(nodes=[]))
        before = (saved / 'data' / 'index.json').read_bytes()
        (saved / 'merged.ply').write_bytes(b'explicit user export')
        self.project.database.set_status(uid, 'changed in draft')
        self.assertEqual((saved / 'data' / 'index.json').read_bytes(), before)
        self.assertEqual(self.project.save(dict(nodes=['changed'])), saved)
        self.assertNotEqual((saved / 'data' / 'index.json').read_bytes(), before)
        self.assertEqual((saved / 'merged.ply').read_bytes(), b'explicit user export')
        self.assertEqual(len(list(self.project.save_root.iterdir())), 1)
        self.project.dispose()
        self.assertTrue((saved / 'session.json').is_file())
        self.assertFalse(self.project.directory.exists())

    def test_copy_load_is_isolated_and_movable_with_mode_check(self):
        uid = self.ingest()
        path = self.project.save({})
        other, workflow = SessionProject.load(path, 'mobile_chain')
        self.addCleanup(other.dispose)
        self.assertNotEqual(other.database.directory, path / 'data')
        other.database.remove([uid])
        self.assertTrue((path / 'data' / 'frames' / uid / 'image.png').exists())
        with self.assertRaisesRegex(ValueError, '类型不匹配'):
            SessionProject.load(path, 'turntable')

    def test_parameters_only_snapshot_has_no_raw_frame_copy(self):
        self.ingest()
        path = self.project.save(dict(calibration={'axis': [0, 0, 1]}), include_raw=False)
        self.assertFalse((path / 'data').exists())
        data = json.loads((path / 'session.json').read_text(encoding='utf-8'))
        self.assertFalse(data['include_raw'])
        self.assertEqual(data['mode'], 'mobile_chain')

    def test_failed_save_preserves_previous_snapshot(self):
        self.ingest()
        path = self.project.save(dict(value=1))
        before = (path / 'session.json').read_bytes()
        with patch('core.session_project.write_json_atomic', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.project.save(dict(value=2))
        self.assertEqual((path / 'session.json').read_bytes(), before)
        self.assertEqual(len(list(self.project.save_root.iterdir())), 1)

    def test_scoped_recycle_cleanup_protects_workflow_dependencies_and_reports_bytes(self):
        one = self.ingest()
        two = self.ingest()
        self.project.database.remove([one, two])
        before = disk_usage(self.project.directory)
        self.assertGreater(before['trash_bytes'], 0)
        self.assertEqual(self.project.database.purge_removed([one]), 1)
        self.assertIn(one, self.project.database.removed)
        self.assertNotIn(two, self.project.database.removed)
        self.assertLess(disk_usage(self.project.directory)['trash_bytes'], before['trash_bytes'])
        self.project.database.restore_last_removal()
        self.assertIn(one, self.project.database.records)
        self.assertTrue(self.source.is_file())

    def test_names_and_dispose_cannot_escape_owned_roots(self):
        self.assertEqual(safe_name('../A:B'), '_A_B')
        self.assertEqual(safe_name('CON'), '未命名项目')
        original = self.project.directory
        self.project.directory = self.root
        with self.assertRaises(ValueError):
            self.project.dispose()
        self.project.directory = original

    def test_managed_capture_does_not_duplicate_station_files_or_delete_raw_pair(self):
        from types import SimpleNamespace
        uid = self.ingest()
        frame, cloud = self.project.database.load_frame(uid)
        manager = StationManager(SimpleNamespace(capture=lambda camera: frame))
        manager.managed_frames = True
        manager._session_dir = str(self.project.directory)
        with patch.object(FrameData, 'save', side_effect=AssertionError('duplicate raw write')), \
             patch('core.station_manager._import_rvc', return_value=None):
            sid, message = manager.capture_station('cam0')
        self.assertEqual(sid, 'station_1')
        self.assertFalse((self.project.directory / 'station_1').exists())
        manager.remove_station(sid)
        self.assertTrue((self.project.database.directory / 'frames' / uid / 'pointmap.ply').exists())


if __name__ == '__main__':
    unittest.main()
