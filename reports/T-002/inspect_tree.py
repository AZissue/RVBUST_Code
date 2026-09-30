#!/usr/bin/env python3
"""T-002 辅助探针：把工具窗口「欧氏距离」页附近的控件树（类型/文本/矩形）打出来，
用来把「顶部那条横向滚动条」落到具体控件上。

用法：python reports/T-002/inspect_tree.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402

EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def main() -> int:
    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    pid = proc.pid
    try:
        mw = None
        deadline = time.time() + 40
        while time.time() < deadline:
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
            if item.window_text().strip() == "欧氏距离":
                item.click_input()
                break
        time.sleep(1.0)

        dlg = next((c for c in mw.descendants(control_type="Window")
                    if c.window_text() == "工具"), None)
        if dlg is None:
            say(error="tools dialog node not found")
            return 2

        rows = []
        for c in dlg.descendants():
            try:
                r = c.rectangle()
                txt = c.window_text()
                ct = c.element_info.control_type
            except Exception:
                continue
            rows.append({"type": ct, "text": txt[:40],
                         "rect": [r.left, r.top, r.right, r.bottom]})
        # 只看内容区上半部分（顶部那条滚动条就在这里）
        rows.sort(key=lambda x: (x["rect"][1], x["rect"][0]))
        say(count=len(rows))
        for row in rows:
            if row["rect"][1] < 340:
                say(**row)
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
