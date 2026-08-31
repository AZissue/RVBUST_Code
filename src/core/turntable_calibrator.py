# -*- coding: utf-8 -*-
"""
转台 360° 拼接原型算法。

坐标系约定：
  - 相机固定，转台带动物体/标记物旋转；
  - 参考帧（frame 0）为转台 0° 位置；
  - 第 i 帧点云通过「绕转台轴旋转 -i*θ」变换到参考系后合并。

核心能力：
  1. 从两帧对应标记点估计刚体变换 (R, t)；
  2. 分解 R 得到旋转轴 axis 与角度 θ；
  3. 由 (R, t) 估计旋转中心 c；
  4. 生成 360° 拼接所需的全部旋转变换；
  5. 按角度把每帧点云变换到参考系并合并。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

import open3d as o3d


def kabsch_rigid_transform(
    src: np.ndarray, dst: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Kabsch 算法：src (N,3) → dst (N,3)，返回 (R, t) 使 dst ≈ src @ R.T + t。

    即：p_dst = R @ p_src + t
    """
    assert src.shape == dst.shape and src.shape[1] == 3
    src_c = src.mean(axis=0)
    dst_c = dst.mean(axis=0)
    P = src - src_c
    Q = dst - dst_c
    H = P.T @ Q
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    t = dst_c - R @ src_c
    return R.astype(np.float64), t.astype(np.float64)


def decompose_rotation(R: np.ndarray) -> Tuple[np.ndarray, float]:
    """把旋转矩阵分解为轴角，返回 (axis, angle_rad)。"""
    angle = np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))
    if abs(angle) < 1e-8:
        return np.array([0.0, 0.0, 1.0]), 0.0
    rx = R[2, 1] - R[1, 2]
    ry = R[0, 2] - R[2, 0]
    rz = R[1, 0] - R[0, 1]
    axis = np.array([rx, ry, rz])
    axis = axis / np.linalg.norm(axis)
    return axis, float(angle)


def estimate_rotation_center(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """已知 p' = R @ p + t，求旋转中心 c：(R - I)c = -t。"""
    A = R - np.eye(3)
    # 用最小二乘，容忍数值噪声
    c, *_ = np.linalg.lstsq(A, -t, rcond=None)
    return c.astype(np.float64)


def rodrigues(axis: np.ndarray, angle: float) -> np.ndarray:
    """轴角 → 旋转矩阵。"""
    k = axis / np.linalg.norm(axis)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def transform_matrix(axis: np.ndarray, angle: float, center: np.ndarray) -> np.ndarray:
    """构造绕 axis 过 center 旋转 angle 的 4x4 变换矩阵。

    含义：把第 i 帧点云旋转回参考帧（frame 0）。
    """
    R = rodrigues(axis, angle)
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = center - R @ center
    return T


class TurntableCalibrator:
    """转台拼接标定器。"""

    def __init__(self):
        self.axis: Optional[np.ndarray] = None
        self.center: Optional[np.ndarray] = None
        self.angle_rad: float = 0.0
        self.step_count: int = 0
        self.R_init: Optional[np.ndarray] = None
        self.t_init: Optional[np.ndarray] = None

    def calibrate_from_markers(
        self,
        points_frame0: np.ndarray,
        points_frame1: np.ndarray,
    ) -> Tuple[bool, str, dict]:
        """用 frame0/frame1 的对应标记点标定转台。

        Args:
            points_frame0: (N,3) 参考帧标记点
            points_frame1: (N,3) 旋转一帧后标记点（与 frame0 一一对应）

        Returns:
            (ok, message, info_dict)
        """
        if points_frame0.shape != points_frame1.shape or points_frame0.shape[0] < 3:
            return False, "对应点不足 3 对", {}

        # 求 frame0 -> frame1 的刚体变换 (R, t)，使 p1 ≈ R @ p0 + t。
        # 这样 R 的轴角直接对应转台从 frame0 旋转到 frame1 的角度 +θ，
        # 后续第 i 帧用 -i*θ 反向旋转即可回到参考系。
        R, t = kabsch_rigid_transform(points_frame0, points_frame1)
        axis, angle = decompose_rotation(R)
        center = estimate_rotation_center(R, t)

        self.axis = axis
        self.center = center
        self.angle_rad = angle
        self.R_init = R
        self.t_init = t

        # 估算 360° 需要几次旋转（取整）
        if abs(angle) < 1e-6:
            self.step_count = 0
            return False, "旋转角度几乎为 0，无法估算步数", {}

        self.step_count = int(round(2 * np.pi / angle))

        info = {
            "axis": axis.tolist(),
            "center": center.tolist(),
            "angle_deg": float(np.degrees(angle)),
            "step_count": self.step_count,
        }
        return (
            True,
            f"标定成功：旋转轴 {axis.round(4)}, 角度 {np.degrees(angle):.2f}°, "
            f"中心 {center.round(2)}, 估算 {self.step_count} 步/360°",
            info,
        )

    def is_calibrated(self) -> bool:
        return self.axis is not None and self.step_count > 0

    def get_transform_for_step(self, step: int) -> np.ndarray:
        """第 step 帧（从 0 开始）变换到参考帧的 4x4 矩阵。"""
        if not self.is_calibrated():
            raise RuntimeError("转台尚未标定")
        return transform_matrix(self.axis, -step * self.angle_rad, self.center)

    def stitch_pointclouds(
        self,
        pcds: List[o3d.geometry.PointCloud],
        downsample_voxel: Optional[float] = None,
    ) -> Tuple[Optional[o3d.geometry.PointCloud], str]:
        """按标定角度把多帧点云变换到参考系并合并。

        Args:
            pcds: 第 0, 1, 2, ... 帧点云（长度应 ≤ step_count+1）
            downsample_voxel: 合并后可选体素下采样（mm），None 表示不下采样
        """
        if not self.is_calibrated():
            return None, "转台尚未标定"
        if len(pcds) < 2:
            return None, "至少需要 2 帧点云"

        merged = o3d.geometry.PointCloud()
        for i, pcd in enumerate(pcds):
            if pcd is None or len(pcd.points) == 0:
                continue
            T = self.get_transform_for_step(i)
            pcd_t = o3d.geometry.PointCloud(pcd)
            pcd_t.transform(T)
            merged += pcd_t

        if len(merged.points) == 0:
            return None, "合并结果为空"

        valid_pcds = [p for p in pcds if p is not None]
        msg = f"合并 {len(valid_pcds)} 帧，原始共 {sum(len(p.points) for p in valid_pcds)} 点，"
        if downsample_voxel is not None and downsample_voxel > 0:
            before = len(merged.points)
            merged = merged.voxel_down_sample(downsample_voxel)
            msg += f"下采样后 {len(merged.points)} 点（原 {before} 点）"
        else:
            msg += f"合并后 {len(merged.points)} 点"
        return merged, msg


# ---------------------------------------------------------------------------
# 标记点匹配与在线会话管理
# ---------------------------------------------------------------------------
def match_markers_pair(
    markers0: List[Dict],
    markers1: List[Dict],
    key: str = "code",
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], str]:
    """按 key（默认 code）匹配两帧标记点，返回 (pts0, pts1, message)。

    标定板模式 markers 没有 code，可传 key='index' 按顺序索引匹配。
    返回的 pts0/pts1 形状为 (N,3)，按同一顺序排列。
    """
    if not markers0 or not markers1:
        return None, None, "标记点为空"

    def _get_code(m: Dict, idx: int) -> int:
        if key == "index":
            return idx
        return m.get(key, m.get("code", idx))

    dict0 = {_get_code(m, i): m for i, m in enumerate(markers0)}
    dict1 = {_get_code(m, i): m for i, m in enumerate(markers1)}
    common = sorted(set(dict0.keys()) & set(dict1.keys()))
    if len(common) < 3:
        return None, None, f"两帧共有标记点不足 3 个: {len(common)}"

    pts0, pts1 = [], []
    for k in common:
        m0, m1 = dict0[k], dict1[k]
        pts0.append([m0.get("x_3d", 0.0), m0.get("y_3d", 0.0), m0.get("z_3d", 0.0)])
        pts1.append([m1.get("x_3d", 0.0), m1.get("y_3d", 0.0), m1.get("z_3d", 0.0)])

    return np.asarray(pts0, dtype=np.float64), np.asarray(pts1, dtype=np.float64), f"匹配 {len(common)} 对标记点"


class OnlineTurntableSession:
    """在线转台拼接会话：管理相机拍摄的帧、标定结果、步进采集。"""

    def __init__(self, session_dir: Optional[str] = None):
        self.session_dir = session_dir
        self.frame0: Optional[object] = None          # FrameData
        self.frame1: Optional[object] = None
        self.markers0: List[Dict] = []
        self.markers1: List[Dict] = []
        self.sequence: List[object] = []              # 后续帧 FrameData 列表
        self.current_step: int = 0                    # 0=未开始采集，1=已拍 frame0，2=已拍 frame1 ...
        self.calib = TurntableCalibrator()
        self.calibrated: bool = False
        self.frame0_pcd: Optional[o3d.geometry.PointCloud] = None
        self.frame1_pcd: Optional[o3d.geometry.PointCloud] = None
        self.sequence_pcds: List[o3d.geometry.PointCloud] = []

    def set_frame0(self, frame_data, markers: List[Dict], pcd: o3d.geometry.PointCloud):
        self.frame0 = frame_data
        self.markers0 = markers
        self.frame0_pcd = pcd
        self.current_step = max(self.current_step, 1)

    def set_frame1(self, frame_data, markers: List[Dict], pcd: o3d.geometry.PointCloud):
        self.frame1 = frame_data
        self.markers1 = markers
        self.frame1_pcd = pcd
        self.current_step = max(self.current_step, 2)

    def calibrate(self, marker_key: str = "code") -> Tuple[bool, str, dict]:
        """用 frame0/frame1 的标记点在线标定。

        标定成功后，清空 frame0/frame1 的拍摄数据（它们仅用于计算角度），
        让步进采集从 step 1 重新开始，总步数为 step_count + 1。
        """
        pts0, pts1, match_msg = match_markers_pair(self.markers0, self.markers1, marker_key)
        if pts0 is None:
            return False, match_msg, {}
        ok, msg, info = self.calib.calibrate_from_markers(pts0, pts1)
        self.calibrated = ok
        if ok:
            # 标定帧仅用于计算角度，不进入最终拼接；清空后重新采集
            self.frame0 = None
            self.frame1 = None
            self.frame0_pcd = None
            self.frame1_pcd = None
            self.sequence = []
            self.sequence_pcds = []
            self.current_step = 1
        return ok, f"{match_msg}; {msg}", info

    def is_calibrated(self) -> bool:
        return self.calibrated and self.calib.is_calibrated()

    def step_count(self) -> int:
        return self.calib.step_count if self.is_calibrated() else 0

    def total_steps_needed(self) -> int:
        """包含 frame0 在内，完成 360° 共需多少帧。"""
        return self.step_count() + 1 if self.is_calibrated() else 0

    def add_sequence_frame(self, frame_data, pcd: o3d.geometry.PointCloud):
        """添加步进采集帧。标定后 frame0/1 已清空，从 step 1 开始计数。"""
        self.sequence.append(frame_data)
        self.sequence_pcds.append(pcd)
        self.current_step = 1 + len(self.sequence)

    def get_all_pcds(self) -> List[o3d.geometry.PointCloud]:
        """获取完整序列点云（frame0, frame1, frame2, ...）。"""
        result = []
        if self.frame0_pcd is not None:
            result.append(self.frame0_pcd)
        if self.frame1_pcd is not None:
            result.append(self.frame1_pcd)
        result.extend(self.sequence_pcds)
        return result

    def get_all_frames(self) -> List[object]:
        result = []
        if self.frame0 is not None:
            result.append(self.frame0)
        if self.frame1 is not None:
            result.append(self.frame1)
        result.extend(self.sequence)
        return result

    def can_stitch(self) -> bool:
        return self.is_calibrated() and len(self.get_all_pcds()) >= 2

    def stitch(self, downsample_voxel: Optional[float] = None) -> Tuple[Optional[o3d.geometry.PointCloud], str]:
        if not self.can_stitch():
            return None, "尚未标定或帧数不足"
        return self.calib.stitch_pointclouds(self.get_all_pcds(), downsample_voxel=downsample_voxel)

    def reset(self):
        """重置会话（保留 session_dir）。"""
        self.frame0 = None
        self.frame1 = None
        self.markers0 = []
        self.markers1 = []
        self.sequence = []
        self.sequence_pcds = []
        self.frame0_pcd = None
        self.frame1_pcd = None
        self.current_step = 0
        self.calib = TurntableCalibrator()
        self.calibrated = False


class SyntheticTurntableData:
    """生成合成转台数据，用于无硬件时验证算法。"""

    def __init__(
        self,
        axis: np.ndarray = None,
        center: np.ndarray = None,
        angle_deg: float = 30.0,
        radius: float = 100.0,
        noise_mm: float = 0.5,
    ):
        self.axis = axis / np.linalg.norm(axis) if axis is not None else np.array([0.0, 0.0, 1.0])
        self.center = center if center is not None else np.array([50.0, -30.0, 200.0])
        self.angle_rad = np.radians(angle_deg)
        self.radius = radius
        self.noise_mm = noise_mm

    def _generate_scene(self) -> o3d.geometry.PointCloud:
        """生成一个放在转台上的简单物体（立方体 + 平面）。"""
        cube = o3d.geometry.TriangleMesh.create_box(80, 60, 40)
        cube = cube.translate([-40, -30, 0])
        plane = o3d.geometry.TriangleMesh.create_box(200, 200, 2)
        plane = plane.translate([-100, -100, -2])
        pcd_cube = cube.sample_points_uniformly(number_of_points=8000)
        pcd_plane = plane.sample_points_uniformly(number_of_points=4000)
        pcd = pcd_cube + pcd_plane
        # 整体平移到转台中心附近
        pcd = pcd.translate(self.center + np.array([0, 0, 20]))
        return pcd

    def generate_markers(self, n_markers: int = 6) -> np.ndarray:
        """生成转台平面上的标记点（围绕中心半径分布）。"""
        angles = np.linspace(0, 2 * np.pi, n_markers, endpoint=False)
        pts = []
        for a in angles:
            # 在转台平面上生成点：axis 为法向，找两个正交方向
            u = np.array([1.0, 0.0, 0.0])
            if np.allclose(np.abs(self.axis), np.abs(u)):
                u = np.array([0.0, 1.0, 0.0])
            u = u - np.dot(u, self.axis) * self.axis
            u = u / np.linalg.norm(u)
            v = np.cross(self.axis, u)
            p = self.center + self.radius * (np.cos(a) * u + np.sin(a) * v)
            pts.append(p)
        return np.array(pts)

    def rotate_points(self, pts: np.ndarray, step: int) -> np.ndarray:
        """把点绕转台轴旋转 step * angle。"""
        T = transform_matrix(self.axis, step * self.angle_rad, self.center)
        homo = np.hstack([pts, np.ones((pts.shape[0], 1))])
        return (homo @ T.T)[:, :3]

    def generate_sequence(
        self, n_steps: int
    ) -> Tuple[List[o3d.geometry.PointCloud], List[np.ndarray]]:
        """生成 0..n_steps 帧点云及对应标记点。"""
        base_pcd = self._generate_scene()
        base_markers = self.generate_markers()
        pcds = []
        markers_list = []
        for i in range(n_steps + 1):
            T = transform_matrix(self.axis, i * self.angle_rad, self.center)
            pcd_i = base_pcd.transform(T)
            if self.noise_mm > 0:
                pts = np.asarray(pcd_i.points)
                pts += np.random.normal(0, self.noise_mm, pts.shape)
                pcd_i.points = o3d.utility.Vector3dVector(pts)
            pcds.append(pcd_i)
            markers_list.append(self.rotate_points(base_markers, i))
        return pcds, markers_list


def test_synthetic():
    """命令行快速验证。"""
    print("=" * 60)
    print("转台拼接合成数据验证")
    print("=" * 60)
    synth = SyntheticTurntableData(angle_deg=30.0, noise_mm=0.3)
    pcds, markers = synth.generate_sequence(n_steps=11)  # 0~330°

    calib = TurntableCalibrator()
    ok, msg, info = calib.calibrate_from_markers(markers[0], markers[1])
    print(msg)
    print(f"真实角度: 30.00°, 估计角度: {info.get('angle_deg', 0):.2f}°")
    print(f"真实轴:   {synth.axis.round(4)}")
    print(f"估计轴:   {np.array(info.get('axis')).round(4)}")
    print(f"真实中心: {synth.center.round(2)}")
    print(f"估计中心: {np.array(info.get('center')).round(2)}")

    merged, msg = calib.stitch_pointclouds(pcds, downsample_voxel=2.0)
    print(msg)
    return calib, merged


if __name__ == "__main__":
    test_synthetic()
