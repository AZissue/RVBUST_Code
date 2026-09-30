#!/usr/bin/env python3
"""T-011 判据 1：预览 worker 与 CameraManager 生命周期之间的那道缝。

**为什么这条判据是结构性的**：`~CameraManager()` 里 `m_impl.reset()` 与
预览 worker 之间确实有一小段窗口（worker 已经越过 token 检查、正在
`capturePreviewFrameX1()` 里用 `this`/`m_impl`，析构却把 `m_impl` 拆了），
但窗口太窄，靠反复开/关程序跑不出稳定复现（A 试过，见 reports/T-011/）。
所以**红判据**钉在"机制"上，**绿判据**（reports/T-011/exit_cycles.py）钉在
"真机开关不崩"上。两条一起才说明这件事被处理了。

接受两种合法修法（任一即可）：
  A. 预览 worker **不再捕获裸 `this`**（改成捕获 shared_ptr/weak_ptr 之类的生命周期凭据）；
  B. 析构路径**确实等**在飞的预览 worker（对预览的 future/watcher 调
     `waitForFinished()`，或有等价的显式同步）。

用法：python reports/T-011/preview_lifetime.py     # exit 0 = PASS
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
CPP = REPO_ROOT / "src" / "logic" / "CameraManager.cpp"


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main() -> int:
    text = CPP.read_text(encoding="utf-8", errors="replace")

    # A：预览那一路的 QtConcurrent::run 的捕获列表里不许有裸 this。
    captures = re.findall(r"QtConcurrent::run\(\s*\[([^\]]*)\]", text)
    with_this = [c for c in captures if re.search(r"\bthis\b", c)]
    ok_a = len(captures) > 0 and not with_this
    emit({"check": "预览/concurrent worker 不捕获裸 this", "ok": ok_a,
          "lambdas": len(captures), "capturing_this": with_this})

    # B：析构路径显式等预览 worker。
    waits = re.findall(r"waitForFinished\s*\(", text)
    ok_b = len(waits) > 0
    emit({"check": "析构路径显式等待在飞的 worker（waitForFinished）", "ok": ok_b,
          "found": len(waits)})

    # 顺带把"预览确实是在 worker 里跑"这条事实钉住（别为了过判据把它挪回 UI 线程）。
    ok_c = "QtConcurrent::run" in text
    emit({"check": "预览仍然跑在线程池（没有退化成 UI 线程同步调用）", "ok": ok_c})

    ok = ok_c and (ok_a or ok_b)
    emit({"result": "PASS" if ok else "FAIL",
          "note": "A（不捕获 this）或 B（析构等待）任一成立即算过"})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
