# -*- coding: utf-8 -*-
"""
标量场计算与色映射（Scalar Field）。

对标 CloudCompare 的 Scalar Fields 功能：
  - 高度 (Z)
  - 点密度（局部邻居数）
  - 曲率估计（PCA 最小特征值）
  - 强度（Intensity，需输入点云含 intensity 属性）
  - 距离（到某平面/点的距离）
"""

from __future__ import annotations

from typing import Optional

import numpy as np


# =========================================================================
# 色映射表（向量化）
# =========================================================================
def _jet_colormap(t: np.ndarray) -> np.ndarray:
    """matplotlib jet 的向量化实现。"""
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    r = np.interp(t, [0.0, 0.35, 0.66, 0.89, 1.0], [0.0, 0.0, 1.0, 1.0, 0.5])
    g = np.interp(t, [0.0, 0.125, 0.375, 0.64, 0.89, 1.0], [0.0, 0.0, 1.0, 1.0, 0.0, 0.0])
    b = np.interp(t, [0.0, 0.11, 0.34, 0.65, 1.0], [0.5, 1.0, 1.0, 0.0, 0.0])
    return np.stack([r, g, b], axis=1).astype(np.float32)


def _hot_colormap(t: np.ndarray) -> np.ndarray:
    """Hot 色映射。"""
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    r = np.clip(t * 3.0, 0.0, 1.0)
    g = np.clip((t - 1.0 / 3.0) * 3.0, 0.0, 1.0)
    b = np.clip((t - 2.0 / 3.0) * 3.0, 0.0, 1.0)
    return np.stack([r, g, b], axis=1).astype(np.float32)


def _coolwarm_colormap(t: np.ndarray) -> np.ndarray:
    """Coolwarm 色映射（蓝→白→红）。"""
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    # 简化版：线性插值
    colors = np.array([[0.23, 0.30, 0.75], [0.86, 0.86, 0.86], [0.71, 0.02, 0.15]])
    r = np.interp(t, [0.0, 0.5, 1.0], colors[:, 0])
    g = np.interp(t, [0.0, 0.5, 1.0], colors[:, 1])
    b = np.interp(t, [0.0, 0.5, 1.0], colors[:, 2])
    return np.stack([r, g, b], axis=1).astype(np.float32)


def _viridis_colormap(t: np.ndarray) -> np.ndarray:
    """Viridis 色映射（简化近似版）。"""
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    colors = np.array([
        [0.27, 0.01, 0.33],
        [0.13, 0.57, 0.55],
        [0.99, 0.91, 0.13],
    ])
    r = np.interp(t, [0.0, 0.5, 1.0], colors[:, 0])
    g = np.interp(t, [0.0, 0.5, 1.0], colors[:, 1])
    b = np.interp(t, [0.0, 0.5, 1.0], colors[:, 2])
    return np.stack([r, g, b], axis=1).astype(np.float32)


COLORMAP_FUNCS = {
    "jet": _jet_colormap,
    "hot": _hot_colormap,
    "coolwarm": _coolwarm_colormap,
    "viridis": _viridis_colormap,
}


def apply_colormap(values: np.ndarray, cmap: str = "jet") -> np.ndarray:
    """将 [0,1] 归一化值映射为 RGB 颜色。"""
    fn = COLORMAP_FUNCS.get(cmap, _jet_colormap)
    return fn(values)


# =========================================================================
# 标量场计算
# =========================================================================
def compute_scalar_field(pcd, field: str, **kwargs) -> Optional[np.ndarray]:
    """计算点云的标量场。

    Args:
        pcd: open3d.geometry.PointCloud
        field: "z" | "density" | "curvature" | "intensity" | "distance_to_plane"
        **kwargs: 额外参数

    Returns:
        标量值数组 (N,) 或 None
    """
    pts = np.asarray(pcd.points)
    n = len(pts)
    if n == 0:
        return None

    if field == "z":
        return pts[:, 2].astype(np.float64)

    elif field == "density":
        return _compute_density(pcd, kwargs.get("radius", 5.0))

    elif field == "curvature":
        return _compute_curvature(pcd, kwargs.get("radius", 10.0),
                                   kwargs.get("max_nn", 30))

    elif field == "intensity":
        return _compute_intensity(pcd)

    elif field == "distance_to_plane":
        plane = kwargs.get("plane")  # (a,b,c,d)  ax+by+cz+d=0
        if plane is None:
            return None
        a, b, c, d = plane
        dists = np.abs(pts @ np.array([a, b, c]) + d) / np.sqrt(a * a + b * b + c * c)
        return dists.astype(np.float64)

    return None


def _compute_density(pcd, radius: float = 5.0) -> np.ndarray:
    """基于半径邻居的局部密度。"""
    import open3d as o3d
    tree = o3d.geometry.KDTreeFlann(pcd)
    pts = np.asarray(pcd.points)
    densities = np.zeros(len(pts), dtype=np.float64)
    for i in range(len(pts)):
        _, idx, _ = tree.search_radius_vector_3d(pcd.points[i], radius)
        densities[i] = len(idx)
    return densities


def _compute_curvature(pcd, radius: float = 10.0, max_nn: int = 30) -> np.ndarray:
    """基于局部 PCA 的曲率估计（最小特征值 / 特征值和）。"""
    import open3d as o3d
    pts = np.asarray(pcd.points)
    n = len(pts)
    tree = o3d.geometry.KDTreeFlann(pcd)
    curvatures = np.zeros(n, dtype=np.float64)

    for i in range(n):
        _, idx, _ = tree.search_radius_vector_3d(pcd.points[i], radius)
        if len(idx) < 3:
            continue
        neighbors = pts[idx]
        cov = np.cov((neighbors - neighbors.mean(axis=0)).T)
        eigvals = np.linalg.eigvalsh(cov)
        eigvals = np.sort(eigvals)
        trace = eigvals.sum()
        if trace > 1e-12:
            curvatures[i] = eigvals[0] / trace

    return curvatures


def _compute_intensity(pcd) -> Optional[np.ndarray]:
    """提取 intensity（如果点云支持）。open3d 不原生支持 intensity，
    这里尝试从颜色反推灰度作为替代。"""
    if not pcd.has_colors():
        return None
    cols = np.asarray(pcd.colors)
    # 灰度 = 0.299*R + 0.587*G + 0.114*B
    intensity = 0.299 * cols[:, 0] + 0.587 * cols[:, 1] + 0.114 * cols[:, 2]
    return intensity.astype(np.float64)
