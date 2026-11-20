"""Fixed-anchor, all-edge camera calibration and durable final transforms."""
import _bootstrap
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from core.calibration_engine import CalibrationEngine
from core.frame_data import FrameData
from core.multi_camera_topology import quality_gate
from test_multi_camera_topology import fixture, workflow


def loop_frames(bias=.8):
    rng = np.random.default_rng(48)
    markers = {f'cam{i}': [] for i in range(4)}
    for edge, (a, b) in enumerate([(0, 1), (1, 2), (2, 3), (0, 3)]):
        for j, world in enumerate(rng.uniform([-50, -40, 400], [80, 90, 600], (12, 3))):
            for camera in (a, b):
                point = world - [camera * 100, camera * 20, 0]
                if edge == 3 and camera == 3:
                    point = point + [bias, 0, 0]
                markers[f'cam{camera}'].append(dict(code=edge*12+j,
                    x_3d=point[0], y_3d=point[1], z_3d=point[2]))
    return {cid: FrameData(1, cid, markers=rows, is_offline=True, kind='calib')
            for cid, rows in markers.items()}


class JointCameraTests(unittest.TestCase):
    def test_default_connects_indirect_cameras_and_fixes_middle_reference(self):
        poses, frames = fixture(5)
        wf = workflow(frames)
        wf._reference_id = 'cam2'
        self.assertTrue(wf.calibrate()[0])
        self.assertEqual(wf.calibration_engine.topology, 'joint')
        for cid, expected in poses.items():
            np.testing.assert_allclose(wf.calibration_engine.get_transform(cid, 'cam2'),
                np.linalg.inv(poses['cam2']) @ expected, atol=1e-7)

    def test_redundant_edges_reduce_loop_error_and_queries_are_path_consistent(self):
        wf = workflow(loop_frames())
        self.assertTrue(wf.calibrate()[0])
        engine = wf.calibration_engine
        self.assertEqual(len(engine.pair_results), 4)
        report = engine.joint_report
        self.assertTrue(report['optimized'])
        self.assertLess(report['final_rms_mm'], report['initial_rms_mm'] * .85)
        np.testing.assert_array_equal(engine.global_poses['cam0'], np.eye(4))
        np.testing.assert_allclose(engine.get_transform('cam3', 'cam0'),
            engine.get_transform('cam1', 'cam0') @ engine.get_transform('cam3', 'cam1'), atol=1e-9)

    def test_all_common_views_are_preserved_and_roundtrip_keeps_final_poses(self):
        _, frames = fixture(4, all_visible=True)
        wf = workflow(frames)
        self.assertTrue(wf.calibrate()[0])
        engine = wf.calibration_engine
        self.assertEqual(len(engine.pair_results), 6)
        saved = json.loads(json.dumps(engine.to_dict()))
        restored = CalibrationEngine()
        self.assertTrue(restored.load_from_dict(saved)[0])
        self.assertTrue(quality_gate(restored)[0])
        for cid in frames:
            np.testing.assert_allclose(restored.get_transform(cid, 'cam0'), engine.get_transform(cid, 'cam0'))
        before = restored.get_transform('cam3', 'cam0').copy()
        bad = copy.deepcopy(saved)
        bad['global_poses']['cam3'][0][3] += 100
        self.assertFalse(restored.load_from_dict(bad)[0])
        np.testing.assert_allclose(restored.get_transform('cam3', 'cam0'), before)
        bad = copy.deepcopy(saved)
        del bad['global_poses']['cam2']
        self.assertFalse(restored.load_from_dict(bad)[0])

    def test_locally_good_but_contradictory_loop_cannot_pass(self):
        wf = workflow(loop_frames(50))
        ok, message = wf.calibrate()
        self.assertFalse(ok, message)
        self.assertFalse(wf.start_scanning()[0])
        self.assertIn('约束', message)

    def test_failed_solver_retains_only_a_consistent_initial_solution(self):
        _, frames = fixture(4, all_visible=True)
        wf = workflow(frames)
        with patch('core.joint_camera_calibration.least_squares', side_effect=RuntimeError('solver unavailable')):
            self.assertTrue(wf.calibrate()[0])
        self.assertFalse(wf.calibration_engine.joint_report['optimized'])
        self.assertIn('solver unavailable', wf.calibration_engine.joint_report['message'])

    def test_disconnected_participants_cannot_pass(self):
        _, frames = fixture(4)
        frames['cam2'].markers = []
        wf = workflow(frames)
        self.assertFalse(wf.calibrate()[0])
        self.assertFalse(wf.start_scanning()[0])

    def test_invalid_or_worse_solver_result_is_not_published(self):
        for kind in ('nonfinite', 'worse', 'not_converged'):
            wf = workflow(loop_frames())
            def proposal(function, x0, **kwargs):
                x = x0.copy()
                x[3] += 100 if kind == 'worse' else 0
                if kind == 'nonfinite':
                    x[0] = np.nan
                return SimpleNamespace(success=kind != 'not_converged', x=x,
                    fun=np.zeros(3), message='not converged')
            with patch('core.joint_camera_calibration.least_squares', side_effect=proposal):
                self.assertTrue(wf.calibrate()[0])
            self.assertFalse(wf.calibration_engine.joint_report['optimized'])
            self.assertIn('回退', wf.calibration_engine.joint_report['message'])

    def test_final_inspection_uses_optimized_not_measured_pair_transforms(self):
        from core.joint_camera_calibration import inspection_pairs
        wf = workflow(loop_frames())
        self.assertTrue(wf.calibrate()[0])
        engine = wf.calibration_engine
        measured = engine.pair_results['cam0', 'cam3']['T'].copy()
        display = inspection_pairs(engine)
        from ui_v2.backend_bridge import _pairs_from_engine
        rows = {row['pair']: row for row in _pairs_from_engine(engine)}
        np.testing.assert_allclose(rows['cam3→cam0']['T'], engine.get_transform('cam3', 'cam0'))
        np.testing.assert_allclose(display['cam0', 'cam3']['T'], engine.get_transform('cam3', 'cam0'))
        self.assertFalse(np.allclose(display['cam0', 'cam3']['T'], measured))
        np.testing.assert_array_equal(engine.pair_results['cam0', 'cam3']['T'], measured)

    def test_malformed_pose_containers_are_rejected_without_losing_last_result(self):
        wf = workflow(loop_frames())
        self.assertTrue(wf.calibrate()[0])
        engine = wf.calibration_engine
        before = engine.get_transform('cam3', 'cam0').copy()
        for field, value in [('global_poses', []), ('joint_report', []),
                             ('joint_report', dict(optimized=True, final_rms_mm='bad'))]:
            saved = engine.to_dict()
            saved[field] = value
            self.assertFalse(engine.load_from_dict(saved)[0])
            np.testing.assert_array_equal(engine.get_transform('cam3', 'cam0'), before)

    def test_joint_load_cannot_silently_drop_a_corrupted_loop_edge(self):
        wf = workflow(loop_frames())
        self.assertTrue(wf.calibrate()[0])
        saved = copy.deepcopy(wf.calibration_engine.to_dict())
        saved['pairs']['cam0|cam3']['T'][0][0] = float('nan')
        restored = CalibrationEngine()
        self.assertFalse(restored.load_from_dict(saved)[0])

    def test_early_failed_recalibration_cannot_reuse_previous_final_poses(self):
        _, frames = fixture(4, all_visible=True)
        wf = workflow(frames)
        self.assertTrue(wf.calibrate()[0])
        self.assertTrue(wf.start_calibration('cam0')[0])
        frames['cam0'].markers = []
        self.assertFalse(wf.calibrate()[0])
        with self.assertRaises(ValueError):
            wf.calibration_engine.get_transform('cam3', 'cam0')


if __name__ == '__main__':
    unittest.main()
