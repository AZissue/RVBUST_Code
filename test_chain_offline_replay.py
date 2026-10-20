"""Replay real saved stool markers; keep online detection and quality gates."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'src'))
from core.calibration_engine import CalibrationEngine
from core.chain_stitcher import ChainStitcher
from core.frame_data import FrameData
from core.mobile_chain_workflow import MobileChainWorkflow


class OfflineReplayTests(unittest.TestCase):
    def setUp(self):
        manifest = json.loads((ROOT / 'offline_test_data/stool/manifest.json').read_text(encoding='utf-8'))
        self.saved = {f'station_{i}': row['markers'] for i, row in enumerate(manifest['frames'], 1)}
        self.detector = Mock()
        self.workflow = MobileChainWorkflow(Mock(), self.detector, CalibrationEngine(), Mock(), Mock())
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for name in self.saved:
            folder = Path(self.directory.name) / name
            folder.mkdir()
            cv2.imwrite(str(folder / f'{name}.png'), np.zeros((4, 4, 3), np.uint8))
            (folder / f'{name}.ply').write_bytes(b'not loaded in this marker registration test')
        cache = patch.object(ChainStitcher, '_cache_node_pcd', return_value=None)
        cache.start()
        self.addCleanup(cache.stop)

    def test_saved_stool_results_replay_repeatably_without_detection(self):
        self.detector.detect_3d.side_effect = AssertionError('saved replay must not redetect')
        for _ in range(3):
            ok, message = self.workflow.load_session_dir(self.directory.name, saved_markers=self.saved)
            self.assertTrue(ok, message)
            self.assertEqual(len(self.workflow.get_station_evaluations()), 2)
            edge = self.workflow.last_edge or self.workflow._chain_stitcher.edges[-1]
            self.assertEqual(edge.inlier_count, 25)
            self.assertAlmostEqual(edge.inlier_ratio, 25 / 34)
            self.assertAlmostEqual(edge.rms_mm, .6082519617)
        self.detector.detect_3d.assert_not_called()
        self.assertNotIn('u', self.saved['station_1'][0])

    def test_ordinary_offline_load_detects_each_frame_once(self):
        def detect(image, **kwargs):
            name = Path(kwargs['offline_ply_path']).stem
            return copy.deepcopy(self.saved[name])
        self.detector.detect_3d.side_effect = detect
        ok, message = self.workflow.load_session_dir(self.directory.name)
        self.assertTrue(ok, message)
        self.assertEqual(len(self.workflow.get_station_evaluations()), 2)
        self.assertEqual(self.detector.detect_3d.call_count, 2)

    def test_saved_replay_does_not_weaken_quality_gate_and_reports_reason(self):
        self.workflow.calibration_engine.calibrate_pair = Mock(return_value=dict(
            success=True, T=np.eye(4), rms_mm=.6661, inlier_ratio=23 / 34, inlier_count=23))
        ok, message = self.workflow.load_session_dir(self.directory.name, saved_markers=self.saved)
        self.assertTrue(ok)  # Existing loader permits viewing one surviving station.
        self.assertEqual(len(self.workflow.get_station_evaluations()), 1)
        self.assertIn('station_2', message)
        self.assertIn('67.6% < 70.0%', message)

    def test_incomplete_saved_records_never_fall_back_to_detector(self):
        self.detector.detect_3d.side_effect = AssertionError('unexpected detection')
        ok, message = self.workflow.load_session_dir(self.directory.name,
            saved_markers={'station_1': self.saved['station_1']})
        self.assertTrue(ok)
        self.assertIn('station_2 无有效3D标记', message)
        self.detector.detect_3d.assert_not_called()

    def test_online_frames_cannot_skip_detection(self):
        stitcher = ChainStitcher(self.detector, CalibrationEngine(), Mock())
        frame = FrameData(1, 'online', markers=self.saved['station_1'])
        ok, message, edge = stitcher.add_frame(frame, detect_markers=False)
        self.assertFalse(ok)
        self.assertIn('仅离线帧', message)
        self.assertIsNone(edge)


if __name__ == '__main__':
    unittest.main()
