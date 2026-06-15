"""
标记物检测模块。
整合两个检测来源：
1. HandEyeSDK.dll（通过 ctypes）—— 支持同心圆和标定板检测
2. PyRVC 内置函数 —— 支持同心圆和编码圆检测
"""

import os

import numpy as np
import PyRVC as RVC
from handeye_sdk import detect_concentric_circles_3d, detect_caliboard_3d


class MarkerDetector:
    """标记物检测器（无状态，所有方法为静态方法）"""

    # 标定板默认参数
    DEFAULT_PATTERN_W = 7
    DEFAULT_PATTERN_H = 11
    DEFAULT_CIRCLE_STEP = 15.0  # mm

    @staticmethod
    def detect_concentric(png_path, ply_path):
        """
        从已保存的 PNG+PLY 文件检测同心圆标记。
        使用 HandEyeSDK.dll 的 DetectConcentricCircles3D。
        返回: (points_2d, points_3d)
          points_2d: [(x, y), ...] 像素坐标
          points_3d: [(x, y, z), ...] 或 None（孔洞处）
        """
        if not os.path.exists(png_path) or not os.path.exists(ply_path):
            return [], []
        try:
            return detect_concentric_circles_3d(png_path, ply_path)
        except Exception:
            return [], []

    @staticmethod
    def detect_caliboard(png_path, ply_path, intrinsic, distortion,
                         pattern_w=None, pattern_h=None, circle_step=None):
        """
        从已保存的 PNG+PLY 文件检测非对称黑底白圆标定板。
        使用 HandEyeSDK.dll 的 DetectCaliboard3D。
        返回: (points_2d, points_3d, distance, error)
          points_2d: [x0, y0, x1, y1, ...] 扁平像素坐标列表
          points_3d: [x0, y0, z0, x1, y1, z1, ...] 扁平3D坐标列表
          distance: 实测相邻圆心距离
          error: 误差百分比
        """
        if not os.path.exists(png_path) or not os.path.exists(ply_path):
            return [], [], 0.0, 0.0
        pw = pattern_w or MarkerDetector.DEFAULT_PATTERN_W
        ph = pattern_h or MarkerDetector.DEFAULT_PATTERN_H
        cs = circle_step or MarkerDetector.DEFAULT_CIRCLE_STEP
        try:
            return detect_caliboard_3d(
                png_path, ply_path, intrinsic, distortion, pw, ph, cs
            )
        except Exception:
            return [], [], 0.0, 0.0

    @staticmethod
    def detect_from_rvc(image_obj, point_map_obj):
        """
        从内存中的 RVC Image + PointMap 对象检测同心圆。
        使用 PyRVC 内置的 DetectConcentricCircleMarker3d。
        返回: (marker_count, points_2d_list, points_3d_list)
        """
        ret, num, pts2d, pts3d = RVC.DetectConcentricCircleMarker3d(
            image_obj, point_map_obj
        )
        if ret != 0:
            return 0, [], []

        pts2d_list = [(pts2d[i * 2], pts2d[i * 2 + 1]) for i in range(num)]
        pts3d_list = [
            (pts3d[i * 3], pts3d[i * 3 + 1], pts3d[i * 3 + 2]) for i in range(num)
        ]
        return num, pts2d_list, pts3d_list

    @staticmethod
    def detect_coded_circles(np_image, n=15, r1_ratio=4.0 / 1.5, r2_ratio=6.0 / 1.5):
        """
        在 numpy 图像中检测编码圆标记。
        返回: [(x, y, code), ...] 每个编码圆的像素坐标和 ID
        """
        marker_type = RVC.CodedCircleMarkerType()
        marker_type.N = n
        marker_type.r1_to_r0_ratio = r1_ratio
        marker_type.r2_to_r0_ratio = r2_ratio
        markers = RVC.DetectCodedCircleMarker(np_image, marker_type)
        return [(m.x, m.y, m.code) for m in markers]

    @staticmethod
    def format_xyz_for_card(points_3d):
        """
        将检测到的 3D 点格式化为输入卡片需要的文本。
        取第一个有效点，格式为 "x y z"（空格分隔，保留 3 位小数）。
        """
        valid = [p for p in points_3d if p is not None
                 and not (isinstance(p, float) and np.isnan(p))]
        if not valid:
            return ""
        p = valid[0]
        if isinstance(p, (list, tuple)):
            return f"{p[0]:.3f} {p[1]:.3f} {p[2]:.3f}"
        return ""

    @staticmethod
    def format_markers_for_overlay(points_2d, points_3d):
        """
        将检测结果格式化为 2D 覆盖层和 3D 高亮所需的数据。
        兼容两种输入格式：
          - 成对列表: [(x,y), ...] / [(x,y,z), ...]
          - 扁平列表: [x0, y0, x1, y1, ...] / [x0, y0, z0, ...]
        返回: (overlay_2d, highlight_3d)
        """
        overlay = []
        highlights = []

        # 将 points_2d 规范化为 [(x,y), ...]
        if points_2d and not isinstance(points_2d[0], (list, tuple)):
            pts2 = [(points_2d[i], points_2d[i + 1]) for i in range(0, len(points_2d), 2)]
        else:
            pts2 = list(points_2d)

        # 将 points_3d 规范化为 [(x,y,z), ...]
        if points_3d and not isinstance(points_3d[0], (list, tuple)):
            pts3 = [(points_3d[i], points_3d[i + 1], points_3d[i + 2])
                    for i in range(0, len(points_3d), 3)]
        else:
            pts3 = list(points_3d)

        for i, p2 in enumerate(pts2):
            overlay.append((float(p2[0]), float(p2[1]), str(i)))
            if i < len(pts3) and pts3[i] is not None:
                p3 = pts3[i]
                if not any(np.isnan(float(v)) for v in p3[:3]):
                    highlights.append((float(p3[0]), float(p3[1]), float(p3[2])))

        return overlay, highlights
