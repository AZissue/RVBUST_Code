# -*- coding: utf-8 -*-
"""
变换链（transform_chain）—— A1 变换链数学正确。

compute_cam2base：由手眼结果 + 当前机器人位姿求相机→基座系矩阵。
  眼在手上: T_cam2base = T_base2tool @ T_cam2tool（手眼结果 = T_cam2tool）
  眼在手外: T_cam2base = T_cam2base（手眼结果本身，与机器人位姿无关）
与官方 HandEyeSDK 口径同式（P_base = T_g2b·T_result·P_cam，@feas DLL oracle
逐点最大偏差 0.000076 mm 实证）；src/core/robot_stitch_workflow.py:110-121 同链。

transform_pcd：点云变换到基座系。**先 copy 再 transform（K3）**——
open3d 的 pcd.transform(T) 原地修改入参（转台 P1-c2 已实证踩坑）；
禁止对调用方持有的点云原地变换，禁止裸 += 合并（走 src/core/pcd_utils.merge_pointclouds）。

内部统一毫米（A2/§4.1）。
"""

from __future__ import annotations

import numpy as np


def compute_cam2base(eye_in_hand: bool,
                     T_handeye_mm: np.ndarray,
                     T_base2tool_mm: np.ndarray) -> np.ndarray:
    """求相机→基座系变换矩阵（毫米域）。

    Args:
        eye_in_hand: True 手眼结果为 T_cam2tool；False 为 T_cam2base。
        T_handeye_mm: 4×4 手眼矩阵（毫米）。
        T_base2tool_mm: 4×4 当前机器人位姿（毫米）。

    Returns:
        4×4 T_cam2base（p_base = T_cam2base @ p_cam）。
    """
    T_handeye = np.asarray(T_handeye_mm, dtype=np.float64)
    T_base2tool = np.asarray(T_base2tool_mm, dtype=np.float64)
    if T_handeye.shape != (4, 4) or T_base2tool.shape != (4, 4):
        raise ValueError("T_handeye 与 T_base2tool 都必须是 4×4")
    if eye_in_hand:
        return T_base2tool @ T_handeye
    return T_handeye


def transform_pcd(pcd_mm, T_cam2base_mm):
    """把相机系点云变换到基座系，返回**新点云**（入参不被修改，K3）。

    Args:
        pcd_mm: open3d PointCloud（毫米）。
        T_cam2base_mm: 4×4。

    Returns:
        变换后的新 PointCloud（颜色/法线随 copy 保留）。
    """
    import open3d as o3d

    T = np.asarray(T_cam2base_mm, dtype=np.float64)
    if T.shape != (4, 4):
        raise ValueError("T_cam2base 必须是 4×4")
    out = o3d.geometry.PointCloud(pcd_mm)  # 先复制（K3），绝不原地改入参
    out.transform(T)
    return out


def transform_points_mm(points_mm: np.ndarray, T_cam2base_mm: np.ndarray) -> np.ndarray:
    """N×3 点数组的齐次左乘版本（测试/真值比对用，纯 numpy）。"""
    pts = np.asarray(points_mm, dtype=np.float64)
    T = np.asarray(T_cam2base_mm, dtype=np.float64)
    hom = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
    return (T @ hom.T).T[:, :3]
