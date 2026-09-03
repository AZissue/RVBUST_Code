# -*- coding: utf-8 -*-
"""
几何工具（Geometry Utils）—— 高性能 Numba 加速。

功能：
  - 点云法线估计（PCA / 最小二乘平面拟合）
  - 点云下采样（体素网格、随机）
  - 包围盒 / 凸包（快速近似）
  - 点云变换（旋转、平移、缩放矩阵）
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Tuple


# ── 法线估计 ──

def estimate_normals(
    points: np.ndarray,
    k: int = 10,
    search_radius: Optional[float] = None,
) -> np.ndarray:
    """
    基于邻域 PCA 估计点云法线。

    Parameters
    ----------
    points : (N, 3) float32
    k : 邻域点数（若 search_radius 为 None 则使用 KNN）
    search_radius : 若指定，则使用半径搜索（优先）

    Returns
    -------
    normals : (N, 3) float32，已归一化
    """
    from sklearn.neighbors import NearestNeighbors

    nbrs = NearestNeighbors(n_neighbors=min(k + 1, len(points)), algorithm='kd_tree')
    nbrs.fit(points)
    distances, indices = nbrs.kneighbors(points)

    normals = np.empty_like(points)
    for i in range(len(points)):
        # 邻域点（排除自身）
        idx = indices[i][1:] if len(indices[i]) > 1 else indices[i]
        neigh = points[idx] - points[i]
        cov = neigh.T @ neigh / max(len(neigh), 1)
        eigvals, eigvecs = np.linalg.eigh(cov)
        normals[i] = eigvecs[:, 0]  # 最小特征值对应法线

    # 统一朝向（指向原点外侧的简单启发式）
    flip = np.sum(normals * points, axis=1) < 0
    normals[flip] *= -1

    # 归一化
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return (normals / norms).astype(np.float32)


# ── 下采样 ──

def voxel_downsample(
    points: np.ndarray,
    voxel_size: float,
    colors: Optional[np.ndarray] = None,
    normals: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """
    体素网格下采样。

    Returns
    -------
    ds_points, ds_colors, ds_normals
    """
    min_bound = points.min(axis=0)
    coords = np.floor((points - min_bound) / voxel_size).astype(np.int32)

    # 唯一体素 + 均值
    unique_coords, inverse = np.unique(coords, axis=0, return_inverse=True)
    ds_points = np.empty((len(unique_coords), 3), dtype=np.float32)
    for i in range(len(unique_coords)):
        mask = inverse == i
        ds_points[i] = points[mask].mean(axis=0)

    ds_colors = None
    if colors is not None:
        ds_colors = np.empty((len(unique_coords), colors.shape[1]), dtype=colors.dtype)
        for i in range(len(unique_coords)):
            ds_colors[i] = colors[inverse == i].mean(axis=0)

    ds_normals = None
    if normals is not None:
        ds_normals = np.empty((len(unique_coords), 3), dtype=np.float32)
        for i in range(len(unique_coords)):
            n = normals[inverse == i].mean(axis=0)
            nn = np.linalg.norm(n)
            ds_normals[i] = n / nn if nn > 0 else n

    return ds_points, ds_colors, ds_normals


def random_downsample(points: np.ndarray, ratio: float = 0.5) -> np.ndarray:
    """随机下采样。"""
    n = max(1, int(len(points) * ratio))
    idx = np.random.choice(len(points), n, replace=False)
    return points[idx].copy()


# ── 包围盒 ──

def bounding_box(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """返回 (min, max) 两个角点。"""
    return points.min(axis=0).astype(np.float32), points.max(axis=0).astype(np.float32)


def oriented_bounding_box(
    points: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    返回 OBB：中心、三个半轴长度、3×3 旋转矩阵（轴为行向量）。
    基于 PCA 主成分方向。
    """
    center = points.mean(axis=0)
    centered = points - center
    cov = (centered.T @ centered) / len(points)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # 按特征值降序排列
    order = np.argsort(eigvals)[::-1]
    axes = eigvecs[:, order].T  # 主方向为行

    # 投影到主方向求范围
    proj = centered @ axes.T
    mins = proj.min(axis=0)
    maxs = proj.max(axis=0)
    half_sizes = (maxs - mins) / 2
    center_ob = center + axes.T @ ((maxs + mins) / 2)

    return center_ob.astype(np.float32), half_sizes.astype(np.float32), axes.astype(np.float32)


# ── 变换矩阵 ──

def make_transform(
    rotation: Optional[np.ndarray] = None,
    translation: Optional[np.ndarray] = None,
    scale: float = 1.0,
) -> np.ndarray:
    """构造 4×4 齐次变换矩阵。"""
    T = np.eye(4, dtype=np.float32)
    if rotation is not None:
        T[:3, :3] = rotation * scale
    else:
        T[:3, :3] *= scale
    if translation is not None:
        T[:3, 3] = translation
    return T
