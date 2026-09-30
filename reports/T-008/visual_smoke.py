#!/usr/bin/env python3
"""T-008 r3 判据 4：配色重构之后**界面看起来没变**（真进程 + 像素比对）。

做法：起程序 → 开工具面板 → 截工具列表里被选中那一项的矩形 → 取平均 RGB，
与改之前采集的基线比。只比"平均值差 ≤3/通道"，因为：
  * 这条任务要的是"同一个颜色换个写法"，不是重新配色；
  * 平均值对 1 px 的边框/抗锯齿差异不敏感，对整块底色变了很敏感（正是我们要抓的）。

用法：
    python reports/T-008/visual_smoke.py --capture     # 改之前采基线（A 跑）
    python reports/T-008/visual_smoke.py               # 改之后比对，exit 0 = 没变
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

OUT = REPO_ROOT / "reports" / "T-008"
EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
BASELINE = OUT / "visual_baseline.json"

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def hwnd_of(pid: int, prefix: str, timeout=12.0):
    from ctypes import wintypes
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


def mean_rgb(box) -> list[float]:
    img = ImageGrab.grab().convert("RGB").crop(box)
    px = list(img.getdata())
    n = max(1, len(px))
    return [round(sum(p[i] for p in px) / n, 2) for i in range(3)]


def main() -> int:
    capture = "--capture" in sys.argv
    if not EXE.exists():
        emit({"result": "FAIL", "why": f"missing {EXE}"})
        return 1
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
        time.sleep(11.0)
        main_hwnd = hwnd_of(proc.pid, "手眼标定数据收集助手")
        panel = None
        for _ in range(4):
            ui.post_click(ui.find_button(mw, "工具"), main_hwnd)
            panel = hwnd_of(proc.pid, "工具", timeout=10.0)
            if panel:
                break
            time.sleep(1.0)
        if panel is None:
            emit({"result": "FAIL", "why": "工具面板没打开"})
            return 1
        # 左侧列表第一项（当前选中态 = 品牌蓝 0.12 底）
        item = ui.find_button(mw, "欧氏距离", timeout=6.0)
        if item is None:
            emit({"result": "FAIL", "why": "找不到左侧第一项"})
            return 1
        r = item.rectangle()
        box = (r.left + 6, r.top + 2, r.right - 6, r.bottom - 2)
        sample = mean_rgb(box)
        emit({"check": "sampled selected list item", "box": list(box), "mean_rgb": sample})

        if capture:
            BASELINE.write_text(json.dumps({"box": list(box), "mean_rgb": sample},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
            emit({"result": "CAPTURED", "file": str(BASELINE)})
            return 0

        if not BASELINE.exists():
            emit({"result": "FAIL", "why": "没有基线，先跑 --capture"})
            return 1
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        diff = [round(abs(a - b), 2) for a, b in zip(sample, base["mean_rgb"])]
        ok = max(diff) <= 3.0
        emit({"check": "选中的列表项目底色没变（≤3/通道）", "ok": ok,
              "baseline": base["mean_rgb"], "now": sample, "diff": diff})
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
