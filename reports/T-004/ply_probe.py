#!/usr/bin/env python3
"""T-004 判据 1：PLY 解析器遇到"坏头部"不再把进程带走。

测的不是"能解析好文件"（那是既有用例的活），而是**A 在 tests/test_pixel_to_3d.cpp
里新增的两条验收用例**：

    plyReaderRejectsOversizedVertexCount     —— ascii，声称 99999999999 个顶点
    plyReaderRejectsShortBinaryWithBigClaim  —— binary，声称 2000000 个顶点但只有 3 个

两条都要求 `PlyPointReader::read()` 返回 `ok == false`。改动前，解析器在读到
顶点头之前就 `reserve(vertexCount * 3)`，第一条会把 `std::bad_alloc` 抛到没有 try
的调用点 → 进程 terminate。

所以 PASS 要同时成立四件事：
  1. `unit_tests.exe` 进程**正常结束**（返回码 0/1；别的码说明它被崩掉了）；
  2. `pixel_to_3d` 那一类的报告文件**存在**（进程被 bad_alloc/terminate 带走时
     这个文件根本不会写出来 —— 这正是"没崩"的直接证据）；
  3. 该类 `failed == 0`；
  4. 该类 `passed >= 12`（现有 10 条 + 新增 2 条；少一条说明用例被删了）。

报告文件按类分开是 `tests/test_main.cpp` 的 `reportArgsFor()` 干的：给 `-o` 的路径
插一个 `.pixel_to_3d` 后缀。测试 exe 是 GUI 子系统、stdout 抓不到，只能读文件。

用法：python reports/T-004/ply_probe.py          # exit 0 = PASS
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
MIN_PASSED = 12
TOTALS = re.compile(r"Totals:\s*(\d+)\s+passed,\s*(\d+)\s+failed")


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main() -> int:
    if not EXE.exists():
        emit({"check": "unit_tests.exe exists", "ok": False, "path": str(EXE)})
        emit({"result": "FAIL", "why": "先构建：cmake --build build --config Release"})
        return 1

    with tempfile.TemporaryDirectory(prefix="t004_") as tmp:
        report = Path(tmp) / "rep.txt"
        try:
            proc = subprocess.run(
                [str(EXE), "-o", f"{report},txt"],
                cwd=str(EXE.parent), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=300,
            )
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            emit({"check": "unit_tests terminated normally", "ok": False,
                  "why": "300 s timeout"})
            emit({"result": "FAIL"})
            return 1

        # QTest 给每个类写自己的文件；报告文件名里插了类名。
        class_report = report.with_name("rep.pixel_to_3d.txt")
        alive = class_report.exists() and class_report.stat().st_size > 0
        emit({"check": "unit_tests exited without being killed", "ok": rc in (0, 1),
              "exit_code": rc})
        emit({"check": "pixel_to_3d class report was written (process survived)",
              "ok": alive, "path": class_report.name})
        if not alive:
            emit({"result": "FAIL",
                  "why": "no class report — the process died before QTest could finish "
                         "(bad_alloc/terminate is the failure this task is about)"})
            return 1

        text = class_report.read_text(encoding="utf-8", errors="replace")
        m = TOTALS.search(text)
        if not m:
            emit({"check": "Totals line present", "ok": False,
                  "tail": text[-400:]})
            emit({"result": "FAIL"})
            return 1
        passed, failed = int(m.group(1)), int(m.group(2))
        emit({"check": "pixel_to_3d: no failures", "ok": failed == 0,
              "passed": passed, "failed": failed})
        emit({"check": f"pixel_to_3d: at least {MIN_PASSED} cases ran",
              "ok": passed >= MIN_PASSED, "passed": passed})

        if failed == 0 and passed >= MIN_PASSED and rc in (0, 1):
            emit({"result": "PASS"})
            return 0

        # 只截失败那几行的上下文，别把整份报告倒出来。
        lines = text.splitlines()
        bad_lines = [ln for ln in lines if ln.startswith("FAIL!")]
        emit({"result": "FAIL", "failures": bad_lines[:6]})
        return 1


if __name__ == "__main__":
    sys.exit(main())
