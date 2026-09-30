#!/usr/bin/env python3
"""一次性诊断：点「连接」之后到底发生了什么（T-002 探针调试用）。

用法：python reports/T-002/_diag_connect.py
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

EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
user32 = ctypes.WinDLL("user32", use_last_error=True)


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def top_windows(pid):
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            out.append({"hwnd": hwnd, "text": buf.value,
                        "visible": bool(user32.IsWindowVisible(hwnd))})
        return True

    user32.EnumWindows(cb, 0)
    return out


def main() -> int:
    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    try:
        mw = None
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                mw = ui.main_window(proc.pid)
                break
            except Exception:
                time.sleep(0.5)
        if mw is None:
            say(error="no main window")
            return 2
        time.sleep(12.0)                    # 等启动预扫描跑完
        btns = [c.window_text() for c in mw.descendants(control_type="Button")]
        say(step="buttons before click", buttons=btns[:20])
        hit = None
        for c in mw.descendants(control_type="Button"):
            if c.window_text().strip() == "连接":
                hit = c
                break
        say(step="found 连接 button", found=hit is not None)
        if hit is not None:
            hit.click_input()
        for i in range(5):
            time.sleep(3.0)
            say(step=f"t+{(i + 1) * 3}s", tops=top_windows(proc.pid),
                windows=[c.window_text() for c in mw.descendants(control_type="Window")],
                alive=proc.poll() is None)
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
