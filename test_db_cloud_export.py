"""Full DB PLY exports preserve stored data and isolate output failures."""
import unittest
from unittest.mock import patch
from pathlib import Path
import test_frame_database as fixture
from core.frame_database import STALE_RESULT


class CloudExportTests(unittest.TestCase):
    setUp = fixture.FrameDatabaseTests.setUp
    frame = fixture.FrameDatabaseTests.frame

    def test_raw_export_keeps_exact_ply_slots_and_source_metadata(self):
        uid = self.db.ingest(self.frame())
        before = self.db.snapshot()
        target = self.root/'单帧完整点云.ply'
        self.db.export_cloud(uid, target)
        self.assertEqual(target.read_bytes(), fixture.PLY)
        self.assertIn(b'nan nan nan', target.read_bytes())
        self.assertEqual(self.db.snapshot(), before)
        self.assertEqual((self.db.directory/'frames'/uid/'pointmap.ply').read_bytes(), fixture.PLY)

    def test_derived_branch_is_exportable_without_kind_specific_reader(self):
        raw = self.db.ingest(self.frame())
        _, cloud = self.db.load_frame(raw, 'cloud')
        uid = self.db.publish_result(cloud, [raw])
        self.db.records[uid].kind = 'postprocessed'
        self.db.records[uid].logical_name = '后处理分支'
        target = self.root/'derived.ply'
        self.db.export_cloud(uid, target)
        self.assertEqual(target.read_bytes(), (self.db.directory/'frames'/uid/'pointmap.ply').read_bytes())

    def test_failed_copy_or_replace_preserves_existing_destination_and_cleans_temp(self):
        uid = self.db.ingest(self.frame())
        target = self.root/'existing.ply'
        target.write_bytes(b'previous export')
        for function in ('shutil.copyfileobj', 'os.replace'):
            with self.subTest(function=function), patch('core.frame_database.'+function, side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    self.db.export_cloud(uid, target)
            self.assertEqual(target.read_bytes(), b'previous export')
            self.assertEqual(list(self.root.glob('.existing.ply.*.tmp')), [])

    def test_missing_stale_and_internal_targets_are_rejected(self):
        uid = self.db.ingest(self.frame())
        original = self.db.directory/'frames'/uid/'pointmap.ply'
        with self.assertRaises(ValueError):
            self.db.export_cloud(uid, original)
        self.assertEqual(original.read_bytes(), fixture.PLY)
        with self.assertRaises(ValueError):
            self.db.export_cloud(uid, self.root/'bad.xyz')
        self.db.records[uid].status = STALE_RESULT
        with self.assertRaises(ValueError):
            self.db.export_cloud(uid, self.root/'stale.ply')
        self.db.records[uid].status = '已入库'
        original.unlink()
        with self.assertRaises(FileNotFoundError):
            self.db.export_cloud(uid, self.root/'missing.ply')
        self.assertFalse((self.root/'missing.ply').exists())
