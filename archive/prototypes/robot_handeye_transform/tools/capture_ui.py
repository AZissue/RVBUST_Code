# -*- coding: utf-8 -*-
"""
原型 UI 复刻 —— 运行实测截图 + S1~S7/S9 脚本内断言（M2b）。

文档：`docs/原型UI一次性复刻方案与截图验收标准_20260923.md` §4
判据修订：`docs/UI截图验收标准可行性审核_20260923.md`（@verify 2026-09-23，S1 按类给值 /
S3 集合补 Microsoft YaHei UI / S4 采状态标签像素 / S5 删③ / S6·S7 补口径）

跑法（真实桌面会话，主组；**不设 QT_QPA_PLATFORM**）：
  cd D:\\RVC_SRC\\Python\\MultiCameraCalibration
  unset PYTHONPATH
  "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/robot_handeye_transform/tools/capture_ui.py
副组（色值回归，字体/中文类判据豁免）：
  ... capture_ui.py --offscreen          # 图存 docs/ui_review/offscreen/

硬性口径（§4.1）：不调 app.exec()；grab() 原始分辨率不入缩放；状态 2/3/4 走 core 公开路径
（handeye_result / validation 真实接口），禁止只改标签文本伪造状态。
"""

from __future__ import annotations

import os
import re
import sys

_OFFSCREEN = "--offscreen" in sys.argv
if _OFFSCREEN:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
else:
    # §4.1 主组硬性口径：真实桌面会话（不设 QT_QPA_PLATFORM）。外部环境变量残留
    # （如本终端此前 export 过 offscreen）会静默把主组跑成 offscreen → 中文全 tofu。
    os.environ.pop("QT_QPA_PLATFORM", None)

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_PROTO = os.path.dirname(_TOOLS)
APP_DIR = os.path.join(_PROTO, "app")
sys.path.insert(0, APP_DIR)
os.chdir(_PROTO)                      # R12：路径引导依赖 cwd（或 MCC_REPO_ROOT）

import numpy as np                                              # noqa: E402
from PySide6.QtCore import QRect, Qt                            # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter       # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox,         # noqa: E402
                               QGroupBox, QLabel, QLineEdit,
                               QPushButton)

import host as host_mod                                         # noqa: E402
import window as ws_mod                                         # noqa: E402
from ui_v2.launcher_dialog import LauncherDialog                # noqa: E402
from ui_v2.main_window import MainWindowShell                   # noqa: E402
from ui_v2.theme import (ACCENT, BG_CARD, BG_INPUT,             # noqa: E402
                         BG_PANEL, BG_WINDOW, GLOBAL_QSS,
                         STATUS_ERR, STATUS_OK, STATUS_WARN,
                         TEXT_MUTED)
from ui_v2.widgets.device_table import DeviceInfo               # noqa: E402

# theme.py:84 `QPushButton#primary:disabled` 的字面值（QSS 内部色，非 token）
PRIMARY_DISABLED = "#5A2A28"
FONT_ALLOWED = ("Segoe UI", "Microsoft YaHei", "Microsoft YaHei UI")

REPO = ws_mod.REPO_ROOT or os.path.abspath(os.path.join(_PROTO, "..", ".."))
OUT = os.path.join(REPO, "docs", "ui_review", "offscreen" if _OFFSCREEN else "")
os.makedirs(OUT, exist_ok=True)

MATRIX_TEXT = "1,0,0,20, 0,1,0,-10, 0,0,1,120, 0,0,0,1"
POSES = [("400,100,420", "0,0,0"), ("420,90,430", "0,60,0"), ("380,110,410", "60,0,0")]
P_TRUE_BASE = np.array([420.0, 90.0, 350.0])   # 真值针尖点（基座系，mm）

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
    """Chebyshev 距离（通道最大偏差）。"""
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def _tok(h):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def _edge(w_or_img, token, tol=3):
    """控件边缘点采样（避文字 / drop-down 污染），返回 (ok, 描述)。"""
    if hasattr(w_or_img, "grab"):
        if not w_or_img.isVisible():
            return False, f"控件不可见（隐藏控件 grab 回 #000000）: {w_or_img}"
        img, w, h = w_or_img.grab().toImage(), w_or_img.width(), w_or_img.height()
    else:
        img, w, h = w_or_img
    got = _rgb(img, w - 6, h // 2)
    d = _dist(got, _tok(token))
    return d <= tol, f"({w}x{h}) 实测 {_hex(got)} vs {token} Δ={d}"


def _combo_sample(combo, token, tol=3):
    """下拉框填充色：内部区最近像素比对（单点会撞上「请选择」文字 / drop-down 箭头，
    @verify 实测 (w//4,h//2) 采到 #C7C98B 文字抗锯齿像素 → 改内部区最近点）。"""
    img, w, h = combo.grab().toImage(), combo.width(), combo.height()
    tr, tg, tb = _tok(token)
    best = 999
    for y in range(4, max(5, h - 4), 2):
        for x in range(4, max(5, w - 26), 2):      # 右侧 drop-down 区不采
            c = img.pixelColor(x, y)
            best = min(best, max(abs(c.red() - tr), abs(c.green() - tg), abs(c.blue() - tb)))
    return best <= tol, f"({w}x{h}) 内部区最近像素 Δ={best} vs {token}"


def _nearest(img, token):
    """全图最接近 token 的像素（S4：标签文字色，抗锯齿不影响最近点）。"""
    tr, tg, tb = _tok(token)
    best, px = 999, None
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            d = max(abs(c.red() - tr), abs(c.green() - tg), abs(c.blue() - tb))
            if d < best:
                best, px = d, (c.red(), c.green(), c.blue())
    return best, px


def _light_ratio(img):
    """浅底像素占比（min(R,G,B) > 200），S2。"""
    n = light = 0
    for y in range(2, img.height() - 2, 3):
        for x in range(2, img.width() - 2, 3):
            r, g, b = _rgb(img, x, y)
            light += 1 if min(r, g, b) > 200 else 0
            n += 1
    return light / max(n, 1)


# ------------------------------------------------------------------ 状态构造
def grab(widget, name):
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()
    img = widget.grab().toImage()
    path = os.path.join(OUT, name)
    img.save(path)
    print(f"      -> {path}  ({img.width()}x{img.height()})")
    return img


def load_matrix(ws):
    """走 core 公开路径加载矩阵（UNVERIFIED）。"""
    ws.on_manual_handeye(MATRIX_TEXT, "mm", True)
    assert ws.handeye is not None and not ws.handeye.validated, "矩阵加载失败"


def record_tips(ws, offsets):
    """按姿态录戳点：针尖相机系坐标由 compute_cam2base 反算（真值一致性可控）。"""
    for (xyz, rpy), off in zip(POSES, offsets):
        ws.on_manual_pose(xyz, rpy, "ZYX", "mm", "absolute")
        ok, msg, T = ws.pose_src.get_pose()
        assert ok, msg
        T_cam2base = ws_mod.transform_chain.compute_cam2base(
            True, ws.handeye.T_handeye_mm, T)
        p = np.append(P_TRUE_BASE + np.array([off, 0.0, 0.0]), 1.0)
        tip = (np.linalg.inv(T_cam2base) @ p)[:3]
        ws.on_tip_record(",".join(f"{v:.6f}" for v in tip))


def state_label(panel):
    for lb in panel.findChildren(QLabel, "stateLabel"):
        if lb.text().startswith("状态："):
            return lb
    return None


# ------------------------------------------------------------------ S5 代码扫描
def s5_scan():
    app_dir = APP_DIR
    hex_hits, font_hits = [], []
    for fn in sorted(os.listdir(app_dir)):
        if not fn.endswith(".py"):
            continue
        for i, line in enumerate(open(os.path.join(app_dir, fn), encoding="utf-8"), 1):
            code = re.split(r"\s#", line)[0]        # 去行尾注释（原判据"注释除外"）
            if code.lstrip().startswith("#"):
                continue
            if re.search(r"#[0-9a-fA-F]{6}|rgba\(", code):
                hex_hits.append(f"{fn}:{i}")
            if re.search(r"font-family|setFont\(", code):
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
        f = QFont("Segoe UI", 9)
        pt.setFont(f)
        pt.drawText(QRect(x, y, cell[0], label_h), Qt.AlignVCenter | Qt.AlignLeft, title)
        scaled = img.scaled(cell[0], cell[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pt.drawImage(x, y + label_h, scaled)
    pt.end()
    canvas.save(out_path)
    print(f"      -> {out_path}  ({canvas.width()}x{canvas.height()})")


# ------------------------------------------------------------------ 主流程
def main() -> int:
    global app
    app = QApplication.instance() or QApplication(["capture_ui"])
    app.setStyleSheet(GLOBAL_QSS)         # M2a-1：设计语言唯一来源
    print(f"platform={app.platformName()}  offscreen={_OFFSCREEN}  out={OUT}")
    print(f"app.font()={app.font().family()!r}")

    host = host_mod.RobotHandEyeHost()
    host.resize(1400, 850)
    host.show()
    for _ in range(4):
        app.processEvents()
    host.set_log_visible(True)            # FloatingLogPanel 构造后即 hide()
    ws = host.workspace
    panel = ws.panel
    real_w, real_h = host.width(), host.height()
    print(f"窗口 nominal=1400x850 → 实际 {real_w}x{real_h}"
          f"（host minimumSizeHint={host.minimumSizeHint().width()}"
          f"x{host.minimumSizeHint().height()}）")

    # ===== 状态 1：IDLE =====
    img_idle = grab(host, "proto_host_1400x850_idle.png")

    # -- S1 色值与 token 一致（按类给值，@verify 修订口径）--
    parts = []
    ok_all = True
    for tag, w, tok in (("QGroupBox", panel.findChildren(QGroupBox)[0], BG_PANEL),
                        ("QLineEdit", panel.edit_he_path, BG_INPUT),
                        ("QPushButton(默认)", panel.btn_apply_pose, BG_CARD),
                        ("QPushButton#primary", panel.btn_capture, ACCENT),
                        ("QPushButton#secondary", panel.btn_import_he_file, BG_PANEL),
                        ("FloatingLogPanel", host._log_panel, BG_PANEL)):
        ok, d = _edge(w, tok)
        ok_all &= ok
        parts.append(f"{tag}{d}")
    ok, d = _combo_sample(panel.combo_he_unit, BG_INPUT)
    ok_all &= ok
    parts.append(f"QComboBox{d}")
    # primary:disabled（IDLE 态戳点门禁按钮应为置灰）
    if not panel.btn_tip_check.isEnabled():
        ok, d = _edge(panel.btn_tip_check, PRIMARY_DISABLED)
        ok_all &= ok
        parts.append(f"QPushButton#primary:disabled{d}")
    # 中央窗口底（左右边中部）与顶栏/状态栏
    edge_mid = _rgb(img_idle, 5, real_h // 2)
    ok_edge = _dist(edge_mid, _tok(BG_WINDOW)) <= 3
    top = _rgb(img_idle, real_w // 2, 5)
    bot = _rgb(img_idle, real_w // 2, real_h - 6)
    ok_bar = (_dist(top, _tok(BG_PANEL)) <= 3) and (_dist(bot, _tok(BG_PANEL)) <= 3)
    ok_all &= (ok_edge and ok_bar)
    parts.append(f"中央底(5,h/2){_hex(edge_mid)} vs {BG_WINDOW}Δ={_dist(edge_mid, _tok(BG_WINDOW))}"
                 f"；顶栏{_hex(top)}/状态栏{_hex(bot)} vs {BG_PANEL}")
    check("S1 色值=token（元素级）", ok_all, " | ".join(parts))

    # -- S2 无浅色残留 --
    lr = _light_ratio(img_idle)
    check("S2 浅底像素占比 ≤1%", lr <= 0.01, f"实测 {lr * 100:.2f}%（改前基线 39.2%）")

    # -- S3 字体 --
    fam = panel.font().family()
    if _OFFSCREEN:
        check("S3 字体（offscreen 豁免）", True, f"控件字体={fam!r}（字体族判据仅真机）")
    else:
        check("S3 字体一致", fam in FONT_ALLOWED,
              f"QSS 生效后控件字体={fam!r} ∈ {FONT_ALLOWED}；app.font()={app.font().family()!r}")

    # -- S4 状态色 --
    sl = state_label(panel)
    d, px = _nearest(sl.grab().toImage(), TEXT_MUTED)
    check("S4 IDLE→TEXT_MUTED", d <= 8, f"{sl.text()!r} 最近像素 {_hex(px)} vs {TEXT_MUTED} Δ={d}")

    # ===== 状态 2：UNVERIFIED =====
    load_matrix(ws)
    img_unv = grab(host, "proto_host_1400x850_unverified.png")
    d, px = _nearest(sl.grab().toImage(), STATUS_WARN)
    check("S4 UNVERIFIED→STATUS_WARN", d <= 8, f"最近像素 {_hex(px)} vs {STATUS_WARN} Δ={d}")

    # ===== 状态 3：VERIFIED（3 个离面姿态全一致）=====
    load_matrix(ws)                       # 重置样本
    record_tips(ws, (0.0, 0.0, 0.0))
    ws.on_tip_check()
    ok_v = bool(ws.handeye.validated)
    img_ver = grab(host, "proto_host_1400x850_verified.png")
    d, px = _nearest(sl.grab().toImage(), STATUS_OK)
    check("S4 VERIFIED→STATUS_OK", ok_v and d <= 8,
          f"门禁 verdict={ws.tip_report['verdict']} err_mean={ws.tip_report['err_mean_mm']:.3f}mm；"
          f"最近像素 {_hex(px)} vs {STATUS_OK} Δ={d}")

    # 左面板 4 组特写（VERIFIED 态内容最全：门禁绿条 + 元数据行）
    zoom = panel.grab().toImage()
    zoom.save(os.path.join(OUT, "proto_panel_zoom.png"))
    print(f"      -> {os.path.join(OUT, 'proto_panel_zoom.png')}  ({zoom.width()}x{zoom.height()})")
    # -- S6 无裁剪 --
    groups = panel.findChildren(QGroupBox)
    vis = [g for g in groups if g.isVisible()]
    sbar = ws._left_panel.verticalScrollBar().maximum()
    check("S6 无裁剪（4 组可见 + 滚动区可达）", len(vis) == 4 and sbar > 0,
          f"QGroupBox {len(vis)}/4 可见；scrollBar.max={sbar}；面板内容高={panel.height()}px")

    # ===== 状态 4：FAILED（第 3 个姿态针尖偏 5 mm → 落点分散超门禁）=====
    load_matrix(ws)
    record_tips(ws, (0.0, 0.0, 5.0))
    ws.on_tip_check()
    img_fail = grab(host, "proto_host_1400x850_failed.png")
    d, px = _nearest(sl.grab().toImage(), STATUS_ERR)
    ok_f = (ws.tip_report["verdict"] == "FAIL") and d <= 8
    check("S4 FAILED→STATUS_ERR", ok_f,
          f"verdict={ws.tip_report['verdict']} err_mean={ws.tip_report['err_mean_mm']:.3f}mm；"
          f"最近像素 {_hex(px)} vs {STATUS_ERR} Δ={d}")

    # ===== 缩窗档（S7）：900×600 不可达（host minimumSizeHint 见上），取最小宽 × 600 =====
    wn = host.minimumSizeHint().width()
    host.resize(wn, 600)
    for _ in range(3):
        app.processEvents()
    img_small = grab(host, "proto_host_900x600_resized.png")
    inside = host.rect().contains(host._log_panel.geometry())
    check("S7 浮动日志面板（叠加层 + 不跑出窗外）",
          (not host._log_panel.isWindow()) and host._log_panel.isVisible() and inside,
          f"isWindow={host._log_panel.isWindow()} visible={host._log_panel.isVisible()} "
          f"inside={inside}@ {host.width()}x{host.height()}"
          f"（900x600 不可达：minimumSizeHint 宽 {wn}）")

    # ===== 主程序参照图（同 QSS 同尺寸）=====
    win = MainWindowShell()
    devs = [DeviceInfo(model="M2600R", serial="SN1", ip="192.168.1.10", online=True),
            DeviceInfo(model="M2600R", serial="SN2", ip="192.168.1.11", online=True)]
    win.set_mode(LauncherDialog.MODE_MULTI_CAM, devs)
    win.resize(1400, 850)
    win.show()
    img_main = grab(win, "main_ref_1400x850.png")
    tb = win._toolbar.height() if win._toolbar else 42
    sb = win._statusbar.height() if win._statusbar else 28
    main_close = img_main.copy(QRect(0, tb, 330, max(80, img_main.height() - tb - sb)))

    # -- S9 防"只改色号"：五个外壳元素必须同时可见 --
    check("S9 外壳元素齐备", host._toolbar.isVisible() and host._statusbar.isVisible()
          and host._log_panel.isVisible() and len(vis) == 4 and ws._left_panel.isVisible(),
          "顶栏 + 状态栏 + 浮动日志 + 左面板 4 组 + 3D 区")

    # ===== 并排图 =====
    compose([("主程序 MainWindowShell · 多相机工作区 1400x850", img_main),
             ("原型宿主 · 手眼变换 %dx%d" % (real_w, real_h), img_idle),
             ("主程序左面板特写（裁剪）", main_close),
             ("原型左面板特写 · 4 组（VERIFIED 态）", zoom)],
            os.path.join(OUT, "cmp_side_by_side.png"))

    # ===== S5 零硬编码 =====
    hex_hits, font_hits = s5_scan()
    check("S5 零硬编码（hex/rgba + setFont/font-family）",
          not hex_hits and not font_hits,
          f"hex/rgba 命中 {len(hex_hits)}：{hex_hits[:5]}；字体命中 {len(font_hits)}：{font_hits[:5]}")

    bad = [t for t, ok, _ in _results if not ok]
    print("\n==== capture_ui 小结 ====")
    print(f"断言 {len(_results)} 项，PASS {len(_results) - len(bad)}，FAIL {len(bad)}"
          + (f"：{bad}" if bad else ""))
    print(f"图目录：{OUT}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
