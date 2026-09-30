#!/usr/bin/env python3
"""T-008 r3 判据 1：品牌色与 Tab 缩进的"单一出处"。

症状（改之前，A 实测 2026-09-30）：
  * `rgba(22,119,255` 在 `Theme.{h,cpp}` 之外还散落 **5 处**
    （ToolsPanel.cpp 1、DeviceListDialog.cpp 3、ActionButtons.cpp 1）；
  * `VisSceneView.cpp:586` 直接写死 `rgb(26, 31, 46)` —— 那是 Theme 的背景色；
  * `URRealtimeReader.{h,cpp}` 里 **84 行**用 Tab 缩进，其余文件全是空格。

收敛之后：颜色只在 Theme 里定义、各处经 `Theme::withAlpha()` 取；Tab 清零。

用法：python reports/T-008/cleanup_probe.py     # exit 0 = PASS
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
UI = REPO_ROOT / "src" / "ui"
THEME = ("Theme.h", "Theme.cpp")
BRAND_RGBA = re.compile(r"rgba\(\s*22\s*,\s*119\s*,\s*255")
CALLERS = ("ToolsPanel.cpp", "DeviceListDialog.cpp", "ActionButtons.cpp")
TABBED = ("src/logic/URRealtimeReader.h", "src/logic/URRealtimeReader.cpp")


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main() -> int:
    ok = True

    stray, where = 0, []
    for path in UI.glob("*.cpp"):
        n = len(BRAND_RGBA.findall(path.read_text(encoding="utf-8", errors="replace")))
        if n:
            stray += n
            where.append(f"{path.name}:{n}")
    ok &= stray == 0
    emit({"check": "Theme 之外没有手写的品牌蓝 rgba(22,119,255…)", "ok": stray == 0,
          "now": stray, "before": 5, "where": where})

    vis = (UI / "VisSceneView.cpp").read_text(encoding="utf-8", errors="replace")
    n_bg = len(re.findall(r"rgb\(\s*26\s*,\s*31\s*,\s*46", vis))
    ok &= n_bg == 0
    emit({"check": "VisSceneView 不再手写背景色 rgb(26,31,46)", "ok": n_bg == 0,
          "now": n_bg, "before": 1})

    theme_h = (UI / "Theme.h").read_text(encoding="utf-8", errors="replace")
    declared = "withAlpha" in theme_h
    ok &= declared
    emit({"check": "Theme.h 提供 withAlpha()", "ok": declared})

    for name in CALLERS:
        text = (UI / name).read_text(encoding="utf-8", errors="replace")
        used = "Theme::withAlpha(" in text
        ok &= used
        emit({"check": f"{name} 经 Theme::withAlpha() 取色", "ok": used})

    tabs = 0
    for rel in TABBED:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        n = sum(1 for line in text.splitlines() if line.startswith("\t"))
        tabs += n
        emit({"check": f"{rel} 没有 Tab 缩进", "ok": n == 0, "now": n})
    emit({"check": "URRealtimeReader 整体无 Tab 缩进", "ok": tabs == 0,
          "now": tabs, "before": 84})

    # ── 颜色值逐点比对（替代截图比对：截图在某些窗口层级下会采到别的地方，
    #    实测把基线采成了暗区、把改后采成了浅色区，那种判据自己会抖）──
    # 规则：HEAD 里每个 rgba(22,119,255,A) 的 A，现在必须在同一个文件里以
    # `Theme::withAlpha(<色>, A)` 的形式出现；alpha 集合逐一相等。
    import subprocess
    for name in CALLERS:
        rel = f"src/ui/{name}"
        try:
            old = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(REPO_ROOT),
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=30).stdout
        except Exception as exc:           # noqa: BLE001
            emit({"check": f"{rel} 读 HEAD 版本", "ok": False, "why": str(exc)})
            ok = False
            continue
        old_alphas = sorted(re.findall(r"rgba\(\s*22\s*,\s*119\s*,\s*255\s*,\s*([\d.]+)",
                                       old))
        new_alphas = sorted(re.findall(r"Theme::withAlpha\([^,]+,\s*([\d.]+)\s*\)",
                                       (UI / name).read_text(encoding="utf-8",
                                                             errors="replace")))
        same = old_alphas == new_alphas
        ok &= same
        emit({"check": f"{name}：alpha 与原字面量一致", "ok": same,
              "old": old_alphas, "new": new_alphas})

    emit({"result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
