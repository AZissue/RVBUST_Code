# -*- coding: utf-8 -*-
"""
stereo_reconstruct.py —— 由双目左右 2D 图 + 内外参离线重建点云（纯算法，无 SDK 依赖）。

坐标系约定
----------
- 输出点云位于**左相机坐标系**：左相机光心为原点，单位米，Z 轴沿光轴指向场景。
- 双目外参遵循 OpenCV 约定：x_right = R @ x_left + T（T 为右相机系相对左相机系的
  平移，单位米；典型水平基线 T = [-B, 0, 0] 对应正视差）。

畸变顺序的坑（本模块关键正确性点）
----------------------------------
RVC SDK ``X2.GetIntrinsicParameters()`` 返回的 5 个畸变系数顺序是::

    k1 k2 k3 p1 p2

而 OpenCV 全程期望 ``(k1, k2, p1, p2, k3)``。必须先用 :func:`rvc_dist_to_opencv`
重排后再传入本模块，否则切向/径向畸变张冠李戴。

无效视差约定
------------
``disp <= minDisparity`` 或非有限值的像素在 valid_mask 中标 False，对应 points 置 0。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import numpy as np


def rvc_dist_to_opencv(k1: float, k2: float, k3: float, p1: float, p2: float) -> np.ndarray:
    """把 RVC SDK 顺序 (k1, k2, k3, p1, p2) 重排为 OpenCV 顺序 (k1, k2, p1, p2, k3)。"""
    return np.asarray([k1, k2, p1, p2, k3], dtype=np.float64)


# SGBM 默认参数（调用方可通过 sgbm_params 覆盖其中任意项，含 P1/P2）
DEFAULT_SGBM_PARAMS: Dict[str, int] = {
    "minDisparity": 0,
    "numDisparities": 128,
    "blockSize": 5,
    "uniquenessRatio": 10,
    "speckleWindowSize": 100,
    "speckleRange": 2,
    "disp12MaxDiff": 1,
}


class StereoReconstructor:
    """由左右 2D 图 + 双目内外参离线重建左相机系点云。

    构造时只做一次 ``stereoRectify`` + ``initUndistortRectifyMap``（预计算两路
    remap 映射），之后每帧 ``reconstruct()`` 仅做 remap → SGBM → reprojectImageTo3D，
    适合在采集循环里反复调用。
    """

    def __init__(self, K_left, dist_left_cv, K_right, dist_right_cv,
                 R, T, image_size, sgbm_params: Optional[Dict] = None):
        self.image_size = (int(image_size[0]), int(image_size[1]))
        K_left = np.asarray(K_left, dtype=np.float64).reshape(3, 3)
        K_right = np.asarray(K_right, dtype=np.float64).reshape(3, 3)
        dist_left_cv = np.asarray(dist_left_cv, dtype=np.float64).reshape(-1)
        dist_right_cv = np.asarray(dist_right_cv, dtype=np.float64).reshape(-1)
        R = np.asarray(R, dtype=np.float64).reshape(3, 3)
        T = np.asarray(T, dtype=np.float64).reshape(3)

        # CALIB_ZERO_DISPARITY：校正后两相机行主极线严格对齐，匹配只需沿水平线搜索
        R1, R2, P1, P2, Q, _roi1, _roi2 = cv2.stereoRectify(
            K_left, dist_left_cv, K_right, dist_right_cv,
            self.image_size, R, T, flags=cv2.CALIB_ZERO_DISPARITY)
        self.Q = Q.astype(np.float64)

        # 预计算 remap 映射（只算一次，构造开销不计入帧耗时）
        self.map1x, self.map1y = cv2.initUndistortRectifyMap(
            K_left, dist_left_cv, R1, P1, self.image_size, cv2.CV_32FC1)
        self.map2x, self.map2y = cv2.initUndistortRectifyMap(
            K_right, dist_right_cv, R2, P2, self.image_size, cv2.CV_32FC1)

        params = dict(DEFAULT_SGBM_PARAMS)
        if sgbm_params:
            params.update(sgbm_params)
        if int(params["numDisparities"]) <= 0 or int(params["numDisparities"]) % 16 != 0:
            raise ValueError(
                f"numDisparities 必须为正且能被 16 整除，got {params['numDisparities']}")
        self.min_disparity = int(params["minDisparity"])
        block = int(params["blockSize"])
        P1 = int(params.get("P1", 8 * 3 * block ** 2))
        P2 = int(params.get("P2", 32 * 3 * block ** 2))
        self.sgbm_params = dict(params, P1=P1, P2=P2)
        self.matcher = cv2.StereoSGBM_create(
            minDisparity=self.min_disparity,
            numDisparities=int(params["numDisparities"]),
            blockSize=block,
            P1=P1,
            P2=P2,
            uniquenessRatio=int(params["uniquenessRatio"]),
            speckleWindowSize=int(params["speckleWindowSize"]),
            speckleRange=int(params["speckleRange"]),
            disp12MaxDiff=int(params["disp12MaxDiff"]),
        )

    # -- 内部工具 ----------------------------------------------------------
    @staticmethod
    def _to_gray(img: np.ndarray) -> np.ndarray:
        """转灰度；3 通道按 BGR 处理，单通道原样返回。"""
        if img.ndim == 2:
            return img
        if img.ndim == 3 and img.shape[2] == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        raise ValueError(f"不支持的图像形状: {img.shape}")

    # -- 供计时的分阶段接口 -------------------------------------------------
    def compute_disparity(self, img_left: np.ndarray, img_right: np.ndarray) -> np.ndarray:
        """remap + 灰度化 + SGBM，返回 float32 视差图（亚像素，单位像素）。"""
        gray_l = self._to_gray(cv2.remap(img_left, self.map1x, self.map1y, cv2.INTER_LINEAR))
        gray_r = self._to_gray(cv2.remap(img_right, self.map2x, self.map2y, cv2.INTER_LINEAR))
        disp16 = self.matcher.compute(gray_l, gray_r)
        return disp16.astype(np.float32) / 16.0

    def disparity_to_points(self, disp: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """视差图 → (points (H,W,3) float32 米, valid_mask (H,W) bool)。

        无效视差（<= minDisparity 或非有限值）在 valid_mask 标 False，
        对应 points 置 0（本模块约定）。
        """
        valid = np.isfinite(disp) & (disp > float(self.min_disparity))
        points = cv2.reprojectImageTo3D(disp, self.Q).astype(np.float32)
        points[~valid] = 0.0
        return points, valid

    def reconstruct(self, img_left: np.ndarray, img_right: np.ndarray):
        """完整流程：remap → SGBM → reprojectImageTo3D。

        返回 (points (H,W,3) float32 米, valid_mask (H,W) bool)。
        """
        return self.disparity_to_points(self.compute_disparity(img_left, img_right))
