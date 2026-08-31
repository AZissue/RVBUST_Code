# -*- coding: utf-8 -*-
"""点云小工具：属性对齐、安全合并等。"""

from __future__ import annotations

import numpy as np


def merge_pointclouds(merged: "o3d.geometry.PointCloud",
                      pcd: "o3d.geometry.PointCloud") -> "o3d.geometry.PointCloud":
    """安全地执行 merged += pcd，避免属性不一致导致颜色/法向量被清零。

    open3d 的 += 在两侧属性不一致时行为未定义（常见：带色 + 无色 → colors=0）。
    本函数在合并前统一 colors/normals 属性。
    """
    import open3d as o3d

    # 颜色对齐
    merged_has_color = merged.has_colors()
    pcd_has_color = pcd.has_colors()
    if merged_has_color and not pcd_has_color:
        pcd.colors = o3d.utility.Vector3dVector(
            np.full((len(pcd.points), 3), 0.85))
    elif pcd_has_color and not merged_has_color:
        merged.colors = o3d.utility.Vector3dVector(
            np.full((len(merged.points), 3), 0.85))

    # 法向量对齐
    merged_has_normal = merged.has_normals()
    pcd_has_normal = pcd.has_normals()
    if merged_has_normal and not pcd_has_normal:
        pcd.normals = o3d.utility.Vector3dVector(
            np.zeros((len(pcd.points), 3)))
    elif pcd_has_normal and not merged_has_normal:
        merged.normals = o3d.utility.Vector3dVector(
            np.zeros((len(merged.points), 3)))

    merged += pcd
    return merged
