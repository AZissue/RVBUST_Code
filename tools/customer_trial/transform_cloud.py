"""Transform a PLY from local coordinates to a reference frame."""
import argparse
import json
from pathlib import Path

import open3d as o3d
from core.point_cloud_processor import PointCloudProcessor
from core.postprocess.fpfh_registration import validate_transform
from core.utils import write_point_cloud_atomic


def transform_cloud(source, transform, output):
    """Apply p_reference = T @ p_local. Coordinates and translation are in mm."""
    matrix = validate_transform(transform)
    output = Path(output)
    if output.suffix.lower() != '.ply':
        raise ValueError('输出文件扩展名必须为 .ply')
    if output.exists():
        raise FileExistsError(output)
    cloud = o3d.io.read_point_cloud(str(source))
    # Filter placeholders before translating them into the reference frame.
    cloud, _ = PointCloudProcessor._filter_valid(cloud)
    if not len(cloud.points):
        raise ValueError('输入 PLY 不包含有效点')
    cloud.transform(matrix)
    if not write_point_cloud_atomic(str(output), cloud):
        raise OSError(f'写入失败：{output}')
    return len(cloud.points)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('transform_json', type=Path, help='4×4 JSON 数组，平移单位 mm')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        matrix = json.loads(args.transform_json.read_text(encoding='utf-8-sig'))
        print(transform_cloud(args.source, matrix, args.output))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'转换失败：{exc}\n')
