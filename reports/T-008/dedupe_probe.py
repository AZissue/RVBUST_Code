#!/usr/bin/env python3
"""T-008 r2 判据：标定结果正文的"单一出处"。

症状（改之前）：
  * 「4×4 矩阵（行主序）」这句话在 src/ 里出现 **2 次**（MainWindow.cpp:1077
    与 ToolsPanel.cpp:860 各一份，逐组误差的循环也各一份）；
  * 两个文件里都**没有** `formatResult(` —— 因为那时它还不存在。

收敛之后：正文只在 `src/logic/CalibrationService.cpp` 里拼一次，
两个界面页各自 `CalibrationService::formatResult(` 调用它。

用法：python reports/T-008/dedupe_probe.py     # exit 0 = PASS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
MATRIX_LITERAL = "4×4 矩阵（行主序）"
PERFRAME_LITERAL = "逐组误差"
CALLERS = (
    "app/MainWindow.cpp",
    "ui/ToolsPanel.cpp",
)


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def count_in_src(literal: str) -> tuple[int, list[str]]:
    total, where = 0, []
    for path in SRC.rglob("*"):
        if path.suffix not in (".cpp", ".h"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = text.count(literal)
        if n:
            total += n
            where.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{n}")
    return total, where


def main() -> int:
    ok = True

    n_matrix, where_matrix = count_in_src(MATRIX_LITERAL)
    passed = n_matrix == 1
    ok &= passed
    emit({"check": f"「{MATRIX_LITERAL}」在 src/ 里只出现 1 次", "ok": passed,
          "now": n_matrix, "before": 2, "where": where_matrix})

    n_per, where_per = count_in_src(PERFRAME_LITERAL)
    passed = n_per == 1
    ok &= passed
    emit({"check": f"「{PERFRAME_LITERAL}」在 src/ 里只出现 1 次", "ok": passed,
          "now": n_per, "before": 2, "where": where_per})

    for rel in CALLERS:
        path = SRC / rel
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        called = "CalibrationService::formatResult(" in text
        ok &= called
        emit({"check": f"{rel} 调用 CalibrationService::formatResult()",
              "ok": called})

    emit({"result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
