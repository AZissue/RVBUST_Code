#!/usr/bin/env python3
"""诊断用：主窗口里到底有哪些控件、点「工具」之后多出来什么。
（不是判据，只是一次性的现场勘察；结论会写进 EVIDENCE.md。）
用法：python reports/T-007/_diag_panel.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))
import ui  # noqa: E402

EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"


def snapshot(root):
    out = []
    for ctrl in root.descendants():
        try:
            t = ctrl.element_info.control_type
            n = ctrl.window_text()
        except Exception:
            continue
        if n:
            out.append(f"{t}|{n}")
    return out


def main() -> int:
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    try:
        win = None
        deadline = time.time() + 30
        while time.time() < deadline and win is None:
            try:
                win = ui.main_window(proc.pid)
            except Exception:
                time.sleep(0.5)
        if win is None:
            print("no main window")
            return 1
        hwnd = ui._top_hwnd(proc.pid)
        before = snapshot(win)
        print(json.dumps({"phase": "before", "controls": before}, ensure_ascii=False))

        btn = ui.find_button(win, "工具", timeout=3.0)
        print(json.dumps({"tool_button": None if btn is None else btn.element_info.control_type},
                         ensure_ascii=False))
        if btn is not None:
            ui.post_click(btn, hwnd)
        time.sleep(3.0)
        after = snapshot(win)
        new = [c for c in after if c not in before]
        print(json.dumps({"phase": "after", "new_controls": new}, ensure_ascii=False))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
