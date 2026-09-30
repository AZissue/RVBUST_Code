#!/usr/bin/env python3
"""T-007 判据 3（不变量，真机/真进程）：机器人这条链在重构之后仍然通。

T-007 只改"四种协议怎么分派"，**不改**任何适配器。没有真机器人在台上，
能真正跑通的路径是「模拟连接成功 → 拍照位姿」，它恰好把整条链走一遍：

    工具面板「模拟连接成功」→ MainWindow::onRobotSimulateConnect
      → 主界面「拍照位姿」按钮出现 → MainWindow::onRobotRead
      → readRobotPose()（重构后的分派）→ 模拟位姿
      → 填卡片 + 写操作日志「机器人位姿读取成功: …」

判据（三条同时成立才算 PASS）：
  1. 点两次「拍照位姿」，用户日志 `logs/app_<date>.log` 里出现 **≥2 条**
     「机器人位姿读取成功」；
  2. 两次的值**不一样**（模拟位姿每次 +10 —— 证明是真的走了一遍，不是缓存字符串）；
  3. 全程进程存活（没有崩、没有卡死到超时）。

用法：python reports/T-007/robot_simulate_probe.py
（UIA 助手复用 `.codex-loop/tools/ui.py`，用 posted mouse messages，不抢物理鼠标。）
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

EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
READ_OK = re.compile(r"机器人位姿读取成功[:：]\s*(\S+)")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def hwnd_of(pid: int, title_prefix: str):
    """按标题前缀找该进程的顶层窗口句柄。

    必须有这个：工具面板是一个**独立顶层窗口**（Qt QDialog），把「机器人通信」
    这些控件的鼠标消息投到主窗口句柄上是打不中的（这是第一版探针失败的原因）。
    """
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not _user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        _user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value.startswith(title_prefix):
            found.append(hwnd)
            return False
        return True

    _user32.EnumWindows(cb, 0)
    return found[0] if found else None


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def wait_text(root, text, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ui.find_button(root, text, timeout=0.3) is not None:
            return True
        time.sleep(0.2)
    return False


def read_log_values() -> list[str]:
    logs = sorted((EXE.parent / "logs").glob("app_*.log"))
    values: list[str] = []
    for path in logs:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        values += READ_OK.findall(text)
    return values


def main() -> int:
    if not EXE.exists():
        emit({"result": "FAIL", "why": f"missing {EXE}"})
        return 1
    before = read_log_values()

    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    try:
        main_window = None
        deadline = time.time() + 30
        while time.time() < deadline and main_window is None:
            try:
                main_window = ui.main_window(proc.pid)
            except Exception:                     # noqa: BLE001
                time.sleep(0.5)
        if main_window is None:
            emit({"result": "FAIL", "why": "main window never appeared"})
            return 1
        hwnd = hwnd_of(proc.pid, "手眼标定数据收集助手")
        if hwnd is None:
            emit({"result": "FAIL", "why": "main window handle not found"})
            return 1
        emit({"check": "main window up", "ok": True})

        # 1) 工具面板 → 机器人通信页（面板自己的窗口句柄要单独取）
        ui.post_click(ui.find_button(main_window, "工具"), hwnd)
        panel_hwnd = None
        deadline = time.time() + 10
        while time.time() < deadline and panel_hwnd is None:
            panel_hwnd = hwnd_of(proc.pid, "工具")
            time.sleep(0.2)
        if panel_hwnd is None:
            emit({"result": "FAIL", "why": "工具面板没有打开"})
            return 1
        item = ui.find_button(main_window, "机器人通信", timeout=5.0)
        if item is None:
            emit({"result": "FAIL", "why": "找不到左侧「机器人通信」条目"})
            return 1
        ui.post_click(item, panel_hwnd)
        if not wait_text(main_window, "模拟连接成功"):
            emit({"result": "FAIL", "why": "机器人通信页没有出现「模拟连接成功」"})
            return 1
        emit({"check": "robot comm page open", "ok": True})

        # 2) 模拟连接 → 主界面出现「拍照位姿」
        ui.post_click(ui.find_button(main_window, "模拟连接成功"), panel_hwnd)
        if not wait_text(main_window, "拍照位姿", timeout=8.0):
            emit({"result": "FAIL",
                  "why": "模拟连接后主界面没有出现「拍照位姿」按钮"})
            return 1
        emit({"check": "simulated connect surfaced 拍照位姿", "ok": True})

        # 3) 连点两次读位姿
        for i in range(2):
            btn = ui.find_button(main_window, "拍照位姿", timeout=5.0)
            if btn is None:
                emit({"result": "FAIL", "why": "找不到「拍照位姿」按钮"})
                return 1
            ui.post_click(btn, hwnd)
            time.sleep(1.2)
            emit({"check": f"read #{i + 1} posted", "ok": True})

        alive = proc.poll() is None
        emit({"check": "process still alive", "ok": alive})
        after = read_log_values()
        fresh = after[len(before):]
        emit({"check": "log has >= 2 「机器人位姿读取成功」",
              "ok": len(fresh) >= 2, "count": len(fresh), "values": fresh[:4]})
        distinct = len(set(fresh)) >= 2
        emit({"check": "two reads produced different poses (not a cached string)",
              "ok": distinct})

        if alive and len(fresh) >= 2 and distinct:
            emit({"result": "PASS"})
            return 0
        emit({"result": "FAIL"})
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:                          # noqa: BLE001
            try:
                proc.kill()
            except Exception:                      # noqa: BLE001
                pass


if __name__ == "__main__":
    sys.exit(main())
