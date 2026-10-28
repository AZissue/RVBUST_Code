# -*- coding: utf-8 -*-
"""
test_coded_circle_rig.py —— 编码圆 rig 标定全链路合成验证（无硬件）。

用生成器渲染一块真实排版的编码圆板，按已知内外参和已知 rig 投影出左右两幅
虚拟视图（透视 warp），然后走完整标定链路：

    生成板 → DetectCodedCircleMarker 检测（左右）→ 按 code 配对 →
    stereoCalibrate(CALIB_FIX_INTRINSIC) → 恢复 rig

断言恢复出的 R/T 与真值：基线相对误差 <1%、相对旋转 <0.3°。
覆盖了：板生成与布局一致性、SDK 编码圆检测、配对、标定求解——
实机前即可证明链路正确。

运行：python tests/test_coded_circle_rig.py   （判据：exit 0，各步打印 [PASS]）
"""
from __future__ import annotations

import os
import sys

import numpy as np
import cv2

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.abspath(os.path.join(_HERE, "..", "app"))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_APP, _REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from calib_rig_from_coded_circle import (  # noqa: E402
    board_layout, make_detector, detect_map, rig_from_pair)
from calib_rig_from_board import quat_avg  # noqa: E402

_PAGE_W_MM = 210.0   # A4 宽（board_layout 默认 A4；若改页幅需同步）


def _check(cond, name, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        raise SystemExit(1)


def render_view(board_bgr, K, board_R, board_t, image_size):
    """把板面（Z=0 平面）经单应 H = K[r1 r2 t] 投影到虚拟相机视图。

    ⚠️ 板图像素坐标 → 米：H 的前两列要乘 (板宽米/板宽像素)，否则会把
    板角映射到数米外（几乎全白、只剩鬼影）。
    """
    gray = cv2.cvtColor(board_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    k = (_PAGE_W_MM / 1000.0) / w          # 米/像素（A4 210mm）
    H = K @ np.column_stack([board_R[:, 0] * k, board_R[:, 1] * k, board_t])
    view = cv2.warpPerspective(gray, H, image_size, flags=cv2.INTER_AREA,
                               borderValue=90)
    return view


def main() -> int:
    np.random.seed(7)

    # ---- 真值设定：M51000C 内参 + 50mm 水平基线 ----
    K = np.array([[2390.92, 0, 1193.53], [0, 2391.60, 1037.66], [0, 0, 1.0]])
    image_size = (2448, 2048)
    d_zero = np.zeros(5)
    R_gt, _ = cv2.Rodrigues(np.array([0.0, 0.0, 0.008]))       # 0.46° 微量旋转
    t_gt = np.array([-0.05, 0.0, 0.0])                          # 50mm 基线（米）

    # ---- 生成标定板（半径 6mm → 12 圆, 60mm 间距）----
    board_img, layout = board_layout(6.0, 1.0, "A4", 300, 5.0, 12)
    _check(len(layout["points"]) >= 8, "板生成", f"{len(layout['points'])} 个圆, "
           f"间距 {layout['params']['cell_mm']}mm")

    # ---- 4 个板位，各渲染左右视图 ----
    det = make_detector()
    rig_samples, rms_list = [], []
    n_poses = 4
    for i in range(n_poses):
        ang = np.array([0.12 + 0.05 * i, -0.10 + 0.04 * i, 0.3 + 0.5 * i])
        R_b, _ = cv2.Rodrigues(ang)
        t_b = np.array([-0.02 + 0.02 * i, 0.01 - 0.02 * i, 0.85 + 0.05 * i])
        view_l = render_view(board_img, K, R_b, t_b, image_size)
        # 右相机系下板位姿：p_r = R_gt p_l + t_gt
        view_r = render_view(board_img, K, R_gt @ R_b, R_gt @ t_b + t_gt, image_size)

        dl = detect_map(det, view_l)
        dr = detect_map(det, view_r)
        res, nl, nr, nc, rms = rig_from_pair(layout, dl, dr, K, d_zero, K, d_zero,
                                             image_size)
        _check(res is not None, f"样本{i+1} 检出并解算",
               f"左{nl} 右{nr} 公共{nc} rms {rms:.3f}px")
        rig_samples.append(res)
        rms_list.append(rms)

    # ---- 聚合并与真值比对 ----
    R_avg = quat_avg([R for R, _ in rig_samples])
    t_avg = np.median(np.array([t for _, t in rig_samples]), axis=0)

    base_err = abs(np.linalg.norm(t_avg) - np.linalg.norm(t_gt)) / np.linalg.norm(t_gt)
    Rdiff = R_gt.T @ R_avg
    ang_err = np.degrees(np.arccos(np.clip((np.trace(Rdiff) - 1) / 2, -1, 1)))
    rms_max = max(rms_list)

    print(f"\n真值: 基线 {np.linalg.norm(t_gt)*1000:.1f}mm")
    print(f"恢复: 基线 {np.linalg.norm(t_avg)*1000:.2f}mm  相对旋转 {ang_err:.3f}°  "
          f"rms≤{rms_max:.3f}px")
    _check(base_err < 0.01, "基线恢复误差 <1%", f"实际 {base_err * 100:.3f}%")
    _check(ang_err < 0.3, "相对旋转误差 <0.3°", f"实际 {ang_err:.3f}°")
    _check(rms_max < 0.5, "标定重投影 rms <0.5px", f"实际 {rms_max:.3f}px")
    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
