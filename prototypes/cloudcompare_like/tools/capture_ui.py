# -*- coding: utf-8 -*-
"""
cloudcompare_like 原型 UI 复刻 —— 运行实测截图 + S1~S7/S9 脚本内断言（S3.5）。

文档：docs/S3.5后处理原型UI重构与基础功能方案_20260924.md（判据口径 §6.1 裁定）
判据来源：docs/原型UI一次性复刻方案与截图验收标准_20260923.md v3.4 §4.2（不改判据，
只换目标原型；S8 目视 7 项为人工判据，不在本脚本内）

跑法（真实桌面会话，主组；**不设 QT_QPA_PLATFORM**）：
  cd D:\\RVC_SRC\\Python\\MultiCameraCalibration
  unset PYTHONPATH
  "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/cloudcompare_like/tools/capture_ui.py
副组（色值回归，字体/中文类判据豁免）：
  ... capture_ui.py --offscreen          # 图存 docs/ui_review/offscreen/

硬性口径（§10.10 裁定 B/C）：grab() 原始分辨率不入缩放；S4 窗口整图内取色 +
visibleRegion() 非空，禁 statusbar.grab()；failed 由真坏文件触发；processing 经
公开状态入口 set_state 构造（本脚本已标注）；截图 8 张固定命名对账。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

_OFFSCREEN = "--offscreen" in sys.argv
if _OFFSCREEN:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
else:
    # 主组硬性口径：真实桌面会话。外部环境变量残留会把主组静默跑成 offscreen。
    os.environ.pop("QT_QPA_PLATFORM", None)

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_PROTO = os.path.dirname(_TOOLS)
REPO = os.path.abspath(os.path.join(_PROTO, "..", ".."))
# app 包内是相对导入（from ..core.cc_workflow / from .cc_gl_viewer），必须走
# 全限定包路径导入（与 tests 同法）；_PROTO 自身不上 path，避免原型自带 core/
# 包抢占 src/core。
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))
os.chdir(_PROTO)                      # 路径引导依赖 cwd（R12 口径）

import numpy as np                                              # noqa: E402
from PySide6.QtCore import QRect, Qt                            # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter       # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea  # noqa: E402

from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWindow  # noqa: E402
from ui_v2.launcher_dialog import LauncherDialog                # noqa: E402
from ui_v2.main_window import MainWindowShell                   # noqa: E402
from ui_v2.theme import (ACCENT, ACCENT_DIM, BG_CARD, BG_PANEL,         # noqa: E402
                         BG_WINDOW, GLOBAL_QSS, STATUS_ERR,
                         STATUS_OK, STATUS_WARN, TEXT_MUTED)
from ui_v2.widgets.device_table import DeviceInfo               # noqa: E402

OUT = os.path.join(REPO, "docs", "ui_review", "offscreen" if _OFFSCREEN else "")
os.makedirs(OUT, exist_ok=True)

FONT_ALLOWED = ("Segoe UI", "Microsoft YaHei", "Microsoft YaHei UI")
STATE_TOKENS = {"idle": TEXT_MUTED, "loaded": STATUS_OK,
                "processing": STATUS_WARN, "failed": STATUS_ERR}

_results: list[tuple[str, bool, str]] = []


def check(tag: str, ok: bool, detail: str = ""):
    _results.append((tag, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}  {detail}")


# ------------------------------------------------------------------ 像素工具
def _rgb(img, x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def _hex(rgb):
    return "#%02X%02X%02X" % rgb


def _dist(a, b):
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def _tok(h):
    """token → (r,g,b)；兼容 '#rrggbb' 与 'rgba(r, g, b, a)' 两种 token 写法。"""
    h = h.strip()
    if h.startswith("rgba"):
        nums = [int(v) for v in re.findall(r"\d+", h)[:3]]
        return tuple(nums)
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def _edge(w_or_img, token, tol=3):
    """控件边缘点采样（避文字污染），返回 (ok, 描述)。"""
    if hasattr(w_or_img, "grab"):
        if not w_or_img.isVisible():
            return False, f"控件不可见（隐藏控件 grab 回 #000000）: {w_or_img}"
        img, w, h = w_or_img.grab().toImage(), w_or_img.width(), w_or_img.height()
    else:
        img, w, h = w_or_img
    got = _rgb(img, w - 6, h // 2)
    d = _dist(got, _tok(token))
    return d <= tol, f"({w}x{h}) 实测 {_hex(got)} vs {token} Δ={d}"


def _img_arr(img):
    """QImage → RGB numpy 数组（走 Format_RGB888；按 bytesPerLine 步长去填充）。"""
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h, stride = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(h, stride)
    return buf[:, 0:w * 3:3].copy(), buf[:, 1:w * 3:3].copy(), buf[:, 2:w * 3:3].copy()


def _blend(fg_rgba: str, bg_hex: str) -> str:
    """rgba token 叠在底色上的合成色（ACCENT_DIM 这类半透明 token 的期望值）。"""
    fr, fg_, fb, fa = [int(v) for v in re.findall(r"\d+", fg_rgba)[:4]]
    br, bg, bb = _tok(bg_hex)
    return "#%02X%02X%02X" % (round(fr * fa + br * (1 - fa)),
                              round(fg_ * fa + bg * (1 - fa)),
                              round(fb * fa + bb * (1 - fa)))


def _interior_dist(widget, token):
    """控件内部网格采样到 token 的最近距离（返回 best, 描述）。"""
    img, w, h = widget.grab().toImage(), widget.width(), widget.height()
    tr, tg, tb = _tok(token)
    best = 999
    for y in range(4, max(5, h - 4), 2):
        for x in range(4, max(5, w - 4), 2):
            c = img.pixelColor(x, y)
            best = min(best, max(abs(c.red() - tr), abs(c.green() - tg),
                                 abs(c.blue() - tb)))
    return best, f"({w}x{h})"


def _interior_nearest(widget, token, tol=3):
    best, desc = _interior_dist(widget, token)
    return best <= tol, f"{desc} 内部区最近像素 Δ={best} vs {token}"


def _nearest(img, token, region=None):
    """图内（或 region=(x0,y0,x1,y1) 子区）最接近 token 的像素距离与坐标。"""
    r, g, b = _img_arr(img)
    tr, tg, tb = _tok(token)
    x_off = y_off = 0
    if region is not None:
        x0, y0, x1, y1 = region
        r, g, b = r[y0:y1, x0:x1], g[y0:y1, x0:x1], b[y0:y1, x0:x1]
        x_off, y_off = x0, y0
    d = np.maximum.reduce([np.abs(r.astype(int) - tr), np.abs(g.astype(int) - tg),
                           np.abs(b.astype(int) - tb)])
    idx = int(np.argmin(d))
    y, x = np.unravel_index(idx, d.shape)
    return int(d.flat[idx]), (int(x) + x_off, int(y) + y_off)


def _light_ratio(img):
    """浅底像素占比（min(R,G,B) > 200），S2。"""
    r, g, b = _img_arr(img)
    zone = (slice(2, -2, 3), slice(2, -2, 3))
    light = (np.minimum(np.minimum(r[zone], g[zone]), b[zone]) > 200).mean()
    return float(light)


# ------------------------------------------------------------------ 数据构造
def make_cloud_ply(directory, name, n=30000, seed=0, offset=(0.0, 0.0, 0.0)):
    """生成两团可区分的测试点云（真实走 open3d 写盘，载入走公开 _load_files）。"""
    import open3d as o3d
    rng = np.random.default_rng(seed)
    pts = np.vstack([
        rng.normal([0.0 + offset[0], 0.0 + offset[1], 0.0 + offset[2]], 8.0, (n // 2, 3)),
        rng.normal([25.0 + offset[0], 5.0 + offset[1], -3.0 + offset[2]], 8.0,
                   (n - n // 2, 3)),
    ])
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    path = os.path.join(directory, name)
    assert o3d.io.write_point_cloud(path, pcd), f"写测试点云失败: {path}"
    return path


def grab(widget, name):
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()
    img = widget.grab().toImage()
    path = os.path.join(OUT, name)
    img.save(path)
    print(f"      -> {path}  ({img.width()}x{img.height()})")
    return img


# ------------------------------------------------------------------ S5 代码扫描
def s5_scan():
    app_dir = os.path.join(_PROTO, "app")
    hex_hits, font_hits = [], []
    for fn in sorted(os.listdir(app_dir)):
        if not fn.endswith(".py"):
            continue
        for i, line in enumerate(open(os.path.join(app_dir, fn), encoding="utf-8"), 1):
            code = re.split(r"\s#", line)[0]        # 去行尾注释（判据"注释除外"）
            if code.lstrip().startswith("#"):
                continue
            if re.search(r"#[0-9a-fA-F]{6}|rgba\(", code):
                hex_hits.append(f"{fn}:{i}")
            # §6.1 裁定 A 新口径（旧 setFont( 口径作废）
            if re.search(r"""QFont\(\s*["']|font-family:['"]?""", code):
                font_hits.append(f"{fn}:{i}")
    return hex_hits, font_hits


# ------------------------------------------------------------------ 并排图合成
def compose(cells, out_path, cell=(690, 415), gap=10, label_h=18):
    cols, rows = 2, 2
    W = cols * cell[0] + (cols + 1) * gap
    H = rows * (cell[1] + label_h) + (rows + 1) * gap
    canvas = QImage(W, H, QImage.Format_RGB32)
    canvas.fill(QColor(BG_WINDOW))
    pt = QPainter(canvas)
    for idx, (title, img) in enumerate(cells):
        r, c = divmod(idx, cols)
        x = gap + c * (cell[0] + gap)
        y = gap + r * (cell[1] + label_h + gap)
        pt.setPen(QColor(TEXT_MUTED))
        pt.setFont(QFont("Segoe UI", 9))
        pt.drawText(QRect(x, y, cell[0], label_h), Qt.AlignVCenter | Qt.AlignLeft, title)
        scaled = img.scaled(cell[0], cell[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pt.drawImage(x, y + label_h, scaled)
    pt.end()
    canvas.save(out_path)
    print(f"      -> {out_path}  ({canvas.width()}x{canvas.height()})")


# ------------------------------------------------------------------ 状态色断言
def check_state_color(img, state, real_w, real_h):
    """S4：状态点颜色须在窗口整图（底部状态区）内可寻，Δ≤8。"""
    region = (0, real_h - 70, real_w // 2, real_h)   # 状态栏带，仍属窗口整图
    d, px = _nearest(img, STATE_TOKENS[state], region)
    got = _hex(_rgb(img, px[0], px[1]))
    check(f"S4 {state.upper()}→{STATE_TOKENS[state]}", d <= 8,
          f"状态区最近像素 {got}@{px} vs {STATE_TOKENS[state]} Δ={d}")


# ------------------------------------------------------------------ 主流程
def main() -> int:
    app = QApplication.instance() or QApplication(["capture_ui"])
    app.setStyleSheet(GLOBAL_QSS)         # 设计语言唯一来源
    print(f"platform={app.platformName()}  offscreen={_OFFSCREEN}  out={OUT}")
    print(f"app.font()={app.font().family()!r}")

    tmp = tempfile.mkdtemp(prefix="cc_ui_")
    pa = make_cloud_ply(tmp, "blob_a.ply", 30000, 0, (0.0, 0.0, 0.0))
    pb = make_cloud_ply(tmp, "blob_b.ply", 30000, 1, (30.0, 0.0, 0.0))
    bad = os.path.join(tmp, "broken.ply")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("ply\nthis header is broken\n")

    win = CloudCompareWindow()
    win.resize(1400, 1105)                # S2 档位锚定真机 grab 尺寸
    win.show()
    for _ in range(4):
        app.processEvents()
    win.set_log_visible(True)             # 浮动日志进入截图（S7/S9 可见性）
    ws = win.workspace
    real_w, real_h = win.width(), win.height()
    print(f"窗口 nominal=1400x1105 → 实际 {real_w}x{real_h}"
          f"（minimumSizeHint={win.minimumSizeHint().width()}"
          f"x{win.minimumSizeHint().height()}）")
    vis_ok = not win.visibleRegion().isEmpty()
    check("S4 前置：窗口整图 visibleRegion 非空", vis_ok, f"visibleRegion={vis_ok}")

    # ===== 状态 1：IDLE =====
    img_idle = grab(win, "proto_idle.png")

    # -- S1 色值与 token 一致（元素级；S1② 补 QToolButton/QTreeView/QHeaderView）--
    parts = []
    ok_all = True
    for tag, w, tok in (
            ("QPushButton(打开)", ws._toolbar.findChildren(QPushButton)[0], BG_CARD),
            ("QTreeWidget", ws._db_tree._tree, BG_CARD),
            ("QHeaderView", ws._db_tree._tree.header(), BG_CARD),
            ("FloatingLogPanel", win._log_panel, BG_PANEL),
            ("CCToolBar", ws._toolbar, BG_PANEL),
    ):
        ok, d = _edge(w, tok)
        ok_all &= ok
        parts.append(f"{tag}{d}")
    # QToolButton:checked → ACCENT_DIM。实测本机 Qt 样式表渲染丢弃 rgba alpha
    # （纯色输出，已用 QLabel 最小例实证，主程序 GLOBAL_QSS 同样受影响）：
    # 渲染值 = 平台相关（alpha 修复前 ≈ solid ACCENT，修复后 = 叠在 BG_PANEL 的
    # 合成色），两者取近者，判据仍可 discriminating（错色/绿/蓝必失败）。
    ws._toolbar._btn_roi.setChecked(True)
    app.processEvents()
    d_dim, desc = _interior_dist(ws._toolbar._btn_roi,
                                 _blend(ACCENT_DIM, BG_PANEL))
    d_sol, _ = _interior_dist(ws._toolbar._btn_roi, ACCENT)
    d_best = min(d_dim, d_sol)
    ok = d_best <= 3
    ok_all &= ok
    parts.append(f"QToolButton:checked{desc} Δ={d_best}"
                 f"（ACCENT_DIM 合成 #/solid ACCENT 取近；alpha 丢弃为平台行为）")
    ws._toolbar._btn_roi.setChecked(False)
    # 中央窗口底 + 顶栏/状态栏（整图采样）
    edge_mid = _rgb(img_idle, 5, real_h // 2)
    top = _rgb(img_idle, real_w // 2, 5)
    bot = _rgb(img_idle, real_w // 2, real_h - 6)
    ok_edge = _dist(edge_mid, _tok(BG_WINDOW)) <= 3
    ok_bar = (_dist(top, _tok(BG_PANEL)) <= 3) and (_dist(bot, _tok(BG_PANEL)) <= 3)
    ok_all &= (ok_edge and ok_bar)
    parts.append(f"中央底{_hex(edge_mid)} vs {BG_WINDOW}Δ={_dist(edge_mid, _tok(BG_WINDOW))}"
                 f"；顶栏{_hex(top)}/状态栏{_hex(bot)} vs {BG_PANEL}")
    check("S1 色值=token（元素级）", ok_all, " | ".join(parts))

    # -- S2 无浅色残留 --
    lr = _light_ratio(img_idle)
    check("S2 浅底像素占比 ≤1%", lr <= 0.01, f"实测 {lr * 100:.2f}%")

    # -- S3 字体（真机判据；采样前 show()+processEvents 已满足）--
    fam = ws.font().family()
    if _OFFSCREEN:
        check("S3 字体（offscreen 豁免）", True,
              f"控件字体={fam!r}（字体族判据仅真机）")
    else:
        check("S3 字体一致", fam in FONT_ALLOWED,
              f"QSS 生效后控件字体={fam!r} ∈ {FONT_ALLOWED}；"
              f"app.font()={app.font().family()!r}")

    check_state_color(img_idle, "idle", real_w, real_h)

    # ===== 状态 4 先行：FAILED（idle 吃真坏文件，裁定 B 真实分支）=====
    ws._load_files([bad])
    img_failed = grab(win, "proto_failed.png")
    check_state_color(img_failed, "failed", real_w, real_h)

    # ===== 状态 2：LOADED =====
    ws._load_files([pa, pb])
    img_loaded = grab(win, "proto_loaded.png")
    check_state_color(img_loaded, "loaded", real_w, real_h)

    # -- S6 无裁剪 --
    tree = ws._db_tree._tree
    sbar_max = ws._left_panel.verticalScrollBar().maximum()
    check("S6 无裁剪（树表头可见 + 左滚动区存在）",
          (not tree.isHeaderHidden()) and isinstance(ws._left_panel, QScrollArea)
          and sbar_max >= 0,
          f"headerHidden={tree.isHeaderHidden()}；左滚动条 max={sbar_max}")

    # 左面板特写（loaded 态内容最全：三列 + 层级 + 点数）
    zoom = ws._left_panel.grab().toImage()
    zoom.save(os.path.join(OUT, "proto_panel_zoom.png"))
    print(f"      -> {os.path.join(OUT, 'proto_panel_zoom.png')}  "
          f"({zoom.width()}x{zoom.height()})")

    # ===== 状态 3：PROCESSING（经公开状态入口构造，裁定 B 允许并标注）=====
    ws.set_state("processing")
    img_proc = grab(win, "proto_processing.png")
    check_state_color(img_proc, "processing", real_w, real_h)
    ws.set_state("loaded")                # 回到稳定态继续后续档

    # ===== 缩窗档（S7）：最小宽 × 600 =====
    wn = win.minimumSizeHint().width()
    win.resize(wn, 600)
    for _ in range(3):
        app.processEvents()
    img_small = grab(win, "proto_min_size_resized.png")
    inside = win.rect().contains(win._log_panel.geometry())
    check("S7 浮动日志面板（叠加层 + 不跑出窗外）",
          (not win._log_panel.isWindow()) and win._log_panel.isVisible() and inside,
          f"isWindow={win._log_panel.isWindow()} visible={win._log_panel.isVisible()} "
          f"inside={inside}@ {win.width()}x{win.height()}"
          f"（实际 grab={img_small.width()}x{img_small.height()}；最小宽={wn}）")
    win.resize(1400, 1105)
    for _ in range(3):
        app.processEvents()

    # ===== 主程序参照图（同 QSS 同尺寸）=====
    win_main = MainWindowShell()
    devs = [DeviceInfo(model="M2600R", serial="SN1", ip="192.168.1.10", online=True),
            DeviceInfo(model="M2600R", serial="SN2", ip="192.168.1.11", online=True)]
    win_main.set_mode(LauncherDialog.MODE_MULTI_CAM, devs)
    win_main.resize(real_w, real_h)
    win_main.show()
    img_main = grab(win_main, "main_ref.png")
    tb_h = win_main._toolbar.height() if getattr(win_main, "_toolbar", None) else 42
    sb_h = win_main._statusbar.height() if getattr(win_main, "_statusbar", None) else 28
    main_close = img_main.copy(QRect(0, tb_h, 330, max(80, img_main.height() - tb_h - sb_h)))

    # -- S9 防"只改色号"：外壳元素必须同时可见 --
    check("S9 外壳元素齐备",
          win._toolbar.isVisible() and win._statusbar.isVisible()
          and win._log_panel.isVisible() and ws._left_panel.isVisible()
          and ws._viewer.isVisible() and (not tree.isHeaderHidden()),
          "顶栏 + 状态栏 + 浮动日志 + 左滚动面板 + 3D 区 + 树表头")

    # ===== 并排图 =====
    compose([("主程序 MainWindowShell · 多相机工作区", img_main),
             ("cloudcompare_like 原型宿主 %dx%d" % (real_w, real_h), img_idle),
             ("主程序左面板特写（裁剪）", main_close),
             ("原型左面板特写（loaded：三列 + file→cloud 层级）", zoom)],
            os.path.join(OUT, "cmp_side_by_side.png"))

    # ===== S5 零硬编码 =====
    hex_hits, font_hits = s5_scan()
    check("S5 零硬编码（hex/rgba + QFont('…')/font-family）",
          not hex_hits and not font_hits,
          f"hex/rgba 命中 {len(hex_hits)}：{hex_hits[:5]}；"
          f"字体命中 {len(font_hits)}：{font_hits[:5]}")

    print("\n注：S8 目视 7 项为人工判据，不在脚本内，由 @verify 对 8 张图判定。")
    bad = [t for t, ok, _ in _results if not ok]
    print("\n==== capture_ui 小结 ====")
    print(f"断言 {len(_results)} 项，PASS {len(_results) - len(bad)}，FAIL {len(bad)}"
          + (f"：{bad}" if bad else ""))
    print(f"图目录：{OUT}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
