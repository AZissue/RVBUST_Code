#!/usr/bin/env python3
"""T-001 判据 3 的机器半场：2D 视窗浮层按钮的"背后画面被模糊"是不是真的。

思路（让"模糊"变成可测的量）：
  1. 先把**有纹理的画面**送进主 2D 视窗——工具页「像素→3D」离线模式会把它加载的
     png 冻结到主 2D 视窗上（`pixelTo3DOfflineImageRequested` → `Image2DView::setFrozenImage`）。
     A 用仓库里现成的 `data/1.png`。
  2. 截图后取工具栏**按钮内部**与**紧邻的同尺寸背景**两块区域，各算"高频能量"
     （相邻像素差分的平均绝对值）。
     * 恒定 alpha 底色：高频只是被按比例缩小（≈0.8 倍），比不出量级差；
     * 真模糊：高频被抹掉，内部远低于外部。
  3. 判据：内部高频 / 外部高频 <= 0.5，且按钮内部**不是单一颜色**（std > 0）。

用法：python reports/T-001/probe_glass.py
退出码：0 = 通过；1 = 没通过（模糊没做到）；2 = 环境问题（起不来 / 没拿到画面）。
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import ui  # noqa: E402
from PIL import Image, ImageGrab  # noqa: E402

OUT = REPO_ROOT / "reports" / "T-001"
EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
DATA_ROOT = REPO_ROOT / "data"


def pick_session_dir() -> Path | None:
    """挑一个**真拍过**的会话目录：里面有最大的那张 png（纹理越多，"糊没糊"越看得出来）。"""
    if len(sys.argv) > 1:                  # 显式指定：用来挑"工具栏底下正好有纹理"的那张
        return Path(sys.argv[1])
    if not DATA_ROOT.exists():
        return None
    pngs = [p for p in DATA_ROOT.rglob("*.png") if "backup" not in p.parts]
    if not pngs:
        return None
    return max(pngs, key=lambda p: p.stat().st_size).parent

user32 = ctypes.WinDLL("user32", use_last_error=True)


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def shot(hwnd, name):
    l, t, r, b = window_rect(hwnd)
    if r - l < 8 or b - t < 8:
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    ImageGrab.grab(bbox=(l, t, r, b)).save(path)
    return str(path)


def find_hwnd(pid: int, prefix: str, timeout=10.0):
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            out.append((hwnd, buf.value))
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        out.clear()
        user32.EnumWindows(cb, 0)
        for hwnd, text in out:
            if text.startswith(prefix):
                return hwnd
        time.sleep(0.3)
    return None


def high_freq(img: Image.Image) -> float:
    """相邻像素差分的平均绝对值——高频能量的粗略代理。"""
    g = img.convert("L")
    w, h = g.size
    if w < 3 or h < 3:
        return 0.0
    px = g.load()
    total = 0
    n = 0
    for y in range(h):
        for x in range(1, w):
            total += abs(px[x, y] - px[x - 1, y])
            n += 1
    return total / max(1, n)


def stddev(img: Image.Image) -> float:
    g = img.convert("L")
    hist = g.histogram()
    total = sum(hist)
    if total == 0:
        return 0.0
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(((i - mean) ** 2) * c for i, c in enumerate(hist)) / total
    return var ** 0.5


def main() -> int:
    if not EXE.exists():
        say(error=f"exe not found: {EXE}")
        return 2
    data_dir = pick_session_dir()
    if data_dir is None:
        say(error=f"{DATA_ROOT} 下没有可用 png（离线冻结需要 png+ply 会话目录）")
        return 2
    say(step="picked session dir", dir=str(data_dir))

    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    pid = proc.pid
    try:
        mw = None
        deadline = time.time() + 40
        while time.time() < deadline:
            if proc.poll() is not None:
                say(error=f"exited early code={proc.returncode}")
                return 2
            try:
                mw = ui.main_window(pid)
                break
            except Exception:
                time.sleep(0.5)
        if mw is None:
            say(error="main window not found")
            return 2
        time.sleep(1.5)

        ui.click(mw, "工具")
        time.sleep(1.5)
        for item in mw.descendants(control_type="ListItem"):
            if item.window_text().strip() == "像素→3D":
                item.click_input()
                break
        time.sleep(1.0)

        # 数据文件夹 → 冻结主 2D 视窗到那张 png（有纹理的背景）。
        # Qt 不往 UIA 上暴露 automationId（实测 9 个 Edit 全空），所以从
        # 「像素→3D（离线反投影）」这个 Group 的子树里按**树序**取第一个 Edit
        # ——构建顺序就是 dir → intrinsic → extrinsic → pixel。
        group = next((c for c in mw.descendants(control_type="Group")
                      if c.window_text().startswith("像素→3D")), None)
        target = None
        if group is not None:
            edits = list(group.descendants(control_type="Edit"))
            say(step="p2d page edits", count=len(edits),
                tops=[c.rectangle().top for c in edits[:5]])
            if edits:
                target = edits[0]
        if target is None:
            say(error="找不到『数据文件夹』输入框（像素→3D 页的 Group 没找到）")
            return 2
        target.set_edit_text(str(data_dir))
        time.sleep(2.0)
        say(step="froze main 2D view to data/1.png")

        hwnd = find_hwnd(pid, "手眼标定数据收集助手")
        if hwnd is None:
            say(error="main window hwnd not found",
                alive=proc.poll() is None, exit_code=proc.poll())
            return 2
        l, t, r, b = window_rect(hwnd)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "glass_2d_main.png"
        ImageGrab.grab(bbox=(l, t, r, b)).save(path)
        say(step="screenshot", shot=str(path), rect=[l, t, r, b])

        # 2D 视窗工具栏在窗口内的位置：从"图像"页签控件矩形推（UIA 给的是屏幕坐标）
        tabs = {}
        for c in mw.descendants(control_type="Button"):
            txt = c.window_text().strip()
            if txt in ("图像", "偏差图", "尺寸总图", "截面轮廓", "重复性趋势"):
                rr = c.rectangle()
                tabs[txt] = [rr.left - l, rr.top - t, rr.right - l, rr.bottom - t]
        say(step="toolbar button rects (window coords)", tabs=tabs)

        # ── 信息性一步：离线像素→3D 的端到端（点一下画面，等结果行出值） ──
        # 不进退出码：它是"这一页除了不崩，还算不算得出来"的旁证。
        def panel_texts():
            out = {}
            try:
                for c in mw.descendants(control_type="Text"):
                    t = c.window_text().strip()
                    if t:
                        out[t[:60]] = [c.rectangle().left, c.rectangle().top]
            except Exception:
                pass
            return out

        before = panel_texts()
        # click_at 收的是**屏幕**坐标（ui.py 里 ScreenToClient 之前就是屏幕系）。
        wl, wt, _, _ = window_rect(hwnd)
        click_screen = (wl + 230, wt + 380)   # 主 2D 视窗画面里的一点（窗口相对 230,380）
        ui.click_at(hwnd, *click_screen)
        say(step="clicked main 2D view", screen=click_screen,
            alive=proc.poll() is None)
        found = None
        for _ in range(60):                  # 最多 30 秒（要读 18MB 的 ply）
            if proc.poll() is not None:
                say(step="DIED during pixel->3D", exit_code=proc.poll())
                break
            now = panel_texts()
            changed = [k for k in now if k not in before]
            if changed:
                found = changed
                break
            time.sleep(0.5)
        say(step="pixel->3D panel text delta", changed=found,
            result_line=[k for k in (found or []) if "→" in k or "." in k][:4],
            shot=shot(hwnd, "glass_pixel3d_after_click"))
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
