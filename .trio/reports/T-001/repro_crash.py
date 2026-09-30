#!/usr/bin/env python3
"""T-003 复现探针：在真机上选中工具列表里的「像素→3D」，看进程是否还活着。

判据（用户原话）：「图2左边红色箭头指的像素->坐标在选中的时候会导致整个程序闪退」。

用法：python reports/T-003/repro_crash.py
输出：逐步 JSON 到 stdout；截图到 reports/T-003/。
退出码：0 = 进程存活（没复现）；1 = 进程退出/崩溃（复现了）；2 = 环境问题。

为什么不写进单测：项目规则「UI 不做自动化测试」——UI 验证走真机探针 + 人眼看图。
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

OUT = REPO_ROOT / "reports" / "T-003"
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
            out.append(buf.value)
        return True

    user32.EnumWindows(cb, 0)
    return out


def shot(name: str):
    try:
        img = ImageGrab.grab()
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{name}.png"
        img.save(path)
        return str(path)
    except Exception as exc:  # noqa: BLE001
        return f"(screenshot failed: {exc})"


def select_tool(mw, name: str) -> bool:
    """在工具面板左侧列表里选中一项。列表有 objectName=tool_list。"""
    deadline = time.time() + 8.0
    while time.time() < deadline:
        for item in mw.descendants(control_type="ListItem"):
            if item.window_text().strip() == name:
                item.click_input()
                return True
        time.sleep(0.3)
    return False


def main() -> int:
    if not EXE.exists():
        say(error=f"exe not found: {EXE}")
        return 2

    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    pid = proc.pid
    say(started=pid, exe=str(EXE))

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
        say(error="main window not found", top=top_windows(pid))
        return 2
    time.sleep(1.5)
    say(step="main window up", shot=shot("00_main"))

    ui.click(mw, "工具")
    time.sleep(1.5)
    say(step="tools panel opened", top=top_windows(pid), shot=shot("01_tools"))

    # 逐个选中，看**哪一个**选中动作把进程打死——用来把根因从"像素→3D"
    # 这个标签上摘下来，落到具体的页面构造/切换路径上。
    for i, name in enumerate(["欧氏距离", "手眼标定", "坐标转换", "机器人通信",
                              "像素→3D", "平面度"], start=2):
        if not select_tool(mw, name):
            say(error=f"tool list item {name} not found")
            return 2
        time.sleep(2.0)
        alive = proc.poll() is None
        say(step=f"selected {name}", alive=alive, exit_code=proc.poll(),
            shot=shot(f"{i:02d}_after_{name.replace('→', '-')}"))
        if not alive:
            break

    alive = proc.poll() is None
    say(result="REPRODUCED (crash)" if not alive else "NOT REPRODUCED (alive)",
        exit_code=proc.poll())

    if alive:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0 if alive else 1


if __name__ == "__main__":
    sys.exit(main())
