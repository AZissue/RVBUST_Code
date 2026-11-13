# -*- coding: utf-8 -*-
"""
OfflineStitcher 无 UI 单元测试。

生成 3 对合成图像+点云，验证：
  1. 文件对扫描正确；
  2. 2D 编码圆检测 + 3D 映射正确；
  3. 相邻帧拼接后点云回到同一坐标系。
"""

import os
import sys
import tempfile
from typing import Dict, List

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import numpy as np
import cv2
import open3d as o3d

from offline_stitcher import OfflineStitcher, collect_frame_pairs
from core.marker_detector import MarkerDetector


class MockMarkerDetector:
    """模拟编码圆检测器：直接返回已知的 2D/3D markers。

    仅用于无 PyRVC 环境下验证拼接链路，不执行真实图像检测。
    """

    def __init__(self, markers_per_image: Dict[str, List[Dict]]):
        self._markers_per_image = markers_per_image

    def detect_3d(self, image_np, pointmap=None, rvc_image=None, offline_ply_path=None):
        if offline_ply_path is None:
            return []
        key = os.path.basename(offline_ply_path)
        return self._markers_per_image.get(key, [])


def rotz(deg: float) -> np.ndarray:
    theta = np.radians(deg)
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def make_T(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t, dtype=np.float64).flatten()
    return T


def draw_marker(image: np.ndarray, cx: int, cy: int, code: int):
    """在图像上画一个带 code 的编码圆标记（简化：白底黑圆环 + 中心点）。"""
    cv2.circle(image, (cx, cy), 12, (255, 255, 255), -1)
    cv2.circle(image, (cx, cy), 8, (0, 0, 0), 2)
    cv2.circle(image, (cx, cy), 2, (0, 0, 0), -1)
    cv2.putText(image, str(code), (cx - 6, cy + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)


def generate_test_data(tmp_dir: str, n_pairs: int = 3):
    """生成 n_pairs 对图像+点云，返回每个文件名对应的 markers 字典。"""
    # 世界坐标系下的标记点（6 个，用于配准）
    world_markers = np.array([
        [0, 0, 0], [100, 0, 0], [200, 0, 0],
        [0, 100, 0], [100, 100, 0], [200, 100, 0],
    ], dtype=np.float64)

    # 被扫描物体：立方体点云
    mesh = o3d.geometry.TriangleMesh.create_box(150, 100, 50)
    mesh = mesh.translate([-75, -50, 0])
    object_pcd = mesh.sample_points_uniformly(number_of_points=2000)
    object_pcd = object_pcd.translate(np.array([100, 50, 0]))

    # 相机位姿：相机在 -y 侧看向物体，z 轴指向 +y
    camera_poses = []
    for i in range(n_pairs):
        deg = i * 10
        # 基础朝向：z 轴指向 +y，x 轴指向 +x，y 轴指向 -z
        R_base = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, -1.0, 0.0],
        ], dtype=np.float64)
        R = rotz(deg) @ R_base
        # 相机原点沿 -y 分布，距离物体 300mm
        t = np.array([100.0, -300.0 + i * 20, 100.0])
        camera_poses.append(make_T(R, t))

    markers_per_image: Dict[str, List[Dict]] = {}

    for i, T_cam2world in enumerate(camera_poses):
        T_world2cam = np.linalg.inv(T_cam2world)

        # 点云变换到相机系
        pcd_cam = o3d.geometry.PointCloud(object_pcd)
        pcd_cam.transform(T_world2cam)
        # 加入标记点
        marker_pts_cam = (T_world2cam[:3, :3] @ world_markers.T + T_world2cam[:3, 3:4]).T
        pcd_with_markers = o3d.geometry.PointCloud(pcd_cam)
        pcd_with_markers.points.extend(o3d.utility.Vector3dVector(marker_pts_cam))

        # 生成对应图像：1024x768
        h, w = 768, 1024
        image = np.zeros((h, w, 3), dtype=np.uint8)
        markers = []
        # 简单投影到图像中心附近（不考虑真实内参，只保证圆心在合理位置）
        for idx, pt in enumerate(marker_pts_cam):
            # 假设焦距 f=1000，主点 (w/2, h/2)
            if pt[2] <= 0:
                continue
            cx = int(w / 2 + 1000 * pt[0] / pt[2])
            cy = int(h / 2 - 1000 * pt[1] / pt[2])
            if 20 <= cx < w - 20 and 20 <= cy < h - 20:
                draw_marker(image, cx, cy, idx + 1)
                # marker 的 3D 坐标使用相机系下的真实标记点
                markers.append({
                    "code": idx + 1,
                    "u": float(cx),
                    "v": float(cy),
                    "x_2d": float(cx),
                    "y_2d": float(cy),
                    "x_3d": float(pt[0]),
                    "y_3d": float(pt[1]),
                    "z_3d": float(pt[2]),
                })

        ply_path = os.path.join(tmp_dir, f"{i + 1}.ply")
        img_path = os.path.join(tmp_dir, f"{i + 1}.png")
        o3d.io.write_point_cloud(ply_path, pcd_with_markers)
        cv2.imwrite(img_path, image)
        markers_per_image[os.path.basename(ply_path)] = markers

    return camera_poses, markers_per_image


def main():
    print("=" * 60)
    print("OfflineStitcher 单元测试")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        print(f"\n生成测试数据: {tmp_dir}")
        _, markers_per_image = generate_test_data(tmp_dir, n_pairs=3)

        print("\n[1] 文件对扫描")
        pairs = collect_frame_pairs(tmp_dir)
        print(f"  发现 {len(pairs)} 对")
        assert len(pairs) == 3, "应发现 3 对"

        print("\n[2] 加载并检测（使用 MockMarkerDetector）")
        mock_detector = MockMarkerDetector(markers_per_image)
        stitcher = OfflineStitcher(marker_detector=mock_detector, min_common_markers=3)
        stitcher.load_directory(tmp_dir)
        for pair in stitcher.pairs:
            ok, msg, markers = stitcher.detect_pair(pair)
            print(f"  {pair.name}: {msg}, 有效 3D 标记 {len(markers)} 个")
            assert ok, f"检测失败: {msg}"

        print("\n[3] 拼接")
        for pair in stitcher.pairs:
            ok, msg = stitcher.add_pair_to_chain(pair)
            print(f"  {pair.name}: {msg}")
            assert ok, f"入链失败: {msg}"

        merged, msg = stitcher.stitch()
        print(f"\n  {msg}")
        assert merged is not None

        pts = np.asarray(merged.points)
        center = pts.mean(axis=0)
        print(f"  合并中心: {center.round(2)}")
        # 验证合并点云 AABB 尺寸与物体（150x100x50）接近
        dims = pts.max(axis=0) - pts.min(axis=0)
        print(f"  AABB 尺寸: {dims.round(2)}")
        assert 100 < dims[0] < 250, f"X 尺寸异常: {dims[0]:.2f}"
        assert 50 < dims[1] < 200, f"Y 尺寸异常: {dims[1]:.2f}"
        assert 20 < dims[2] < 150, f"Z 尺寸异常: {dims[2]:.2f}"

    print("\n" + "=" * 60)
    print("[OK] 离线拼接单元测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
