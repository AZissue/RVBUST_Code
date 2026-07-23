# -*- coding: utf-8 -*-
"""
帧数据封装（FrameData）。

从 DualCameraFusion/src/app.py:310-437 原样抽取，仅做两处适配：
  1. PyRVC 不在模块顶层 import（改为函数内延迟导入 + TYPE_CHECKING 类型标注），
     便于无 SDK 环境做离线开发与测试；
  2. camera_name 含义泛化为 camera_id（任意字符串，不再限定 "A"/"B"）。

FrameData 是单帧捕获数据 dataclass，支持：
  - 在线模式：持有 RVC PointMap / Image 对象；
  - 离线模式：持有图像 / PLY 文件路径；
  - save/load：帧数据落盘与恢复。
"""

from __future__ import annotations

import os
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING

import numpy as np
import cv2

from .utils import logger, safe_destroy

if TYPE_CHECKING:
    import PyRVC as RVC
    import open3d as o3d


def _import_rvc():
    """延迟导入 PyRVC；无 SDK 环境返回 None。"""
    try:
        import PyRVC as RVC
        return RVC
    except ImportError:
        return None


@dataclass
class FrameData:
    """单帧捕获数据。支持在线（RVC对象）和离线（文件路径）模式。"""
    frame_id: int
    camera_name: str           # 相机 ID（任意字符串，如 "cam0" / "A"）
    image_np: Optional[np.ndarray] = None
    pointmap: Optional['RVC.PointMap'] = None
    rvc_image: Optional['RVC.Image'] = None
    markers: List[Dict] = field(default_factory=list)
    # 标定板模式缓存（位姿法外参标定用）
    board_pose: Optional[np.ndarray] = None        # 4×4 位姿 T_board_in_cam，单位 mm
    board_pattern: Optional[Tuple[int, int]] = None  # (cols, rows)
    board_pattern_name: Optional[str] = None       # 如 '4x11'
    # 离线模式字段
    is_offline: bool = False
    offline_dir: Optional[str] = None  # 离线数据文件夹路径
    offline_image_path: Optional[str] = None
    offline_pointmap_path: Optional[str] = None

    @property
    def marker_count(self) -> int:
        return len(self.markers)

    @property
    def has_pointcloud(self) -> bool:
        if self.is_offline:
            return self.offline_pointmap_path is not None and os.path.exists(self.offline_pointmap_path)
        return self.pointmap is not None and self.rvc_image is not None

    def release(self):
        """释放 RVC 资源（在线模式）。无 SDK 环境下静默跳过。"""
        RVC = _import_rvc()
        if RVC is not None:
            safe_destroy(self.pointmap, RVC.PointMap.Destroy, "PointMap")
            safe_destroy(self.rvc_image, RVC.Image.Destroy, "Image")
        self.pointmap = None
        self.rvc_image = None
        self.image_np = None
        self.markers = []

    def save(self, base_dir: str, frame_dir: Optional[str] = None) -> str:
        """保存帧数据到磁盘。返回保存的文件夹路径。

        两种目录模式：
          - frame_dir=None（默认，独立目录模式）：
              在 base_dir 下建 frame_{id:04d}_{camera}/ 目录，
              文件名 image.png / pointmap.ply / meta.json（向后兼容）；
          - frame_dir 显式给定（共享目录模式，离线会话多相机同帧用）：
              文件名 {camera}.png / {camera}.ply，
              meta.json 按相机合并写入（{"frame_id": N, "cameras": {cam: {...}}}）。
        """
        RVC = _import_rvc()
        shared = frame_dir is not None
        if frame_dir is None:
            frame_dir = os.path.join(base_dir, f"frame_{self.frame_id:04d}_{self.camera_name}")
        os.makedirs(frame_dir, exist_ok=True)

        img_name = f"{self.camera_name}.png" if shared else "image.png"
        ply_name = f"{self.camera_name}.ply" if shared else "pointmap.ply"

        # 保存图像
        if self.image_np is not None:
            img_path = os.path.join(frame_dir, img_name)
            cv2.imwrite(img_path, self.image_np)
            self.offline_image_path = img_path

        # 保存点云（在线：SaveWithImage；已是离线帧：复制已有 PLY）
        pcd_path = os.path.join(frame_dir, ply_name)
        if self.pointmap is not None and self.rvc_image is not None and RVC is not None:
            ret = self.pointmap.SaveWithImage(pcd_path, self.rvc_image, RVC.PointMapUnitEnum.Millimeter, True)
            if ret:
                self.offline_pointmap_path = pcd_path
        elif self.offline_pointmap_path and os.path.exists(self.offline_pointmap_path):
            if os.path.abspath(self.offline_pointmap_path) != os.path.abspath(pcd_path):
                shutil.copy2(self.offline_pointmap_path, pcd_path)
            self.offline_pointmap_path = pcd_path

        # 保存元数据
        entry = {
            "frame_id": self.frame_id,
            "camera_name": self.camera_name,
            "has_image": self.image_np is not None or self.offline_image_path is not None,
            "has_pointcloud": self.has_pointcloud,
            "markers": self.markers,
            "board_pose": self.board_pose.tolist() if self.board_pose is not None else None,
            "board_pattern": list(self.board_pattern) if self.board_pattern is not None else None,
            "board_pattern_name": self.board_pattern_name,
        }
        meta_path = os.path.join(frame_dir, "meta.json")
        if shared:
            # 共享目录：按相机合并写入同一份 meta.json
            meta = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                except Exception:
                    meta = {}
            meta["frame_id"] = self.frame_id
            meta.setdefault("cameras", {})[self.camera_name] = entry
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        else:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)

        self.is_offline = True
        self.offline_dir = frame_dir
        return frame_dir

    @classmethod
    def load(cls, frame_dir: str) -> 'FrameData':
        """从磁盘加载帧数据。"""
        meta_path = os.path.join(frame_dir, "meta.json")
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f"找不到元数据文件: {meta_path}")

        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        bp_list = meta.get("board_pose")
        bp_tuple = meta.get("board_pattern")
        frame = cls(
            frame_id=meta["frame_id"],
            camera_name=meta["camera_name"],
            is_offline=True,
            offline_dir=frame_dir,
            markers=meta.get("markers", []),
            board_pose=np.asarray(bp_list, dtype=np.float64) if bp_list is not None else None,
            board_pattern=tuple(bp_tuple) if bp_tuple is not None else None,
            board_pattern_name=meta.get("board_pattern_name"),
        )

        # 加载图像
        img_path = os.path.join(frame_dir, "image.png")
        if os.path.exists(img_path):
            frame.image_np = cv2.imread(img_path)
            frame.offline_image_path = img_path

        # 加载点云路径
        pcd_path = os.path.join(frame_dir, "pointmap.ply")
        if os.path.exists(pcd_path):
            frame.offline_pointmap_path = pcd_path

        return frame

    def load_pointcloud_o3d(self) -> Optional['o3d.geometry.PointCloud']:
        """加载点云为 Open3D 格式。"""
        RVC = _import_rvc()
        if self.offline_pointmap_path and os.path.exists(self.offline_pointmap_path):
            import open3d as o3d
            return o3d.io.read_point_cloud(self.offline_pointmap_path)
        if self.pointmap is not None and self.rvc_image is not None and RVC is not None:
            fd, tmp = tempfile.mkstemp(suffix=".ply")
            os.close(fd)
            try:
                ret = self.pointmap.SaveWithImage(tmp, self.rvc_image, RVC.PointMapUnitEnum.Millimeter, True)
                if ret:
                    import open3d as o3d
                    return o3d.io.read_point_cloud(tmp)
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
        return None

    def get_image_for_detection(self) -> Optional[np.ndarray]:
        """获取用于检测的图像（numpy 格式）。"""
        return self.image_np

    def get_pointmap_for_detection(self) -> Optional[np.ndarray]:
        """获取用于检测的3D点云数组（从 PLY 读取）。"""
        if self.offline_pointmap_path and os.path.exists(self.offline_pointmap_path):
            import open3d as o3d
            pcd = o3d.io.read_point_cloud(self.offline_pointmap_path)
            return np.asarray(pcd.points)
        return None
