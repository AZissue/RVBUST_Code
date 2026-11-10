"""Production offline image/organized-PLY pairing. Coordinates are millimetres."""
from dataclasses import dataclass
from pathlib import Path
import re
import cv2
import numpy as np
import open3d as o3d
from .frame_data import FrameData
from .marker_detector import MarkerDetector

@dataclass
class FramePair:
    name: str
    image_path: str
    ply_path: str
    frame: object = None
    markers_all: object = None

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp'}
SUFFIXES = ('_color', '_rgb', '_img', '_image', '_2d', '_depth', '_dep',
            '_pcd', '_ply', '_points', '_cloud', '_3d', '_c', '_d')


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
    for key in sorted(set(images) & set(clouds), key=lambda item: (str(item[0]), tuple(
            (0, int(part)) if part.isdigit() else (1, part.lower())
            for part in re.split(r'(\d+)', item[1])))):
        if len(images[key]) != 1 or len(clouds[key]) != 1:
            raise ValueError(f'文件配对歧义: {key[0]}/{key[1]} 存在多个图像或点云候选')
        image, cloud = images[key][0], clouds[key][0]
        name = key[1] if str(key[0]) == '.' else f'{key[0].as_posix()}/{key[1]}'
        pairs.append(FramePair(name, str(image), str(cloud)))
    return pairs


class OfflinePairLoader:
    def __init__(self, detector=None):
        self.detector = detector or MarkerDetector()

    def load_directory(self, directory, recursive=True):
        return collect_frame_pairs(directory, recursive)

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
