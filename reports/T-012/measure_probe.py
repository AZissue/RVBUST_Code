#!/usr/bin/env python3
"""T-012 基线探针：连真实相机 → 拍照 → 在测量页上框 ROI → 点「测量」→ 把结果读出来。

为什么先做这个：人的原话是"测量值与实际的误差很大"，但没有数字。
**先把误差量出来**（基线），才谈得上"改到 0.2%"。

用法：
    python reports/T-012/measure_probe.py --shot                 # 只连相机+拍照+截图
    python reports/T-012/measure_probe.py --tool 孔径(孔洞边界法) --roi x1,y1,x2,y2
    python reports/T-012/measure_probe.py --tool 圆环拟合 --roi x1,y1,x2,y2

坐标是 **2D 视窗控件内的像素**（不是屏幕坐标）：探针会把 2D 视窗控件的屏幕矩形打出来，
ROI 坐标按 `图像坐标` 与控件内坐标 1:1 换算（视窗按"适应"显示，探针会把缩放比打出来）。

结果从两处读：① 操作日志里的 `[测量-结果]` 行（机器可读）；② 截一张整屏图留档。
退出码：0 = 走到了；1 = 流程/环境问题；2 = 相机不可用。
"""

from __future__ import annotations

import ctypes
import json
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

OUT = REPO_ROOT / "reports" / "T-012"
EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
SN = "I1GM112B652"

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
MK_LBUTTON = 0x0001


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def hwnd_by_title(pid: int, title: str, prefix=True, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            p = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value != pid or not _user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(512)
            _user32.GetWindowTextW(hwnd, buf, 512)
            hit = buf.value.startswith(title) if prefix else buf.value == title
            if hit:
                found.append(hwnd)
                return False
            return True

        _user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def click_text(root, text, timeout=8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for c in root.descendants(control_type="Button"):
            try:
                if c.window_text().strip() == text:
                    ui.activate(c)
                    return True
            except Exception:              # noqa: BLE001
                continue
        time.sleep(0.3)
    return False


def post_drag(hwnd, x1, y1, x2, y2, steps=10, hold_ms=60):
    """在目标窗口里按住左键拖一条直线（ROI 就这么画）。

    参数是**屏幕坐标**（与 ui.post_click 一致：内部换算成该 HWND 的客户区坐标）。
    """
    def to_client(x, y):
        pt = wintypes.POINT(int(x), int(y))
        _user32.ScreenToClient(hwnd, ctypes.byref(pt))
        return pt.x, pt.y

    def lparam(x, y):
        return (int(y) << 16) | (int(x) & 0xFFFF)

    cx1, cy1 = to_client(x1, y1)
    _user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam(cx1, cy1))
    _user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(cx1, cy1))
    for i in range(1, steps + 1):
        x = x1 + (x2 - x1) * i / steps
        y = y1 + (y2 - y1) * i / steps
        cx, cy = to_client(x, y)
        _user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam(cx, cy))
        time.sleep(hold_ms / 1000.0 / steps)
    cx2, cy2 = to_client(x2, y2)
    _user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(cx2, cy2))


def move_panel_right(panel_hwnd, win_rect):
    """把工具面板挪到屏幕右侧，别挡住 2D 视窗。

    用 SetWindowPos 而不是拖标题栏：标题栏是非客户区，PostMessage 的鼠标消息
    到不了（第一次就是这么失败的）。
    """
    SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
    w = win_rect.right - win_rect.left
    x = max(8, 1912 - w)
    ok = _user32.SetWindowPos(panel_hwnd, 0, x, 40, 0, 0,
                              SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.8)
    return bool(ok)


def controls_with_rects(root, min_w=200, min_h=150):
    out = []
    for c in root.descendants():
        try:
            r = c.rectangle()
            t = c.element_info.control_type
            n = c.window_text()
        except Exception:                  # noqa: BLE001
            continue
        if r.width() >= min_w and r.height() >= min_h:
            out.append({"type": t, "text": n[:24],
                        "rect": [r.left, r.top, r.right, r.bottom],
                        "size": [r.width(), r.height()]})
    return sorted(out, key=lambda d: -d["size"][0] * d["size"][1])[:8]


def image_view_rect(root):
    """2D 视窗控件：主窗口里最大的一块 Pane/Image（经验：左侧那块大区域）。"""
    best = None
    images = []
    for c in root.descendants():
        try:
            r = c.rectangle()
            t = c.element_info.control_type
        except Exception:                  # noqa: BLE001
            continue
        if t == "Image" and r.width() > 200 and r.height() > 150:
            images.append((r.width() * r.height(), r))
        if t == "Image":
            continue                        # 图像控件优先，下面只兜底 Pane/Custom
        if t not in ("Pane", "Image", "Custom"):
            continue
        area = r.width() * r.height()
        if best is None or area > best[0]:
            best = (area, r)
    if images:
        return max(images, key=lambda p: p[0])[1]
    return best[1] if best else None


def log_tail_values() -> list[str]:
    logs = sorted((EXE.parent / "logs").glob("app_*.log"))
    hits: list[str] = []
    for path in logs:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits += re.findall(r"\[测量-结果\].*", text)
    return hits


def main() -> int:
    args = sys.argv[1:]
    shot_only = "--shot" in args
    tool = "孔径(孔洞边界法)"
    roi = None
    for i, a in enumerate(args):
        if a == "--tool" and i + 1 < len(args):
            tool = args[i + 1]
        if a == "--roi" and i + 1 < len(args):
            roi = [int(float(v)) for v in args[i + 1].split(",")]

    OUT.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    try:
        mw = None
        deadline = time.time() + 45
        while time.time() < deadline and mw is None:
            try:
                mw = ui.main_window(proc.pid)
            except Exception:              # noqa: BLE001
                time.sleep(0.5)
        if mw is None:
            say(error="main window not found")
            return 1
        time.sleep(13.0)                   # 启动预扫描

        # ── 连相机 ──
        dlg = None
        for attempt in range(4):
            if not click_text(mw, "连接"):
                say(error="找不到『连接』按钮")
                return 1
            deadline = time.time() + 20
            while time.time() < deadline:
                dlg = None
                for c in mw.descendants(control_type="Window"):
                    try:
                        if c.window_text() == "选择相机设备":
                            dlg = c
                            break
                    except Exception:      # noqa: BLE001
                        continue
                if dlg is not None:
                    break
                time.sleep(0.5)
            if dlg is not None:
                break
        if dlg is None:
            say(error="设备选择对话框没出现", attempt=attempt + 1)
            return 2
        picked = None
        for c in dlg.descendants():
            try:
                if SN in c.window_text():
                    picked = c
                    break
            except Exception:              # noqa: BLE001
                continue
        if picked is None:
            say(error=f"设备列表里没有 {SN}")
            return 2
        dlg_hwnd = hwnd_by_title(proc.pid, "选择相机设备", prefix=False)
        if dlg_hwnd:
            ui.post_click(picked, dlg_hwnd)
        time.sleep(0.5)
        for label in ("确定", "连接", "OK"):
            if click_text(dlg, label, timeout=1.5):
                break
        time.sleep(7.0)
        if proc.poll() is not None:
            say(error="连相机时进程退出", exit_code=proc.poll())
            return 1
        say(step="connected")

        # ── 开工具面板、选测量方法 ──
        main_hwnd = hwnd_by_title(proc.pid, "手眼标定数据收集助手")
        ui.post_click(ui.find_button(mw, "工具"), main_hwnd)
        panel_hwnd = hwnd_by_title(proc.pid, "工具")
        if panel_hwnd is None:
            say(error="工具面板没打开")
            return 1
        item = ui.find_button(mw, tool, timeout=6.0)
        if item is None:
            say(error=f"工具列表里没有 {tool}")
            return 1
        ui.post_click(item, panel_hwnd)
        time.sleep(1.5)
        say(step="tool selected", tool=tool)

        # ── 拍照（主窗口的「拍照」按钮）──
        if not click_text(mw, "拍照"):
            say(error="找不到『拍照』按钮")
            return 1
        time.sleep(9.0)
        if proc.poll() is not None:
            say(error="拍照后进程退出", exit_code=proc.poll())
            return 1
        say(step="captured")

        # 把工具面板挪到右边，别挡住 2D 视窗（要量外圆时必须看得见整圈）。
        panel_win = None
        for c in mw.descendants(control_type="Window"):
            try:
                if c.window_text() == "工具":
                    panel_win = c
                    break
            except Exception:              # noqa: BLE001
                continue
        moved = False
        if panel_win is not None:
            moved = move_panel_right(panel_hwnd, panel_win.rectangle())
        say(step="panel moved", moved=moved)

        rect = image_view_rect(mw)
        info = {"step": "layout",
                "image_view": None if rect is None else
                [rect.left, rect.top, rect.right, rect.bottom],
                "big_controls": controls_with_rects(mw)}
        say(**info)
        ImageGrab.grab().save(OUT / "live_shot.png")
        say(shot=str(OUT / "live_shot.png"))

        if shot_only or roi is None:
            say(result="SHOT ONLY")
            return 0

        # ── 拖 ROI + 测量 ──
        if rect is None:
            say(error="找不到 2D 视窗矩形")
            return 1
        before = log_tail_values()
        post_drag(main_hwnd, rect.left + roi[0], rect.top + roi[1],
                  rect.left + roi[2], rect.top + roi[3])
        time.sleep(1.2)
        if not click_text(mw, "测量", timeout=5.0):
            say(error="找不到『测量』按钮")
            return 1
        time.sleep(2.5)
        after = log_tail_values()
        fresh = after[len(before):] if len(after) >= len(before) else after
        say(step="measured", tool=tool, roi=roi, results=fresh[-3:])
        say(result="DONE")
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:                  # noqa: BLE001
            try:
                proc.kill()
            except Exception:              # noqa: BLE001
                pass


if __name__ == "__main__":
    sys.exit(main())
