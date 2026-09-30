#!/usr/bin/env python3
"""T-007 判据 1：四种协议的分派是不是真的从"复制粘贴四份"收敛成了一处。

这不测"设计长什么样"（B 想用工厂 / switch / 表驱动都行），只测**症状**：
同一句话原来在 `onRobotConnect` 里被抄了四遍，收敛之后就只该出现一次。

被测文件：src/app/MainWindow.cpp（改动前的数字是 A 实测的，写在 BEFORE 里）。

用法：python reports/T-007/dispatch_consolidated.py     # exit 0 = PASS
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
TARGET = REPO_ROOT / "src" / "app" / "MainWindow.cpp"

# 模式 → (改动前的次数, 收敛后允许的上限, 说明)
BEFORE = {
    "机器人已连接（": (8, 2, "每个协议一份 setTip + 一份 log，四份＝8"),
    "机器人连接失败：%1": (8, 2, "同上，失败分支"),
    "setRobotConnected(true)": (5, 2, "每个协议结尾各调一次"),
}
MAX_LINES = 2080            # 改动前 2143 行


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main() -> int:
    if not TARGET.exists():
        emit({"result": "FAIL", "why": f"missing {TARGET}"})
        return 1
    text = TARGET.read_text(encoding="utf-8", errors="replace")
    ok = True
    for pattern, (before, limit, why) in BEFORE.items():
        now = len(re.findall(re.escape(pattern), text))
        passed = now <= limit
        ok &= passed
        emit({"check": f"「{pattern}」收敛到 ≤ {limit} 处", "ok": passed,
              "before": before, "now": now, "why": why})

    lines = text.count("\n") + 1
    passed = lines <= MAX_LINES
    ok &= passed
    emit({"check": f"MainWindow.cpp 行数 ≤ {MAX_LINES}", "ok": passed,
          "before": 2143, "now": lines,
          "why": "四段各 ~28 行的块收敛之后，文件必然明显变短"})

    emit({"result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
