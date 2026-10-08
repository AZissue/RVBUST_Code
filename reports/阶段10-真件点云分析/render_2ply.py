#!/usr/bin/env python3
"""把 2.ply 画成俯视图，肉眼确认孔口/孔壁/倒角长什么样。

用法：
    python -I reports/阶段10-真件点云分析/render_2ply.py <file.ply> <out.png>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_2ply import read_ply, robust_plane  # noqa: E402


def turbo(x):
    """x in [0,1] -> (r,g,b) 0-255，近似 turbo 色标。"""
    x = np.clip(x, 0, 1)
    r = np.clip(34 + 240 * np.minimum(1, 3 * x), 0, 255)
    g = np.clip(30 + 240 * np.minimum(1, np.maximum(0, 3 * x - 1)) * 1.0
                + 0 * x, 0, 255)
    b = np.clip(180 - 180 * np.minimum(1, 3 * x), 0, 255)
    # 粗但够用：暗蓝 -> 青 -> 黄 -> 红
    r = np.clip(255 * np.minimum(1, 1.5 * x), 0, 255)
    g = np.clip(255 * np.minimum(1, np.maximum(0, 1.5 * x - 0.25)), 0, 255)
    b = np.clip(255 * (1 - np.minimum(1, 2.5 * x)), 0, 255)
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def main():
    ply, out = Path(sys.argv[1]), Path(sys.argv[2])
    xyz, meta = read_ply(ply)
    pts = xyz[np.isfinite(xyz).all(axis=1)]
    normal, c, in_plane, dep = robust_plane(pts)

    u_ax = np.cross(normal, [0.0, 0.0, 1.0])
    if np.linalg.norm(u_ax) < 1e-6:
        u_ax = np.array([1.0, 0.0, 0.0])
    u_ax /= np.linalg.norm(u_ax)
    v_ax = np.cross(normal, u_ax)
    uv = np.stack([pts @ u_ax, pts @ v_ax], axis=1)

    step = 0.05          # mm / px
    lo = uv.min(axis=0) - step
    hi = uv.max(axis=0) + step
    w = int(round((hi[0] - lo[0]) / step))
    h = int(round((hi[1] - lo[1]) / step))

    depth_img = np.full((h, w), np.nan)
    count_img = np.zeros((h, w))
    ix = np.clip(((uv[:, 0] - lo[0]) / step).astype(int), 0, w - 1)
    iy = np.clip(((hi[1] - uv[:, 1]) / step).astype(int), 0, h - 1)
    # 每格取"最靠近相机"（d 最小）的那个点：孔壁不会盖住孔口
    order = np.argsort(dep)
    for k in order:
        y, x = iy[k], ix[k]
        count_img[y, x] += 1
        if np.isnan(depth_img[y, x]):
            depth_img[y, x] = dep[k]

    # 图 A：深度着色（深=红，浅=蓝）；无点=黑
    dmin, dmax = -0.3, 1.0
    norm = np.clip((depth_img - dmin) / (dmax - dmin), 0, 1)
    img = np.zeros((h, w, 3), np.uint8)
    mask = ~np.isnan(depth_img)
    img[mask] = turbo(norm[mask])

    # 图 B：3 倍放大的并排（原图 + 只画 |d|>0.15 的孔内点）
    img2 = np.zeros((h, w, 3), np.uint8)
    m2 = mask & (np.abs(depth_img) > 0.15)
    nn = np.clip((depth_img - dmin) / (dmax - dmin), 0, 1)
    img2[m2] = turbo(nn[m2])

    combined = np.concatenate([img, np.full((h, 4, 3), 60, np.uint8), img2], axis=1)
    big = Image.fromarray(combined).resize(
        (combined.shape[1] * 4, combined.shape[0] * 4), Image.NEAREST)
    big.save(out)
    print(f"{out}  {big.size[0]}x{big.size[1]}  grid {w}x{h} @ {step} mm/px")
    print(f"  depth range used: {dmin} .. {dmax} mm")
    print(f"  coverage: {100.0*mask.sum()/(w*h):.1f}% of cells have a point")


if __name__ == "__main__":
    main()
