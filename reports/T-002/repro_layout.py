#!/usr/bin/env python3
"""T-002 复现探针：欧氏距离页在缩小工具窗口时出现横向滚动条 / 遮挡。

判据（用户原话）：「在工具窗口中，欧式距离计算工具这里图2红色箭头指的这块区域
偶现滚动条和按钮遮挡」。

用法：python reports/T-002/repro_layout.py [tool_name]
输出：逐步 JSON 到 stdout；截图（只裁工具窗口）到 reports/T-002/。
退出码：0 = 跑完（结论在 JSON 的 verdict 里）；2 = 环境问题。
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

import ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

OUT = REPO_ROOT / "reports" / "T-002"
EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"

user32 = ctypes.WinDLL("user32", use_last_error=True)


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def top_windows(pid: int):
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

    user32.EnumWindows(cb, 0)
    return out


def find_hwnd(pid: int, title: str, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd, text in top_windows(pid):
            if text == title:
                return hwnd
        time.sleep(0.3)
    return None


def window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def resize(hwnd, w, h):
    l, t, _, _ = window_rect(hwnd)
    user32.MoveWindow(hwnd, l, t, w, h, True)
    time.sleep(0.9)


def shot(hwnd, name):
    l, t, r, b = window_rect(hwnd)
    if r - l < 8 or b - t < 8:
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    ImageGrab.grab(bbox=(l, t, r, b)).save(path)
    return str(path)


def scrollbars(win):
    """UIA 里能看到的所有滚动条：宽度 > 高度 = 横向。"""
    out = []
    try:
        for ctrl in win.descendants(control_type="ScrollBar"):
            try:
                r = ctrl.rectangle()
            except Exception:
                continue
            if r.width() <= 1 and r.height() <= 1:
                continue
            out.append({
                "dir": "h" if r.width() > r.height() else "v",
                "rect": [r.left, r.top, r.right, r.bottom],
            })
    except Exception:
        pass
    return out


def rect_of(ctrl):
    try:
        r = ctrl.rectangle()
        return [r.left, r.top, r.right, r.bottom]
    except Exception:
        return None


def selection_pattern_click(mw, name: str) -> bool:
    """用真鼠标点列表项——UIA 的 SelectionItemPattern 曾给过假阴性（T-003）。"""
    deadline = time.time() + 8.0
    while time.time() < deadline:
        for item in mw.descendants(control_type="ListItem"):
            if item.window_text().strip() == name:
                item.click_input()
                return True
        time.sleep(0.3)
    return False


def main() -> int:
    tool = sys.argv[1] if len(sys.argv) > 1 else "欧氏距离"
    if not EXE.exists():
        say(error=f"exe not found: {EXE}")
        return 2

    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    pid = proc.pid
    say(started=pid)
    try:
        mw = None
        deadline = time.time() + 40
        while time.time() < deadline:
            if proc.poll() is not None:
                say(error=f"process exited early, code={proc.returncode}")
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
        tool_hwnd = find_hwnd(pid, "工具")
        if tool_hwnd is None:
            say(error="tools dialog not found")
            return 2

        if not selection_pattern_click(mw, tool):
            say(error=f"list item {tool} not found")
            return 2
        time.sleep(1.0)

        # 工具面板挂在主窗口子树下（ui_check_012 的注释）。
        dlg = None
        for ctrl in mw.descendants(control_type="Window"):
            if ctrl.window_text() == "工具":
                dlg = ctrl
                break

        steps = []
        for i, (w, h) in enumerate([(820, 620), (1100, 700), (1500, 860),
                                     (660, 460), (640, 440), (820, 620)]):
            resize(tool_hwnd, w, h)
            bars = scrollbars(dlg) if dlg else []
            hbar = next((b for b in bars if b["dir"] == "h"), None)
            vbar = next((b for b in bars if b["dir"] == "v"), None)
            btns = {}
            if dlg:
                for c in dlg.descendants(control_type="Button"):
                    t = c.window_text()
                    if t in ("计算", "复制"):
                        btns.setdefault(t, rect_of(c))
            l, t, r, b = window_rect(tool_hwnd)
            overlap = None
            if hbar and btns:
                hb = hbar["rect"]
                for name, rect in btns.items():
                    if rect and rect[1] < hb[3] and rect[3] > hb[1]:
                        overlap = {"button": name, "hbar": hb, "button_rect": rect}
            steps.append({
                "requested": [w, h],
                "actual": [r - l, b - t],
                "h_scrollbar": hbar,
                "v_scrollbar": vbar,
                "buttons": btns,
                "button_hbar_overlap": overlap,
                "shot": shot(tool_hwnd, f"{i:02d}_{w}x{h}"),
            })

        say(tool=tool, steps=steps)
        bad = [s for s in steps if s["h_scrollbar"] or s["button_hbar_overlap"]]
        say(verdict="LAYOUT PROBLEM VISIBLE" if bad else "clean",
            bad_steps=len(bad))
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
