"""Formal robot hand-eye package and workflow regression tests."""
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest

import numpy as np
import open3d as o3d

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'src'))

from core.camera_manager import CameraManager
from core.frame_data import FrameData
from core.robot_handeye import HandEyeResult, ManualPoseSource
from core.robot_stitch_workflow import RobotStitchWorkflow


def make_handeye():
    matrix = np.eye(4)
    matrix[:3, 3] = [20, -10, 120]
    ok, message, result = HandEyeResult.from_matrix(matrix, 'mm', True)
    assert ok, message
    return result


def make_pose_source():
    source = ManualPoseSource()
    ok, message = source.set_pose_xyz_rpy(
        [400, 100, 420], [0, 0, 15], 'ZYX', 'mm', 'absolute')
    assert ok, message
    return source


def make_cloud():
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
        np.array([[1., 2., 500.], [10., 20., 600.]])))
    cloud.colors = o3d.utility.Vector3dVector(
        np.array([[1., 0., 0.], [0., 1., 0.]]))
    return cloud


class FixtureCamera(CameraManager):
    def __init__(self):
        super().__init__()
        self.cloud = make_cloud()
        self.fail = False
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup = None

    def get_connected_ids(self):
        return ['cam0']

    def capture(self, camera_id, options=None, frame_id=None):
        if self.fail:
            return None
        path = str(Path(self.temp.name) / 'frame.ply')
        o3d.io.write_point_cloud(path, self.cloud)
        frame = FrameData(1, camera_id, image_np=np.zeros((2, 2, 3), np.uint8),
            is_offline=True, offline_pointmap_path=path)
        frame.database_id = 'a' * 32
        return frame


class RobotHandEyeCoreTests(unittest.TestCase):
    def setUp(self):
        self.camera = FixtureCamera()
        self.addCleanup(self.camera.temp.cleanup)
        self.workflow = RobotStitchWorkflow(self.camera, None, None, None)

    def configure(self):
        self.assertTrue(self.workflow.set_handeye(make_handeye())[0])
        self.assertTrue(self.workflow.set_pose_source(make_pose_source())[0])

    def test_formal_package_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('core.robot_handeye'))

    def test_capture_preserves_raw_cloud_and_records_pose_metadata(self):
        self.configure()
        before = np.asarray(self.camera.cloud.points).copy()
        ok, message, info = self.workflow.capture_frame('cam0')
        self.assertTrue(ok, message)
        np.testing.assert_array_equal(np.asarray(self.camera.cloud.points), before)
        expected = (info['T_base2tool'] @ make_handeye().T_handeye_mm @
            np.column_stack([before, np.ones(len(before))]).T).T[:, :3]
        np.testing.assert_allclose(np.asarray(info['pcd_base'].points), expected)
        np.testing.assert_allclose(np.asarray(info['pcd_base'].colors),
            np.asarray(self.camera.cloud.colors))
        self.assertEqual(info['database_id'], 'a' * 32)
        self.assertEqual(self.workflow.get_frame_count(), 1)

    def test_failed_capture_does_not_append_partial_frame(self):
        self.configure()
        self.camera.fail = True
        ok, _, info = self.workflow.capture_frame('cam0')
        self.assertFalse(ok)
        self.assertIsNone(info)
        self.assertEqual(self.workflow.get_frame_count(), 0)
        self.assertIsNone(self.workflow.get_merged_pointcloud())

    def test_merged_export_requires_tip_verification(self):
        self.configure()
        self.assertTrue(self.workflow.capture_frame('cam0')[0])
        with tempfile.TemporaryDirectory() as folder:
            target = str(Path(folder) / 'merged.ply')
            ok, message = self.workflow.save_merged_ply(target)
            self.assertFalse(ok)
            self.assertIn('VERIFIED', message)
            self.workflow.handeye.validated = True
            self.assertTrue(self.workflow.save_merged_ply(target)[0])
            self.assertTrue(Path(target).is_file())

    def test_snapshot_restore_rebuilds_cloud_and_rejects_missing_frames(self):
        self.configure()
        self.assertTrue(self.workflow.capture_frame('cam0')[0])
        snapshot = self.workflow.snapshot()
        restored = RobotStitchWorkflow(self.camera, None, None, None)
        restored.restore_snapshot(snapshot, list(self.workflow.frames))
        self.assertEqual(restored.get_frame_count(), 1)
        np.testing.assert_allclose(
            np.asarray(restored.get_merged_pointcloud().points),
            np.asarray(self.workflow.get_merged_pointcloud().points))
        before = restored.snapshot()
        with self.assertRaisesRegex(ValueError, '缺失'):
            restored.restore_snapshot(snapshot, [])
        self.assertEqual(restored.snapshot(), before)

    def test_csv_pose_source_restores_sequence_without_external_file(self):
        from core.robot_handeye import CsvPoseSource
        pose = make_pose_source().get_pose()[2]
        restored = CsvPoseSource.from_poses([pose, pose], index=1)
        self.assertEqual(restored.current_index(), 1)
        np.testing.assert_array_equal(restored.get_pose()[2], pose)
        with self.assertRaisesRegex(ValueError, '位姿'):
            CsvPoseSource.from_poses([])

    def test_csv_capture_uses_current_pose_then_advances(self):
        from core.robot_handeye import CsvPoseSource
        first = make_pose_source().get_pose()[2]
        second_source = ManualPoseSource()
        second_source.set_pose_xyz_rpy([420, 120, 430], [0, 20, 25], 'ZYX', 'mm', 'absolute')
        second = second_source.get_pose()[2]
        self.assertTrue(self.workflow.set_handeye(make_handeye())[0])
        self.assertTrue(self.workflow.set_pose_source(CsvPoseSource.from_poses([first, second]))[0])
        self.assertTrue(self.workflow.capture_frame('cam0')[0])
        self.assertTrue(self.workflow.capture_frame('cam0')[0])
        np.testing.assert_array_equal(self.workflow.poses[0], first)
        np.testing.assert_array_equal(self.workflow.poses[1], second)
        ok, message, info = self.workflow.capture_frame('cam0')
        self.assertFalse(ok)
        self.assertIn('耗尽', message)
        self.assertIsNone(info)
        self.assertEqual(self.workflow.get_frame_count(), 2)

    def test_tip_samples_roundtrip_restores_verified_state(self):
        from core.robot_handeye.pose_source import euler_to_matrix
        from core.robot_handeye.transform_chain import compute_cam2base
        self.configure()
        point_base = np.array([400., 100., 420.])
        samples = []
        for values in ([400, 100, 420, 0, 0, 0],
                       [420, 110, 430, 0, 20, 25],
                       [410, 120, 425, 25, 0, -20]):
            pose = euler_to_matrix(values[:3], values[3:], 'ZYX')
            transform = compute_cam2base(True, make_handeye().T_handeye_mm, pose)
            tip = (np.linalg.inv(transform) @ np.append(point_base, 1.0))[:3]
            samples.append((pose, tip))
            self.assertTrue(self.workflow.add_tip_sample(pose, tip)[0])
        self.assertEqual(self.workflow.run_tip_check()['verdict'], 'PASS')
        snapshot = self.workflow.snapshot()
        restored = RobotStitchWorkflow(self.camera, None, None, None)
        restored.restore_snapshot(snapshot, [])
        self.assertEqual(len(restored.validator), 3)
        self.assertTrue(restored.handeye.validated)
        self.assertEqual(restored.run_tip_check()['verdict'], 'PASS')
        self.assertTrue(restored.add_tip_sample(*samples[0])[0])
        self.assertFalse(restored.handeye.validated)
        self.assertIsNone(restored.tip_report)

    def test_restore_rejects_non_rigid_pose_even_when_transform_is_self_consistent(self):
        self.configure()
        self.assertTrue(self.workflow.capture_frame('cam0')[0])
        snapshot = self.workflow.snapshot()
        pose = np.asarray(snapshot['captures'][0]['T_base2tool']).copy()
        pose[0, 0] = 2.0
        snapshot['captures'][0]['T_base2tool'] = pose.tolist()
        snapshot['captures'][0]['T_cam2base'] = (
            pose @ make_handeye().T_handeye_mm).tolist()
        restored = RobotStitchWorkflow(self.camera, None, None, None)
        with self.assertRaisesRegex(ValueError, '位姿'):
            restored.restore_snapshot(snapshot, list(self.workflow.frames))
        self.assertIsNone(restored.handeye)

    def test_pose_guards_and_eye_to_hand_truth(self):
        from core.robot_handeye.pose_source import admit_pose
        from core.robot_handeye.transform_chain import compute_cam2base, transform_points_mm
        pose = make_pose_source().get_pose()[2]
        for bad in (np.full((4, 4), np.nan), np.diag([-1., 1., 1., 1.]), np.diag([2., 1., 1., 1.])):
            self.assertFalse(admit_pose(bad, 'mm', 'absolute')[0])
        self.assertFalse(admit_pose(pose, 'mm', 'delta')[0])
        fixed = make_handeye().T_handeye_mm
        points = np.array([[1., 2., 500.]])
        expected = (fixed @ np.append(points[0], 1.0))[:3]
        np.testing.assert_allclose(transform_points_mm(points,
            compute_cam2base(False, fixed, pose))[0], expected)


if __name__ == '__main__':
    unittest.main()
