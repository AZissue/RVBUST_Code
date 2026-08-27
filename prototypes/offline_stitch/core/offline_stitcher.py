# -*- coding: utf-8 -*-
"""
离线拼接核心（OfflineStitcher）。

功能：
  - 扫描指定目录，按文件名前缀匹配 2D 图像 (.png/.jpg/.jpeg/.bmp) 和点云 (.ply)；
  - 加载文件对，用项目现有 MarkerDetector 自动识别编码圆；
  - 把 2D 圆心映射到 3D 点云，构建 FrameData；
  - 用 ChainStitcher 做相邻帧配准/拼接；
  - 保存合并点云。

不生成额外 JSON 配置文件；所有元数据在内存中流转。
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
import open3d as o3d
import cv2

# 依赖项目 src 下的 core 模块；调用方需确保 src 在 sys.path 中
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine
from core.chain_stitcher import ChainStitcher
from core.frame_data import FrameData
from core.point_cloud_processor import PointCloudProcessor


class FramePair:
    """一对离线文件：图像 + 点云。"""

    def __init__(self, name: str, image_path: str, ply_path: str):
        self.name = name
        self.image_path = image_path
        self.ply_path = ply_path
        self.frame: Optional[FrameData] = None
        self.markers: List[Dict] = []
        self.error: str = ""

    @property
    def has_data(self) -> bool:
        return os.path.exists(self.image_path) and os.path.exists(self.ply_path)


def _normalize_name(name: str) -> str:
    """去掉常见后缀，便于 2D/3D 文件前缀匹配。"""
    # 常见成对后缀：xxx_color / xxx_depth / xxx_img / xxx_pcd 等
    suffixes = ("_color", "_rgb", "_img", "_image", "_2d",
                "_depth", "_dep", "_pcd", "_ply", "_points",
                "_cloud", "_3d", "_c", "_d")
    lower = name.lower()
    for suffix in suffixes:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


def collect_frame_pairs(directory: str, recursive: bool = True) -> List[FramePair]:
    """按文件名前缀匹配目录下的图像和点云文件。

    支持：
      - 递归子目录；
      - 精确前缀匹配；
      - 去掉 _color/_depth/_img/_pcd 等常见后缀后的模糊匹配。
    """
    if not directory or not os.path.isdir(directory):
        return []

    image_exts = {".png", ".jpg", ".jpeg", ".bmp"}
    ply_exts = {".ply"}

    images: Dict[str, str] = {}
    plys: Dict[str, str] = {}

    if recursive:
        walker = os.walk(directory)
    else:
        walker = [(directory, [], os.listdir(directory))]

    for dirpath, _dirnames, filenames in walker:
        for entry in filenames:
            lower = entry.lower()
            path = os.path.join(dirpath, entry)
            name, ext = os.path.splitext(entry)
            if ext.lower() in image_exts:
                images[name] = path
            elif ext.lower() in ply_exts:
                plys[name] = path

    pairs: List[FramePair] = []
    matched_plys: set = set()

    # 第一轮：精确前缀匹配
    for name in sorted(images.keys()):
        if name in plys:
            pairs.append(FramePair(name, images[name], plys[name]))
            matched_plys.add(name)

    # 第二轮：去掉常见后缀的模糊匹配
    norm_images = {n: _normalize_name(n) for n in images}
    norm_plys = {n: _normalize_name(n) for n in plys}
    for img_name, img_norm in sorted(norm_images.items()):
        if img_name in plys:
            continue  # 已精确匹配
        for ply_name, ply_norm in norm_plys.items():
            if ply_name in matched_plys:
                continue
            if img_norm and img_norm == ply_norm:
                pair_name = f"{img_name}⇄{ply_name}"
                pairs.append(FramePair(pair_name, images[img_name], plys[ply_name]))
                matched_plys.add(ply_name)
                break

    return sorted(pairs, key=lambda p: p.name)


class OfflineStitcher:
    """离线拼接器。"""

    def __init__(self,
                 marker_detector: Optional[MarkerDetector] = None,
                 min_common_markers: int = 3,
                 min_inlier_ratio: float = 0.7,
                 max_rms_mm: float = 2.0):
        self.marker_detector = marker_detector or MarkerDetector()
        self.calibration_engine = CalibrationEngine()
        self.stitch_engine = StitchEngine()
        self.processor = PointCloudProcessor()

        self.chain_stitcher = ChainStitcher(
            marker_detector=self.marker_detector,
            calibration_engine=self.calibration_engine,
            stitch_engine=self.stitch_engine,
            min_common_markers=min_common_markers,
            min_inlier_ratio=min_inlier_ratio,
            max_rms_mm=max_rms_mm,
        )
        self.directory: Optional[str] = None
        self.pairs: List[FramePair] = []
        self.messages: List[str] = []
        self.merged_pcd: Optional[o3d.geometry.PointCloud] = None

    def load_directory(self, directory: str, recursive: bool = True) -> Tuple[int, str]:
        """加载目录并识别文件对。"""
        self.directory = directory
        self.pairs = collect_frame_pairs(directory, recursive=recursive)
        if self.pairs:
            msg = (f"目录 {directory}: 发现 {len(self.pairs)} 对图像/点云 "
                   f"({len([p for p in self.pairs if '⇄' in p.name])} 对为模糊匹配)")
        else:
            msg = f"目录 {directory}: 发现 0 对图像/点云（请检查文件名是否对应）"
        self.messages.append(msg)
        return len(self.pairs), msg

    def set_marker_type(self, marker_type: str):
        """设置标记物类型（'coded_circle' 或 'asymmetric_grid'）。"""
        self.marker_detector.set_marker_type(marker_type)

    def set_coded_circle_params(self, n: int, r1_ratio: float, r2_ratio: float):
        """设置编码圆参数（N / r1/r0 / r2/r0）。"""
        self.marker_detector.set_params(n, r1_ratio, r2_ratio)

    def detect_pair(self, pair: FramePair) -> Tuple[bool, str, List[Dict]]:
        """对单对文件做 2D+3D 检测。

        复用 MarkerDetector.detect_3d 的离线模式：输入 numpy 图像 + PLY 路径，
        返回含 x_2d/y_2d 和 x_3d/y_3d/z_3d 的 markers。
        """
        image = cv2.imread(pair.image_path)
        if image is None:
            return False, f"无法读取图像: {pair.image_path}", []

        markers = self.marker_detector.detect_3d(
            image,
            offline_ply_path=pair.ply_path,
        )
        if not markers:
            return False, "未检测到有效标记物", []

        # 统一字段名：detect_3d 可能返回 x_2d/y_2d，UI 需要 u/v
        for m in markers:
            if "x_2d" in m and "u" not in m:
                m["u"] = m["x_2d"]
            if "y_2d" in m and "v" not in m:
                m["v"] = m["y_2d"]

        if len(markers) < 3:
            return False, f"有效标记物不足: {len(markers)}", markers

        # 构建 FrameData
        frame = FrameData(
            frame_id=0,
            camera_name=pair.name,
            image_np=image,
            pointmap=None,
            rvc_image=None,
            is_offline=True,
            offline_dir=self.directory,
            offline_image_path=pair.image_path,
            offline_pointmap_path=pair.ply_path,
            markers=markers,
        )
        pair.frame = frame
        pair.markers = markers
        return True, f"检测到 {len(markers)} 个有效标记物", markers

    def add_pair_to_chain(self, pair: FramePair) -> Tuple[bool, str]:
        """把已检测的文件对加入拼接链。"""
        if pair.frame is None:
            ok, msg, _ = self.detect_pair(pair)
            if not ok:
                pair.error = msg
                return False, msg
        ok, msg, edge = self.chain_stitcher.add_frame(pair.frame)
        return ok, msg

    def stitch(self) -> Tuple[Optional[o3d.geometry.PointCloud], str]:
        """执行拼接，缓存并返回合并点云和消息。"""
        self.merged_pcd = self.chain_stitcher.get_merged_pointcloud(self.processor)
        if self.merged_pcd is None:
            return None, "无可用点云"
        info = self.chain_stitcher.get_error_report()
        msg = (f"拼接完成: 节点 {info['n_nodes']}, 边 {info['n_edges']}, "
               f"合并点数 {len(self.merged_pcd.points)}")
        self.messages.append(msg)
        return self.merged_pcd, msg

    def save_merged(self, path: str) -> Tuple[bool, str]:
        """保存缓存的合并点云。"""
        if self.merged_pcd is None:
            return False, "无合并点云"
        try:
            o3d.io.write_point_cloud(path, self.merged_pcd)
            return True, f"已保存 {path}"
        except Exception as e:
            return False, f"保存失败: {e}"
