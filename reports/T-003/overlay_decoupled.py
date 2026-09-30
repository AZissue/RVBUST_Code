#!/usr/bin/env python3
"""T-003 判据 2：两个视窗的浮层按钮到底有没有共用同一套 UI 实现。

检查四件事：
  ① 两边都调用同一个 Theme::viewOverlayButtonStyle()；
  ② VisSceneView.cpp 里不再有 3D 专属的 `background-color: rgba(...)` 覆盖
     （那行就是"配色不一样"的根因）；
  ③ src/ui/ 里存在一个被 Image2DView.cpp 与 VisSceneView.cpp 同时 include 的头文件，
     且里面定义了浮层按钮组件（类名含 Overlay + 按钮/Glass 之类）；
  ④ 程序仍能启动并显示主窗口（冒烟，只看起没起来）。

用法：python reports/T-003/overlay_decoupled.py
退出码：0 = 全过；1 = 有检查没过；2 = 环境问题。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import ui  # noqa: E402

EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
UI = REPO_ROOT / "src" / "ui"


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def includes(text: str) -> set[str]:
    return {m.group(1) for m in
            re.finditer(r'#include\s+"([^"]+)"', text)}


def main() -> int:
    img = (UI / "Image2DView.cpp").read_text(encoding="utf-8", errors="replace")
    vis = (UI / "VisSceneView.cpp").read_text(encoding="utf-8", errors="replace")
    fails = []

    # ① 同一个样式工厂
    both_style = ("viewOverlayButtonStyle" in img) and ("viewOverlayButtonStyle" in vis)
    say(check="both use Theme::viewOverlayButtonStyle()", ok=both_style)
    if not both_style:
        fails.append("两边没有都走 Theme::viewOverlayButtonStyle()")

    # ② 3D 不再有专属底色覆盖
    vis_rgba = re.findall(r"background-color:\s*rgba\([^)]*\)", vis)
    say(check="VisSceneView.cpp has no per-view rgba background override",
        ok=not vis_rgba, found=vis_rgba[:4])
    if vis_rgba:
        fails.append(f"VisSceneView.cpp 里还有专属底色覆盖：{vis_rgba[:2]}")

    # ③ 共享头文件：同时被两边 include，且里面定义了浮层按钮组件
    shared = None
    common = includes(img) & includes(vis)
    for inc in sorted(common):
        name = Path(inc).name
        path = UI / name
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"class\s+\w*(Overlay|Glass)\w*", body) and "QPushButton" in body:
            shared = {"include": inc, "file": str(path.relative_to(REPO_ROOT))}
            break
    say(check="a shared overlay-button header is included by both", ok=shared is not None,
        shared=shared, common_includes=sorted(common))
    if shared is None:
        fails.append("没有找到被两个视窗共同 include 的浮层按钮组件头文件")

    # ④ 冒烟：程序能起来
    if not EXE.exists():
        say(error=f"exe not found: {EXE}")
        return 2
    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    ok_smoke = False
    try:
        deadline = time.time() + 40
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                mw = ui.main_window(proc.pid)
                if mw.window_text().startswith("手眼标定数据收集助手"):
                    ok_smoke = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
    say(check="app starts and shows its main window", ok=ok_smoke,
        exit_code=proc.poll())
    if not ok_smoke:
        fails.append("程序没能正常启动到主窗口")

    if fails:
        for f in fails:
            say(fail=f)
        return 1
    say(result="PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
