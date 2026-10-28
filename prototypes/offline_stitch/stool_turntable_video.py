# -*- coding: utf-8 -*-
"""凳子点云运镜视频生成（相机标定 + 无滚动运镜版）。

流程：
  1. 自动相机标定：向场景加入 5 个外部彩色标记球（+X青/-X品红/+Y绿/
     -Y蓝/+Z黄，位于物体包围盒外），渲染一帧、按颜色分割像素质心，
     弱透视最小二乘解出相机屏幕基 (r, u, c)，随后移除标记；
  2. 自动定位正面：点云中蓝色贴纸质心的水平方位角即凳子正视角
     方位角 az0；
  3. 每帧按期望相机位姿 Rd(az, el)（屏幕水平线始终水平，无滚动）
     计算几何旋转 Q = Rc^T Rd，叠加常量滚动补偿 ROLL_OFFSET
     （标定残差，实测 +10°），缩放实现推拉；
  4. cv2 合成 mp4。

运镜关键帧（相对 az0；模仿参考产品视频）：
  t(s)  az_rel  el   scale   动作
  0      0      12   1.0     正视角平视开场
  3.5   50      15   1.0     缓转
  6.5  110       8   2.0     边角推近特写
  9.5  180      18   1.2     拉远环绕
  12.5 250      72   1.0     升顶俯拍凳面
  16   360      12   1.0     回正视角全景

用法： python stool_turntable_video.py [输入ply] [输出mp4] [留空系数]
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
# 全局留空系数：乘到所有推拉倍数上，<1 画面四周留空更多
MARGIN = float(sys.argv[3]) if len(sys.argv) > 3 else 0.7

FPS = 30
W, H = 1920, 1080
ZOOM = 0.55
KEYS = [  # (t, az_rel_deg, el_deg, scale)；az_rel=0 即正视角
    (0.0, 0, 12, 1.0),    # 正视角平视开场
    (1.8, 15, 14, 1.5),   # 快速推近
    (3.2, 40, 32, 1.3),   # 边转边升
    (5.0, 90, 75, 1.1),   # 升起展示顶面
    (7.5, 95, 78, 1.1),   # 顶面停留
    (9.5, 220, 45, 0.95), # 俯角环绕回落
    (12.0, 360, 12, 1.0), # 回正视角全景
]

# 标定标记：(位置mm, RGB颜色, 颜色键)；位于凳体包围盒外
MARKERS = [
    ((370, 0, 0), (0, 1, 1)), ((-370, 0, 0), (1, 0, 1)),
    ((0, 295, 0), (0, 1, 0)), ((0, -295, 0), (0, 0, 1)),
    ((0, 0, 373), (1, 1, 0)),
]
MARKER_MASKS = [  # 与 MARKERS 顺序一致（RGB 各通道 int 比较）
    lambda R, G, B: (G > 170) & (B > 170) & (R < 90),   # 青
    lambda R, G, B: (R > 170) & (B > 170) & (G < 90),   # 品红
    lambda R, G, B: (G > 170) & (R < 90) & (B < 90),    # 绿
    lambda R, G, B: (B > 170) & (R < 90) & (G < 90),    # 蓝
    lambda R, G, B: (R > 170) & (G > 170) & (B < 90),   # 黄
]


def sample_path(t):
    """关键帧间 smoothstep 插值，返回 (az_rel, el, scale)。"""
    for i in range(len(KEYS) - 1):
        t0, a0, e0, s0 = KEYS[i]
        t1, a1, e1, s1 = KEYS[i + 1]
        if t0 <= t <= t1:
            u = (t - t0) / (t1 - t0)
            u = u * u * (3 - 2 * u)
            return (a0 + (a1 - a0) * u,
                    e0 + (e1 - e0) * u,
                    s0 + (s1 - s0) * u)
    return KEYS[-1][1], KEYS[-1][2], KEYS[-1][3]


def calibrate_camera(vis):
    """加入外部标记球渲染一帧，解相机屏幕基；返回 Rc=[r,u,c]（列向量）。"""
    spheres = []
    for pos, col in MARKERS:
        s = o3d.geometry.TriangleMesh.create_sphere(12.0)
        s.translate(np.asarray(pos, dtype=np.float64))
        p = s.sample_points_poisson_disk(2000)
        p.paint_uniform_color(col)
        spheres.append(p)
    markers = spheres[0]
    for s in spheres[1:]:
        markers += s
    vis.add_geometry(markers)
    vis.poll_events()
    vis.update_renderer()
    img = (np.asarray(vis.capture_screen_float_buffer(False)) * 255).astype(np.uint8)
    vis.remove_geometry(markers)

    R, G, B = (img[:, :, i].astype(int) for i in range(3))
    hh, ww = img.shape[:2]
    A, br, bu = [], [], []
    for (pos, _), mask_fn in zip(MARKERS, MARKER_MASKS):
        m = mask_fn(R, G, B)
        ys, xs = np.where(m)
        if m.sum() < 30:
            print(f"  标定警告: {pos} 处标记不可见", flush=True)
            continue
        A.append(pos)
        br.append(xs.mean() - ww / 2)
        bu.append(-(ys.mean() - hh / 2))
    A = np.asarray(A, dtype=np.float64)
    r = np.linalg.lstsq(A, np.asarray(br), rcond=None)[0]
    u = np.linalg.lstsq(A, np.asarray(bu), rcond=None)[0]
    r /= np.linalg.norm(r)
    u -= np.dot(u, r) * r
    u /= np.linalg.norm(u)
    c = np.cross(r, u)  # 场景→相机
    print(f"  相机基: r={r.round(3)} u={u.round(3)} c={c.round(3)}", flush=True)
    return np.column_stack([r, u, c])


def find_front_azimuth(colors):
    """蓝色贴纸质心的水平方位角（几何中心为原点）。"""
    c = colors * 255.0
    m = (c[:, 2] > c[:, 0] + 15) & (c[:, 2] >= c[:, 1] - 5)
    if m.sum() < 100:
        print("  警告: 未找到蓝色贴纸，正视角方位角取 0", flush=True)
        return 0.0
    cen = c[m].mean(axis=0)  # 颜色数组与点序一致，均值仅用于调试
    pts_cen = _CENTERED[m].mean(axis=0)
    print(f"  贴纸质心: {pts_cen.round(1)}（{int(m.sum())} 点）", flush=True)
    return float(np.degrees(np.arctan2(pts_cen[0], -pts_cen[1])))


_CENTERED = None  # find_front_azimuth 内部使用（点序与 colors 对齐）


def desired_camera(az_deg, el_deg):
    """期望相机旋转矩阵 [x,y,z] 列向量；z=场景→相机方向，屏幕水平无滚动。"""
    az, el = np.deg2rad(az_deg), np.deg2rad(el_deg)
    z = np.array([np.sin(az) * np.cos(el),
                  -np.cos(az) * np.cos(el),
                  np.sin(el)])
    up = np.array([0.0, 0.0, 1.0])
    up -= np.dot(up, z) * z
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


def rot_about_axis(axis, deg):
    """绕任意单位轴的 Rodrigues 旋转矩阵。"""
    axis = np.asarray(axis, dtype=np.float64)
    axis /= np.linalg.norm(axis)
    a = np.deg2rad(deg)
    c, s = np.cos(a), np.sin(a)
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return c * np.eye(3) + s * K + (1 - c) * np.outer(axis, axis)


def add_roll(Rd, roll_deg):
    """图像滚动：绕期望相机的 z 轴（视线轴）旋转，而非几何坐标轴。"""
    return rot_about_axis(Rd[:, 2], roll_deg) @ Rd


def measure_image_roll(img):
    """渲染帧中凳子的主轴偏离竖直方向的角度（度，右偏为正）。

    对白底前景像素做 2D PCA，主轴即凳子竖直棱的投影方向；
    |角|>40° 视为主轴判定失败（正视角下凳子高大于宽，主轴应近竖直）。
    """
    fg = img.min(axis=2) < 245
    ys, xs = np.where(fg)
    if len(xs) < 2000:
        return None
    X = np.column_stack([xs - xs.mean(), -(ys - ys.mean())])
    cov = X.T @ X / len(X)
    _, vecs = np.linalg.eigh(cov)
    v = vecs[:, -1]
    rho = np.degrees(np.arctan2(v[0], v[1]))
    if abs(rho) > 40.0:
        return None
    return float(rho)


def auto_calibrate_roll(vis, pcd, pts0, Rc, az0, margin):
    """渲染正视角帧并迭代消除画面滚动，返回滚动补偿角（度）。

    标定残差随渲染会话变化，常量补偿不可靠；改为自动测量：
    每轮测出主轴倾角 ρ，反向调整补偿角再验证，直至 |ρ|<1.5°。
    """
    def render_with(roll):
        Rd = add_roll(desired_camera(az0, 12.0), roll)
        Q = Rc @ Rd
        pcd.points = o3d.utility.Vector3dVector((Q @ pts0.T).T * margin)
        vis.update_geometry(pcd)
        vis.poll_events()
        vis.update_renderer()
        img = (np.asarray(vis.capture_screen_float_buffer(False))
               * 255).astype(np.uint8)
        return measure_image_roll(img)

    roll, gain, last_err = 0.0, 1.0, None
    for _ in range(5):
        rho = render_with(roll)
        if rho is None:
            print("  滚动标定: 主轴检测失败，沿用当前补偿", flush=True)
            break
        err = abs(rho)
        print(f"  滚动标定: 补偿={roll:.1f}° 实测倾角={rho:+.1f}°",
              flush=True)
        if err < 1.5:
            break
        if last_err is not None and err >= last_err:
            gain = -gain  # 发散说明修正方向反了
        last_err = err
        roll -= gain * rho
    print(f"  滚动补偿最终值: {roll:.1f}°", flush=True)
    return roll


def main():
    global _CENTERED
    src = o3d.io.read_point_cloud(INPUT)
    pts_all = np.asarray(src.points).copy()
    pts_all -= (pts_all.min(axis=0) + pts_all.max(axis=0)) / 2
    _CENTERED = pts_all
    n_render = min(2_500_000, len(pts_all))
    rng = np.random.default_rng(42)
    sub = np.sort(rng.choice(len(pts_all), size=n_render, replace=False))
    pts0 = pts_all[sub]
    colors0 = np.asarray(src.colors)[sub]

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts0)
    pcd.colors = o3d.utility.Vector3dVector(colors0)

    vis = o3d.visualization.Visualizer()
    vis.create_window(visible=False, width=W, height=H)
    vis.add_geometry(pcd)
    ro = vis.get_render_option()
    ro.background_color = np.array([1.0, 1.0, 1.0])
    vc = vis.get_view_control()
    vc.set_zoom(ZOOM)

    print("相机标定中...", flush=True)
    Rc = calibrate_camera(vis)
    az0 = find_front_azimuth(np.asarray(src.colors))
    print(f"正视角方位角 az0 = {az0:.1f}°", flush=True)
    roll = auto_calibrate_roll(vis, pcd, pts0, Rc, az0, MARGIN)

    writer = None
    n_frames = int(KEYS[-1][0] * FPS)
    try:
        for f in range(n_frames):
            t = f / FPS
            az_rel, el, scale = sample_path(t)
            scale *= MARGIN
            Rd = add_roll(desired_camera(az0 + az_rel, el), roll)
            Q = Rc @ Rd
            pcd.points = o3d.utility.Vector3dVector((Q @ pts0.T).T * scale)
            ro.point_size = 2.0 * np.sqrt(scale)
            vis.update_geometry(pcd)
            vis.poll_events()
            vis.update_renderer()
            img = vis.capture_screen_float_buffer(False)
            frame = (np.asarray(img) * 255).astype(np.uint8)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            if frame.shape[:2] != (H, W):
                frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
            if writer is None:
                writer = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"),
                                         FPS, (W, H))
            writer.write(frame)
            if f % 60 == 0:
                print(f"frame {f}/{n_frames}  t={t:.1f}s  "
                      f"az={az0 + az_rel:.0f} el={el:.0f} scale={scale:.2f}",
                      flush=True)
    finally:
        if writer is not None:
            writer.release()
        vis.destroy_window()
    print(f"已保存: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
