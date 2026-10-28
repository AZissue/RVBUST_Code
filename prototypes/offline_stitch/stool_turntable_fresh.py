# -*- coding: utf-8 -*-
"""凳子点云运镜视频生成（逐帧独立窗口版，彻底规避单窗口刷新问题）。

单窗口 update_geometry + capture 在本机 Open3D 0.19 离屏模式下存在
间歇性帧滞后（标定与渲染结果不一致），无法可靠控制视角。改为每帧：

  1. 新建独立离屏窗口（相机由场景包围盒重置，行为确定）；
  2. 先加入固定尺寸的"白点定位盒"（12 条棱上的白色点，白底不可见），
     使相机重置只由盒子决定 —— 每帧相机完全一致，凳子旋转不影响力框；
  3. 加入按关键帧姿态旋转/缩放后的凳子点云；
  4. 渲一帧、写视频、销毁窗口。

视角关键帧 (az, el, roll) 为经验参数（网格探针标定，见 README 注）。
运镜：正视角开场 -> 快速推近 -> 升起展示顶面 -> 回落环绕 -> 回正视角。

用法： python stool_turntable_fresh.py [输入ply] [输出mp4] [留空系数]
"""
import os
import sys

import cv2
import numpy as np
import open3d as o3d

INPUT = sys.argv[1] if len(sys.argv) > 1 else \
    r"E:/jingz/Desktop/凳子拼接/凳子实体_clean.ply"
OUT = sys.argv[2] if len(sys.argv) > 2 else \
    os.path.join(os.path.dirname(INPUT), "凳子运镜.mp4")
MARGIN = float(sys.argv[3]) if len(sys.argv) > 3 else 0.7

FPS = 30
W, H = 1920, 1080
ZOOM = 0.42  # 配合定位盒（半幅 330mm）的取景倍率
BOX_HALF = 330.0  # 定位盒半幅（mm），须大于凳体最大半幅 (~300)

# 视角关键帧：(t, az, el, roll, scale)；基于对齐后数据
# （正视角=az90/el2/roll-4，顶面=el-85）
KEYS = [
    (0.0, 90, 2, -4, 1.0),       # 正视角开场（四条腿垂直向下）
    (1.8, 105, 4, -4, 1.5),      # 快速推近
    (3.2, 100, -30, -4, 1.3),    # 抬升过渡
    (5.0, 105, -85, -4, 1.1),    # 升起展示顶面
    (7.5, 90, -85, -4, 1.1),     # 顶面停留缓转（俯拍时 az 需保持近 90）
    (9.5, 280, -30, -4, 0.95),   # 回落环绕
    (12.0, 450, 2, -4, 1.0),     # 回正视角全景
]

# 凳体长轴在原始数据中的方向（由正交投影图测量）；对齐后凳腿竖直朝 -Z
STOOL_AXIS = np.array([0.68, 0.0, 0.73])


def align_points(pts, colors):
    """把斜躺的凳体对齐：长轴 -> 竖直（脚垫朝 -Z），网格探针标定值。"""
    axis = STOOL_AXIS / np.linalg.norm(STOOL_AXIS)
    cc = colors * 255.0
    m = (cc.max(axis=1) < 70) & ((cc.max(axis=1) - cc.min(axis=1)) < 30)
    if m.sum() > 100:
        feet = pts[m].mean(axis=0)
        if np.dot(feet, axis) < 0:
            axis = -axis  # 轴指向脚端
    target = np.array([0.0, 0.0, -1.0])
    x = np.cross(axis, target)
    sx = np.linalg.norm(x)
    ang = np.arctan2(sx, np.dot(axis, target))
    K = np.array([[0, -x[2], x[1]],
                  [x[2], 0, -x[0]],
                  [-x[1], x[0], 0]]) / sx
    R = np.eye(3) - np.sin(ang) * K + (1 - np.cos(ang)) * K @ K
    return (R @ pts.T).T


def sample_path(t):
    for i in range(len(KEYS) - 1):
        t0, a0, e0, r0, s0 = KEYS[i]
        t1, a1, e1, r1, s1 = KEYS[i + 1]
        if t0 <= t <= t1:
            u = (t - t0) / (t1 - t0)
            u = u * u * (3 - 2 * u)
            return (a0 + (a1 - a0) * u, e0 + (e1 - e0) * u,
                    r0 + (r1 - r0) * u, s0 + (s1 - s0) * u)
    k = KEYS[-1]
    return k[1], k[2], k[3], k[4]


def rot_x(deg):
    r = np.deg2rad(deg)
    c, s = np.cos(r), np.sin(r)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_z(deg):
    r = np.deg2rad(deg)
    c, s = np.cos(r), np.sin(r)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def pose_matrix(az, el, roll):
    """几何旋转：先 roll（绕数据Z），再 el（绕数据X），最后 az（绕数据Z）。"""
    return rot_z(-az) @ rot_x(el) @ rot_z(roll)


def make_box_cloud():
    """定位盒：12 条棱上的白色点（白底不可见），固定相机重置的包围盒。"""
    pts = []
    h = BOX_HALF
    edges = []
    for a, b in [((-h, -h, -h), (h, -h, -h)), ((-h, h, -h), (h, h, -h)),
                 ((-h, -h, h), (h, -h, h)), ((-h, h, h), (h, h, h)),
                 ((-h, -h, -h), (-h, h, -h)), ((h, -h, -h), (h, h, -h)),
                 ((-h, -h, h), (-h, h, h)), ((h, -h, h), (h, h, h)),
                 ((-h, -h, -h), (-h, -h, h)), ((h, -h, -h), (h, -h, h)),
                 ((-h, h, -h), (-h, h, h)), ((h, h, -h), (h, h, h))]:
        a, b = np.asarray(a), np.asarray(b)
        pts.append(np.linspace(a, b, 120))
    box = o3d.geometry.PointCloud()
    box.points = o3d.utility.Vector3dVector(np.vstack(pts))
    n = len(box.points)
    box.colors = o3d.utility.Vector3dVector(np.ones((n, 3)))
    return box


def render_frame(box, pcd, pts, colors, az, el, roll, scale, point_size):
    """独立窗口渲一帧（窗口即建即毁，相机行为确定）。"""
    pcd.points = o3d.utility.Vector3dVector(
        (pose_matrix(az, el, roll) @ pts.T).T * scale)
    vis = o3d.visualization.Visualizer()
    vis.create_window(visible=False, width=W, height=H)
    vis.add_geometry(box)
    vis.add_geometry(pcd)
    ro = vis.get_render_option()
    ro.background_color = np.array([1.0, 1.0, 1.0])
    ro.point_size = point_size
    vis.get_view_control().set_zoom(ZOOM)
    vis.poll_events()
    vis.update_renderer()
    img = vis.capture_screen_float_buffer(False)
    vis.destroy_window()
    frame = (np.asarray(img) * 255).astype(np.uint8)
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    if frame.shape[:2] != (H, W):
        frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
    return frame


def main():
    src = o3d.io.read_point_cloud(INPUT)
    pts = np.asarray(src.points).copy()
    pts -= (pts.min(axis=0) + pts.max(axis=0)) / 2
    colors = np.asarray(src.colors).copy()
    pts = align_points(pts, colors)  # 凳体对齐：腿朝下
    n = min(2_500_000, len(pts))
    rng = np.random.default_rng(42)
    sub = np.sort(rng.choice(len(pts), size=n, replace=False))
    pts, colors = pts[sub], colors[sub]
    pcd = o3d.geometry.PointCloud()
    pcd.colors = o3d.utility.Vector3dVector(colors)
    box = make_box_cloud()
    print(f"points={n:,}", flush=True)

    writer = None
    n_frames = int(KEYS[-1][0] * FPS)
    try:
        for f in range(n_frames):
            t = f / FPS
            az, el, roll, scale = sample_path(t)
            scale *= MARGIN
            frame = render_frame(box, pcd, pts, colors, az, el, roll,
                                 scale, 2.0 * np.sqrt(scale))
            if writer is None:
                writer = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"),
                                         FPS, (W, H))
            writer.write(frame)
            if f % 30 == 0:
                print(f"frame {f}/{n_frames}  t={t:.1f}s  "
                      f"az={az:.0f} el={el:.0f} roll={roll:.0f} "
                      f"scale={scale:.2f}", flush=True)
    finally:
        if writer is not None:
            writer.release()
    print(f"已保存: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
