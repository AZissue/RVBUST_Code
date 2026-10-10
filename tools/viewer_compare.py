# -*- coding: utf-8 -*-
"""
旧控件 (EmbeddedPointCloudViewer, 含 3mm 体素抽稀) vs 新控件 (VTKPointCloudView,
全量渲染) 对照 demo。

用法（conda rvc 环境）：
    python tools/viewer_compare.py [--tiers 1M,2.82M,5M] [--seconds 10]

每档：同一朵云先后在两控件的真实 900x600 窗口里连续旋转 10 s，
记录 输入点数 / 显示点数 / 平均fps / 最小fps，最后打印对照表。
点云来源（真实数据，非合成）：
    - offline_data/session_20260909_173447/frame_0017/cam0.ply
      RVC 实拍 2448x2048 全量深度图（5,013,504 点，含 NaN）；
      1M / 2.82M 档 = 该云前缀切片（demo 输入准备，与控件抽稀无关）；
      2.82M 与 MultiCameraCalibration.log (2026-09-10) 降采样日志同点数。
    - 叶片拼接.ply（Open3D 双精度真实拼接云，1,814,567 点）。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt, QElapsedTimer, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

import open3d as o3d  # noqa: E402

from ui.viewer_3d import EmbeddedPointCloudViewer  # noqa: E402
from ui.vtk_viewer import VTKPointCloudView  # noqa: E402

REAL_CLOUD = ROOT / "offline_data" / "session_20260909_173447" / "frame_0017" / "cam0.ply"
MERGED_CLOUD = ROOT / "叶片拼接.ply"

WIN_W, WIN_H = 900, 600
POINT_SIZE = 2
SPIN_DEG_PER_FRAME = 2.0     # 每帧绕世界 Z(高度轴) 转的角度
CAM0_SLICE_NOTE = "offline_data/session_20260909_173447/frame_0017/cam0.ply 前缀切片"


def load_ply(path: Path, limit: int = 0):
    """返回 (points float32 (N,3), colors uint8 (N,3) 或 None, 总点数, 有效点数)。"""
    print(f"[load] {path.name}{f' 前 {limit} 点' if limit else ''} ...", flush=True)
    t0 = time.time()
    pcd = o3d.io.read_point_cloud(str(path))
    pts = np.asarray(pcd.points, dtype=np.float32)
    cols = np.asarray(pcd.colors, dtype=np.uint8) if pcd.has_colors() else None
    if cols is not None and cols.max() <= 1:          # open3d 颜色为 0~1 float
        cols = (np.asarray(pcd.colors) * 255.0).round().astype(np.uint8)
    total = len(pts)
    if limit:
        pts = pts[:limit]
        cols = cols[:limit] if cols is not None else None
    valid = int(np.isfinite(pts).all(axis=1).sum())
    print(f"[load] {total} 点(本档用 {len(pts)}), 有效 {valid}, "
          f"{time.time() - t0:.2f}s", flush=True)
    return pts, cols, total, valid


def make_tiers(names: list) -> list:
    tiers = []
    all_specs = {
        "1M": ("1M(真实云切片)", REAL_CLOUD, 1_000_000, CAM0_SLICE_NOTE),
        "2.82M": ("2.82M(真实云切片,同日志点数)", REAL_CLOUD, 2_820_096, CAM0_SLICE_NOTE),
        "5M": ("5M(真实云整帧)", REAL_CLOUD, 0, str(REAL_CLOUD.relative_to(ROOT))),
        "1.81M": ("1.81M(真实拼接云)", MERGED_CLOUD, 0, str(MERGED_CLOUD.relative_to(ROOT))),
    }
    for n in names:
        label, path, limit, src = all_specs[n]
        pts, cols, total, valid = load_ply(path, limit)
        tiers.append((label, pts, cols, src, total, valid))
    return tiers


# ----------------------------------------------------------------------
# 旧控件：EmbeddedPointCloudViewer（自带 3mm 体素抽稀路径）
# ----------------------------------------------------------------------
def measure_old(app, points, colors, seconds):
    win = QMainWindow()
    win.resize(WIN_W, WIN_H)
    old = EmbeddedPointCloudViewer()
    win.setCentralWidget(old)
    win.show()

    viewer = old.viewer()
    # 包一层 paintGL 计帧（等 GL 初始化完成再开始）
    painted = {"n": 0, "ready": False, "ts": []}
    orig_paint = viewer.paintGL

    def counted_paint():
        orig_paint()
        painted["n"] += 1
        painted["ts"].append(time.perf_counter())
        painted["ready"] = True

    viewer.paintGL = counted_paint

    while not painted["ready"]:
        app.processEvents()
        time.sleep(0.005)

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points.astype(np.float64))
    if colors is not None:
        pcd.colors = o3d.utility.Vector3dVector(colors.astype(np.float64) / 255.0)
    old.set_pointcloud("cam0", pcd)
    for _ in range(50):                      # 让抽稀结果上传、首帧出来
        app.processEvents()
        time.sleep(0.005)

    # overlay 走多路 VBO 路径，单路属性 point_count 不更新；
    # 显示点数 = 各 cloud VBO 的 point_count 之和
    displayed = sum(int(c.get("point_count", 0))
                    for c in viewer._clouds.values())
    input_n = len(points)

    # 连续旋转：直接累积 ArcBall 旋转矩阵（等效左键拖动）
    rad = np.radians(SPIN_DEG_PER_FRAME)
    R = np.array([[np.cos(rad), -np.sin(rad), 0.0],
                  [np.sin(rad), np.cos(rad), 0.0],
                  [0.0, 0.0, 1.0]], dtype=np.float32)
    spin = QTimer()
    spin.timeout.connect(lambda: (setattr(viewer.camera, "_rotation",
                                          R @ viewer.camera._rotation),
                                  viewer.update()))
    painted["ts"].clear()
    spin.start(0)
    t_end = time.perf_counter() + seconds
    while time.perf_counter() < t_end:
        app.processEvents()
        time.sleep(0.001)
    spin.stop()
    # 末帧可能还在队列里，多转几拍
    for _ in range(10):
        app.processEvents()
        time.sleep(0.002)

    ts = painted["ts"]
    fps_avg = (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 else 0.0
    dts = np.diff(ts)
    fps_min = 1.0 / dts.max() if len(dts) else 0.0
    win.close()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.002)
    return dict(displayed=displayed, input_n=input_n,
                fps_avg=fps_avg, fps_min=fps_min)


# ----------------------------------------------------------------------
# 新控件：VTKPointCloudView（全量上传，零下采样）
# ----------------------------------------------------------------------
def measure_new(app, points, colors, seconds, cold_start=None):
    t0 = time.perf_counter()
    new = VTKPointCloudView()
    construct_s = time.perf_counter() - t0
    if cold_start is not None:
        cold_start["vtk_first_construct_s"] = construct_s

    win = QMainWindow()
    win.resize(WIN_W, WIN_H)
    win.setCentralWidget(new)
    win.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.005)

    new.set_pointcloud("cam0", points, colors)
    new.set_point_size(POINT_SIZE)
    new.set_show_grid(False)
    new.set_show_axes(False)
    app.processEvents()

    stats = new.stats().get("cam0", {})
    displayed = int(stats.get("displayed_count", 0))
    input_n = int(stats.get("input_count", 0))

    ren = new._ren
    rw = new.interactor().GetRenderWindow()
    frames = {"ts": []}

    def spin_frame():
        ren.GetActiveCamera().Azimuth(SPIN_DEG_PER_FRAME)
        t = time.perf_counter()
        rw.Render()
        frames["ts"].append(t)

    spin = QTimer()
    spin.timeout.connect(spin_frame)
    spin.start(0)
    t_end = time.perf_counter() + seconds
    while time.perf_counter() < t_end:
        app.processEvents()
        time.sleep(0.001)
    spin.stop()

    ts = frames["ts"]
    fps_avg = (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 else 0.0
    dts = np.diff(ts)
    fps_min = 1.0 / dts.max() if len(dts) else 0.0
    win.close()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.002)
    return dict(displayed=displayed, input_n=input_n,
                fps_avg=fps_avg, fps_min=fps_min, construct_s=construct_s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="1M,2.82M,5M,1.81M",
                    help="逗号分隔：1M,2.82M,5M,1.81M")
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    tiers = make_tiers(args.tiers.split(","))

    cold = {}
    print(f"\n窗口 {WIN_W}x{WIN_H}, 点大小 {POINT_SIZE}, 每档连转 {args.seconds}s\n", flush=True)
    header = (f"{'档位':<28} {'输入':>9} {'旧显示':>9} {'旧fps均/小':>14} "
              f"{'新显示':>9} {'新fps均/小':>14} 显示==输入")
    print(header, flush=True)
    print("-" * len(header) * 2, flush=True)

    results = []
    for label, pts, cols, src, total, valid in tiers:
        r_old = measure_old(app, pts, cols, args.seconds)
        r_new = measure_new(app, pts, cols, args.seconds,
                            cold_start=cold if "vtk_first_construct_s" not in cold else None)
        ok = "OK" if r_new["displayed"] == r_new["input_n"] else \
             f"FAIL(差 {r_new['input_n'] - r_new['displayed']})"
        row = (f"{label:<28} {r_old['input_n']:>9} {r_old['displayed']:>9} "
               f"{r_old['fps_avg']:>6.1f}/{r_old['fps_min']:>5.1f} "
               f"{r_new['displayed']:>9} {r_new['fps_avg']:>6.1f}/{r_new['fps_min']:>5.1f} {ok}")
        print(row, flush=True)
        results.append((label, src, total, valid, r_old, r_new))

    print(f"\n[vtk 冷启动] 首次构造 VTKPointCloudView 耗时 "
          f"{cold.get('vtk_first_construct_s', float('nan')):.2f}s"
          f"（含惰性 import vtk + 建渲染窗）", flush=True)
    print("\n点云来源:", flush=True)
    for label, src, *_ in results:
        print(f"  {label}: {src}", flush=True)


if __name__ == "__main__":
    main()
