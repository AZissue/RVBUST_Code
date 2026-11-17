# -*- coding: utf-8 -*-
"""
RANSAC 几何检测（CloudCompare 的 "Primitive Shapes" 功能）。

支持：
  - 平面（Plane）
  - 球体（Sphere）
  - 圆柱（Cylinder）——简化实现
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np


def detect_shape(pcd, shape: str, **kwargs) -> Optional[Dict]:
    """检测点云中的几何形状。

    Args:
        pcd: open3d.geometry.PointCloud
        shape: "plane" | "sphere" | "cylinder"
        **kwargs:
            distance_threshold: RANSAC 距离阈值（默认 5.0）
            ransac_n: 每次采样点数（平面=3，球=4）
            num_iterations: RANSAC 迭代次数

    Returns:
        检测结果字典，含 shape, params, inliers, summary
    """
    import open3d as o3d

    if shape == "plane":
        return _detect_plane(pcd, **kwargs)
    elif shape == "sphere":
        return _detect_sphere(pcd, **kwargs)
    elif shape == "cylinder":
        return _detect_cylinder(pcd, **kwargs)
    return None


def _detect_plane(pcd,
                  distance_threshold: float = 5.0,
                  ransac_n: int = 3,
                  num_iterations: int = 1000) -> Optional[Dict]:
    """RANSAC 平面检测（open3d 原生）。"""
    import open3d as o3d
    try:
        plane_model, inliers = pcd.segment_plane(
            distance_threshold=distance_threshold,
            ransac_n=ransac_n,
            num_iterations=num_iterations)
        a, b, c, d = plane_model
        inlier_cloud = pcd.select_by_index(inliers)
        n_inliers = len(inliers)
        total = len(pcd.points)
        fitness = n_inliers / total if total > 0 else 0

        return {
            "shape": "plane",
            "params": {"a": a, "b": b, "c": c, "d": d},
            "inliers": inliers,
            "inlier_cloud": inlier_cloud,
            "fitness": fitness,
            "summary": f"平面 ax+by+cz+d=0, 内点 {n_inliers}/{total} ({fitness*100:.1f}%)",
        }
    except Exception as e:
        return None


def _detect_sphere(pcd,
                   distance_threshold: float = 5.0,
                   num_iterations: int = 1000) -> Optional[Dict]:
    """RANSAC 球体拟合。
    open3d 不原生支持球体检测，使用 scipy.optimize 最小二乘拟合。
    """
    try:
        from scipy.optimize import least_squares
    except ImportError:
        # 无 scipy 时用简单代数法
        return _detect_sphere_algebraic(pcd)

    pts = np.asarray(pcd.points)
    n = len(pts)
    if n < 4:
        return None

    # 初始估计：质心 + 平均半径
    center0 = pts.mean(axis=0)
    r0 = float(np.median(np.linalg.norm(pts - center0, axis=1)))

    def residuals(params):
        cx, cy, cz, r = params
        c = np.array([cx, cy, cz])
        dists = np.linalg.norm(pts - c, axis=1) - r
        return dists

    result = least_squares(residuals, [center0[0], center0[1], center0[2], r0],
                           method="lm")
    if not result.success:
        return None

    cx, cy, cz, r = result.x
    center = np.array([cx, cy, cz])
    dists = np.abs(np.linalg.norm(pts - center, axis=1) - r)
    inliers = np.where(dists <= distance_threshold)[0]
    fitness = len(inliers) / n if n > 0 else 0

    inlier_cloud = pcd.select_by_index(inliers.tolist())
    return {
        "shape": "sphere",
        "params": {"center": center.tolist(), "radius": r},
        "inliers": inliers.tolist(),
        "inlier_cloud": inlier_cloud,
        "fitness": fitness,
        "summary": f"球心 ({cx:.2f}, {cy:.2f}, {cz:.2f}), 半径 {r:.2f}, "
                   f"内点 {len(inliers)}/{n} ({fitness*100:.1f}%)",
    }


def _detect_sphere_algebraic(pcd) -> Optional[Dict]:
    """无 scipy 时的代数球体拟合（线性最小二乘）。"""
    pts = np.asarray(pcd.points)
    n = len(pts)
    if n < 4:
        return None

    # 构建矩阵: [x, y, z, 1] * [2cx, 2cy, 2cz, r^2-cx^2-cy^2-cz^2]^T = x^2+y^2+z^2
    A = np.column_stack([pts, np.ones(n)])
    b = np.sum(pts ** 2, axis=1)
    sol, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, cz, d = sol * 0.5, sol * 0.5, sol * 0.5, sol[3]
    cx, cy, cz = sol[0] / 2, sol[1] / 2, sol[2] / 2
    r2 = d + cx ** 2 + cy ** 2 + cz ** 2
    if r2 <= 0:
        return None
    r = np.sqrt(r2)
    center = np.array([cx, cy, cz])

    dists = np.abs(np.linalg.norm(pts - center, axis=1) - r)
    inliers = np.where(dists <= 5.0)[0]
    fitness = len(inliers) / n if n > 0 else 0

    import open3d as o3d
    inlier_cloud = pcd.select_by_index(inliers.tolist())
    return {
        "shape": "sphere",
        "params": {"center": center.tolist(), "radius": r},
        "inliers": inliers.tolist(),
        "inlier_cloud": inlier_cloud,
        "fitness": fitness,
        "summary": f"球心 ({cx:.2f}, {cy:.2f}, {cz:.2f}), 半径 {r:.2f}",
    }


def _detect_cylinder(pcd, **kwargs) -> Optional[Dict]:
    """圆柱拟合（简化版：先检测平面法线作为轴向，再拟合圆截面）。
    完整实现较复杂，这里提供基础框架。
    """
    # TODO: 完整圆柱 RANSAC 拟合
    return None


def fit_line_3d(pts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """3D 点集拟合直线，返回 (方向向量, 直线上一点)。"""
    center = pts.mean(axis=0)
    cov = np.cov((pts - center).T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    direction = eigvecs[:, np.argmax(eigvals)]
    return direction, center


def point_to_plane_distance(pts: np.ndarray, plane: Tuple[float, float, float, float]) -> np.ndarray:
    """点到平面的有符号距离。"""
    a, b, c, d = plane
    normal = np.array([a, b, c])
    norm = np.linalg.norm(normal)
    if norm < 1e-12:
        return np.zeros(len(pts))
    return (pts @ normal + d) / norm
