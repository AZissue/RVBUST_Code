#!/usr/bin/env python3
"""T-001 判据 5：工作集守卫——B 有没有动到工作集外的文件。

黑名单判定（比白名单稳）：只把**明确不该碰**的目录/文件标红，其余改动照常打印。
为什么不用白名单：`.trio/`（框架安装）、`reports/`（A 的探针与证据）本来就
以未跟踪状态躺在这里，白名单会把 A 自己的东西判成越界。

用法：python reports/T-003/workingset_guard.py     # exit 0 = 没越界；1 = 越界
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:                                   # Windows 控制台默认 GBK，会把 ✓ 打成异常
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]

# B 这一轮不许碰的地方（任务书 §3 明确不做 + §7 工作集外）。
FORBIDDEN_PREFIXES = (
    "src/logic/", "src/sdk/", "src/models/",
    "src/ui/SettingsDialog.", "src/ui/DeviceListDialog.", "src/ui/SidePanel.",
    "src/ui/TopNavBar.", "src/ui/DataInputCard.", "src/ui/ModeSelector.",
    "tests/", "cmake/", "third_party/", "packaging/", "build/",
    ".trio/roles/", ".trio/bus.py", ".trio/router.py",
)
# src/app/ 里只有 MainWindow.cpp 在 T-002 的工作集内（只为新增一个 logger 连接）。
FORBIDDEN_PREFIXES += tuple(
    f"src/app/{name}" for name in
    ("MainWindow.h", "DataManager.", "CaptureFlow.", "AutoFlow.", "RobotPose.")
)
FORBIDDEN_EXACT = ("CMakeLists.txt", "run.bat", "run1.bat", "pack_portable.ps1")


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
        paths.append(rest.strip().strip('"'))
    return paths


def main() -> int:
    paths = changed_paths()
    bad = []
    for p in paths:
        norm = p.replace("\\", "/")
        if norm in FORBIDDEN_EXACT or norm.startswith(FORBIDDEN_PREFIXES):
            bad.append(norm)
    print(f"changed files: {len(paths)}")
    for p in sorted(paths):
        print(f"  {'BAD ' if p.replace(chr(92), '/') in bad else 'ok  '} {p}")
    if bad:
        print(f"\n越界 {len(bad)} 个（工作集外）：")
        for p in sorted(bad):
            print(f"  ✗ {p}")
        return 1
    print("\n✓ 没有动到工作集外的文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
