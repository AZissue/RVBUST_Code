"""Standalone offline pairing and stitching workflow."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import open3d as o3d

from core.calibration_engine import CalibrationEngine
from core.chain_stitcher import ChainStitcher
from core.frame_data import FrameData
from core.marker_detector import MarkerDetector
from core.offline_fixture import load_stool as load_stool_fixture
from core.point_cloud_processor import PointCloudProcessor
from core.stitch_engine import StitchEngine
from core.utils import write_point_cloud_atomic

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp'}
SUFFIXES = ('_color', '_rgb', '_img', '_image', '_2d', '_depth', '_dep',
            '_pcd', '_ply', '_points', '_cloud', '_3d', '_c', '_d')


@dataclass
class FramePair:
    name: str
    image_path: str
    ply_path: str
    frame: Optional[FrameData] = None
    markers_all: Optional[list] = None
    error: str = ''


@dataclass
class StitchResult:
    ok: bool
    message: str
    cloud: Optional[o3d.geometry.PointCloud]
    report: dict
    frame_results: dict = field(default_factory=dict)
    input_paths: set = field(default_factory=set)


def _normalized_stem(path):
    lower = path.stem.lower()
    for suffix in SUFFIXES:
        if lower.endswith(suffix):
            return path.stem[:-len(suffix)]
    return path.stem


def collect_frame_pairs(directory, recursive=True):
    root = Path(directory).resolve()
    if not root.is_dir():
        return []
    files = (path for path in root.rglob('*') if path.is_file()) if recursive else (
        path for path in root.iterdir() if path.is_file())
    images, clouds = {}, {}
    for path in files:
        key = (path.parent.relative_to(root), _normalized_stem(path))
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            images.setdefault(key, []).append(path)
        elif suffix == '.ply':
            clouds.setdefault(key, []).append(path)
    pairs = []
    for key in sorted(set(images) & set(clouds), key=lambda item: (str(item[0]), item[1])):
        if len(images[key]) != 1 or len(clouds[key]) != 1:
            raise ValueError(f'文件配对歧义: {key[0]}/{key[1]} 存在多个图像或点云候选')
        image, cloud = images[key][0], clouds[key][0]
        name = key[1] if str(key[0]) == '.' else f'{key[0].as_posix()}/{key[1]}'
        pairs.append(FramePair(name, str(image), str(cloud)))
    return pairs


def load_preview_cloud(pair):
    cloud = o3d.io.read_point_cloud(pair.ply_path)
    if cloud is None or not len(cloud.points):
        raise ValueError(f'点云为空: {pair.ply_path}')
    points = np.asarray(cloud.points)
    valid = np.isfinite(points).all(axis=1) & (np.linalg.norm(points, axis=1) > 1e-5)
    if not valid.any():
        raise ValueError(f'点云没有有效点: {pair.ply_path}')
    return cloud.select_by_index(np.flatnonzero(valid))


def preview_markers(frame):
    if frame is None or frame.image_np is None:
        return []
    height, width = frame.image_np.shape[:2]
    result = []
    for marker in frame.markers_all or frame.markers or []:
        x = marker.get('x_2d', marker.get('u'))
        y = marker.get('y_2d', marker.get('v'))
        if x is None or y is None:
            continue
        result.append({'x': float(x) / width, 'y': float(y) / height,
            'code': marker.get('code', ''), 'valid_3d': marker.get('valid_3d', True)})
    return result


def _path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


class OfflineWorkflow:
    def __init__(self, detector=None):
        self.detector = detector or MarkerDetector()
        self.calibration_engine = CalibrationEngine()
        self.stitch_engine = StitchEngine()
        self.processor = PointCloudProcessor()
        self.last_result: Optional[StitchResult] = None
        self._new_chain()

    def _new_chain(self):
        self.chain = ChainStitcher(self.detector, self.calibration_engine,
            self.stitch_engine, min_common_markers=3, min_inlier_ratio=.7, max_rms_mm=2.)

    def load_directory(self, directory, recursive=True):
        self.last_result = None
        return collect_frame_pairs(directory, recursive)

    def load_stool(self):
        self.last_result = None
        pairs = []
        for frame, _ in load_stool_fixture():
            pairs.append(FramePair(f'凳子视角 {frame.frame_id}',
                frame.offline_image_path, frame.offline_pointmap_path,
                frame=frame, markers_all=frame.markers_all))
        return pairs

    def load_pair(self, pair):
        if pair.frame is not None:
            return pair.frame
        image = cv2.imdecode(np.fromfile(pair.image_path, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'无法读取图像: {pair.image_path}')
        cloud = o3d.io.read_point_cloud(pair.ply_path)
        if cloud is None or not len(cloud.points):
            raise ValueError(f'点云为空或无法读取: {pair.ply_path}')
        height, width = image.shape[:2]
        if len(cloud.points) != width * height:
            raise ValueError(
                f'点云与图像分辨率不一致：需要 row-major 有组织点云，'
                f'{width}×{height}={width * height} 点，实际 {len(cloud.points)} 点')
        markers_all = self.detector.detect_3d(image, offline_ply_path=pair.ply_path,
            include_invalid=True)
        markers = [marker for marker in markers_all if marker.get('valid_3d', True)]
        pair.frame = FrameData(0, pair.name, image_np=image, is_offline=True,
            offline_image_path=pair.image_path, offline_pointmap_path=pair.ply_path,
            markers=markers, markers_all=markers_all)
        pair.markers_all = markers_all
        return pair.frame

    def stitch(self, pairs):
        self.last_result = None
        self._new_chain()
        frame_results = {}
        for pair in pairs:
            try:
                frame = self.load_pair(pair)
                ok, message, _ = self.chain.add_frame(frame, detect_markers=False)
                if not ok:
                    raise ValueError(message)
                pair.error = ''
                frame_results[pair.name] = (True, message)
            except Exception as exc:
                pair.error = str(exc)
                frame_results[pair.name] = (False, pair.error)
        cloud = self.chain.get_merged_pointcloud()
        report = self.chain.get_error_report()
        failed = [name for name, (ok, _) in frame_results.items() if not ok]
        ok = report['n_nodes'] >= 2 and cloud is not None and len(cloud.points) > 0
        message = (f"拼接完成：{report['n_nodes']} 节点 / {report['n_edges']} 边 / "
                   f"{0 if cloud is None else len(cloud.points)} 点")
        if failed:
            message += f'；{len(failed)} 帧未入链：' + '、'.join(failed)
        if not ok:
            message = '拼接结果不可用：至少需要 2 个成功入链的机位；' + message
        input_paths = {_path_key(pair.ply_path) for pair in pairs}
        self.last_result = StitchResult(ok, message, cloud, report, frame_results, input_paths)
        return self.last_result

    def export(self, path):
        if self.last_result is None or not self.last_result.ok:
            raise RuntimeError('拼接结果不可用，无法导出')
        if _path_key(path) in self.last_result.input_paths:
            raise ValueError('导出路径不能覆盖原始输入 PLY')
        if not write_point_cloud_atomic(path, self.last_result.cloud):
            raise IOError(f'点云导出失败: {path}')
        return path
