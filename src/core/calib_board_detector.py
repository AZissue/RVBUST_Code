# -*- coding: utf-8 -*-
"""
非对称圆标定板检测器（CalibBoardDetector）。

功能：
  - 2D 图像检测非对称圆标定板（OpenCV findCirclesGrid + SimpleBlobDetector）；
  - 自动尝试多种规格（4×11 / 7×11 / 4×5）；
  - 从 PLY/PointMap 双线性插值提取圆心 3D 坐标；
  - SVD 求解标定板在相机坐标系下的 4×4 位姿 T_board_in_cam；
  - 输出统一的 marker 结构，供 UI 显示与 CalibrationEngine 复用。

单位约定：
  - 图像坐标：像素；
  - 3D 坐标 / 圆心间距 / 位姿平移：毫米（mm），与 MultiCameraCalibration 现有 markers 保持一致。
"""

from __future__ import annotations

import os
import tempfile
from typing import Dict, List, Optional, Tuple

import numpy as np
import cv2

from .utils import logger

try:
    import PyRVC as RVC
except ImportError:
    RVC = None


# 默认支持的标定板规格。
# 名称按“行×列”习惯书写；内部 cols/rows 对应 OpenCV findCirclesGrid 的 patternSize=(cols, rows)。
# spacing_mm 为相邻圆心名义距离（用户可按实际标定板修改）。
DEFAULT_BOARD_SPECS: List[Dict] = [
    {"name": "4x11", "cols": 11, "rows": 4, "spacing_mm": 40.0},
    {"name": "7x11", "cols": 11, "rows": 7, "spacing_mm": 30.0},
    {"name": "4x5",  "cols": 5,  "rows": 4, "spacing_mm": 40.0},
]


class CalibBoardDetector:
    """非对称圆标定板检测器。"""

    def __init__(self, board_specs: Optional[List[Dict]] = None, gamma: float = 2.5):
        """
        Args:
            board_specs: 标定板规格列表，每个元素包含 name, cols, rows, spacing_mm。
                         为 None 时使用 DEFAULT_BOARD_SPECS。
            gamma: Gamma 校正系数，用于提升低对比度图像的检测成功率。
        """
        self.board_specs = list(board_specs) if board_specs is not None else list(DEFAULT_BOARD_SPECS)
        self.gamma = gamma
        self._blob_detector = self._create_blob_detector()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def detect(self,
               image_np: np.ndarray,
               pointmap: 'RVC.PointMap' = None,
               rvc_image: 'RVC.Image' = None,
               offline_ply_path: Optional[str] = None) -> Dict:
        """检测标定板并求解位姿。

        Args:
            image_np: 输入图像（uint8 BGR 或 灰度）。
            pointmap: RVC PointMap（在线模式）。
            rvc_image: RVC Image（在线模式，用于 SaveWithImage 对齐）。
            offline_ply_path: 离线 PLY 路径（离线模式）。

        Returns:
            {
                'success': bool,
                'message': str,
                'markers': List[Dict],          # 圆心 marker 列表
                'T_board_in_cam': np.ndarray,   # 4×4 位姿（标定板在相机坐标系下）
                'pattern_name': str,            # 如 '4x11'
                'pattern_size': (cols, rows),
                'spacing_mm': float,
                'rms_mm': float,                # 圆心重投影误差 RMS
            }
        """
        if image_np is None:
            return self._fail("图像为 None")

        # 1. 2D 检测（自动尝试多种规格 + 多种 gamma，提升不同曝光/对比度下的鲁棒性）
        gray = self._to_gray(image_np)
        det = self._detect_pattern_robust(gray)
        if det is None:
            return self._fail("未能检测到任何支持规格的非对称圆标定板")

        centers_2d, spec = det
        n_circles = len(centers_2d)
        logger.info(f"标定板检测成功: {spec['name']} ({n_circles} 个圆心)")

        # 2. 获取 PLY 点云
        ply_path, tmp_path = self._get_ply_path(pointmap, rvc_image, offline_ply_path)
        if ply_path is None:
            return self._fail("未提供有效点云数据")

        try:
            points_3d = self._read_ply_points(ply_path)
        except Exception as e:
            return self._fail(f"读取 PLY 失败: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        if points_3d is None or len(points_3d) == 0:
            return self._fail("PLY 点云为空")

        # 3. 提取圆心 3D 坐标
        h_img, w_img = gray.shape[:2]
        centers_3d = self._extract_centers_3d(centers_2d, points_3d, (w_img, h_img))

        valid_mask = np.isfinite(centers_3d).all(axis=1)
        if valid_mask.sum() < 3:
            return self._fail(f"有效 3D 圆心不足: {valid_mask.sum()}/3")

        # 4. 求解标定板位姿
        obj_pts = self._build_object_points(spec)
        T_board_in_cam, rms_mm = self._solve_board_pose(obj_pts, centers_3d, spec)
        if T_board_in_cam is None:
            return self._fail("标定板位姿求解失败")

        # 5. 构造 markers（与现有 MarkerDetector 输出兼容）
        markers = []
        for i, (pt2, pt3) in enumerate(zip(centers_2d, centers_3d)):
            markers.append({
                'code': i,                       # OpenCV 返回的顺序索引
                'x': float(pt2[0]),
                'y': float(pt2[1]),
                'x_2d': float(pt2[0]),
                'y_2d': float(pt2[1]),
                'x_3d': float(pt3[0]),
                'y_3d': float(pt3[1]),
                'z_3d': float(pt3[2]),
                'valid_3d': bool(np.isfinite(pt3).all()),
            })

        return {
            'success': True,
            'message': f"检测到 {spec['name']} 标定板，{valid_mask.sum()}/{n_circles} 个有效圆心",
            'markers': markers,
            'T_board_in_cam': T_board_in_cam,
            'pattern_name': spec['name'],
            'pattern_size': (spec['cols'], spec['rows']),
            'spacing_mm': float(spec['spacing_mm']),
            'rms_mm': float(rms_mm),
        }

    def set_board_specs(self, board_specs: List[Dict]):
        """运行时更新支持的标定板规格。"""
        self.board_specs = list(board_specs)

    def set_gamma(self, gamma: float):
        """运行时更新 gamma 校正系数。"""
        self.gamma = gamma

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _fail(message: str) -> Dict:
        logger.warning(f"CalibBoardDetector: {message}")
        return {
            'success': False,
            'message': message,
            'markers': [],
            'T_board_in_cam': None,
            'pattern_name': None,
            'pattern_size': None,
            'spacing_mm': 0.0,
            'rms_mm': 0.0,
        }

    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 3 and image.shape[2] in (3, 4):
            if image.shape[2] == 3:
                return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        return image.copy()

    @staticmethod
    def _adjust_gamma(image: np.ndarray, gamma: float) -> np.ndarray:
        """Gamma 校正。"""
        if gamma <= 0 or abs(gamma - 1.0) < 1e-6:
            return image.copy()
        inv_gamma = 1.0 / gamma
        table = (np.arange(256) / 255.0) ** inv_gamma * 255
        table = table.clip(0, 255).astype(np.uint8)
        return cv2.LUT(image.astype(np.uint8), table)

    @staticmethod
    def _create_blob_detector() -> cv2.SimpleBlobDetector:
        """创建 SimpleBlobDetector，适配非对称圆标定板。"""
        params = cv2.SimpleBlobDetector_Params()
        params.filterByArea = True
        params.filterByCircularity = True
        params.filterByConvexity = False
        params.filterByInertia = False
        params.filterByColor = True
        params.minArea = 50
        params.maxArea = 50000
        params.minCircularity = 0.5
        params.minInertiaRatio = 0.01
        params.minRepeatability = 2
        params.minDistBetweenBlobs = 5
        params.minThreshold = 10
        params.maxThreshold = 250
        params.thresholdStep = 10
        params.blobColor = 255
        return cv2.SimpleBlobDetector_create(params)

    def _detect_pattern_robust(self, gray: np.ndarray,
                               gammas: Tuple[float, ...] = (2.5, 1.0, 1.5, 2.0, 3.0)
                               ) -> Optional[Tuple[np.ndarray, Dict]]:
        """依次尝试多种 gamma 与多种规格，返回第一个成功检测到的 (centers_2d, spec)。

        不同光照 / 曝光下，固定 gamma 可能过强或过弱：
          - gamma=2.5 对正常曝光图像可提升低对比度圆点；
          - gamma=1.0 对已经高对比度的图像更稳定（避免过曝/失真）。
        """
        for gamma in gammas:
            adjusted = self._adjust_gamma(gray, gamma)
            det = self._detect_pattern(adjusted)
            if det is not None:
                logger.info(f"标定板 2D 检测成功: gamma={gamma}, 规格={det[1]['name']}")
                return det
        return None

    def _detect_pattern(self, image: np.ndarray) -> Optional[Tuple[np.ndarray, Dict]]:
        """依次尝试支持的规格，返回第一个成功检测到的 (centers_2d, spec)。

        注意：OpenCV findCirclesGrid 的 patternSize 参数为 (points_per_row, rows)，
        对非对称网格实际成功参数为 (rows, cols)（按本项目的 objp 排列）。
        """
        # 优先尝试大规格（圆心数多），降低局部误识别风险
        specs = sorted(self.board_specs, key=lambda s: s['cols'] * s['rows'], reverse=True)
        for spec in specs:
            rows, cols = spec['rows'], spec['cols']
            found, centers = cv2.findCirclesGrid(
                image,
                (rows, cols),
                flags=cv2.CALIB_CB_ASYMMETRIC_GRID | cv2.CALIB_CB_CLUSTERING | cv2.CALIB_CB_FAST_CHECK,
                blobDetector=self._blob_detector,
            )
            if found and centers is not None and len(centers) == cols * rows:
                centers = centers.reshape(-1, 2)
                # 额外校验：检测到的圆心数与规格一致
                if len(centers) == cols * rows:
                    return centers, spec
        return None

    @staticmethod
    def _get_ply_path(pointmap, rvc_image, offline_ply_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """返回要读取的 PLY 路径，以及可能创建的临时文件路径。"""
        if offline_ply_path and os.path.exists(offline_ply_path):
            return offline_ply_path, None
        if pointmap is not None and rvc_image is not None and RVC is not None:
            fd, tmp_path = tempfile.mkstemp(suffix=".ply")
            os.close(fd)
            ret = pointmap.SaveWithImage(tmp_path, rvc_image, RVC.PointMapUnitEnum.Millimeter, True)
            if ret:
                return tmp_path, tmp_path
            os.unlink(tmp_path)
        return None, None

    @staticmethod
    def _read_ply_points(ply_path: str) -> Optional[np.ndarray]:
        """读取 PLY 点云，返回 N×3 numpy 数组。"""
        try:
            import open3d as o3d
            pcd = o3d.io.read_point_cloud(ply_path)
            pts = np.asarray(pcd.points)
            return pts
        except Exception as e:
            logger.error(f"读取 PLY 点云失败: {e}")
            return None

    @staticmethod
    def _extract_centers_3d(centers_2d: np.ndarray,
                            points_3d: np.ndarray,
                            image_size: Tuple[int, int]) -> np.ndarray:
        """通过双线性插值从 PLY 点云提取 2D 圆心对应的 3D 坐标。

        假设 PLY 点顺序与图像像素一致（row-major: idx = y * w + x）。
        """
        w, h = image_size
        n = len(centers_2d)
        centers_3d = np.full((n, 3), np.nan, dtype=np.float64)

        if len(points_3d) < w * h:
            logger.warning(f"PLY 点数 {len(points_3d)} 小于图像尺寸 {w}×{h}={w*h}，可能无法正确映射")

        for i, (cx, cy) in enumerate(centers_2d):
            # 找到最近的四个像素
            x0 = int(np.floor(cx))
            y0 = int(np.floor(cy))
            x1 = x0 + 1
            y1 = y0 + 1

            if x0 < 0 or y0 < 0 or x1 >= w or y1 >= h:
                logger.warning(f"圆心 ({cx:.1f},{cy:.1f}) 超出图像边界，跳过")
                continue

            # 四个邻域像素的 PLY 索引
            idx_00 = y0 * w + x0
            idx_10 = y0 * w + x1
            idx_01 = y1 * w + x0
            idx_11 = y1 * w + x1

            pts = []
            for idx in (idx_00, idx_10, idx_01, idx_11):
                if idx < len(points_3d):
                    pt = points_3d[idx]
                    if np.isfinite(pt).all():
                        pts.append(pt)

            if len(pts) < 4:
                # 邻域存在无效点：退化为最近有效单点
                cx_i, cy_i = int(round(cx)), int(round(cy))
                idx_c = cy_i * w + cx_i
                if 0 <= idx_c < len(points_3d) and np.isfinite(points_3d[idx_c]).all():
                    centers_3d[i] = points_3d[idx_c]
                continue

            p00, p10, p01, p11 = pts[0], pts[1], pts[2], pts[3]
            wx = cx - x0
            wy = cy - y0
            val = (
                p00 * (1 - wx) * (1 - wy) +
                p10 * wx * (1 - wy) +
                p01 * (1 - wx) * wy +
                p11 * wx * wy
            )
            centers_3d[i] = val

        return centers_3d

    @staticmethod
    def _build_object_points(spec: Dict) -> np.ndarray:
        """构造标定板理论圆心坐标（mm）。

        非对称圆排列：相邻列在 y 方向有半格偏移。
        顺序与 OpenCV findCirclesGrid 返回的 centers 一致：
          - 列优先，从右到左（x 从大到小）；
          - 每列内从上到下（y 从小到大，因图像 y 向下为正）。
        坐标系：x 向右，y 向下，z = 0。
        """
        cols = spec['cols']
        rows = spec['rows']
        d = float(spec['spacing_mm'])

        obj_pts = np.zeros((cols * rows, 3), dtype=np.float64)
        for k, j in enumerate(range(cols - 1, -1, -1)):  # 列：从右到左
            for i in range(rows):                         # 行：从上到下
                idx = k * rows + i
                x = j * d
                y = (i + 0.5 * (j % 2)) * d
                obj_pts[idx] = [x, y, 0.0]
        return obj_pts

    @staticmethod
    def _solve_board_pose(object_points: np.ndarray,
                          image_points: np.ndarray,
                          spec: Dict) -> Tuple[Optional[np.ndarray], float]:
        """SVD 求解标定板位姿 T_board_in_cam。

        目标：image_points ≈ object_points @ R.T + t
        返回 4×4 齐次矩阵 T 使得 p_cam = T @ p_board。
        """
        valid_mask = np.isfinite(image_points).all(axis=1)
        if valid_mask.sum() < 3:
            return None, 0.0

        A = object_points[valid_mask]
        B = image_points[valid_mask]

        centroid_A = np.mean(A, axis=0)
        centroid_B = np.mean(B, axis=0)
        AA = A - centroid_A
        BB = B - centroid_B
        H = AA.T @ BB
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T
        t = centroid_B - R @ centroid_A

        # 4×4 齐次矩阵
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = R
        T[:3, 3] = t

        # RMS 重投影误差
        pred = (R @ A.T + t.reshape(3, 1)).T
        errs = np.linalg.norm(pred - B, axis=1)
        rms = float(np.sqrt(np.mean(errs ** 2)))

        return T, rms
