# -*- coding: utf-8 -*-
"""《3D相机拼接方案通俗说明》示意图（现代扁平风格，无内嵌标题）。
输出到本目录 figures/，标题由 Word 题注承担。
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import (Arc, Circle, Ellipse, FancyArrowPatch,
                                FancyBboxPatch, Polygon, Rectangle, Wedge)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
os.makedirs(OUT, exist_ok=True)

# ---- 调色板（柔和扁平） ----
INK = "#334155"      # 主文字
SUB = "#64748B"      # 次要文字
BLUE = "#2563EB"
BLUE_L = "#DBEAFE"
TEAL = "#0D9488"
TEAL_L = "#CCFBF1"
AMBER = "#D97706"
AMBER_L = "#FEF3C7"
ROSE = "#E11D48"
ROSE_L = "#FFE4E6"
GREEN = "#16A34A"
GREEN_L = "#DCFCE7"
GRAY = "#94A3B8"
GRAY_L = "#F1F5F9"
CARD = "#F8FAFC"
CARD_E = "#E2E8F0"
DARK = "#1E293B"


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white",
                pad_inches=0.12)
    plt.close(fig)
    print("saved", path)


def rbox(ax, x, y, w, h, fc, ec="none", lw=0, r=0.14, z=1, ls="-"):
    b = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad=0,rounding_size={r}",
                       facecolor=fc, edgecolor=ec, lw=lw, zorder=z,
                       linestyle=ls)
    ax.add_patch(b)
    return b


def txt(ax, x, y, s, size=10, color=INK, ha="center", va="center",
        weight="normal", z=10, linespacing=1.4):
    return ax.text(x, y, s, fontsize=size, color=color, ha=ha, va=va,
                   fontweight=weight, zorder=z, linespacing=linespacing)


def arrow(ax, p1, p2, color=GRAY, lw=2.2, rad=0.0, ls="-", z=6,
          shrinkA=0, shrinkB=0):
    a = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=18,
                        color=color, lw=lw, linestyle=ls, zorder=z,
                        connectionstyle=f"arc3,rad={rad}",
                        shrinkA=shrinkA, shrinkB=shrinkB,
                        capstyle="round")
    ax.add_patch(a)
    return a


def camera(ax, x, y, angle_deg, size=0.4, body=BLUE):
    """现代相机图标：圆角机身 + 柔和视场。"""
    r = size * 0.28
    b = FancyBboxPatch((x - size / 2, y - size / 2), size, size,
                       boxstyle=f"round,pad=0,rounding_size={r}",
                       facecolor=body, edgecolor="none", zorder=8)
    ax.add_patch(b)
    ax.add_patch(Circle((x, y), size * 0.12, facecolor="white",
                        edgecolor="none", zorder=9))
    a = np.deg2rad(angle_deg)
    d = np.array([np.cos(a), np.sin(a)])
    p = np.array([x, y], dtype=float)
    tip = p + d * size * 2.0
    lat = np.array([-d[1], d[0]]) * size * 0.95
    ax.add_patch(Polygon([tip, p + lat, p - lat], closed=True,
                         facecolor=body, alpha=0.10, edgecolor="none",
                         zorder=2))
    return p, d, size


def axes_xy(ax, x, y, length=0.5, z=9):
    arrow(ax, (x, y), (x + length, y), color=ROSE, lw=1.8, z=z)
    arrow(ax, (x, y), (x, y + length), color=GREEN, lw=1.8, z=z)
    txt(ax, x + length + 0.07, y, "X", size=9, color=ROSE)
    txt(ax, x - 0.02, y + length + 0.12, "Y", size=9, color=GREEN)


# ---------------------------------------------------------------- fig01 拼接原理
def fig01():
    fig, ax = plt.subplots(figsize=(12.6, 4.4))
    ax.axis("off")
    ax.set_xlim(0, 13.4)
    ax.set_ylim(0, 4.9)

    cw, ch, y0 = 3.9, 3.55, 0.5
    xs = [0.3, 4.95, 9.6]

    # 卡片底
    for x in xs:
        rbox(ax, x, y0, cw, ch, CARD, ec=CARD_E, lw=1.2)
    txt(ax, xs[0] + cw / 2, y0 + ch - 0.32, "① 两个机位各拍一张", size=10.5,
        weight="bold")
    txt(ax, xs[1] + cw / 2, y0 + ch - 0.32, "② 解出变换矩阵", size=10.5,
        weight="bold")
    txt(ax, xs[2] + cw / 2, y0 + ch - 0.32, "③ 拼到同一坐标系", size=10.5,
        weight="bold")

    # 卡片间箭头
    arrow(ax, (xs[0] + cw + 0.08, y0 + ch / 2 - 0.2),
          (xs[1] - 0.08, y0 + ch / 2 - 0.2), color=BLUE, lw=2.6)
    arrow(ax, (xs[1] + cw + 0.08, y0 + ch / 2 - 0.2),
          (xs[2] - 0.08, y0 + ch / 2 - 0.2), color=BLUE, lw=2.6)

    # 卡片 A：两机位 + 重叠 + 标记
    axa = xs[0]
    camera(ax, axa + 0.72, y0 + 0.62, 58, size=0.44)
    camera(ax, axa + cw - 0.72, y0 + 0.62, 122, size=0.44)
    rbox(ax, axa + 1.15, y0 + 1.15, cw - 2.3, 1.5, "#CBD5E1", r=0.1, z=3)
    txt(ax, axa + cw / 2, y0 + 1.9, "工件", size=10.5, color=INK, z=5)
    marks = [(1.52, 2.45), (2.05, 2.72), (2.52, 2.35), (1.72, 1.42),
             (2.48, 1.48)]
    for i, (mx, my) in enumerate(marks):
        ax.add_patch(Circle((axa + mx, y0 + my), 0.09, facecolor="white",
                            edgecolor=ROSE, lw=1.8, zorder=6))
        txt(ax, axa + mx + 0.15, y0 + my + 0.14, f"M{i+1}", size=7.5,
            color=ROSE, ha="left")
    txt(ax, axa + cw / 2, y0 + 0.14, "重叠区里的一批标记 = 公共点",
        size=8.5, color=SUB)

    # 卡片 B：矩阵
    axb = xs[1]
    cell, gx, gy = 0.62, axb + 0.62, y0 + 0.42
    vals = ["r11", "r12", "r13", "tx", "r21", "r22", "r23", "ty",
            "r31", "r32", "r33", "tz", "0", "0", "0", "1"]
    for i, v in enumerate(vals):
        r_, c_ = divmod(i, 4)
        fc = BLUE_L if c_ < 3 and r_ < 3 else (
            AMBER_L if c_ == 3 and r_ < 3 else GRAY_L)
        rbox(ax, gx + c_ * (cell + 0.06),
             gy + (3 - r_) * (cell + 0.06), cell, cell, fc, r=0.07, z=3)
        txt(ax, gx + c_ * (cell + 0.06) + cell / 2,
            gy + (3 - r_) * (cell + 0.06) + cell / 2, v, size=9.5, z=5)
    txt(ax, axb + cw / 2, y0 + 0.14,
        "≥3 个公共点即可解（建议 ≥6）｜ 蓝 = 旋转 R　黄 = 平移 t",
        size=8.5, color=SUB)

    # 卡片 C：合并点云
    axc = xs[2]
    rng = np.random.default_rng(7)
    b1 = rng.normal((axc + 1.55, y0 + 2.3), 0.44, size=(150, 2))
    b2 = rng.normal((axc + 2.75, y0 + 1.6), 0.44, size=(150, 2))
    ax.scatter(b1[:, 0], b1[:, 1], s=5, c=BLUE, alpha=0.45, zorder=4)
    ax.scatter(b2[:, 0], b2[:, 1], s=5, c=TEAL, alpha=0.45, zorder=4)
    for mx, my in [(axc + 2.0, y0 + 1.95), (axc + 2.2, y0 + 1.78)]:
        ax.add_patch(Circle((mx, my), 0.09, facecolor="white",
                            edgecolor=ROSE, lw=1.8, zorder=6))
    axes_xy(ax, axc + 0.35, y0 + 0.5, length=0.5)
    txt(ax, axc + cw / 2, y0 + 0.14, "两片点云严丝合缝", size=8.5,
        color=SUB)

    save(fig, "fig01_拼接原理.png")


# ---------------------------------------------------------------- fig02 编码圆
def fig02():
    fig, ax = plt.subplots(figsize=(7.4, 7.0))
    ax.set_aspect("equal")
    ax.axis("off")
    N = 12
    code = [1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1]  # 1=白 0=黑
    r0, r1, r2, r3 = 1.0, 2.15, 3.0, 3.75
    for i in range(N):
        t1 = 90 - i * (360 / N)
        t2 = 90 - (i + 1) * (360 / N)
        face = "#F8FAFC" if code[i] else DARK
        ax.add_patch(Wedge((0, 0), r1, t2, t1, width=r1 - r0,
                           facecolor=face, edgecolor="#CBD5E1", lw=0.8))
    ax.add_patch(Wedge((0, 0), r3, 0, 360, width=r3 - r2,
                       facecolor="white", edgecolor="#CBD5E1", lw=1.0))
    ax.add_patch(Circle((0, 0), r0, facecolor="#F8FAFC",
                        edgecolor="#CBD5E1", lw=1.2, zorder=4))

    def note(x, y, s, px, py):
        txt(ax, x, y, s, size=9.5, ha="left" if x > 0 else "right",
            va="center", linespacing=1.5)
        ax.plot([px, x + (-0.15 if x > 0 else 0.15)],
                [py, y], color=GRAY, lw=1.0, zorder=1)

    note(4.35, 1.9, "中心白圆 R0\n（相机识别它的圆心）", 0.75, 0.68)
    note(-4.35, 2.6, "编码环带：N=12 个扇区\n黑 = 0，白 = 1 → 唯一编号", -1.5,
         1.35)
    note(4.5, -2.9, "外框（印刷定位）", 2.75, -2.55)
    ax.set_xlim(-7.4, 7.4)
    ax.set_ylim(-4.6, 4.4)
    save(fig, "fig02_编码圆.png")


# ---------------------------------------------------------------- fig03 决策图
def fig03():
    fig, ax = plt.subplots(figsize=(10.8, 7.6))
    ax.axis("off")
    ax.set_xlim(0, 21.6)
    ax.set_ylim(0, 15.6)

    # 起点
    rbox(ax, 5.6, 13.9, 10.4, 1.35, TEAL_L, r=0.3)
    txt(ax, 10.8, 14.57, "多片点云要拼成一个整体 —— 变换矩阵从哪来？",
        size=11.5, weight="bold")

    qw, qh = 7.4, 1.7
    qx, ax_x, aw = 1.3, 12.3, 8.0
    qys = [11.0, 7.5, 4.0]

    def question(y, s):
        rbox(ax, qx, y, qw, qh, AMBER_L, r=0.24)
        ax.add_patch(Circle((qx + 0.85, y + qh / 2), 0.34, facecolor=AMBER,
                            edgecolor="none", zorder=5))
        txt(ax, qx + 0.85, y + qh / 2, "?", size=13, color="white",
            weight="bold")
        txt(ax, qx + 1.5, y + qh / 2, s, size=10.5, ha="left")

    def answer(y, s, fc=BLUE_L):
        rbox(ax, ax_x, y - 0.05, aw, qh + 0.1, fc, r=0.24)
        txt(ax, ax_x + aw / 2, y + qh / 2, s, size=10, linespacing=1.55)

    question(qys[0], "有运动机构吗？\n（导轨 / 机器人 / 转台）")
    question(qys[1], "允许在工件上贴标记吗？")
    question(qys[2], "产线固定工位、批量检测吗？")

    answer(qys[0], "已知运动拼接（首选）\n线扫 / 导轨走拍 / 机器人手眼 / 转台\n"
                   "精度 0.2~1 mm · 需要运动硬件")
    answer(qys[1], "标记物拼接（兜底）\n贴编码圆、逐帧链式配准\n"
                   "精度 0.5~2 mm · 人工成本高", fc=ROSE_L)
    answer(qys[2], "多相机固定阵列\n一次标定长期复用、不贴标记\n"
                   "精度 0.1~0.5 mm · 工装成本最高")

    # 是 → 右
    for y in qys:
        arrow(ax, (qx + qw + 0.1, y + qh / 2), (ax_x - 0.1, y + qh / 2),
              color=GREEN, lw=2.2)
        txt(ax, (qx + qw + ax_x) / 2, y + qh / 2 + 0.28, "是", size=9.5,
            color=GREEN, weight="bold")
    # 否 ↓
    for y1, y2 in [(qys[0], qys[1] + qh), (qys[1], qys[2] + qh),
                   (qys[2], 2.6 + 0.0)]:
        arrow(ax, (qx + 0.85, y1 - 0.05), (qx + 0.85, y2 + 0.08),
              color=GRAY, lw=2.0)
        txt(ax, qx + 1.3, (y1 + y2) / 2, "否", size=9.5, color=SUB,
            weight="bold")

    # 兜底 + ICP 提示
    rbox(ax, qx, 0.9, qw + 0.2, 1.7, ROSE_L, r=0.24)
    txt(ax, qx + (qw + 0.2) / 2, 0.9 + 0.85,
        "都不能？→ 中转标定物 / 翻转转台\n（顶底拼接等特殊场景的建系办法）",
        size=9.5, linespacing=1.55)
    rbox(ax, ax_x, 0.9, aw, 1.7, GRAY_L, r=0.24)
    txt(ax, ax_x + aw / 2, 0.9 + 0.85,
        "ICP 只当“精配准微调”\n（圆柱面上纯 ICP 必然漂移）",
        size=9.5, color=SUB, linespacing=1.55)

    save(fig, "fig03_方案决策.png")


# ---------------------------------------------------------------- fig04 已知运动四合一
def fig04():
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 8.2))
    fig.subplots_adjust(hspace=0.32, wspace=0.14,
                        left=0.02, right=0.98, top=0.96, bottom=0.02)

    def panel(ax, title):
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 7.2)
        ax.set_aspect("equal")
        ax.axis("off")
        rbox(ax, 0.15, 0.15, 9.7, 6.9, CARD, ec=CARD_E, lw=1.2)
        rbox(ax, 0.45, 6.15, 5.6, 0.62, BLUE_L, r=0.28)
        txt(ax, 0.75, 6.46, title, size=10.5, ha="left", weight="bold",
            color=BLUE)

    # (a) 编码器线扫
    ax = axes[0][0]
    panel(ax, "a · 编码器线扫：走一趟扫一条")
    ax.plot([0.7, 9.3], [5.5, 5.5], color=GRAY, lw=2.5,
            solid_capstyle="round")
    for x in np.arange(1.0, 9.2, 0.75):
        ax.plot([x, x], [5.32, 5.68], color=GRAY, lw=1.2)
    camera(ax, 2.9, 4.85, -90, size=0.5)
    arrow(ax, (3.6, 4.85), (7.2, 4.85), color=GREEN, lw=2.2)
    txt(ax, 5.4, 5.15, "匀速移动，脉冲逐行触发", size=8.5, color=GREEN)
    rbox(ax, 0.9, 1.3, 8.2, 2.0, "#CBD5E1", r=0.1)
    txt(ax, 5, 2.3, "长工件", size=10.5)
    for x in np.arange(1.3, 8.9, 0.75):
        ax.plot([x, x], [3.42, 3.72], color=GREEN, lw=1.8)
    txt(ax, 5, 0.72, "行间位移 = 编码器读数，轴向无需拼接", size=8.5,
        color=SUB)

    # (b) 导轨走拍
    ax = axes[0][1]
    panel(ax, "b · 导轨/龙门走拍：已知位移 + 微调")
    ax.plot([1, 1, 9, 9], [0.9, 6.0, 6.0, 0.9], color=GRAY, lw=2.5)
    rbox(ax, 3.2, 2.7, 3.6, 1.9, "#CBD5E1", r=0.1)
    txt(ax, 5, 3.65, "工件", size=10.5)
    k = 0
    for gy in (4.9, 3.65, 2.4):
        for gx in (2.3, 4.05, 5.8, 7.55):
            k += 1
            ax.add_patch(Circle((gx, gy), 0.15, facecolor=BLUE,
                                edgecolor="white", lw=1.2, zorder=5))
            txt(ax, gx, gy - 0.42, str(k), size=7, color=SUB)
    txt(ax, 5, 1.35, "每点位置由光栅尺给出 → 已知平移 + 精配准", size=8.5,
        color=SUB)

    # (c) 机器人手眼
    ax = axes[1][0]
    panel(ax, "c · 机器人 + 手眼标定：一次标定随处换算")
    rbox(ax, 0.7, 0.55, 1.9, 1.3, GRAY, r=0.1)
    txt(ax, 1.65, 1.2, "机械臂\n基座", size=8.5, color="white")
    joints = [(1.65, 1.85), (3.3, 4.1), (5.5, 4.9), (7.0, 3.5)]
    segs = [(joints[0], joints[1], 5.5), (joints[1], joints[2], 4.5),
            (joints[2], joints[3], 3.5)]
    for (a, b, lw) in segs:
        ax.plot([a[0], b[0]], [a[1], b[1]], color=INK, lw=lw,
                solid_capstyle="round", zorder=4)
    for j in joints:
        ax.add_patch(Circle(j, 0.19, facecolor="white", edgecolor=INK,
                            lw=1.6, zorder=6))
    camera(ax, 7.35, 3.05, -52, size=0.5)
    txt(ax, 8.35, 2.55, "相机在末端\n（眼在手上）", size=8, color=SUB)
    rbox(ax, 4.3, 0.55, 4.4, 1.05, "#CBD5E1", r=0.1)
    txt(ax, 6.5, 1.07, "工件", size=10)
    arrow(ax, (7.6, 3.9), (5.0, 2.6), color=GREEN, lw=1.8, rad=0.25)
    txt(ax, 6.6, 4.35, "摆 ≥15 个姿势标定一次", size=8.5, color=GREEN)

    # (d) 转台
    ax = axes[1][1]
    panel(ax, "d · 转台/托辊：环向变成已知转角")
    rbox(ax, 3.3, 0.7, 3.4, 0.5, GRAY, r=0.1)
    txt(ax, 5, 0.38, "转台 / 托辊", size=8.5, color=SUB)
    ax.add_patch(Circle((5, 3.2), 1.75, facecolor="#CBD5E1",
                        edgecolor="none"))
    ax.add_patch(Circle((5, 3.2), 0.55, facecolor="white",
                        edgecolor=GRAY, lw=1.2))
    txt(ax, 5, 3.2, "工件\n旋转", size=8.5)
    ax.add_patch(Arc((5, 3.2), 4.9, 4.9, theta1=35, theta2=145,
                     color=GREEN, lw=2.4))
    arrow(ax, (2.05, 4.55), (1.45, 4.0), color=GREEN, lw=2.2, rad=-0.3)
    camera(ax, 8.5, 3.2, 180, size=0.5)
    txt(ax, 8.5, 4.15, "相机固定", size=8.5, color=SUB)
    txt(ax, 5, 5.85, "每转一个已知角度拍一张，环向无需特征配准",
        size=8.5, color=GREEN)

    save(fig, "fig04_已知运动.png")


# ---------------------------------------------------------------- fig05 固定阵列
def fig05():
    fig, ax = plt.subplots(figsize=(8.0, 7.6))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(-6.6, 6.6)
    ax.set_ylim(-6.6, 6.4)

    rbox(ax, -1.6, -0.85, 3.2, 1.7, "#CBD5E1", r=0.16)
    txt(ax, 0, 0, "工件", size=12, weight="bold")
    txt(ax, 0, -1.35, "统一坐标系（标定一次，长期复用）", size=8.5,
        color=SUB)

    ax.add_patch(Arc((0, 0), 7.8, 7.8, theta1=0, theta2=360, color=GREEN,
                     lw=1.6, linestyle=(0, (1, 3))))

    angles = [90, 18, -54, -126, -198]
    for i, adeg in enumerate(angles):
        a = np.deg2rad(adeg)
        px, py = 4.5 * np.cos(a), 4.5 * np.sin(a)
        camera(ax, px, py, adeg + 180, size=0.52)
        lx, ly = 5.6 * np.cos(a), 5.6 * np.sin(a)
        ha = "center"
        dy = 0.3
        if abs(lx) > 4.9:
            ha = "left" if lx > 0 else "right"
            dy = 0
        txt(ax, lx, ly + dy, f"相机 {i+1}", size=9, ha=ha, color=INK)

    axes_xy(ax, 2.6, -5.9, length=0.6)
    save(fig, "fig05_固定阵列.png")


# ---------------------------------------------------------------- fig06 链式闭环
def fig06():
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 4.3))
    fig.subplots_adjust(left=0.02, right=0.98, top=0.86, bottom=0.04,
                        wspace=0.08)

    node_kw = dict(facecolor=BLUE_L, edgecolor=BLUE, lw=1.6, zorder=6)

    def node(ax, x, y, label, fc=BLUE_L, ec=BLUE, tc=BLUE):
        # 用 scatter 画节点，保证任意宽高比下都是正圆
        ax.scatter([x], [y], s=1500, facecolor=fc, edgecolor=ec,
                   linewidth=1.6, zorder=6)
        txt(ax, x, y, label, size=9, color=tc)

    # 左：无闭环
    ax = axes[0]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    rbox(ax, 0.15, 0.15, 9.7, 3.5, CARD, ec=CARD_E, lw=1.2)
    txt(ax, 5, 3.32, "无闭环：误差逐步累积", size=10.5, weight="bold")
    xs = np.linspace(1.15, 6.9, 5)
    for i, x in enumerate(xs):
        node(ax, x, 1.95, f"帧{i+1}")
        if i < 4:
            arrow(ax, (x + 0.48, 1.95), (x + 1.08, 1.95), color=GRAY,
                  lw=1.8, z=4)
    node(ax, 7.35, 3.0, "帧5′", fc="white", ec=AMBER, tc=AMBER)
    arrow(ax, (7.0, 2.2), (7.28, 2.6), color=AMBER, lw=2.0)
    txt(ax, 5, 0.68, "拼到第 5 帧已偏 —— 首尾对不上（漂移）\n"
                     "链越长漂得越多（150 帧末端可错位数毫米）",
        size=8.5, color=AMBER, linespacing=1.6)

    # 右：闭环
    ax = axes[1]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    rbox(ax, 0.15, 0.15, 9.7, 3.5, CARD, ec=CARD_E, lw=1.2)
    txt(ax, 5, 3.9, "闭环 + 全局优化：把漂移拉回来", size=10.5,
        weight="bold", color=GREEN)
    pts = [(1.5, 2.05), (4.1, 2.75), (7.3, 2.3), (6.5, 0.95), (2.5, 0.8)]
    for i in range(4):
        arrow(ax, pts[i], pts[i + 1], color=GRAY, lw=1.8, z=4,
              shrinkA=22, shrinkB=22)
    arrow(ax, pts[4], pts[0], color=GREEN, lw=2.2, ls=(0, (4, 3)), z=4,
          shrinkA=22, shrinkB=22)
    for i, (x, y) in enumerate(pts):
        node(ax, x, y, f"帧{i+1}")
    txt(ax, 4.0, 0.05, "闭环边：扫回起点再拍一次，起点终点“理应重合”",
        size=8.5, color=GREEN)

    save(fig, "fig06_链式闭环.png")


# ---------------------------------------------------------------- fig07 ICP 简并
def fig07():
    fig, ax = plt.subplots(figsize=(11.8, 4.8))
    ax.set_xlim(0, 13.4)
    ax.set_ylim(0, 5.4)
    ax.set_aspect("equal")
    ax.axis("off")

    # 左：周期点阵（展开面）
    def grid(x0, y0, color, dashed=False):
        for gx in np.arange(0, 4.01, 0.8):
            for gy in np.arange(0, 2.01, 0.8):
                kw = dict(facecolor=color, edgecolor="none", zorder=4)
                if dashed:
                    kw = dict(facecolor="none", edgecolor=color, lw=1.4,
                              zorder=5)
                ax.add_patch(Circle((x0 + gx, y0 + gy), 0.09, **kw))

    rbox(ax, 0.7, 1.2, 4.0, 2.7, GRAY_L, r=0.1, z=2)
    grid(0.9, 1.4, INK)
    rbox(ax, 1.9, 1.65, 4.0, 2.7, "none", ec=AMBER, lw=1.8, r=0.1, z=6,
         ls=(0, (4, 3)))
    grid(2.1, 1.85, AMBER, dashed=True)
    txt(ax, 2.7, 4.6, "圆柱面展开：表面点阵有周期性", size=10,
        weight="bold")
    arrow(ax, (2.6, 5.05), (5.0, 5.05), color=AMBER, lw=1.8)
    arrow(ax, (5.0, 5.05), (2.6, 5.05), color=AMBER, lw=1.8)
    txt(ax, 3.8, 5.22, "沿轴滑移一格，照样重合", size=8.5, color=AMBER)
    arrow(ax, (0.42, 3.2), (0.95, 3.95), color=AMBER, lw=1.8, rad=-0.25)
    txt(ax, 0.4, 2.5, "绕轴转一格\n也照样重合", size=8.5, color=AMBER,
        ha="left")

    # 右：结论卡片
    rbox(ax, 7.6, 0.7, 5.5, 3.9, AMBER_L, r=0.2)
    txt(ax, 10.35, 4.05, "纯 ICP 在这类表面上失效", size=10.5,
        weight="bold", color=AMBER)
    txt(ax, 7.95, 3.3, "· 沿轴滑移 —— 点阵照样重合\n"
                       "· 绕轴旋转 —— 点阵照样重合\n\n"
                       "两个方向“怎么挪都差不多”，\n算法分不出对错 → 必然漂移",
        size=9.5, ha="left", va="top", linespacing=1.7)

    save(fig, "fig07_ICP简并.png")


# ---------------------------------------------------------------- fig08 顶底中转
def fig08():
    fig, ax = plt.subplots(figsize=(7.6, 7.4))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(0, 9.6)
    ax.set_ylim(-1.3, 10.2)

    camera(ax, 4.8, 9.2, -90, size=0.62)
    txt(ax, 6.0, 9.2, "顶部相机", size=10, ha="left", weight="bold")
    camera(ax, 4.8, 1.2, 90, size=0.62)
    txt(ax, 6.0, 1.2, "底部相机", size=10, ha="left", weight="bold")

    # 双面标定板
    rbox(ax, 3.3, 4.0, 3.0, 2.1, GRAY_L, ec=CARD_E, lw=1.2, r=0.1)
    rbox(ax, 3.3, 5.05, 3.0, 1.05, BLUE_L, r=0.1, z=3)
    txt(ax, 4.8, 5.58, "A 面", size=9.5, color=BLUE, z=5)
    txt(ax, 4.8, 4.52, "B 面", size=9.5, color=SUB, z=5)
    txt(ax, 2.9, 5.58, "（顶相机看）", size=8, color=SUB, ha="right", z=5)
    txt(ax, 2.9, 4.52, "（底相机看）", size=8, color=SUB, ha="right", z=5)

    arrow(ax, (6.75, 6.1), (6.75, 4.0), color=GRAY, lw=1.2)
    arrow(ax, (6.75, 4.0), (6.75, 6.1), color=GRAY, lw=1.2)
    txt(ax, 7.0, 5.05, "厚度 t 已知", size=8.5, ha="left")

    arrow(ax, (4.35, 8.35), (4.2, 6.35), color=GREEN, lw=2.2)
    txt(ax, 2.2, 7.5, "拍到 A 面", size=9, color=GREEN, ha="center")
    arrow(ax, (5.3, 2.15), (5.45, 3.75), color=GREEN, lw=2.2)
    txt(ax, 7.3, 3.0, "拍到 B 面", size=9, color=GREEN, ha="center")

    txt(ax, 4.8, -0.55, "两面几何关系已知 → 顶、底坐标系被“桥接”起来",
        size=9.5, color=SUB)
    save(fig, "fig08_顶底中转.png")


# ---------------------------------------------------------------- fig09 双层皮
def fig09():
    fig, ax = plt.subplots(figsize=(11.0, 3.9))
    ax.set_xlim(0, 12.4)
    ax.set_ylim(0, 4.4)
    ax.axis("off")

    xs = np.linspace(0.5, 5.0, 80)
    base = 2.3 + 0.22 * np.sin(xs * 2.1)
    ax.plot(xs, base, color=INK, lw=2.4, solid_capstyle="round")
    m = (xs > 1.5) & (xs < 4.0)
    ax.plot(xs[m], base[m] + 0.42, color=AMBER, lw=2.0, ls=(0, (4, 3)))
    ax.plot(xs[m], base[m] - 0.42, color=AMBER, lw=2.0, ls=(0, (4, 3)))
    ax.fill_between(xs[m], base[m] - 0.42, base[m] + 0.42, color=AMBER,
                    alpha=0.10, zorder=1)
    txt(ax, 2.75, 3.6, "重叠区被两帧各采一层 → “双层皮”", size=9.5,
        color=AMBER)
    txt(ax, 2.75, 0.75, "合并后未处理", size=9.5, color=SUB)

    arrow(ax, (5.55, 2.3), (6.35, 2.3), color=GRAY, lw=2.6)

    xs2 = np.linspace(6.9, 12.0, 80)
    ax.plot(xs2, 2.3 + 0.22 * np.sin((xs2 - 6.9 + 0.5) * 2.1), color=INK,
            lw=2.4, solid_capstyle="round")
    txt(ax, 9.45, 3.6, "去重 / 下采样 / 边界平滑", size=9.5, color=GREEN)
    txt(ax, 9.45, 0.75, "后处理后（可交付）", size=9.5, color=SUB)

    save(fig, "fig09_双层皮.png")


if __name__ == "__main__":
    fig01()
    fig02()
    fig03()
    fig04()
    fig05()
    fig06()
    fig07()
    fig08()
    fig09()
    print("all figures done ->", OUT)
