#!/usr/bin/env python3
"""通用工作集守门：这一轮的 diff 里有没有工作集外的文件。

用法：python reports/tools/workingset_guard.py <允许的路径> [<允许的路径> ...]

A 自己的东西（`tests/`、`reports/`、`.trio/`、`codex_testData/`）默认放行——
A 在发任务书之前就会先改验收测试，跟 B 的改动躺在同一个工作树里。
**放行不等于不检查**：每个改动都会逐行打印 `ok`/`BAD`，A 提交前照样看得到
`tests/` 里有没有被动过（真正的把关是 A 读全量 diff）。

判 B 越界才是这个脚本的活：它盯的是 `src/`、`cmake/`、`CMakeLists.txt` 这些
B 一旦"顺手"改了就会把风险扩散出去的地方。

退出码：0 = 工作集内；1 = 有越界。
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
A_OWNED_PREFIXES = ("tests/", "reports/", ".trio/", "codex_testData/")


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


def main(argv: list[str]) -> int:
    allowed = tuple(p.replace("\\", "/") for p in argv[1:])
    if not allowed:
        print("用法：python reports/tools/workingset_guard.py <允许的路径> ...")
        return 2

    paths = changed_paths()
    bad = [p for p in paths
           if p not in allowed and not p.startswith(A_OWNED_PREFIXES)]

    print(f"工作集：{', '.join(allowed)}")
    print(f"changed files: {len(paths)}")
    for p in sorted(paths):
        tag = "BAD " if p in bad else ("A   " if p not in allowed else "ok  ")
        print(f"  {tag} {p}")
    if bad:
        print(f"\n越界 {len(bad)} 个（工作集外的文件）：")
        for p in sorted(bad):
            print(f"  ✗ {p}")
        return 1
    print("\n✓ 工作集内")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
