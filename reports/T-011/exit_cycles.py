#!/usr/bin/env python3
"""T-011 判据 2（不变量，真机）：反复"连相机 → 预览 → 关窗口"，不许崩。

UAF 的窗口很窄（worker 正在用 m_impl、析构把 m_impl 拆了），所以这条**不保证**
能复现它；它的价值是"改动没有把退出路径弄坏"，以及给判据 1 的结构性结论配一份
真机证据。

判据：N 轮里
  * 每轮进程都正常退出（不是 0xC0000005 这种异常码）；
  * runtime 日志里不出现新的 `[CRASH]` 行。

用法：python reports/T-011/exit_cycles.py [N]     # exit 0 = PASS
"""

from __future__ import annotations

import ctypes
import json
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
SN = "I1GM112B652"
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def hwnd_by_title(pid: int, title: str, timeout=10.0):
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
            if buf.value.startswith(title):
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


def crash_lines() -> list[str]:
    logs = sorted((EXE.parent / "logs").glob("runtime_*.log"))
    out: list[str] = []
    for path in logs:
        try:
            out += [ln for ln in path.read_text(encoding="utf-8", errors="replace")
                    .splitlines() if "[CRASH]" in ln]
        except OSError:
            continue
    return out


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def one_cycle(index: int) -> tuple[int | None, str]:
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
            return None, "main window not found"
        time.sleep(12.0)
        for attempt in range(3):
            click_text(mw, "连接", timeout=6.0)
            deadline = time.time() + 18
            dlg = None
            while time.time() < deadline:
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
            if dlg is None:
                continue
            picked = None
            for c in dlg.descendants():
                try:
                    if SN in c.window_text():
                        picked = c
                        break
                except Exception:          # noqa: BLE001
                    continue
            if picked is None:
                return None, "device row not found"
            dlg_hwnd = hwnd_by_title(proc.pid, "选择相机设备", timeout=5.0)
            if dlg_hwnd:
                ui.post_click(picked, dlg_hwnd)
            time.sleep(0.5)
            for label in ("确定", "连接", "OK"):
                if click_text(dlg, label, timeout=1.5):
                    break
            break
        time.sleep(6.0)
        click_text(mw, "预览", timeout=5.0)
        time.sleep(3.0)
        # 关窗口（WM_CLOSE）：走 closeEvent 的正常关闭路径
        hwnd = hwnd_by_title(proc.pid, "手眼标定数据收集助手")
        if hwnd:
            WM_CLOSE = 0x0010
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        try:
            code = proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            proc.kill()
            return None, "did not exit within 25 s"
        return code, ""
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=8)
            except Exception:              # noqa: BLE001
                proc.kill()


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    before = len(crash_lines())
    results = []
    for i in range(n):
        code, note = one_cycle(i + 1)
        results.append({"cycle": i + 1, "exit_code": code, "note": note})
        emit({"step": "cycle", **results[-1]})

    after = crash_lines()
    new_crashes = after[before:]
    bad_exits = [r for r in results if r["exit_code"] not in (0, None) ]
    ok = not new_crashes and not bad_exits and all(r["note"] == "" for r in results)
    emit({"check": "没有新的 [CRASH] 行", "ok": not new_crashes,
          "new": new_crashes[:3]})
    emit({"check": "每轮都是正常退出", "ok": not bad_exits, "bad": bad_exits[:3]})
    emit({"result": "PASS" if ok else "FAIL", "cycles": n})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
