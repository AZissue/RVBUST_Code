"""Recognize 3D markers in an image and its pixel-aligned organized PLY."""
import argparse
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d
from core.marker_detector import MarkerDetector, SUPPORTED_MARKER_TYPES
from core.utils import write_json_atomic


def recognize(image_path, ply_path, marker_type, circle_params=(8, 2., 3.)):
    """Return marker IDs, image coordinates and valid camera-frame XYZ in mm."""
    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('无法读取图像')
    cloud = o3d.io.read_point_cloud(str(ply_path))
    height, width = image.shape[:2]
    if len(cloud.points) != height * width:
        raise ValueError('PLY 必须按行优先顺序与图像逐像素对应')
    if marker_type not in SUPPORTED_MARKER_TYPES:
        raise ValueError(f'未知标记物类型：{marker_type}')
    detector = MarkerDetector(marker_type)
    detector.save_debug_images = False
    detector.raise_errors = True
    if marker_type == 'coded_circle':
        detector.set_params(*circle_params)
    markers = detector.detect_3d(image, offline_ply_path=str(ply_path), include_invalid=True)
    return dict(marker_type=marker_type, unit='mm', image_size=[width, height],
                valid_3d=sum(bool(m.get('valid_3d', True)) for m in markers), markers=markers)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('ply', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--type', choices=SUPPORTED_MARKER_TYPES, default='asymmetric_grid')
    parser.add_argument('--bits', type=int, default=8)
    parser.add_argument('--r1', type=float, default=2.)
    parser.add_argument('--r2', type=float, default=3.)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError(args.output)
        report = recognize(args.image, args.ply, args.type, (args.bits, args.r1, args.r2))
        write_json_atomic(str(args.output), report, ensure_ascii=False, indent=2)
        print(f"有效三维标记：{report['valid_3d']}")
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'识别失败：{exc}\n')
