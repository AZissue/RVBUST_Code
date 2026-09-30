#!/usr/bin/env python3
"""**一条命令复现本仓库的全部证据**（给"人能独立复现"这条判据用）。

DESIGN §6 第 4 条要求"A 交的证据人能独立复现"。以前它只是一句要求：
证据写得很清楚，但**没人真跑过**。这个脚本把"复现"变成一次点击：

1. 游戏侧全套单测（255 项）
2. 框架零成本自检（`run_all.py --fast`）
3. 自动闯关多 seed 真跑（10 个种子必须全胜、0 死亡）
4. 丝滑真机探针（窄阈值：p50 ≤ 6px、拍边界偏差 ≤ 1px、暂停 ≤ 5px）

每一项都拿**记录在案的期望值**去比，不是"跑完就算过"。任一项不达标就退出码 1。

用法::

    python .trio/reproduce.py            # 全跑（约 1 分钟）
    python .trio/reproduce.py --quick    # 只跑 1、2（约 30 秒）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRIO = REPO / ".trio"


def run(label: str, argv: list[str], timeout: int = 600) -> tuple[bool, str]:
    print(f"\n── {label} " + "─" * max(0, 50 - len(label)))
    print(f"   $ {' '.join(argv)}")
    proc = subprocess.run(
        argv, cwd=str(REPO), text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=timeout,
    )
    # unittest 的汇总（Ran N tests / OK）写在 **stderr** 上——只抓 stdout 会漏掉结论，
    # 于是"测试全绿"会被这条脚本误报成失败。（写它的时候真踩到了。）
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    tail = "\n".join(combined.splitlines()[-8:])
    print("   " + tail.replace("\n", "\n   "))
    return proc.returncode == 0, tail


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="复现本仓库的全部证据")
    parser.add_argument("--quick", action="store_true", help="跳过两条真机探针")
    args = parser.parse_args(argv)

    py = sys.executable
    results: list[tuple[str, bool, str]] = []

    ok, tail = run("游戏侧全套单测", [py, "-m", "unittest", "discover", "-s", "tests", "-t", "."])
    counted = next(
        (line for line in tail.splitlines() if line.startswith("Ran ")), "Ran ? tests"
    )
    results.append((f"游戏侧单测（{counted.strip()}）", ok and "OK" in tail, tail))

    ok, tail = run("框架零成本自检", [py, str(TRIO / "tests" / "run_all.py"), "--fast"])
    results.append(("框架自检（总线/闸/界面/版本库）", ok, tail))

    if not args.quick:
        out = TRIO / "reports" / "t008" / "auto-seeds0-9.json"
        ok, tail = run(
            "自动闯关多 seed 真跑",
            [py, str(TRIO / "reports" / "t008" / "auto_verify.py"),
             "--seeds", "0-9", "--out", str(out)],
        )
        data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        passed = data.get("all_won_no_death") and data.get("wasted_within_0_35") \
            and data.get("steps_within_1100")
        results.append(
            (f"自动闯关：{data.get('passed')}/{data.get('total')} 通关、0 死亡", bool(ok and passed), tail)
        )

        out2 = TRIO / "reports" / "t006" / "reproduce-smoothness.json"
        ok, tail = run(
            "丝滑真机探针",
            [py, str(TRIO / "reports" / "t005" / "smoothness_probe.py"),
             "--level", "1", "--out", str(out2)],
        )
        data2 = json.loads(out2.read_text(encoding="utf-8")) if out2.exists() else {}
        steps = data2.get("c2_step_px", {})
        pause = data2.get("c9_pause", {})

        def num(value, fallback: float = 99.0) -> float:
            """注意：**不能用 `value or fallback`**——0.0 会被当成假值。
            （写这个脚本时踩过一次：拍边界偏差正好 0.0，被判成 99 然后误报失败。）"""
            return fallback if value is None else float(value)

        smooth = (
            num(steps.get("p50")) <= 6
            and num(data2.get("c6_parity_px", {}).get("max")) <= 1
            and num(pause.get("pause_step_px")) <= 5
            and num(pause.get("resume_step_px")) <= 5
            and pause.get("frozen") is True
        )
        results.append(
            (f"丝滑：p50 {steps.get('p50')}px、拍边界 {data2.get('c6_parity_px', {}).get('max')}px、"
             f"暂停 {pause.get('pause_step_px')}/{pause.get('resume_step_px')}px", bool(ok and smooth), tail)
        )

    print("\n" + "═" * 62)
    for label, passed, _ in results:
        print(f"  {'✓' if passed else '✗'}  {label}")
    print("═" * 62)
    bad = [label for label, passed, _ in results if not passed]
    if bad:
        print(f"✗ {len(bad)} 项不满足记录在案的期望：{'、'.join(bad)}")
        print("   （证据不可复现——这本身就是结论，不要当成环境问题糊过去）")
        return 1
    print("✓ 全部证据复现通过：命令、期望值、实际值都在上面的输出里")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
