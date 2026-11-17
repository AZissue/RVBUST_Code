"""Load aligned MCC frames and register their selected regions in millimetres."""
from dataclasses import dataclass
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS = ROOT / 'outputs' / 'experiments' / 'superpoint_lightglue'


@dataclass
class AlignedFrame:
    image: np.ndarray
    grid: np.ndarray
    colors: np.ndarray | None
    name: str
    token: tuple


@dataclass
class Analysis:
    pixels: tuple
    valid: np.ndarray
    inliers: np.ndarray
    errors: np.ndarray
    pose: np.ndarray | None
    reason: str = ''
    xyz: tuple = ()


def frame_image(directory, record):
    if record.kind != 'raw' or record.pointcloud_aligned is False:
        raise ValueError('请选择保存了图像与像素对齐点图的原始帧。')
    path = Path(directory) / 'frames' / record.uid / 'image.png'
    image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'无法解码图像 {record.logical_name}')
    return image


def read_frame(directory, record):
    import open3d as o3d

    image = frame_image(directory, record)
    height, width = image.shape[:2]
    path = Path(directory) / 'frames' / record.uid / 'pointmap.ply'
    cloud = o3d.io.read_point_cloud(str(path), remove_nan_points=False, remove_infinite_points=False)
    points = np.asarray(cloud.points)
    if len(points) != height * width:
        raise ValueError(f'{record.logical_name} 的点图数量 {len(points)} 与图像尺寸 {width}×{height} 不符。')
    return AlignedFrame(image, points.reshape(height, width, 3),
                        np.asarray(cloud.colors).reshape(height, width, 3) if cloud.has_colors() else None,
                        record.logical_name, (record.uid, record.revision))


def lift_pixels(grid, pixels, depth_jump):
    """Interpolate XYZ only on a valid, locally continuous 4×4 neighbourhood."""
    pixels = np.asarray(pixels, dtype=float).reshape(-1, 2)
    xyz = np.full((len(pixels), 3), np.nan)
    valid = np.zeros(len(pixels), dtype=bool)
    height, width = grid.shape[:2]
    for index, (u, v) in enumerate(pixels):
        if not (1 <= u < width - 2 and 1 <= v < height - 2):
            continue
        x, y = int(u), int(v)
        patch = grid[y-1:y+3, x-1:x+3]
        z = patch[..., 2]
        if not np.isfinite(patch).all() or np.any(np.all(patch == 0, axis=-1)) or np.ptp(z) > depth_jump:
            continue
        bottom = grid[y+1, x] * (1-u+x) + grid[y+1, x+1] * (u-x)
        top = grid[y, x] * (1-u+x) + grid[y, x+1] * (u-x)
        xyz[index] = top * (1-v+y) + bottom * (v-y)
        valid[index] = True
    return xyz, valid


def estimate_pose(moving, reference, threshold):
    # The project solver requires at least 60% consensus and non-collinear support.
    if len(moving) < 6:
        raise ValueError('连续深度对应不足 6 对。')
    from core.turntable_calibrator import robust_rigid_transform

    try:
        rotation, translation, _, errors = robust_rigid_transform(moving, reference, threshold)
    except ValueError as exc:
        raise ValueError('3D 对应点未形成足够的非共线刚体共识。') from exc
    mask = errors <= threshold
    if mask.sum() < max(6, np.ceil(.6 * len(moving))):
        raise ValueError('3D 刚体内点不足。')
    # Reject near-collinear or very concentrated support relative to the residual threshold.
    for points in (moving[mask], reference[mask]):
        spread = np.linalg.svd(points - points.mean(axis=0), compute_uv=False) / np.sqrt(len(points))
        if spread[1] < threshold:
            raise ValueError('3D 内点分布过窄，无法稳定确定姿态。')
    pose = np.eye(4)
    pose[:3, :3] = rotation
    pose[:3, 3] = translation
    return pose, mask, errors


class PretrainedMatcher:
    def __init__(self, directory=DEFAULT_MODELS):
        self.directory = Path(directory).resolve()
        self.models = None

    def _load(self):
        if self.models is None:
            root = self.directory
            weights = root / 'weights' / 'hub' / 'checkpoints'
            files = ('superpoint_v1.pth', 'superpoint_lightglue_v0-1_arxiv.pth')
            if not (root / 'upstream' / 'lightglue').is_dir() or not all((weights / name).is_file() for name in files):
                raise ValueError(f'模型文件不完整。请按原型 README 准备预训练文件。目录 {root}')
            sys.path[:0] = [str(root / 'upstream'), str(root / 'deps')]
            import torch
            from lightglue import LightGlue, SuperPoint

            torch.set_num_threads(min(torch.get_num_threads(), 4))
            cache = torch.hub.get_dir()
            try:
                torch.hub.set_dir(str(weights.parent))
                extractor = SuperPoint(max_num_keypoints=2048).cpu().eval()
                matcher = LightGlue(features='superpoint').cpu().eval()
            finally:
                torch.hub.set_dir(cache)
            self.models = torch, extractor, matcher
        return self.models

    def match(self, images, boxes):
        torch, extractor, matcher = self._load()
        with torch.inference_mode():
            features = []
            for image, (x0, y0, x1, y1) in zip(images, boxes):
                crop = image[y0:y1, x0:x1]
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                tensor = torch.from_numpy(gray).float()[None] / 255
                features.append(extractor.extract(tensor, resize=min(1024, max(gray.shape))))
            result = matcher({'image0': features[0], 'image1': features[1]})
            pairs = result['matches'][0].numpy()
            return tuple(feature['keypoints'][0].numpy()[pairs[:, side]] + box[:2]
                         for side, (feature, box) in enumerate(zip(features, boxes)))


def analyze_pair(frames, boxes, matcher, threshold, depth_jump):
    pixels = matcher.match([frame.image for frame in frames], boxes)
    (reference, valid_a), (moving, valid_b) = [
        lift_pixels(frame.grid, coordinates, depth_jump) for frame, coordinates in zip(frames, pixels)]
    valid = valid_a & valid_b
    result = Analysis(pixels, valid, np.zeros(len(valid), dtype=bool), np.full(len(valid), np.nan), None,
                      xyz=(reference, moving))
    try:
        result.pose, mask, errors = estimate_pose(moving[valid], reference[valid], threshold)
        result.inliers[valid] = mask
        result.errors[valid] = errors
    except ValueError as exc:
        result.reason = str(exc)
    return result


def merge_pair(frames, boxes, pose):
    from core.postprocess.session import CloudLayer

    if (frames[0].colors is None) != (frames[1].colors is None):
        raise ValueError('两帧的颜色属性不一致。')
    clouds, colors = [], []
    for frame, (x0, y0, x1, y1), transform in zip(frames, boxes, (np.eye(4), pose)):
        points = frame.grid[y0:y1, x0:x1].reshape(-1, 3)
        valid = np.isfinite(points).all(axis=1) & np.any(points != 0, axis=1)
        if not valid.any():
            raise ValueError(f'{frame.name} 选区没有有效点云。')
        clouds.append(points[valid] @ transform[:3, :3].T + transform[:3, 3])
        if frame.colors is not None:
            colors.append(frame.colors[y0:y1, x0:x1].reshape(-1, 3)[valid])
    return CloudLayer(f'{frames[0].name} + {frames[1].name} · SuperPoint + LightGlue',
                      np.vstack(clouds), np.vstack(colors) if colors else None,
                      source='SuperPoint + LightGlue', origins=tuple(frame.token for frame in frames),
                      registration_transform=pose.tolist(),
                      parent_transforms={frames[0].token[0]: np.eye(4).tolist(),
                                         frames[1].token[0]: pose.tolist()})
