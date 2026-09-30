#!/usr/bin/env python3
"""T-010 判据 1：2D 浮层的模糊底**到底花多少时间**（真机实测，不是估算）。

背景：`Image2DView::overlayBlurUnder()` 每画一次浮层就 `copy()` 一次背后画面、
再做两次 `scaled()`（降采样 + 平滑放大）并新建一张 QImage；8 个浮层控件在 30 fps 预览下
就是每秒 240 次。A 的审查结论是"**先量再改**"——量出来很小就别改（改也是白改），
量出来可观就按帧缓存。

所以这个任务的红判据是"**没有测量**"：程序现在不会告诉你这笔开销。
要 B 加的仪表是：在 `Image2DView` 里累计 `overlayBlurUnder()` 的耗时与次数，
每秒往 runtime 日志写一行 `[OVERLAY] per_frame_us=… paints=… calls=…`（仪表**要留下**，
它就是本任务的证据）。

判据：真机跑预览 ~10 s，取最后若干行的 `per_frame_us`：
  * 必须能读到这行（读不到 = 没有仪表 → FAIL）；
  * 中位数 ≤ 500 µs（0.5 ms/帧）。

用法：python reports/T-010/overlay_cost.py        # exit 0 = PASS
"""

from __future__ import annotations

import ctypes
import json
import re
import statistics
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
BUDGET_US = 500
LINE = re.compile(r"\[OVERLAY\].*per_frame_us=([\d.]+)")
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def hwnd_of(pid: int, prefix: str, timeout=12.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            owner = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not _user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(512)
            _user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value.startswith(prefix):
                found.append(hwnd)
                return False
            return True

        _user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def overlay_samples() -> list[float]:
    out: list[float] = []
    for path in sorted((EXE.parent / "logs").glob("runtime_*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out += [float(m) for m in LINE.findall(text)]
    return out


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


def main() -> int:
    before = overlay_samples()
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
            emit({"result": "FAIL", "why": "main window not found"})
            return 1
        time.sleep(13.0)
        # 连相机 → 预览（有画面才有浮层底可画）
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
                emit({"result": "FAIL", "why": "device row not found"})
                return 1
            dlg_hwnd = hwnd_of(proc.pid, "选择相机设备", timeout=5.0)
            if dlg_hwnd:
                ui.post_click(picked, dlg_hwnd)
            time.sleep(0.5)
            for label in ("确定", "连接", "OK"):
                if click_text(dlg, label, timeout=1.5):
                    break
            break
        time.sleep(6.0)
        click_text(mw, "预览", timeout=6.0)
        time.sleep(12.0)                   # 攒十几秒的 [OVERLAY] 行

        samples = overlay_samples()
        fresh = samples[len(before):] if len(samples) >= len(before) else samples
        emit({"check": "日志里能读到 [OVERLAY] per_frame_us", "ok": bool(fresh),
              "count": len(fresh), "sample": fresh[-2:]})
        if not fresh:
            emit({"result": "FAIL", "why": "没有仪表（程序还没报这笔开销）"})
            return 1
        med = statistics.median(fresh)
        ok = med <= BUDGET_US
        emit({"check": f"浮层开销中位数 ≤ {BUDGET_US} µs/帧", "ok": ok,
              "median_us": round(med, 1), "max_us": round(max(fresh), 1),
              "samples": len(fresh)})
        emit({"result": "PASS" if ok else "FAIL"})
        return 0 if ok else 1
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
