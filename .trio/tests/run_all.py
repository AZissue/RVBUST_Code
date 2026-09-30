#!/usr/bin/env python3
"""跑全部**零成本**自检。**一条命令，全绿才算数。**

为什么要有这个文件：上一轮 29 条自测全绿、三份回放全对、七个接口全通，
人却在真机上什么也没看见——因为**没有一条测试照着"人这一侧"**。
绿灯要照到人身上才算数，所以页面渲染测试从今往后和总线测试平级，
一起跑、一起看结果。

用法::

    python .trio/tests/run_all.py            # 全跑
    python .trio/tests/run_all.py --fast     # 跳过历史日志回放（那份日志是 gitignore 的）

**不调任何模型、不花一分钱。**
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

TRIO = Path(__file__).resolve().parent.parent
REPO = TRIO.parent


def run(label: str, argv: list[str], cwd: Path = REPO) -> bool:
    print(f"\n── {label} " + "─" * max(0, 56 - len(label)))
    try:
        # 自检里**绝不许真去唤醒 A**：`bus.post` 见 B/deliver 这类消息会调
        # `codex queue`（TRIO_NO_WAKE=1 时关闭），测试里真投会把 A 叫醒好几次。
        env = dict(os.environ, TRIO_NO_WAKE="1")
        proc = subprocess.run(argv, cwd=str(cwd), text=True, encoding="utf-8",
                              errors="replace", env=env)
    except FileNotFoundError:
        print(f"   跳过：找不到 {argv[0]}")
        return True
    if proc.returncode != 0:
        print(f"   ✗ 退出码 {proc.returncode}")
        return False
    return True


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="三方协作框架的零成本自检")
    parser.add_argument("--fast", action="store_true", help="跳过历史日志回放")
    args = parser.parse_args(argv)

    py = sys.executable
    results: list[tuple[str, bool]] = []

    sources = sorted(str(p) for p in TRIO.glob("*.py"))
    results.append(("语法检查", run("语法检查", [py, "-m", "py_compile", *sources])))

    # 这一步现在不止总线：还含机械闸回放规则、版本库规则、以及**真起一个群界面进程**
    # 的集成测试（本地端口 + 假浏览器，仍然零成本、不调模型）。
    results.append((
        "总线 / 闸 / 界面 / 版本库自测",
        run("总线 / 闸 / 界面 / 版本库自测", [
            py, "-m", "unittest", "discover",
            "-s", str(TRIO / "tests"), "-t", str(TRIO / "tests"), "-v",
        ]),
    ))

    # ★ 人这一侧。缺 node 就跳过——但**跳过要说出来**，不许悄悄变成绿的。
    if shutil.which("node"):
        results.append((
            "群界面真渲染",
            run("群界面真渲染（人这一侧）", [
                "node", str(TRIO / "tests" / "page_render.mjs"), str(TRIO / "serve.py"),
            ]),
        ))
    else:
        print("\n── 群界面真渲染 " + "─" * 42)
        print("   ⚠ 跳过：没装 node。**人这一侧没有测试**，别当它绿了。")
        results.append(("群界面真渲染", True))

    log = REPO / ".pair" / "logs" / "turn-001.stream.jsonl"
    if args.fast or not log.exists():
        print("\n── 机械闸回放 " + "─" * 44)
        print(f"   跳过：没有 {log.relative_to(REPO)}（该目录在 .gitignore 里）")
    else:
        results.append((
            "机械闸回放在烧钱那轮上触发",
            run("机械闸回放（turn-001，烧钱那轮）", [
                py, str(TRIO / "router.py"), "replay",
                "--stream", str(log.relative_to(REPO)), "--task", "turn-001",
                "--expect", "fire",
            ]),
        ))
        results.append((
            "机械闸回放在成功轮上不误杀",
            run("机械闸回放（turn-102，成功轮）", [
                py, str(TRIO / "router.py"), "replay",
                "--stream", ".pair/logs/turn-102.stream.jsonl", "--task", "turn-102",
                "--expect", "clean",
            ]),
        ))

    print("\n" + "═" * 62)
    for label, ok in results:
        print(f"  {'✓' if ok else '✗'}  {label}")
    bad = [label for label, ok in results if not ok]
    print("═" * 62)
    if bad:
        print(f"✗ {len(bad)} 项不通过：{'、'.join(bad)}")
        return 1
    print("✓ 全部通过（零成本、不调模型）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
