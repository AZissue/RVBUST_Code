# -*- coding: utf-8 -*-
"""
统一标记物检测器（MarkerDetector）。

从 DualCameraFusion/src/app.py:591-759 原样抽取并扩展，支持：
  - 编码圆 2D 检测 + 3D 坐标提取；
  - 非对称圆标定板检测 + 位姿估计。

无 SDK 环境下 detect 返回空列表而不崩溃。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, TYPE_CHECKING

import numpy as np
import cv2

from .utils import logger
from .calib_board_detector import CalibBoardDetector, DEFAULT_BOARD_SPECS

if TYPE_CHECKING:
    import PyRVC as RVC

try:
    import PyRVC as RVC
except ImportError:
    RVC = None  # 无 SDK 环境：detect 一律返回空列表

# 标记物类型常量
MARKER_TYPE_CODED_CIRCLE = "coded_circle"
MARKER_TYPE_ASYMMETRIC_GRID = "asymmetric_grid"

# 有效标记物类型集合
SUPPORTED_MARKER_TYPES = (MARKER_TYPE_CODED_CIRCLE, MARKER_TYPE_ASYMMETRIC_GRID)


class MarkerDetector:
    """统一标记物检测器（编码圆 / 非对称圆标定板）。"""

    def __init__(self, marker_type: str = MARKER_TYPE_CODED_CIRCLE):
        self._marker_type = marker_type
        self._coded_marker_type = None
        if RVC is not None:
            self._coded_marker_type = RVC.CodedCircleMarkerType()
            self._coded_marker_type.N = 8
            self._coded_marker_type.r1_to_r0_ratio = 2.0
            self._coded_marker_type.r2_to_r0_ratio = 3.0

        self._board_detector = CalibBoardDetector()
        # 标定板模式下，保存最近一次完整检测结果（含位姿），供主窗口读取
        self.last_board_result: Optional[Dict] = None

    # ------------------------------------------------------------------
    # 标记物类型
    # ------------------------------------------------------------------
    def set_marker_type(self, marker_type: str):
        if marker_type not in SUPPORTED_MARKER_TYPES:
            logger.warning(f"不支持的标记物类型: {marker_type}，保持当前类型: {self._marker_type}")
            return
        self._marker_type = marker_type
        self.last_board_result = None

    def get_marker_type(self) -> str:
        return self._marker_type

    def is_board_mode(self) -> bool:
        return self._marker_type == MARKER_TYPE_ASYMMETRIC_GRID

    # ------------------------------------------------------------------
    # 编码圆参数
    # ------------------------------------------------------------------
    def set_params(self, n: int, r1_ratio: float, r2_ratio: float):
        if self._coded_marker_type is None:
            return
        self._coded_marker_type.N = n
        self._coded_marker_type.r1_to_r0_ratio = r1_ratio
        self._coded_marker_type.r2_to_r0_ratio = r2_ratio

    # ------------------------------------------------------------------
    # 标定板参数转发
    # ------------------------------------------------------------------
    def set_board_specs(self, board_specs: List[Dict]):
        """设置支持的标定板规格列表。"""
        self._board_detector.set_board_specs(board_specs)

    def set_board_gamma(self, gamma: float):
        """设置标定板检测的 gamma 校正系数。"""
        self._board_detector.set_gamma(gamma)

    def get_board_specs(self) -> List[Dict]:
        """获取当前支持的标定板规格列表。"""
        return self._board_detector.board_specs

    def detect(self, image: np.ndarray) -> List[Dict]:
        """2D 编码圆检测（仅编码圆模式下使用）。"""
        if image is None:
            logger.warning("detect: 图像为 None")
            return []
        if self._coded_marker_type is None:
            logger.warning("detect: PyRVC 未安装，无法检测")
            return []
        try:
            logger.info(f"detect 输入: shape={image.shape}, dtype={image.dtype}, min={image.min()}, max={image.max()}")
            img = self._preprocess(image)
            logger.info(f"detect 预处理后: shape={img.shape}, dtype={img.dtype}")
            markers = RVC.DetectCodedCircleMarker(img, self._coded_marker_type)
            logger.info(f"detect 结果: {len(markers)} 个编码圆")
            return [
                {
                    'code': int(m.code),
                    'x': float(m.x),
                    'y': float(m.y),
                    'center': (int(m.x), int(m.y))
                }
                for m in markers
            ]
        except Exception as e:
            logger.error(f"detect 异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """预处理图像以适配编码圆检测器。"""
        # 处理数据类型：uint16 → uint8（M2600 等相机可能返回 16 位图像）
        if image.dtype == np.uint16:
            # 低动态范围图像直接用低 8 位，避免 /256 后再 *255 的二次缩放
            if image.max() > 256:
                image = (image / 256).astype(np.uint8)
            else:
                image = image.astype(np.uint8)
            logger.info(f"图像 uint16 → uint8 转换")
        elif image.dtype != np.uint8:
            if image.max() <= 1.0:
                image = (image * 255).clip(0, 255).astype(np.uint8)
            else:
                image = image.clip(0, 255).astype(np.uint8)
            logger.info(f"图像 {image.dtype} → uint8 转换")

        # 确保值范围正确：仅对仍在 [0,1] 区间的浮点图像做归一化缩放
        if image.dtype != np.uint8 and image.max() <= 1.0:
            image = (image * 255).astype(np.uint8)

        # 通道处理
        if len(image.shape) == 3 and image.shape[2] == 3:
            return np.ascontiguousarray(image).copy()
        elif len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif len(image.shape) == 3 and image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return np.ascontiguousarray(image).copy()

    def detect_3d(self, image_np: np.ndarray, pointmap: 'RVC.PointMap' = None, rvc_image: 'RVC.Image' = None, offline_ply_path: str = None) -> List[Dict]:
        """从 2D numpy 图像检测标记物并提取 3D 坐标。

        支持两种模式：
        - 在线模式：提供 pointmap + rvc_image（RVC 对象）
        - 离线模式：提供 offline_ply_path（PLY 文件路径）

        根据当前 marker_type 自动分发到编码圆检测或标定板检测。
        """
        self.last_board_result = None

        if self._marker_type == MARKER_TYPE_ASYMMETRIC_GRID:
            result = self._board_detector.detect(image_np, pointmap, rvc_image, offline_ply_path)
            self.last_board_result = result if result.get('success') else None
            return result.get('markers', [])

        # 编码圆模式（原有逻辑）
        return self._detect_3d_coded_circle(image_np, pointmap, rvc_image, offline_ply_path)

    def _detect_3d_coded_circle(self, image_np: np.ndarray, pointmap: 'RVC.PointMap' = None, rvc_image: 'RVC.Image' = None, offline_ply_path: str = None) -> List[Dict]:
        """编码圆 2D+3D 检测（原 detect_3d 逻辑）。"""
        import tempfile
        ply_path = offline_ply_path
        tmp_path = None

        try:
            # 获取 PLY 点云文件
            if ply_path and os.path.exists(ply_path):
                # 离线模式：直接使用已有 PLY
                logger.info(f"离线模式：使用 PLY 文件 {ply_path}")
            elif pointmap is not None and rvc_image is not None and RVC is not None:
                # 在线模式：保存临时 PLY
                fd, tmp_path = tempfile.mkstemp(suffix=".ply")
                os.close(fd)
                ret = pointmap.SaveWithImage(tmp_path, rvc_image, RVC.PointMapUnitEnum.Millimeter, True)
                if not ret:
                    logger.warning("PointMap.SaveWithImage 失败")
                    return []
                ply_path = tmp_path
            else:
                logger.warning("detect_3d: 未提供 pointmap/rvc_image 或 offline_ply_path")
                return []

            # 读取 PLY 获取 3D 点
            try:
                import open3d as o3d
                pcd = o3d.io.read_point_cloud(ply_path)
                points = np.asarray(pcd.points)
                logger.info(f"PLY 读取成功: {len(points)} 点")
            except Exception as e:
                logger.error(f"读取 PLY 失败: {e}")
                return []

            # 2D 图像检测编码圆（直接用 numpy 图像，不转换 RVC.Image）
            if image_np is None:
                logger.warning("image_np 为 None")
                return []
            h_img, w_img = image_np.shape[:2]
            logger.info(f"图像尺寸: {w_img}×{h_img}, dtype={image_np.dtype}")

            markers_2d = self.detect(image_np)
            logger.info(f"2D 检测到 {len(markers_2d)} 个编码圆")
            if not markers_2d:
                # 保存调试图像供用户检查
                try:
                    debug_path = f"debug_detect_{w_img}x{h_img}_{image_np.dtype}.png"
                    cv2.imwrite(debug_path, image_np)
                    logger.info(f"调试图像已保存: {debug_path}")
                except Exception:
                    pass
                return []

            # 从 PLY 提取 3D（通过图像坐标映射）
            # 注意：PLY 点顺序与像素顺序一致（row-major: y*w + x）
            w, h = w_img, h_img  # 使用图像尺寸
            logger.info(f"PLY 映射尺寸: {w}×{h}, 总点数: {len(points)}, 期望: {w*h}")

            # 调试：检查点云范围
            if len(points) > 0:
                valid_pts = points[np.isfinite(points).all(axis=1)]
                if len(valid_pts) > 0:
                    logger.info(f"点云范围: X[{valid_pts[:,0].min():.1f}, {valid_pts[:,0].max():.1f}] Y[{valid_pts[:,1].min():.1f}, {valid_pts[:,1].max():.1f}] Z[{valid_pts[:,2].min():.1f}, {valid_pts[:,2].max():.1f}]")

            # 使用双线性插值提取 3D 坐标（与标定板检测器保持一致）
            centers_2d = np.array([[m['x'], m['y']] for m in markers_2d], dtype=np.float64)
            centers_3d = CalibBoardDetector._extract_centers_3d(centers_2d, points, (w, h))

            markers_3d = []
            for m, pt in zip(markers_2d, centers_3d):
                if np.isfinite(pt).all():
                    markers_3d.append({
                        'code': m['code'],
                        'x_2d': m['x'],
                        'y_2d': m['y'],
                        'x_3d': float(pt[0]),
                        'y_3d': float(pt[1]),
                        'z_3d': float(pt[2]),
                    })
                else:
                    logger.warning(f"编码圆 code={m['code']} at ({m['x']:.1f},{m['y']:.1f}) 对应点无效")
            logger.info(f"3D 有效编码圆: {len(markers_3d)}/{len(markers_2d)}")
            return markers_3d
        except Exception as e:
            logger.error(f"detect_3d 异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
