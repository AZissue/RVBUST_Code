"""Portable, lossless stool fixtures shared by production and prototype UIs.

Archives retain the organized PLY byte-for-byte (including invalid pixels).
Only the render cloud excludes non-finite/zero placeholders; no valid points
are sampled or modified. Runtime files live outside the immutable fixture.
"""
from pathlib import Path
import hashlib
import json
import zipfile

import cv2
import numpy as np

from .frame_data import FrameData


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'offline_test_data' / 'stool'


def digest(path):
    with Path(path).open('rb') as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
        return value.hexdigest()


def load_stool(root=None):
    """Return [(FrameData, full valid Open3D cloud), ...], without SDK calls."""
    root = Path(root or DEFAULT_ROOT)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['units'] != 'mm' or len(manifest['frames']) < 2:
        raise ValueError('离线数据需要至少两帧且单位必须为 mm')
    cache = root / '.cache'
    cache.mkdir(exist_ok=True)
    result = []
    for entry in manifest['frames']:
        stem = str(int(entry['id']))
        with zipfile.ZipFile(root / entry['archive']) as archive:
            for suffix in ('ply', 'png'):
                name = f'{stem}.{suffix}'
                path = cache / name
                expected = entry['sha256'][suffix]
                if not path.exists() or digest(path) != expected:
                    # Never use extractall: archive members cannot escape cache.
                    temporary = path.with_suffix(path.suffix + '.tmp')
                    with archive.open(name) as source, temporary.open('wb') as target:
                        import shutil
                        shutil.copyfileobj(source, target)
                    if digest(temporary) != expected:
                        temporary.unlink()
                        raise ValueError(f'离线数据校验失败: {name}')
                    temporary.replace(path)
        image = cv2.imdecode(np.fromfile(cache / f'{stem}.png', dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'无法读取离线图像: {stem}')
        markers = entry['markers']
        frame = FrameData(int(stem), f'cam{len(result)}', image_np=image,
                          markers=[m for m in markers if m.get('valid_3d', True)],
                          markers_all=markers, is_offline=True, kind='calib',
                          offline_dir=str(cache), offline_image_path=str(cache / f'{stem}.png'),
                          offline_pointmap_path=str(cache / f'{stem}.ply'))
        cloud = frame.load_pointcloud_o3d()
        if cloud is None or not len(cloud.points):
            raise ValueError(f'离线点云为空: {stem}')
        xyz = np.asarray(cloud.points)
        keep = np.flatnonzero(np.isfinite(xyz).all(axis=1) & (np.linalg.norm(xyz, axis=1) > 1e-5))
        cloud = cloud.select_by_index(keep)
        result.append((frame, cloud))
    return result
