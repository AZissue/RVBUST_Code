# -*- coding: utf-8 -*-
"""
点云后处理器（PointCloudProcessor）。

从 DualCameraFusion/src/app.py:1289-1392 原样抽取。
功能：裁切（AABB 中心比例 / 球 / OBB 主轴）+ 体素下采样 + 统计离群点去除。

注意：open3d / numpy 均为函数内延迟导入，模块顶层无重依赖，
且已修正原 app.py 中 _crop_center_aabb 未 import o3d 的隐患
（本文件每个方法都显式 import 所需库）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import open3d as o3d


class PointCloudProcessor:
    """点云后处理器：裁切 + 下采样 + 滤波。"""

    def __init__(self):
        self.voxel_size = 0.5  # mm
        self.enable_voxel_downsample = False
        self.crop_mode = "none"  # none | aabb | sphere | obb
        self.crop_ratio = 0.6
        self.crop_radius = 500.0  # mm
        self.enable_outlier_removal = False
        self.outlier_nb_neighbors = 20
        self.outlier_std_ratio = 2.0

    def process(self, pcd: 'o3d.geometry.PointCloud') -> 'o3d.geometry.PointCloud':
        """按配置顺序处理点云，返回 (结果点云, 统计信息)。"""
        result = pcd
        stats = {"input_points": len(pcd.points)}

        # 1. 中心裁切
        if self.crop_mode == "aabb":
            result = self._crop_center_aabb(result)
            stats["after_crop"] = len(result.points)
        elif self.crop_mode == "sphere":
            result = self._crop_center_sphere(result)
            stats["after_crop"] = len(result.points)
        elif self.crop_mode == "obb":
            result = self._crop_center_obb(result)
            stats["after_crop"] = len(result.points)

        # 2. 体素下采样
        if self.enable_voxel_downsample and self.voxel_size > 0:
            result = result.voxel_down_sample(self.voxel_size)
            stats["after_downsample"] = len(result.points)

        # 3. 统计离群点去除
        if self.enable_outlier_removal:
            result, _ = result.remove_statistical_outlier(
                nb_neighbors=self.outlier_nb_neighbors,
                std_ratio=self.outlier_std_ratio
            )
            stats["after_filter"] = len(result.points)

        return result, stats

    def _crop_center_aabb(self, pcd: 'o3d.geometry.PointCloud') -> 'o3d.geometry.PointCloud':
        """保留 AABB 中心 crop_ratio 比例的区域。"""
        import open3d as o3d
        bbox = pcd.get_axis_aligned_bounding_box()
        min_b = bbox.get_min_bound()
        max_b = bbox.get_max_bound()
        center = (min_b + max_b) / 2
        half_ext = (max_b - min_b) / 2 * self.crop_ratio
        min_crop = center - half_ext
        max_crop = center + half_ext
        bbox_crop = o3d.geometry.AxisAlignedBoundingBox(min_crop, max_crop)
        return pcd.crop(bbox_crop)

    def _crop_center_sphere(self, pcd: 'o3d.geometry.PointCloud') -> 'o3d.geometry.PointCloud':
        """以点云质心为球心，保留半径内点。"""
        import numpy as np
        points = np.asarray(pcd.points)
        center = np.mean(points, axis=0)
        dists = np.linalg.norm(points - center, axis=1)
        mask = dists <= self.crop_radius
        indices = np.where(mask)[0]
        return pcd.select_by_index(indices)

    def _crop_center_obb(self, pcd: 'o3d.geometry.PointCloud') -> 'o3d.geometry.PointCloud':
        """基于 OBB 主轴方向裁切。"""
        import numpy as np
        bbox = pcd.get_oriented_bounding_box()
        center = bbox.center
        half_ext = bbox.extent / 2 * self.crop_ratio
        points = np.asarray(pcd.points)
        local_pts = (points - center) @ bbox.R
        mask = np.all((local_pts >= -half_ext) & (local_pts <= half_ext), axis=1)
        indices = np.where(mask)[0]
        return pcd.select_by_index(indices)

    def auto_tune(self, pcd: 'o3d.geometry.PointCloud',
                  target_points: int = 800_000) -> dict:
        """根据实际点云数据自动估计合理的后处理参数。

        解决默认参数（裁切 0.6 / 球半径 500mm / 体素 0.5mm）对真实数据
        过激、可能把点云"全滤掉"的问题：
          - 自动检测数据单位（米 / 毫米），内部统一换算到 mm 估计；
          - 平均点距用 KDTree + 随机采样（≤3000 点）估计，百万级点云不做全量最近邻；
          - 体素大小由点数 / 目标点数反推，避免过采或欠采；
          - 裁切默认推荐"不裁切"，仅在 P1~P99 核心范围明显小于全范围
            （存在飞点）时推荐 AABB 中心裁切；
          - 最后用推荐参数实跑一遍 process()，给出真实预估点数（数据就是证据）。

        Args:
            pcd: 输入点云（任意单位，自动检测）
            target_points: 目标点数（体素下采样的反推基准）

        Returns:
            参数字典，键：unit / unit_scale / diag_mm / avg_spacing_mm /
            crop_mode / crop_ratio / crop_radius(mm) / enable_voxel_downsample /
            voxel_size(mm) / enable_outlier_removal / outlier_nb_neighbors /
            outlier_std_ratio / estimated_points / notes。
            其中 voxel_size、crop_radius 一律以 mm 输出（供 UI 显示）；
            内部实跑 process() 时已按 unit_scale 换算回点云原始单位。
        """
        import numpy as np
        import open3d as o3d

        notes = []
        pts = np.asarray(pcd.points)
        n = int(pts.shape[0])
        if n < 10:
            raise ValueError(f"点云点数过少（{n}），无法自动估计参数")

        # ---- 1. 单位检测（按包围盒对角线量级）----
        min_b = pts.min(axis=0)
        max_b = pts.max(axis=0)
        diag = float(np.linalg.norm(max_b - min_b))
        if diag < 10.0:
            unit, unit_scale = 'm', 1000.0
        elif diag > 100.0:
            unit, unit_scale = 'mm', 1.0
        else:
            # 10~100 之间：RVC 近距离场景 mm 对角线一般几百，米单位一般 < 2m
            unit, unit_scale = ('m', 1000.0) if diag < 50.0 else ('mm', 1.0)
        diag_mm = diag * unit_scale
        notes.append(
            f"包围盒对角线 {diag_mm:.1f}mm → 判定单位为{'米' if unit == 'm' else '毫米'}"
            + ("（输出参数统一为 mm 量级；若处理管线直接用米单位点云，体素/半径需 ÷1000）"
               if unit == 'm' else ""))

        # ---- 2. 平均最近邻点距（随机采样 ≤3000 点查 KDTree，取中位数）----
        rng = np.random.default_rng(42)
        sample_n = min(3000, n)
        sample_idx = rng.choice(n, size=sample_n, replace=False)
        tree = o3d.geometry.KDTreeFlann(pcd)
        nn_dists = np.empty(sample_n, dtype=np.float64)
        for i, pi in enumerate(sample_idx):
            # 返回的 distances 为平方距离，[0] 是点自身（=0），[1] 为最近邻
            _, _, dist2 = tree.search_knn_vector_3d(pcd.points[int(pi)], 2)
            nn_dists[i] = dist2[1] if len(dist2) > 1 else 0.0
        avg_spacing_mm = float(np.median(np.sqrt(nn_dists))) * unit_scale
        notes.append(f"平均点距 ≈ {avg_spacing_mm:.3f}mm"
                     f"（采样 {sample_n} 点最近邻距离中位数）")

        # ---- 3. 体素大小：由 n / target_points 反推，限制上下限 ----
        if n <= target_points:
            enable_voxel = False
            # 仍给出一个合理的体素建议值（用户手动启用时可用）
            voxel_size = max(0.05, round(avg_spacing_mm * 1.5 / 0.05) * 0.05)
            notes.append(f"点数 {n:,} ≤ 目标 {target_points:,}，建议不启用体素下采样")
        else:
            ratio = (n / target_points) ** (1.0 / 3.0)
            voxel = avg_spacing_mm * ratio
            voxel = max(voxel, avg_spacing_mm * 1.5)  # 下限：避免过采
            voxel = min(voxel, diag_mm / 50.0)        # 上限：场景尺度的 1/50
            voxel_size = max(0.05, round(voxel / 0.05) * 0.05)  # 取整到 0.05mm 步长
            enable_voxel = True
            notes.append(f"体素={voxel_size:.2f}mm（平均点距{avg_spacing_mm:.2f}mm"
                         f" × {voxel_size / max(avg_spacing_mm, 1e-9):.1f}，"
                         f"目标{target_points / 10000:.0f}万点）")

        # ---- 4. 裁切：P1~P99 核心范围 vs 全范围，检测明显飞点 ----
        pts_mm = pts * unit_scale if unit_scale != 1.0 else pts
        p1 = np.percentile(pts_mm, 1, axis=0)
        p99 = np.percentile(pts_mm, 99, axis=0)
        full_range = (max_b - min_b) * unit_scale
        core_range = p99 - p1
        axis_ratio = np.divide(core_range, full_range,
                               out=np.ones_like(core_range),
                               where=full_range > 1e-12)
        min_ratio = float(axis_ratio.min())
        crop_ratio = float(np.clip(axis_ratio.max(), 0.3, 1.0))
        if min_ratio < 0.8:
            crop_mode = 'aabb'
            notes.append(f"检测到明显飞点（某轴 P1~P99 核心范围仅占全范围 "
                         f"{min_ratio * 100:.0f}%），建议 AABB 中心裁切，"
                         f"比例 {crop_ratio:.2f}")
        else:
            crop_mode = 'none'
            notes.append("点云分布集中、无明显飞点，建议不裁切"
                         "（零散飞点交给离群点去除）")
        crop_radius = round(diag_mm / 2.0, 1)  # 球形裁切的合理默认半径

        # ---- 5. 离群点去除：成熟默认值，飞点严重时收紧 ----
        enable_outlier = True
        outlier_nb = 20
        outlier_std = 1.5 if min_ratio < 0.6 else 2.0
        notes.append(f"离群点去除：nb_neighbors=20, std_ratio={outlier_std}"
                     + ("（飞点严重，收紧标准差）" if outlier_std == 1.5
                        else "（成熟默认值）"))

        # ---- 6. 用推荐参数实跑一遍 process()，得真实预估点数 ----
        proc = PointCloudProcessor()
        proc.crop_mode = crop_mode
        proc.crop_ratio = crop_ratio
        proc.crop_radius = crop_radius / unit_scale        # 换算回原始单位
        proc.enable_voxel_downsample = enable_voxel
        proc.voxel_size = voxel_size / unit_scale          # 换算回原始单位
        proc.enable_outlier_removal = enable_outlier
        proc.outlier_nb_neighbors = outlier_nb
        proc.outlier_std_ratio = outlier_std
        result, _stats = proc.process(pcd)
        estimated_points = len(result.points)
        notes.append(f"按推荐参数实跑验证：{n:,} → {estimated_points:,} 点")

        return {
            'unit': unit,
            'unit_scale': unit_scale,
            'diag_mm': diag_mm,
            'avg_spacing_mm': avg_spacing_mm,
            'crop_mode': crop_mode,
            'crop_ratio': crop_ratio,
            'crop_radius': crop_radius,
            'enable_voxel_downsample': enable_voxel,
            'voxel_size': voxel_size,
            'enable_outlier_removal': enable_outlier,
            'outlier_nb_neighbors': outlier_nb,
            'outlier_std_ratio': outlier_std,
            'estimated_points': estimated_points,
            'notes': notes,
        }

    def get_crop_bbox(self, pcd: 'o3d.geometry.PointCloud'):
        """获取当前裁切配置的包围盒（用于可视化）。"""
        import open3d as o3d
        import numpy as np
        if self.crop_mode == "aabb":
            bbox = pcd.get_axis_aligned_bounding_box()
            min_b = bbox.get_min_bound()
            max_b = bbox.get_max_bound()
            center = (min_b + max_b) / 2
            half_ext = (max_b - min_b) / 2 * self.crop_ratio
            return o3d.geometry.AxisAlignedBoundingBox(center - half_ext, center + half_ext)
        elif self.crop_mode == "sphere":
            # Open3D 没有球体包围盒，返回 None
            return None
        elif self.crop_mode == "obb":
            bbox = pcd.get_oriented_bounding_box()
            center = bbox.center
            half_ext = bbox.extent / 2 * self.crop_ratio
            obb = o3d.geometry.OrientedBoundingBox(center, bbox.R, half_ext * 2)
            return obb
        return None
