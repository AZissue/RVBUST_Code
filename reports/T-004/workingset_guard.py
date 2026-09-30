#!/usr/bin/env python3
"""T-004 工作集守门：这一轮的 diff 里，除了 B 该改的那一个文件，还有没有别的。

与 T-003 那份的区别：T-003 用"黑名单目录"判定，本轮不适用——**A 自己在发任务书
之前先改了验收测试**（`tests/test_pixel_to_3d.{h,cpp}` 里新增两条红线用例），
那两份改动会一直躺在工作树里，黑名单会误伤。

所以这里用**白名单**，并且把 A 自己的改动显式列出来：
  * B 允许改：`src/logic/PlyPointReader.h`（任务书 §7 的工作集）
  * A 自己的：`tests/test_pixel_to_3d.{h,cpp}`（验收测试）、`reports/T-004/**`（证据）、
    `.trio/**`（框架与任务书）
  其余任何改动 = 越界。

用法：python reports/T-004/workingset_guard.py     # exit 0 = 没越界
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:                                   # Windows 控制台默认 GBK
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_EXACT = ("src/logic/PlyPointReader.h",)
A_OWNED_EXACT = ("tests/test_pixel_to_3d.h", "tests/test_pixel_to_3d.cpp")
A_OWNED_PREFIXES = ("reports/T-004/", ".trio/")


def changed_paths() -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    ).stdout
    paths = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:]
        if " -> " in rest:                 # rename：取新路径
            rest = rest.split(" -> ", 1)[1]
        paths.append(rest.strip().strip('"').replace("\\", "/"))
    return paths


def main() -> int:
    paths = changed_paths()
    bad = [p for p in paths
           if p not in ALLOWED_EXACT
           and p not in A_OWNED_EXACT
           and not p.startswith(A_OWNED_PREFIXES)]

    print(f"changed files: {len(paths)}")
    for p in sorted(paths):
        print(f"  {'BAD ' if p in bad else 'ok  '} {p}")
    if bad:
        print(f"\n越界 {len(bad)} 个（本轮只准动 src/logic/PlyPointReader.h）：")
        for p in sorted(bad):
            print(f"  ✗ {p}")
        return 1
    print("\n✓ 工作集内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
