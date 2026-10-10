# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
test_pointcloud_processor.py —— PointCloudProcessor 默认行为测试（无 GUI、无需相机）。

背景（2026-09 现场 bug）：ui_v2 移除了后处理入口（src/ui_v2/main_window.py:14），
拼接输出使用裸默认 PointCloudProcessor：enable_outlier_removal / 裁切 / 体素
下采样全部关闭，合并点云中的飞点（噪点团）原样落盘。
而 auto_tune() 的推荐口径中离群点去除恒为 True（成熟默认值 nb=20, std=2.0）。
本测试锁定：默认构造的 processor 必须去除统计离群点，显式关闭时保留。

验证：
  [1] 默认 processor：密集平面 + 远处飞点 → 飞点被去除，平面点保留
  [2] 显式 enable_outlier_removal=False：飞点保留（开关仍然有效）
  [3] 默认仍剔除 NaN/Inf/全零点（既有行为不回退）
  [4] 默认不裁切、不体素下采样（保持最小行为面，仅开启离群点去除）

无 open3d 环境：自动跳过（模块按设计延迟导入）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

print("=" * 60)
print("PointCloudProcessor 默认行为测试")
print("=" * 60)

try:
    import open3d as o3d
    import numpy as np
except ImportError:
    print("\n[!] 未安装 open3d/numpy，跳过")
    sys.exit(0)

from core.point_cloud_processor import PointCloudProcessor  # noqa: E402


def make_cloud(n_grid: int = 50, n_outliers: int = 60, seed: int = 42):
    """密集 1mm 间距平面（z=0）+ 远处飞点团（z≈100~200mm）。"""
    rng = np.random.default_rng(seed)
    g = np.linspace(0, (n_grid - 1), n_grid)
    xs, ys = np.meshgrid(g, g)
    plane = np.stack([xs.ravel(), ys.ravel(), np.zeros(n_grid * n_grid)], axis=1)
    outliers = np.stack([
        rng.uniform(-500, 550, n_outliers),
        rng.uniform(-500, 550, n_outliers),
        rng.uniform(100, 200, n_outliers),
    ], axis=1)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.vstack([plane, outliers]))
    return pcd, n_grid * n_grid, n_outliers


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        print("\n测试失败：" + name)
        sys.exit(1)


# ------------------------------------------------------------------
# [1] 默认构造：离群点必须被去除（bug 修复点）
# ------------------------------------------------------------------
print("\n[1] 默认 processor 去除统计离群点")
pcd, n_plane, n_out = make_cloud()
proc_default = PointCloudProcessor()
result, stats = proc_default.process(pcd)
pts = np.asarray(result.points)
n_remaining = len(pts)
print(f"  输入 {n_plane + n_out} 点（平面 {n_plane} + 飞点 {n_out}）"
      f" → 输出 {n_remaining} 点, stats={stats}")
check("默认开启离群点去除", n_remaining < n_plane + n_out,
      f"输出 {n_remaining} 点，飞点未被去除")
check("平面点基本保留（≥95%）", n_remaining >= n_plane * 0.95,
      f"剩 {n_remaining} 点")
check("剩余点不含远飞点（z < 50mm）", bool((pts[:, 2] < 50).all()),
      f"z 最大 {pts[:, 2].max():.1f}mm" if n_remaining else "无点")

# ------------------------------------------------------------------
# [2] 显式关闭：飞点保留（开关语义不变）
# ------------------------------------------------------------------
print("\n[2] enable_outlier_removal=False 时飞点保留")
proc_off = PointCloudProcessor()
proc_off.enable_outlier_removal = False
result_off, _ = proc_off.process(pcd)
# 平面角点 (0,0,0) 会被无效点过滤（全零）剔除，属既有行为
check("飞点保留（除 1 个全零原点）", len(result_off.points) == n_plane + n_out - 1,
      f"输出 {len(result_off.points)} 点")

# ------------------------------------------------------------------
# [3] 默认仍剔除 NaN/Inf/全零点
# ------------------------------------------------------------------
print("\n[3] 无效点（NaN/Inf/零）默认剔除")
pcd_bad, _, _ = make_cloud(n_grid=10, n_outliers=0)
pts_bad = np.asarray(pcd_bad.points)
pts_bad[0] = [np.nan, 0, 0]
pts_bad[1] = [np.inf, 0, 0]
pts_bad[2] = [0, 0, 0]  # 与平面原点 (0,0,0) 共 2 个全零点
pcd_bad.points = o3d.utility.Vector3dVector(pts_bad)
# 关闭离群点去除以隔离 _filter_valid 行为
proc_bad = PointCloudProcessor()
proc_bad.enable_outlier_removal = False
result_bad, stats_bad = proc_bad.process(pcd_bad)
check("3 个无效点（NaN/Inf/零）被剔除",
      len(result_bad.points) == len(pts_bad) - 3 and stats_bad.get("invalid_removed") == 3,
      f"剩 {len(result_bad.points)} 点, invalid_removed={stats_bad.get('invalid_removed')}")
result_def, stats_def = PointCloudProcessor().process(pcd_bad)
check("默认路径同样报告 invalid_removed=3", stats_def.get("invalid_removed") == 3,
      f"invalid_removed={stats_def.get('invalid_removed')}")

# ------------------------------------------------------------------
# [4] 默认不裁切、不体素下采样（最小行为面）
# ------------------------------------------------------------------
print("\n[4] 默认不裁切 / 不下采样")
check("crop_mode 默认 none", proc_default.crop_mode == "none")
check("体素下采样默认关闭", proc_default.enable_voxel_downsample is False)

print("\n" + "=" * 60)
print("全部断言通过")
print("=" * 60)
