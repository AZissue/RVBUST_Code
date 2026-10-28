# -*- coding: utf-8 -*-
"""凳子拼接数据一键离线拼接 + 后处理。

流程：
  1. 扫描文件夹内 图像+PLY 文件对（1.png/1.ply ... 8.png/8.ply）；
  2. 逐帧编码圆检测（2D+3D），ChainStitcher 链式配准拼接；
  3. 保存原始彩色合并点云 <文件夹>_merged_raw.ply；
  4. 后处理：高光亮面区域剔除（近白高亮低饱和点）→ 统计离群点去除
     → auto_tune 体素下采样；
  5. 保存后处理结果 <文件夹>_merged_processed.ply。

用法：
  python run_stool_stitch.py [数据文件夹]
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(os.path.dirname(_HERE))  # MultiCameraCalibration/
for _p in (os.path.join(_PROJECT, "src"), os.path.join(_HERE, "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import open3d as o3d

from offline_stitcher import OfflineStitcher  # noqa: E402


def remove_specular(pcd: "o3d.geometry.PointCloud",
                    bright_thresh: float = 200.0,
                    sat_thresh: float = 40.0) -> "o3d.geometry.PointCloud":
    """剔除材质反光亮面区域：近白色高亮低饱和点（RGB 0~255 系）。

    亮面高光在彩色图上呈"各通道同时很高且接近"（max>bright_thresh 且
    max-min<sat_thresh），与橙色凳面（B 通道低）、灰色地面（亮度中等）
    可区分；地面/凳面上的反光斑与白色标记纸带一并被剔除。
    """
    colors = np.asarray(pcd.colors)
    if len(colors) == 0:
        return pcd
    rgb = colors * 255.0
    mx = rgb.max(axis=1)
    mn = rgb.min(axis=1)
    keep = ~((mx > bright_thresh) & ((mx - mn) < sat_thresh))
    removed = int((~keep).sum())
    print(f"高光剔除: 移除 {removed:,}/{len(colors):,} 点 "
          f"({removed / len(colors) * 100:.1f}%)")
    return pcd.select_by_index(np.where(keep)[0])


def main() -> int:
    data_dir = sys.argv[1] if len(sys.argv) > 1 else r"E:/jingz/Desktop/凳子拼接"
    base = os.path.basename(data_dir.rstrip("/\\"))
    out_raw = os.path.join(data_dir, f"{base}_merged_raw.ply")
    out_final = os.path.join(data_dir, f"{base}_merged_processed.ply")

    stitcher = OfflineStitcher(min_common_markers=3,
                               min_inlier_ratio=0.4,
                               max_rms_mm=2.0)
    n, msg = stitcher.load_directory(data_dir, recursive=False)
    print(msg)
    if n == 0:
        return 1

    # 自然排序：1,2,...,8（避免 10 排在 2 前）
    stitcher.pairs.sort(key=lambda p: int(p.name) if p.name.isdigit() else p.name)
    for pair in stitcher.pairs:
        ok, msg = stitcher.add_pair_to_chain(pair)
        print(f"[{pair.name}] {'OK ' if ok else 'FAIL'} {msg}")

    merged, msg = stitcher.stitch()
    print(msg)
    if merged is None:
        return 1
    print("误差报告:", stitcher.chain_stitcher.get_error_report())

    o3d.io.write_point_cloud(out_raw, merged)
    print(f"原始彩色合并点云已保存: {out_raw} ({len(merged.points):,} 点)")

    # ---- 后处理 ----
    merged = remove_specular(merged)

    from core.point_cloud_processor import PointCloudProcessor
    processor = PointCloudProcessor()
    tuned = processor.auto_tune(merged, target_points=800_000)
    for note in tuned["notes"]:
        print("  auto_tune:", note)
    processor.crop_mode = tuned["crop_mode"]
    processor.crop_ratio = tuned["crop_ratio"]
    processor.enable_voxel_downsample = tuned["enable_voxel_downsample"]
    processor.voxel_size = tuned["voxel_size"]  # 单位已是 mm，点云也是 mm
    processor.enable_outlier_removal = True
    processor.outlier_nb_neighbors = tuned["outlier_nb_neighbors"]
    processor.outlier_std_ratio = tuned["outlier_std_ratio"]

    final, stats = processor.process(merged)
    print(f"后处理统计: {stats}")
    o3d.io.write_point_cloud(out_final, final)
    print(f"后处理点云已保存: {out_final} ({len(final.points):,} 点)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
