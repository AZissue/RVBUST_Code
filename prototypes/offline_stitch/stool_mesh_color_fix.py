# -*- coding: utf-8 -*-
"""凳子实体 mesh 顶点颜色修复（配合 stool_entity_postprocess.py 使用）。

针对 Poisson 网格的三类颜色问题：
  1. 灰白边缘：边界外推顶点离点云远（实测 p99 达 18mm），最近点取色
     抓到灰白/背景点 → 低饱和亮色强制回主体橙色（保亮度）；
  2. 深色斑点：单点最近邻取色把点云暗噪点印成斑块 → 改为 k=8 近邻中值取色；
  3. 亮度色带：多视角曝光差异 → Lab 亮度大尺度低通，压平 65% 低频起伏。

用法： python stool_mesh_color_fix.py [mesh.ply] [cloud.ply] [输出ply]
"""
import sys

import cv2
import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

MESH = sys.argv[1] if len(sys.argv) > 1 else r"E:/jingz/Desktop/凳子拼接/凳子实体_mesh.ply"
CLOUD = sys.argv[2] if len(sys.argv) > 2 else r"E:/jingz/Desktop/凳子拼接/凳子实体_clean.ply"
OUT = sys.argv[3] if len(sys.argv) > 3 else MESH

mesh = o3d.io.read_triangle_mesh(MESH)
pcd = o3d.io.read_point_cloud(CLOUD)
mp = np.asarray(mesh.vertices)
cp = np.asarray(pcd.points)
cc = (np.asarray(pcd.colors) * 255.0).astype(np.uint8)
print(f"mesh: {len(mp):,} 顶点, cloud: {len(cp):,} 点")

# ---- 1. k=8 近邻中值取色（替代最近邻单点，去深色斑点）----
d, idx = cKDTree(cp).query(mp, k=8, workers=-1)
d_min = d[:, 0]
cols = np.median(cc[idx], axis=1).astype(np.uint8)  # (n,3)
print(f"取色距离: p50={np.percentile(d_min, 50):.2f} "
      f"p99={np.percentile(d_min, 99):.2f} mm")

# ---- 2. 低饱和亮灰点（白边）强制回主体橙色 ----
hsv = cv2.cvtColor(cols.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
h, s, v = hsv[:, 0].astype(int), hsv[:, 1].astype(int), hsv[:, 2].astype(int)
# 主体色调：饱和且非暗顶点的色相中位数（OpenCV H: 0~179）
body = (s > 80) & (v > 80)
h0 = int(np.median(h[body]))
print(f"主体色相 H={h0}（{h0 * 2}°），参与统计顶点 {body.sum():,}")

fringe = (s < 60) & (v > 100)
hsv[fringe, 0] = h0
hsv[fringe, 1] = 150  # 橙色饱和度的常见量级
print(f"灰白边回染橙色: {fringe.sum():,} 顶点")

rgb = cv2.cvtColor(hsv.reshape(-1, 1, 3).astype(np.uint8),
                   cv2.COLOR_HSV2RGB).reshape(-1, 3).astype(np.float64)

# ---- 3. 亮度大尺度低通，压平多视角曝光色带 ----
lab = cv2.cvtColor(rgb.reshape(-1, 1, 3).astype(np.uint8),
                   cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float64)
L = lab[:, 0]
_, nbr = cKDTree(mp).query(mp, k=31, workers=-1)  # 含自身，半径~15mm
lowpass = L[nbr].mean(axis=1)
L_even = L - 0.65 * (lowpass - np.median(lowpass))
lab[:, 0] = np.clip(L_even, 0, 255)
rgb2 = cv2.cvtColor(lab.reshape(-1, 1, 3).astype(np.uint8),
                    cv2.COLOR_LAB2RGB).reshape(-1, 3)

mesh.vertex_colors = o3d.utility.Vector3dVector(rgb2 / 255.0)
o3d.io.write_triangle_mesh(OUT, mesh)
print(f"已保存: {OUT}")
