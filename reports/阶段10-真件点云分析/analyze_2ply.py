#!/usr/bin/env python3
"""阶段 10 真件点云探针：把 2.ply（平面 + 5 mm 孔）的几何量出来。

为什么要它：用户实测「助手读出 5.4321 mm，名义 5 mm」(+8.64%)。合成回归只能证明
*算法在理想场景下的行为*，真件上误差往哪个方向偏、偏多少、为什么偏，必须从真实
点云里量出来。这个脚本只读数据、不碰产品代码，结论落 txt。

用法：
    python -I reports/阶段10-真件点云分析/analyze_2ply.py <file.ply> [--out out.txt]

输出：
  1. 点云清况（点数/包围盒/非有限点/飞点）
  2. 稳健平面拟合（RANSAC 式迭代，MAD 剔除）
  3. (半径, 深度) 二维直方图 —— 孔壁/孔口/倒角在图上长什么样
  4. 孔口半径（最内材料边缘）拟合 —— 这是「孔径」工具应当报出的那个数
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

PLY_TYPES = {
    "char": ("b", 1), "int8": ("b", 1),
    "uchar": ("B", 1), "uint8": ("B", 1),
    "short": ("h", 2), "int16": ("h", 2),
    "ushort": ("H", 2), "uint16": ("H", 2),
    "int": ("i", 4), "int32": ("i", 4),
    "uint": ("I", 4), "uint32": ("I", 4),
    "float": ("f", 4), "float32": ("f", 4),
    "double": ("d", 8), "float64": ("d", 8),
}


def read_ply(path: Path):
    """只取 vertex 的 x/y/z。返回 (N,3) float64 + 头条信息。"""
    raw = path.read_bytes()
    end = raw.find(b"end_header")
    if end < 0:
        raise SystemExit("not a ply: no end_header")
    nl = raw.find(b"\n", end)
    header = raw[: nl + 1].decode("ascii", "replace")
    body = raw[nl + 1:]

    fmt = None
    n_vertex = 0
    props: list[tuple[str, int]] = []      # (name, bytes) in declared order
    in_vertex = False
    for line in header.splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == "format":
            fmt = t[1]
        elif t[0] == "element":
            in_vertex = (t[1] == "vertex")
            if in_vertex:
                n_vertex = int(t[2])
            else:
                # 只支持只有 vertex 的文件；别的 element 会让 stride 算错
                raise SystemExit(f"unsupported extra element: {line!r}")
        elif t[0] == "property" and in_vertex:
            if t[1] == "list":
                raise SystemExit("list property unsupported")
            props.append((t[2], PLY_TYPES[t[1]][1]))   # type name / size

    stride = sum(s for _, s in props)
    off = {}
    acc = 0
    for name, size in props:
        off[name] = (acc, size)
        acc += size

    if fmt == "binary_little_endian":
        # 按 ply 声明的类型建结构化 dtype —— 宽度对但类型错会静默读出垃圾
        kind_map = {}
        for line in header.splitlines():
            t = line.split()
            if t and t[0] == "property" and len(t) == 3 and t[1] != "list":
                kind_map[t[2]] = t[1]
        fields = []
        for name, _ in props:
            ty = kind_map[name]
            code, size = PLY_TYPES[ty]
            npk = {1: "u1", 2: "<i2" if code in "h" else "<u2",
                   4: "<i4" if code in "i" else ("<u4" if code in "I" else "<f4"),
                   8: "<f8" if code == "d" else "<i8"}[size]
            fields.append((name, npk))
        dt = np.dtype(fields)
        arr = np.frombuffer(body, dtype=dt, count=n_vertex)
        xyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float64)
    elif fmt == "ascii":
        vals = np.array(body.split(), dtype=np.float64)[: n_vertex * len(props)]
        vals = vals.reshape(n_vertex, len(props))
        idx = {n: i for i, (n, _) in enumerate(props)}
        xyz = vals[:, [idx["x"], idx["y"], idx["z"]]]
    else:
        raise SystemExit(f"unsupported format {fmt}")

    return xyz, {
        "format": fmt,
        "vertices": n_vertex,
        "stride": stride,
        "props": [n for n, _ in props],
        "header_bytes": len(raw[: nl + 1]),
    }


def robust_plane(pts: np.ndarray, band_mm=0.3, iters=8):
    """拟合占比最大的那个平面。返回 (法向, 平面常数 c, 内点掩码)，满足 n·p = c。"""
    work = pts.copy()
    mask = np.ones(len(pts), dtype=bool)
    normal = np.array([0.0, 0.0, 1.0])
    centroid = work.mean(axis=0)
    for _ in range(iters):
        centroid = work.mean(axis=0)
        q = work - centroid
        # 最小奇异向量 = 平面法向
        _, _, vt = np.linalg.svd(q, full_matrices=False)
        normal = vt[2]
        d = q @ normal
        med = np.median(d)
        mad = np.median(np.abs(d - med)) or 1e-9
        sigma = 1.4826 * mad
        keep = np.abs(d - med) <= max(band_mm, 3.0 * sigma)
        if keep.all():
            break
        work = work[keep]
    centroid = work.mean(axis=0)
    q = work - centroid
    _, _, vt = np.linalg.svd(q, full_matrices=False)
    normal = vt[2]
    c = float(normal @ centroid)
    d_all = pts @ normal - c
    return normal, c, np.abs(d_all) <= band_mm, d_all


def ascii_map(counts, fname, rows_label, cols_label, header):
    """把二维计数表打成灰度字符图（0-9）。"""
    out = [header]
    colw = max(len(s) for s in cols_label)
    out.append(" " * 12 + " ".join(f"{s:>{colw}}" for s in cols_label))
    mx = counts.max() or 1
    for i, rname in enumerate(rows_label):
        line = f"{rname:>10}  "
        for j in range(counts.shape[1]):
            v = counts[i, j]
            if v == 0:
                line += " " * (colw + 1)
            else:
                lvl = int(round(9 * np.log1p(v) / np.log1p(mx)))
                line += f"{lvl:>{colw}}" + " "
        out.append(line)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ply")
    ap.add_argument("--out")
    args = ap.parse_args()

    p = Path(args.ply)
    xyz, meta = read_ply(p)

    lines = []
    def say(s=""):
        lines.append(s)

    say(f"# 真件点云分析 —— {p}")
    say(f"# 头: format={meta['format']}  vertices={meta['vertices']}  "
        f"stride={meta['stride']}B  props={','.join(meta['props'])}")
    say()

    finite = np.isfinite(xyz).all(axis=1)
    say(f"## 1. 点云清况")
    say(f"  非有限点（NaN/inf）: {np.count_nonzero(~finite)}")
    pts = xyz[finite]
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    say(f"  包围盒 min = ({lo[0]:.3f}, {lo[1]:.3f}, {lo[2]:.3f})")
    say(f"          max = ({hi[0]:.3f}, {hi[1]:.3f}, {hi[2]:.3f})")
    say(f"          size = ({hi[0]-lo[0]:.3f}, {hi[1]-lo[1]:.3f}, {hi[2]-lo[2]:.3f}) mm")
    say()

    # 2. 平面
    normal, c, in_plane, dep = robust_plane(pts)
    n_plane = int(in_plane.sum())
    say(f"## 2. 稳健平面拟合（带内 |d| ≤ 0.3 mm）")
    say(f"  法向 n = ({normal[0]:+.5f}, {normal[1]:+.5f}, {normal[2]:+.5f})  c = {c:+.4f}")
    tilt = np.degrees(np.arccos(min(1.0, abs(normal[2]))))
    say(f"  与 Z 轴夹角 = {tilt:.3f}°")
    say(f"  平面内点 {n_plane} / {len(pts)} = {100.0*n_plane/len(pts):.1f}%")
    # 平面残差的稳健尺度
    d_in = dep[in_plane]
    say(f"  平面残差: std={d_in.std():.4f} mm   "
        f"PV={d_in.max()-d_in.min():.4f} mm   "
        f"MADσ={1.4826*np.median(np.abs(d_in-np.median(d_in))):.4f} mm")
    # 离面点（孔内 / 飞点）深度分布
    off = dep[~in_plane]
    say(f"  离面点 {off.size} 个，深度范围 {off.min():+.3f} … {off.max():+.3f} mm")
    say()

    # 3. 平面坐标 + 圆心初值
    #    取平面内点，用"平面内每角度最小半径"迭代拟合孔口圆
    u_ax = np.cross(normal, [0.0, 0.0, 1.0])
    if np.linalg.norm(u_ax) < 1e-6:
        u_ax = np.array([1.0, 0.0, 0.0])
    u_ax /= np.linalg.norm(u_ax)
    v_ax = np.cross(normal, u_ax)

    def to_uv(P):
        return np.stack([P @ u_ax, P @ v_ax], axis=1)

    uv_plane = to_uv(pts[in_plane])
    centre0 = uv_plane.mean(axis=0)

    def fit_hole(uv, c0, max_r=6.0, iters=12):
        """按角度最小半径迭代拟合内边界（孔口）。"""
        cen = c0.copy()
        for _ in range(iters):
            dv = uv - cen
            r = np.hypot(dv[:, 0], dv[:, 1])
            m = r < max_r
            if m.sum() < 12:
                return cen, None
            ang = np.arctan2(dv[m, 1], dv[m, 0])
            rr = r[m]
            nbin = 240
            bins = ((ang + np.pi) / (2 * np.pi) * nbin).astype(int) % nbin
            sel = []
            for b in range(nbin):
                idx = np.nonzero(bins == b)[0]
                if idx.size == 0:
                    continue
                sel.append(idx[np.argmin(rr[idx])])
            sel = np.array(sel, dtype=int)
            edge = uv[m][sel]
            # 代数圆拟合（Kasa）
            A = np.column_stack([2 * edge[:, 0], 2 * edge[:, 1], np.ones(len(edge))])
            b = (edge ** 2).sum(axis=1)
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            cx, cy = sol[0], sol[1]
            rad = float(np.sqrt(sol[2] + cx * cx + cy * cy))
            if np.hypot(cx - cen[0], cy - cen[1]) < 1e-4:
                cen = np.array([cx, cy])
                break
            cen = np.array([cx, cy])
        # 半径用 edge 点的稳健中位数（对单个飞点不敏感）
        r_edge = np.hypot(edge[:, 0] - cen[0], edge[:, 1] - cen[1])
        return cen, (float(np.median(r_edge)), r_edge, edge)

    cen, res = fit_hole(uv_plane, centre0)
    say(f"## 3. 孔口圆拟合（只看平面内的点 → 这是「孔径」工具应报的数）")
    say(f"  圆心（平面系） = ({cen[0]:.4f}, {cen[1]:.4f})")
    if res is None:
        say("  拟合失败：平面内点太少")
    else:
        r_med, r_edge, edge = res
        say(f"  孔口半径 中位数 = {r_med:.4f} mm  → 直径 {2*r_med:.4f} mm")
        say(f"  孔口半径 均值   = {r_edge.mean():.4f} mm  → 直径 {2*r_edge.mean():.4f} mm")
        say(f"  孔口半径 极差   = {r_edge.max()-r_edge.min():.4f} mm"
            f"   (min {r_edge.min():.4f} / max {r_edge.max():.4f})")
        say(f"  边界点数 = {edge.size}")
    say()

    # 4. (r, d) 二维直方图 —— 看孔壁/倒角/沉孔
    all_uv = to_uv(pts)
    all_r = np.hypot(all_uv[:, 0] - cen[0], all_uv[:, 1] - cen[1])
    rmax = min(4.0, float(np.percentile(all_r, 99.5)))
    dr, dd = 0.04, 0.1
    rbins = np.arange(0.0, rmax + dr, dr)
    dmin = float(np.percentile(dep, 0.5))
    dmax = 0.6
    dbins = np.arange(dmin, dmax + dd, dd)
    H, _, _ = np.histogram2d(dep, all_r, bins=[dbins, rbins])
    say(f"## 4. (深度 d, 半径 r) 点密度图   d<0 = 低于平面（孔内）")
    say(f"  行 = 深度（步长 {dd} mm，上=深下=浅），列 = 半径（步长 {dr} mm）")
    say("  0-9 = log 计数的相对大小，空格 = 无点")
    # 行：深 → 浅打印
    rows = [f"{dbins[i]:+.2f}" for i in range(len(dbins) - 1)]
    cols = [f"{rbins[j]:.2f}" for j in range(0, len(rbins) - 1, 5)]
    say(ascii_map(H[::-1, ::5], "H", rows[::-1], cols, "  d\\r"))
    say()

    # 5. 每个半径上，点的深度范围 —— 倒角/沉孔会在这里露出来
    say("## 5. 半径切片：每个半径处的深度分布（中位数 / 5% / 95%）")
    say(f"{'r(mm)':>7} {'n':>7} {'d中位':>9} {'d 5%':>9} {'d 95%':>9}")
    for j in range(len(rbins) - 1):
        m = (all_r >= rbins[j]) & (all_r < rbins[j + 1])
        if m.sum() < 10:
            continue
        dj = dep[m]
        say(f"{rbins[j]:>7.2f} {m.sum():>7} {np.median(dj):>9.3f} "
            f"{np.percentile(dj, 5):>9.3f} {np.percentile(dj, 95):>9.3f}")
    say()

    # 6. 稳健口径下的孔半径（不依赖极值，对孔壁点/飞点更宽容）
    say("## 6. 交叉验证：不同口径下的孔直径")
    face = in_plane
    r_face = np.hypot(uv_plane[:, 0] - cen[0], uv_plane[:, 1] - cen[1])
    say(f"  平面内点最小半径的 1% 分位 : {np.percentile(r_face, 1):.4f} mm "
        f"→ 直径 {2*np.percentile(r_face,1):.4f} mm")
    say(f"  平面内点最小半径的 5% 分位 : {np.percentile(r_face, 5):.4f} mm "
        f"→ 直径 {2*np.percentile(r_face,5):.4f} mm")
    say(f"  按角度的最小值再取中位数   : {r_med if res else float('nan'):.4f} mm "
        f"→ 直径 {2*(r_med if res else float('nan')):.4f} mm")

    # 7. 细半径分箱：材料面在哪结束、孔口在哪开始
    say("## 7. 细半径分箱（步长 0.02 mm）—— 找「材料面结束 / 孔口开始」的拐点")
    say(f"{'r(mm)':>7} {'n':>6} {'|d|<0.05':>9} {'d中位':>8} {'d5%':>8} {'d95%':>8} "
        f"{'dmin':>8} {'dmax':>8}")
    r0, r1, step = 2.00, 3.60, 0.02
    for rlo in np.arange(r0, r1, step):
        m = (all_r >= rlo) & (all_r < rlo + step)
        if m.sum() < 5:
            continue
        dj = dep[m]
        near = 100.0 * np.count_nonzero(np.abs(dj) < 0.05) / dj.size
        say(f"{rlo:>7.2f} {m.sum():>6} {near:>8.0f}% {np.median(dj):>8.3f} "
            f"{np.percentile(dj,5):>8.3f} {np.percentile(dj,95):>8.3f} "
            f"{dj.min():>8.3f} {dj.max():>8.3f}")
    say()

    # 8. 紧带平面点的半径分布（孔口半径的另一种口径）
    tight = np.abs(dep) < 0.05
    r_tight = np.hypot(all_uv[tight, 0] - cen[0], all_uv[tight, 1] - cen[1])
    say("## 8. 只取 |d|<0.05 mm 的「平面」点：它们的最小半径就是孔口半径")
    for q in (0.5, 1, 2, 5, 10):
        rq = np.percentile(r_tight, q)
        say(f"  {q:>4.1f}% 分位 r={rq:.4f} mm → 直径 {2*rq:.4f} mm")
    say(f"  紧带点数 {tight.sum()}（占 {100.0*tight.sum()/len(pts):.1f}%）")
    say()

    # 9. 孔壁点（明显低于平面）的半径分布
    wall = dep > 0.3
    r_wall = np.hypot(all_uv[wall, 0] - cen[0], all_uv[wall, 1] - cen[1])
    say("## 9. 孔壁点（d > 0.3 mm，即明显低于平面）的半径分布")
    if wall.sum() < 10:
        say("  孔内几乎没有点（传感器没看到孔壁）")
    else:
        say(f"  点数 {wall.sum()}，深度 {dep[wall].min():.3f} … {dep[wall].max():.3f} mm")
        for q in (5, 25, 50, 75, 95):
            rq = np.percentile(r_wall, q)
            say(f"  {q:>4.1f}% 分位 r={rq:.4f} mm → 直径 {2*rq:.4f} mm")
    say()

    # 10. 俯视高度图（ASCII）—— 孔/倒角/沉孔长什么样，一眼看
    say("## 10. 俯视图（每格 = 1×1 mm，字符 = 该格点的中位深度 d）")
    say("   ' ' 无点   '.' |d|<0.03   '-' 0.03..0.1   'o' 0.1..0.3   "
        "'O' 0.3..1   '#' >1 mm（越深字符越重）")
    gstep = 1.0
    gul = np.floor(np.min(all_uv, axis=0) / gstep) * gstep
    guh = np.ceil(np.max(all_uv, axis=0) / gstep) * gstep
    ngu = int(round((guh[0] - gul[0]) / gstep))
    ngv = int(round((guh[1] - gul[1]) / gstep))
    gi = np.clip(((all_uv - gul) / gstep).astype(int), 0, [ngu - 1, ngv - 1])
    grid = np.full((ngv, ngu), np.nan)
    for iv in range(ngv - 1, -1, -1):     # v 从上往下打
        row = ""
        for iu in range(ngu):
            m = (gi[:, 0] == iu) & (gi[:, 1] == iv)
            if not m.any():
                row += " "
                continue
            v = float(np.median(dep[m]))
            a = abs(v)
            row += ("." if a < 0.03 else "-" if a < 0.1 else
                    "o" if a < 0.3 else "O" if a < 1.0 else "#")
        grid[iv] = 0
        say(f"  {row}")
    say(f"  网格 {ngu}×{ngv}，每格 {gstep} mm")

    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
