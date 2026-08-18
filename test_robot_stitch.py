# -*- coding: utf-8 -*-
"""
RobotStitchWorkflow 合成数据测试（无硬件、无 GUI）。

验证：
  [1] Eye-in-Hand 配置下，多机位点云能正确拼到基座系；
  [2] Eye-to-Hand 配置下，固定相机点云拼到基座系；
  [3] MockRobot 位姿序列驱动拍摄。
"""

import os
import sys
import tempfile

import numpy as np
import open3d as o3d

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from core.robot_interface import MockRobot
from core.robot_stitch_workflow import RobotStitchWorkflow
from core.camera_manager import CameraManager
from core.frame_data import FrameData
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine


def rotz(deg: float) -> np.ndarray:
    theta = np.radians(deg)
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def rotx(deg: float) -> np.ndarray:
    theta = np.radians(deg)
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def make_T(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t, dtype=np.float64).flatten()
    return T


def make_box_pcd(center: np.ndarray, size: float = 60.0, n_points: int = 2000):
    """在 center 附近生成一个立方体点云。"""
    mesh = o3d.geometry.TriangleMesh.create_box(size, size, size)
    mesh = mesh.translate(center - np.array([size / 2, size / 2, size / 2]))
    return mesh.sample_points_uniformly(number_of_points=n_points)


class MockCameraManager(CameraManager):
    """覆盖 capture 返回合成点云的 CameraManager。"""

    def __init__(self, pcds: list):
        super().__init__()
        self._pcds = pcds
        self._idx = 0
        self._temp_dir = tempfile.mkdtemp()

    def get_connected_ids(self):
        return ['mock']

    def capture(self, camera_id: str) -> FrameData:
        pcd = self._pcds[self._idx % len(self._pcds)]
        self._idx += 1
        # 将点云写入临时 PLY，让 FrameData 通过 offline_pointmap_path 加载
        ply_path = os.path.join(self._temp_dir, f"frame_{self._idx:04d}.ply")
        o3d.io.write_point_cloud(ply_path, pcd)
        frame = FrameData(
            frame_id=self._idx,
            camera_name=camera_id,
            image_np=np.zeros((100, 100, 3), dtype=np.uint8),
            pointmap=None,
            rvc_image=None,
            is_offline=True,
            offline_dir=self._temp_dir,
            offline_pointmap_path=ply_path,
        )
        return frame

    def is_connected(self, camera_id: str) -> bool:
        return True


def test_eye_in_hand():
    print("\n[1] Eye-in-Hand 机器人拼接测试")

    # 真值：T_cam2tool（相机相对工具法兰的位姿）
    T_cam2tool_true = make_T(rotz(15) @ rotx(10), [20.0, -10.0, 50.0])
    T_tool2cam_true = np.linalg.inv(T_cam2tool_true)

    # 机器人基座系下有一个立方体，作为被扫描物体
    object_center = np.array([400.0, 200.0, 100.0])
    object_pcd = make_box_pcd(object_center, size=80.0, n_points=3000)

    # 生成 5 个机器人位姿：绕 Z 轴平移+旋转，从四周看物体
    poses_base2tool = []
    pcds_cam = []
    for deg in [0, 45, 90, 135, 180]:
        # 工具法兰原点
        t_base2tool = object_center + np.array([
            200.0 * np.cos(np.radians(deg)),
            200.0 * np.sin(np.radians(deg)),
            80.0
        ])
        # 工具绕 Z 轴旋转
        R_base2tool = rotz(deg)
        T_base2tool = make_T(R_base2tool, t_base2tool)
        poses_base2tool.append(T_base2tool)

        # 相机坐标系下的点云 p_cam = T_base2cam @ p_base
        # T_base2cam = inv(T_cam2base) = inv(T_base2tool @ T_cam2tool_true)
        T_cam2base = T_base2tool @ T_cam2tool_true
        T_base2cam = np.linalg.inv(T_cam2base)
        pcd_cam = o3d.geometry.PointCloud(object_pcd)
        pcd_cam.transform(T_base2cam)
        pcds_cam.append(pcd_cam)

    robot = MockRobot(poses=poses_base2tool)
    cm = MockCameraManager(pcds_cam)
    wf = RobotStitchWorkflow(
        camera_manager=cm,
        marker_detector=MarkerDetector(),
        calibration_engine=CalibrationEngine(),
        stitch_engine=StitchEngine(),
    )

    ok, msg = wf.set_robot(robot)
    assert ok, msg
    ok, msg = wf.set_handeye_result(eye_in_hand=True, T_handeye=T_cam2tool_true)
    assert ok, msg

    for i in range(len(poses_base2tool)):
        robot._current_pose = poses_base2tool[i].copy()
        ok, msg, info = wf.capture_frame('mock')
        assert ok, msg

    merged = wf.get_merged_pointcloud()
    assert merged is not None
    pts = np.asarray(merged.points)
    center_est = pts.mean(axis=0)
    err = np.linalg.norm(center_est - object_center)
    print(f"  合并点数: {len(pts)}")
    print(f"  物体中心估计: {center_est.round(2)}")
    print(f"  中心误差: {err:.3f} mm")
    assert err < 15.0, f"Eye-in-Hand 拼接中心误差过大: {err:.3f} mm"

    fd, path = tempfile.mkstemp(suffix='.ply')
    os.close(fd)
    ok, msg = wf.save_merged_ply(path)
    assert ok, msg
    assert os.path.exists(path)
    os.unlink(path)
    print("  [OK] Eye-in-Hand 拼接精度满足要求")


def test_eye_to_hand():
    print("\n[2] Eye-to-Hand 机器人拼接测试")

    # 真值：T_cam2base（相机固定在基座系某处）
    T_cam2base_true = make_T(rotz(-20) @ rotx(10), [800.0, 100.0, 600.0])

    object_center = np.array([400.0, 200.0, 100.0])
    object_pcd = make_box_pcd(object_center, size=80.0, n_points=3000)

    # 相机坐标系下点云 = inv(T_cam2base) @ object_pcd（固定不变，每次独立副本）
    pcds_cam = []
    for _ in range(5):
        pcd_cam = o3d.geometry.PointCloud(object_pcd)
        pcd_cam.transform(np.linalg.inv(T_cam2base_true))
        pcds_cam.append(pcd_cam)

    # 机器人位姿任意变化（不影响 Eye-to-Hand 的 T_base2cam）
    poses_base2tool = []
    for deg in [0, 30, 60, 90, 120]:
        t = np.array([200.0 + deg, 0.0, 300.0])
        R = rotz(deg) @ rotx(10)
        poses_base2tool.append(make_T(R, t))

    robot = MockRobot(poses=poses_base2tool)
    cm = MockCameraManager(pcds_cam)
    wf = RobotStitchWorkflow(
        camera_manager=cm,
        marker_detector=MarkerDetector(),
        calibration_engine=CalibrationEngine(),
        stitch_engine=StitchEngine(),
    )

    ok, msg = wf.set_robot(robot)
    assert ok, msg
    ok, msg = wf.set_handeye_result(eye_in_hand=False, T_handeye=T_cam2base_true)
    assert ok, msg

    for i in range(len(poses_base2tool)):
        robot._current_pose = poses_base2tool[i].copy()
        ok, msg, info = wf.capture_frame('mock')
        assert ok, msg

    merged = wf.get_merged_pointcloud()
    pts = np.asarray(merged.points)
    center_est = pts.mean(axis=0)
    err = np.linalg.norm(center_est - object_center)
    print(f"  合并点数: {len(pts)}")
    print(f"  物体中心估计: {center_est.round(2)}")
    print(f"  中心误差: {err:.3f} mm")
    assert err < 15.0, f"Eye-to-Hand 拼接中心误差过大: {err:.3f} mm"
    print("  [OK] Eye-to-Hand 拼接精度满足要求")


if __name__ == "__main__":
    print("=" * 60)
    print("RobotStitchWorkflow 合成数据测试")
    print("=" * 60)
    test_eye_in_hand()
    test_eye_to_hand()
    print("\n" + "=" * 60)
    print("[OK] 所有机器人拼接测试通过")
    print("=" * 60)
