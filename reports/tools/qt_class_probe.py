#!/usr/bin/env python3
"""通用探针：跑 unit_tests.exe 里的**某一个测试类**，判定 PASS/FAIL。

T-004 的 `ply_probe.py` 是这份的特例；从 T-005 起各任务用这一份，避免每个任务
复制 100 行探针代码。

用法：python reports/tools/qt_class_probe.py <class-tag> <min-passed>
  class-tag  = QTest 的**类报告文件名后缀**（tests/test_main.cpp 的 runClass 第三参）
  min-passed = 这一类的用例数下限（防止"用例被删掉"仍然绿）

PASS 的四个条件（缺一不可）：
  1. unit_tests.exe 正常结束（返回码 0/1；其它码说明进程被崩掉了）；
  2. 该类的报告文件写出来了（进程没被 bad_alloc / SEH 带走）；
  3. 该类 failed == 0；
  4. 该类 passed >= min-passed。

测试 exe 是 GUI 子系统、stdout 抓不到，所以只能读 `-o <file>,txt` 的报告文件。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:                                   # Windows 控制台默认 GBK
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
EXE = REPO_ROOT / "build" / "src" / "Release" / "unit_tests.exe"
TOTALS = re.compile(r"Totals:\s*(\d+)\s+passed,\s*(\d+)\s+failed")


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        emit({"result": "FAIL", "why": "usage: qt_class_probe.py <class-tag> <min-passed>"})
        return 2
    tag, min_passed = argv[1], int(argv[2])

    if not EXE.exists():
        emit({"check": "unit_tests.exe exists", "ok": False, "path": str(EXE)})
        emit({"result": "FAIL", "why": "先构建：cmake --build build --config Release"})
        return 1

    with tempfile.TemporaryDirectory(prefix="qtprobe_") as tmp:
        report = Path(tmp) / "rep.txt"
        try:
            proc = subprocess.run(
                [str(EXE), "-o", f"{report},txt"],
                cwd=str(EXE.parent), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=300,
            )
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            emit({"check": "unit_tests terminated normally", "ok": False, "why": "300 s timeout"})
            emit({"result": "FAIL"})
            return 1

        class_report = report.with_name(f"rep.{tag}.txt")
        emit({"check": "unit_tests exited without being killed", "ok": rc in (0, 1),
              "exit_code": rc})
        if not class_report.exists() or class_report.stat().st_size == 0:
            emit({"check": f"{tag}: class report was written", "ok": False})
            emit({"result": "FAIL",
                  "why": "no class report — the process died before QTest finished"})
            return 1
        emit({"check": f"{tag}: class report was written", "ok": True})

        text = class_report.read_text(encoding="utf-8", errors="replace")
        m = TOTALS.search(text)
        if not m:
            emit({"check": f"{tag}: Totals line present", "ok": False, "tail": text[-400:]})
            emit({"result": "FAIL"})
            return 1
        passed, failed = int(m.group(1)), int(m.group(2))
        emit({"check": f"{tag}: no failures", "ok": failed == 0,
              "passed": passed, "failed": failed})
        emit({"check": f"{tag}: at least {min_passed} cases ran",
              "ok": passed >= min_passed, "passed": passed})

        if failed == 0 and passed >= min_passed and rc in (0, 1):
            emit({"result": "PASS"})
            return 0

        failures = [ln for ln in text.splitlines() if ln.startswith("FAIL!")]
        emit({"result": "FAIL", "failures": failures[:6]})
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
