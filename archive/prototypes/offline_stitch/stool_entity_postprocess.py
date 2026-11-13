# -*- coding: utf-8 -*-
"""凳子实体点云后处理 + 顶点色网格封装。

流程：
  1. 剔除反光/白边点：橙色塑料主体 B/R ≈ 0.14~0.26，高光与白边
     的 B/R 明显升高或接近灰白，按 (B/R>0.45 & max>160) 或
     (近白低饱和 max>190 & sat<50) 剔除；
  2. 轻微体素下采样（0.3mm）；
  3. 颜色双边平滑（kNN 域 + 值域权重），让橙色均匀、保留细节；
  4. 保存后处理点云 凳子实体_clean.ply；
  5. 估算法线 + 切平面一致定向 + Poisson 重建，密度裁剪后把点云
     颜色迁移到网格顶点，保存 凳子实体_mesh.ply。

用法： python stool_entity_postprocess.py [输入ply] [输出目录]
"""
import os
import sys

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

INPUT = sys.argv[1] if len(sys.argv) > 1 else r"E:/jingz/Desktop/凳子拼接/凳子实体.ply"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(INPUT)
OUT_PCD = os.path.join(OUT_DIR, "凳子实体_clean.ply")
OUT_MESH = os.path.join(OUT_DIR, "凳子实体_mesh.ply")


def clean_specular(pcd):
    """剔除高光与白边点（依据橙色主体上的颜色异常）。"""
    c = np.asarray(pcd.colors) * 255.0
    r, mx, mn = c[:, 0], c.max(axis=1), c.min(axis=1)
    sat = mx - mn
    ratio = c[:, 2] / np.maximum(r, 1.0)
    mask = ((ratio > 0.45) & (mx > 160)) | ((mx > 190) & (sat < 50))
    print(f"反光/白边剔除: {mask.sum():,}/{len(c):,} 点 ({mask.mean() * 100:.2f}%)")
    return pcd.select_by_index(np.where(~mask)[0])


def smooth_colors(pcd, k=10, sigma_c=40.0, sigma_p=2.0, strength=0.7):
    """双边颜色平滑：几何近邻 + 颜色相似度加权，混回原色保留纹理。"""
    pts = np.asarray(pcd.points)
    cols = np.asarray(pcd.colors) * 255.0
    n = len(pts)
    _, idx = cKDTree(pts).query(pts, k=k + 1, workers=-1)
    idx = idx[:, 1:]  # 去掉自身
    nb_pts = pts[idx]            # (n, k, 3)
    nb_cols = cols[idx]          # (n, k, 3)
    dp2 = ((nb_pts - pts[:, None, :]) ** 2).sum(axis=2)      # (n, k)
    dc2 = ((nb_cols - cols[:, None, :]) ** 2).sum(axis=2)    # (n, k)
    w = np.exp(-dc2 / (2 * sigma_c ** 2)) * np.exp(-dp2 / (2 * sigma_p ** 2))
    w_sum = w.sum(axis=1, keepdims=True)
    mean = (nb_cols * w[..., None]).sum(axis=1) / np.maximum(w_sum, 1e-12)
    smoothed = (1 - strength) * cols + strength * mean
    pcd.colors = o3d.utility.Vector3dVector(np.clip(smoothed / 255.0, 0, 1))
    return pcd


def main():
    pcd = o3d.io.read_point_cloud(INPUT)
    print(f"输入: {len(pcd.points):,} 点, colors={pcd.has_colors()}")
    assert pcd.has_colors(), "输入点云无颜色"

    pcd = clean_specular(pcd)
    pcd = pcd.voxel_down_sample(0.15)  # mm，轻微下采样，尽量保完整
    print(f"下采样(0.15mm)后: {len(pcd.points):,} 点")
    pcd = smooth_colors(pcd)
    # 不用统计离群点去除：薄壁/棱线/轮廓点的邻域是单侧的，必被误删啃出
    # 缺块（实测棱线带成片丢失）。只剔除真正孤立的无邻域飞点。
    from scipy.spatial import cKDTree
    pts = np.asarray(pcd.points)
    d_nn, _ = cKDTree(pts).query(pts, k=2, workers=-1)
    keep = d_nn[:, 1] < 1.0  # 最近邻 >1mm 的孤立点视为飞点
    print(f"孤立飞点剔除: {(~keep).sum():,}/{len(pts):,}")
    pcd = pcd.select_by_index(np.where(keep)[0])
    print(f"离群点去除后: {len(pcd.points):,} 点")
    o3d.io.write_point_cloud(OUT_PCD, pcd)
    print(f"已保存: {OUT_PCD}")

    # ---- Mesh：法线 → 定向 → Poisson → 密度裁剪 → 顶点着色 ----
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=3.0, max_nn=30))
    print("法线估计完成，开始切平面一致定向...")
    pcd.orient_normals_consistent_tangent_plane(10)
    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pcd, depth=9)
    print(f"Poisson: {len(mesh.vertices):,} 顶点, {len(mesh.triangles):,} 三角面")

    # 密度裁剪：去掉低置信度"填补 blob"
    dens = np.asarray(densities)
    keep = dens > np.quantile(dens, 0.01)
    mesh.remove_vertices_by_mask(~keep)
    print(f"密度裁剪后: {len(mesh.vertices):,} 顶点")

    # 颜色迁移：k=8 近邻中值取色（单点最近邻会把点云暗噪点印成
    # 深色斑块）；低饱和亮灰顶点（Poisson 外推白边）回染主体橙色；
    # Lab 亮度大尺度低通压平多视角曝光色带
    import cv2
    verts = np.asarray(mesh.vertices)
    pts = np.asarray(pcd.points)
    cols8 = (np.asarray(pcd.colors) * 255.0).astype(np.uint8)
    d, nn8 = cKDTree(pts).query(verts, k=8, workers=-1)
    rgb = np.median(cols8[nn8], axis=1).astype(np.uint8)

    hsv = cv2.cvtColor(rgb.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
    h, s, v = hsv[:, 0].astype(int), hsv[:, 1].astype(int), hsv[:, 2].astype(int)
    body = (s > 80) & (v > 80)
    h0 = int(np.median(h[body]))
    fringe = (s < 60) & (v > 100)
    hsv[fringe, 0] = h0
    hsv[fringe, 1] = 150
    rgb = cv2.cvtColor(hsv.reshape(-1, 1, 3).astype(np.uint8),
                       cv2.COLOR_HSV2RGB).reshape(-1, 3)

    lab = cv2.cvtColor(rgb.reshape(-1, 1, 3).astype(np.uint8),
                       cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float64)
    _, nbr = cKDTree(verts).query(verts, k=31, workers=-1)
    lowpass = lab[nbr, 0].mean(axis=1)
    lab[:, 0] = np.clip(lab[:, 0] - 0.65 * (lowpass - np.median(lowpass)),
                        0, 255)
    rgb = cv2.cvtColor(lab.reshape(-1, 1, 3).astype(np.uint8),
                       cv2.COLOR_LAB2RGB).reshape(-1, 3)
    mesh.vertex_colors = o3d.utility.Vector3dVector(rgb / 255.0)
    o3d.io.write_triangle_mesh(OUT_MESH, mesh)
    print(f"已保存: {OUT_MESH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
