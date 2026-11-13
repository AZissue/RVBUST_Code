# -*- coding: utf-8 -*-
"""测试 E:/jingz/Desktop/凳子拼接/ 数据的编码圆标记物识别（离线模式）。"""
import sys
import numpy as np
import cv2

sys.path.insert(0, "D:/RVC_SRC/Python/MultiCameraCalibration")

from src.core.marker_detector import MarkerDetector, MARKER_TYPE_CODED_CIRCLE

DATA_DIR = r"E:/jingz/Desktop/凳子拼接"

# 中文路径不能用 cv2.imread
data = np.fromfile(f"{DATA_DIR}/Image.png", dtype=np.uint8)
image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
print(f"图像: {image.shape}, dtype={image.dtype}, min={image.min()}, max={image.max()}")

detector = MarkerDetector(marker_type=MARKER_TYPE_CODED_CIRCLE)
markers = detector.detect_3d(
    image,
    offline_ply_path=f"{DATA_DIR}/PointCloud.ply",
    include_invalid=True,
)

print(f"\n共检出 {len(markers)} 个编码圆：")
for m in markers:
    if m.get("valid_3d"):
        print(f"  code={m['code']:3d}  2D=({m['x_2d']:.1f},{m['y_2d']:.1f})  "
              f"3D=({m['x_3d']:.1f}, {m['y_3d']:.1f}, {m['z_3d']:.1f})")
    else:
        print(f"  code={m['code']:3d}  2D=({m['x_2d']:.1f},{m['y_2d']:.1f})  3D=无效")
