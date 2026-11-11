"""Generate reproducible millimetre data for the three stitching examples."""
import argparse
import json
from pathlib import Path

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
    manifest = root / 'input.json'
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(generate(parser.parse_args().directory))
