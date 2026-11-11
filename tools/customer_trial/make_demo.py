"""Generate reproducible millimetre data for the three stitching examples."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d


def generate(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(17)
    points = rng.normal(size=(1000, 3)) * [35, 19, 11] + [100, 100, 100]
    marker_xyz = points[:12]
    frames = []
    pairs = {}
    for index in range(3):
        name = f'cam{index}'
        translation = index * np.array([15., -9., 6.])
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points - translation))
        cloud.colors = o3d.utility.Vector3dVector(np.tile([.3, .6, .9], (len(points), 1)))
        filename = name + '.ply'
        if not o3d.io.write_point_cloud(str(root / filename), cloud):
            raise OSError(f'点云写入失败：{filename}')
        markers = [dict(code=i, x_3d=x, y_3d=y, z_3d=z, valid_3d=True)
                   for i, (x, y, z) in enumerate(marker_xyz - translation)]
        frames.append(dict(id=name, ply=filename, markers=markers))
        if index:
            pose = np.eye(4)
            pose[:3, 3] = translation
            pairs[f'cam0|{name}'] = {'T': pose.tolist()}
    payload = dict(unit='mm', frames=frames, calibration=dict(reference_id='cam0', pairs=pairs),
                   fpfh=dict(voxel_mm=3., normal_radius_mm=8., feature_radius_mm=20.,
                             min_consensus=20, min_fscore=.85, icp=True))
    (root / 'cam1_to_cam0.json').write_text(
        json.dumps(pairs['cam0|cam1']['T'], indent=2), encoding='utf-8')
    make_board_pair(root)
    manifest = root / 'input.json'
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def make_board_pair(root):
    """Render a 7×11 circle grid with a synthetic, pixel-aligned depth plane."""
    image = np.zeros((200, 240), dtype=np.uint8)
    for row in range(11):
        for col in range(7):
            cv2.circle(image, (50 + (2 * col + row % 2) * 8, 45 + row * 8), 3, 255, -1)
    y, x = np.indices(image.shape)
    points = np.column_stack((x.ravel() * .5, y.ravel() * .5, np.full(x.size, 500.)))
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    ok, png = cv2.imencode('.png', image)
    if not ok:
        raise OSError('示例标定板图像编码失败')
    (root / 'board.png').write_bytes(png.tobytes())
    if not o3d.io.write_point_cloud(str(root / 'board.ply'), cloud):
        raise OSError('示例标定板点云写入失败')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(generate(parser.parse_args().directory))
