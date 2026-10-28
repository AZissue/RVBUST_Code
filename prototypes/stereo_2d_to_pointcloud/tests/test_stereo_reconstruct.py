# -*- coding: utf-8 -*-
"""
test_stereo_reconstruct.py —— StereoReconstructor 无硬件单元测试。

运行：python tests/test_stereo_reconstruct.py（任意 cwd 均可）
判据：进程退出码 0 = 全部通过，1 = 有失败；每个测试通过时打印 [PASS] 名称。

import 方式：从本文件向上找含 src/ 的目录定为仓库根，把
prototypes/stereo_2d_to_pointcloud 加入 sys.path 后直接 import core.stereo_reconstruct。
"""
from __future__ import annotations

import os
import sys
import unittest

import cv2
import numpy as np


def _find_repo_root(start: str) -> str:
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, "src")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RuntimeError(f"从 {start} 向上未找到含 src/ 的仓库根目录")
        d = parent


_REPO_ROOT = _find_repo_root(os.path.dirname(os.path.abspath(__file__)))
_PROTO_DIR = os.path.join(_REPO_ROOT, "prototypes", "stereo_2d_to_pointcloud")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

# noqa: E402 —— sys.path 准备好后再 import
from core.stereo_reconstruct import StereoReconstructor, rvc_dist_to_opencv  # noqa: E402

# 合成场景公共参数
IMG_W, IMG_H = 640, 480
FX = FY = 800.0
CX, CY = IMG_W / 2.0, IMG_H / 2.0
K_SYN = np.array([[FX, 0.0, CX], [0.0, FY, CY], [0.0, 0.0, 1.0]], dtype=np.float64)
ZERO_DIST = np.zeros(5, dtype=np.float64)
R_IDENTITY = np.eye(3, dtype=np.float64)
T_BASELINE = np.array([-0.06, 0.0, 0.0], dtype=np.float64)  # 60mm 基线，正视差


def plane_homography_rl(K: np.ndarray, R: np.ndarray, T: np.ndarray, depth: float) -> np.ndarray:
    """前平行平面（法向 n=(0,0,1)，距离 depth）"右图←左图"的单应矩阵。

    OpenCV 外参约定 x_r = R x_l + T，映射左图像素→右图像素的单应为
    H = K (R + T n^T / depth) K^{-1}（注意是 **加号**；文献里常见的
    "R - T n^T/d" 对应 x_r = R x_l - T 的约定，与 OpenCV/stereoRectify 不符）。

    返回 H：cv2.warpPerspective(src, M, dsize) 默认把 M 解释为"源→目标"映射
    （内部再求逆做反向采样），故由左图生成右图时直接传 M = H 即可。
    """
    n = np.array([0.0, 0.0, 1.0])
    H = K @ (R + np.outer(T, n) / depth) @ np.linalg.inv(K)
    return H / H[2, 2]


def make_texture(h: int = IMG_H, w: int = IMG_W) -> np.ndarray:
    """平滑随机纹理：raw 噪声 + 轻模糊，块匹配友好；调用方负责 np.random.seed。"""
    noise = np.random.randint(0, 256, (h, w), dtype=np.uint8)
    return cv2.GaussianBlur(noise, (3, 3), 0)


def central_roi(mask: np.ndarray, margin_x: int = 160, margin_y: int = 40) -> np.ndarray:
    """取中央有效区：避开 SGBM 左侧 numDisparities 搜索带与右图边缘 warp 盲区。"""
    m = mask.copy()
    m[:margin_y, :] = False
    m[-margin_y:, :] = False
    m[:, :margin_x] = False
    m[:, -margin_x:] = False
    return m


class TestStereoReconstruct(unittest.TestCase):

    def test_distortion_reorder(self):
        """RVC 顺序 (k1,k2,k3,p1,p2) → OpenCV 顺序 (k1,k2,p1,p2,k3)。"""
        got = rvc_dist_to_opencv(0.1, 0.2, 0.3, 0.01, 0.02)
        np.testing.assert_allclose(got, [0.1, 0.2, 0.01, 0.02, 0.3], rtol=0.0, atol=1e-12)
        print("[PASS] test_distortion_reorder")

    def test_planar_reconstruction_accuracy(self):
        """Z0=1.0m 前平行平面：有效区内 Z 中位数与 1.0m 偏差 < 5%。"""
        np.random.seed(42)
        img_l = make_texture()
        H_rl = plane_homography_rl(K_SYN, R_IDENTITY, T_BASELINE, 1.0)
        img_r = cv2.warpPerspective(img_l, H_rl, (IMG_W, IMG_H),
                                    flags=cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_REPLICATE)
        rec = StereoReconstructor(K_SYN, ZERO_DIST, K_SYN, ZERO_DIST,
                                  R_IDENTITY, T_BASELINE, (IMG_W, IMG_H))
        points, valid = rec.reconstruct(img_l, img_r)

        self.assertEqual(points.shape, (IMG_H, IMG_W, 3))
        self.assertEqual(points.dtype, np.float32)
        roi = central_roi(valid)
        self.assertGreater(int(roi.sum()), 10000, "有效区过小，SGBM 匹配失败")
        z_med = float(np.median(points[..., 2][roi]))
        self.assertLess(abs(z_med - 1.0) / 1.0, 0.05,
                        f"Z 中位数 {z_med:.4f}m 偏离 1.0m 超过 5%")
        print(f"[PASS] test_planar_reconstruction_accuracy (有效 {int(roi.sum())} px, "
              f"Z 中位数 {z_med:.4f}m)")

    def test_two_depth_layers(self):
        """远层 1.0m + 近层 0.7m 局部区域：两层各自 Z 中位数均在 ±5% 内。"""
        np.random.seed(7)
        img_l = make_texture()
        Z_FAR, Z_NEAR = 1.0, 0.7
        H_far = plane_homography_rl(K_SYN, R_IDENTITY, T_BASELINE, Z_FAR)
        H_near = plane_homography_rl(K_SYN, R_IDENTITY, T_BASELINE, Z_NEAR)
        img_far_r = cv2.warpPerspective(img_l, H_far, (IMG_W, IMG_H),
                                        flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_REPLICATE)
        img_near_r = cv2.warpPerspective(img_l, H_near, (IMG_W, IMG_H),
                                         flags=cv2.INTER_LINEAR,
                                         borderMode=cv2.BORDER_REPLICATE)
        img_r = img_far_r.copy()
        y0, y1, x0, x1 = 160, 320, 200, 440
        img_r[y0:y1, x0:x1] = img_near_r[y0:y1, x0:x1]

        rec = StereoReconstructor(K_SYN, ZERO_DIST, K_SYN, ZERO_DIST,
                                  R_IDENTITY, T_BASELINE, (IMG_W, IMG_H))
        points, valid = rec.reconstruct(img_l, img_r)

        # 远层：中央区扣掉近层及其边界余量
        roi_far = central_roi(valid)
        roi_far[y0 - 20:y1 + 20, x0 - 20:x1 + 20] = False
        # 近层：区域内缩 12px，避开拼接缝与 SGBM 块边界
        roi_near = np.zeros((IMG_H, IMG_W), dtype=bool)
        roi_near[y0 + 12:y1 - 12, x0 + 12:x1 - 12] = True
        roi_near &= valid

        for name, roi, expect in (("far", roi_far, Z_FAR), ("near", roi_near, Z_NEAR)):
            self.assertGreater(int(roi.sum()), 3000, f"{name} 层有效区过小")
            z_med = float(np.median(points[..., 2][roi]))
            self.assertLess(abs(z_med - expect) / expect, 0.05,
                            f"{name} 层 Z 中位数 {z_med:.4f}m 偏离 {expect}m 超过 5%")
        print(f"[PASS] test_two_depth_layers "
              f"(far={float(np.median(points[..., 2][roi_far])):.4f}m, "
              f"near={float(np.median(points[..., 2][roi_near])):.4f}m)")

    def test_invalid_region_mask(self):
        """右图局部替换为独立噪声（任何水平位移都不匹配）：该区域应无效。"""
        np.random.seed(11)
        img_l = make_texture()
        img_r = img_l.copy()
        x0, x1 = 200, 440
        img_r[:, x0:x1] = make_texture(IMG_H, x1 - x0)  # 等效"超出 numDisparities 的位移"的无匹配区

        rec = StereoReconstructor(K_SYN, ZERO_DIST, K_SYN, ZERO_DIST,
                                  R_IDENTITY, T_BASELINE, (IMG_W, IMG_H))
        points, valid = rec.reconstruct(img_l, img_r)

        region = np.zeros((IMG_H, IMG_W), dtype=bool)
        region[40:-40, x0 + 10:x1 - 10] = True
        frac = float(valid[region].mean())
        self.assertLess(frac, 0.2, f"无匹配区有效比例 {frac:.2f}，应接近 0")
        # 与实现约定一致：无效区 points 置 0（若实现改 NaN，此断言需同步改）
        self.assertTrue(bool(np.all(points[~valid] == 0.0)),
                        "无效区 points 应置 0（本模块约定）")
        print(f"[PASS] test_invalid_region_mask (无匹配区有效比例 {frac:.4f})")


def main() -> int:
    suite = unittest.TestLoader().loadTestsFromTestCase(TestStereoReconstruct)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
