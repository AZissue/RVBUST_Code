#!/usr/bin/env python3
"""批次编排器：一次给多个任务，逐任务跑到通过为止。

它把 ``run-turn.py``（跑一轮）串成队列执行：

    for 每个任务 in 队列:
        attempt = 1
        while attempt <= 任务.max_attempts:
            跑一轮（第 1 次用任务书；之后用自动生成的"回灌任务书"）
            跑该任务的验证命令
            通过 -> 记录 PASS，进下一个任务
            不通过 -> 把失败原文写进回灌任务书，继续下一轮
        超过 max_attempts -> 记录 BLOCKED，停止整批（不猜、不硬撑）

硬闸：单轮预算（透传 run-turn）、整批真实花费上限、整批墙钟上限、总轮数上限。
判断"通过"的标准是**任务自带的验证命令退出码**；需要人眼/主观判断的任务请写
``verify: manual``，编排器只跑一轮然后标记 NEEDS_HUMAN。

用法：

    python .pair/orchestrate.py --queue .pair/queue/001.md
    python .pair/orchestrate.py --queue .pair/queue/001.md --dry-run
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PAIR_DIR = REPO_ROOT / ".pair"
INBOX_DIR = PAIR_DIR / "inbox"
REPORT_DIR = PAIR_DIR / "reports"
QUEUE_DIR = PAIR_DIR / "queue"
RUN_TURN = PAIR_DIR / "run-turn.py"


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ------------------------------------------------------------------ 队列


@dataclass
class Task:
    title: str
    inbox: str = ""
    verify: str = ""
    max_attempts: int = 3
    notes: str = ""

    @property
    def manual(self) -> bool:
        return self.verify.strip().lower() in ("", "manual")


@dataclass
class TaskResult:
    task: Task
    status: str = "PENDING"  # PASS / BLOCKED / NEEDS_HUMAN / SKIPPED
    attempts: int = 0
    last_verify_exit: int | None = None
    claude_cost_cny: float = 0.0
    evidence: list = field(default_factory=list)
    residual: str = ""


def parse_queue(text: str) -> list:
    """解析队列文件：``## 任务标题`` + ``- key: value``。"""
    tasks: list = []
    current: Task | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        heading = re.match(r"^#{2,3}\s+(.*)$", line)
        if heading:
            current = Task(title=heading.group(1).strip())
            tasks.append(current)
            continue
        field_match = re.match(r"^\s*[-*]\s*([a-z_]+)\s*[:：]\s*(.*)$", line, re.I)
        if field_match and current is not None:
            key, value = field_match.group(1).lower(), field_match.group(2).strip()
            if key in ("inbox", "verify", "max_attempts", "notes"):
                if key == "max_attempts":
                    try:
                        current.max_attempts = max(1, int(value))
                    except ValueError:
                        pass
                else:
                    setattr(current, key, value)
            continue
        if current is not None and line.strip() and not line.lstrip().startswith("#"):
            current.notes = (current.notes + " " + line.strip()).strip()
    return [task for task in tasks if task.title]


def next_turn_number() -> int:
    numbers = []
    for path in list(INBOX_DIR.glob("*.md")) + list(REPORT_DIR.glob("turn-*-verify.md")):
        match = re.search(r"(\d{3,})", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return (max(numbers) + 1) if numbers else 1


# ------------------------------------------------------------- 回合调用


def call_run_turn(turn: int, inbox: Path, verify: str, budget: float, dry_run: bool) -> dict:
    """调用 run-turn.py 跑一轮，返回它产出的关键字段。"""
    command = [
        sys.executable,
        str(RUN_TURN),
        "--turn",
        str(turn),
        "--inbox",
        str(inbox.relative_to(REPO_ROOT)),
        "--budget",
        str(budget),
    ]
    if verify:
        command += ["--verify", verify]
    if dry_run:
        command.append("--dry-run")
    result = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    report = REPORT_DIR / f"turn-{turn:03d}-verify.md"
    info = {"stdout": result.stdout, "verify_exit": None, "claude_exit": None, "cost": None}
    if report.exists():
        text = report.read_text(encoding="utf-8", errors="replace")
        verify_match = re.search(r"验证命令：.*→ 退出码 `(-?\d+)`", text)
        if verify_match:
            info["verify_exit"] = int(verify_match.group(1))
        claude_match = re.search(r"退出码：`(-?\d+)`", text)
        if claude_match:
            info["claude_exit"] = int(claude_match.group(1))
        cost_match = re.search(r"真实花费：¥([\d.]+)", text)
        if cost_match:
            info["cost"] = float(cost_match.group(1))
    return info


def build_retry_inbox(task: Task, attempt: int, failure: str, turn: int, path: Path) -> Path:
    """不通过时自动生成"回灌任务书"：只带失败原文 + 一条小要求。"""
    body = f"""# 回灌 · {task.title}（第 {attempt} 次尝试）

上一轮（`{task.inbox}`）**没有通过我的验证**。请只修下面这一个问题，不要扩大范围、
不要顺手改别的东西、不要写测试。

## 我实测到的失败原文

```text
{failure.strip()[-4000:]}
```

## 本轮要做的事

1. 让上面这条失败消失：能解释根因就说明根因，然后改动最小的地方。
2. 改完最多跑 1 条语法/导入自检。
3. 把交回说明写到 `.pair/outbox/{turn:03d}.md`。

## 明确不做

- 不改 `tests/` 下任何文件（测试归 Codex）。
- 不重构无关代码、不调整玩法数值、不改配色。
- 若判断失败原因不在你的改动范围（例如测试本身写错），**不要改测试**，
  在交回说明里写清楚证据，我会下一步处理。
"""
    path.write_text(body, encoding="utf-8")
    return path


def failure_signature(info: dict) -> str:
    """用验证输出的特征去重：同样的失败重复出现就说明原地打转。"""
    text = info.get("stdout") or ""
    interesting = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"(FAIL|ERROR|AssertionError|Traceback)", line)
    ]
    return " | ".join(interesting[-3:]) or f"exit={info.get('verify_exit')}"


# ------------------------------------------------------------- 批次执行


def resolve_inbox(task_inbox: str) -> Path | None:
    """把任务书路径解析成真实文件。

    队列里通常写 `.pair/inbox/004.md`（相对仓库根）。移植到新仓库时，任务书可能
    只写文件名；这时回退到 `INBOX_DIR` 里找同名文件，让编排器不依赖仓库根的写法。
    """
    if not task_inbox:
        return None
    direct = REPO_ROOT / task_inbox
    if direct.exists():
        return direct
    fallback = INBOX_DIR / Path(task_inbox).name
    return fallback if fallback.exists() else direct


def run_batch(args) -> tuple[list, dict]:
    queue_text = Path(args.queue).read_text(encoding="utf-8")
    tasks = parse_queue(queue_text)
    if args.max_tasks:
        tasks = tasks[: args.max_tasks]
    turn = args.start_turn or next_turn_number()
    results: list = []
    totals = {"turns": 0, "cost": 0.0, "started": time.time(), "stopped": ""}

    for task in tasks:
        result = TaskResult(task=task)
        results.append(result)
        inbox_path = resolve_inbox(task.inbox)

        if inbox_path is not None and not inbox_path.exists():
            result.status = "BLOCKED"
            result.residual = f"任务书不存在：{task.inbox}"
            totals["stopped"] = result.residual
            break

        signatures: list = []
        while result.attempts < task.max_attempts:
            result.attempts += 1
            totals["turns"] += 1

            if result.attempts == 1:
                current_inbox = inbox_path
            else:
                current_inbox = build_retry_inbox(
                    task,
                    result.attempts,
                    result.residual,
                    turn,
                    INBOX_DIR / f"{turn:03d}-retry.md",
                )

            print(f"\n=== [{task.title}] 第 {result.attempts}/{task.max_attempts} 次 · turn {turn:03d} ===")
            info = call_run_turn(
                turn, current_inbox, task.verify, args.budget, args.dry_run
            )
            result.last_verify_exit = info.get("verify_exit")
            if info.get("cost"):
                result.claude_cost_cny += float(info["cost"])
                totals["cost"] += float(info["cost"])
            result.evidence.append(f"turn-{turn:03d}")

            if task.manual:
                result.status = "NEEDS_HUMAN"
                result.residual = "verify: manual —— 需要人/Codex 主观或真机确认"
                break

            if info.get("verify_exit") == 0:
                result.status = "PASS"
                break

            signature = failure_signature(info)
            signatures.append(signature)
            result.residual = signature
            if len(signatures) >= 2 and signatures[-1] == signatures[-2]:
                result.status = "BLOCKED"
                result.residual = f"连续两次同一个失败，停止硬撑：{signature}"
                break
            turn += 1

        if result.status not in ("PASS", "NEEDS_HUMAN"):
            result.status = "BLOCKED"
            totals["stopped"] = f"任务「{task.title}」未通过，已停止整批"
            break
        turn += 1

        if totals["turns"] >= args.max_turns:
            totals["stopped"] = f"达到总轮数上限 {args.max_turns}"
            break
        if totals["cost"] >= args.total_cny:
            totals["stopped"] = f"达到整批真实花费上限 ¥{args.total_cny}"
            break
        if (time.time() - totals["started"]) >= args.total_wall:
            totals["stopped"] = f"达到整批墙钟上限 {args.total_wall:.0f}s"
            break

    return results, totals


def write_summary(batch_id: str, results: list, totals: dict, args) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"batch-{batch_id}-summary.md"
    lines = [
        f"# 批次 {batch_id} 汇总（orchestrate 自动生成）",
        "",
        f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 队列：`{args.queue}`",
        f"- 轮数：{totals['turns']}，真实花费：¥{totals['cost']:.2f}（DeepSeek 实扣）",
        f"- 用时：{int(time.time() - totals['started'])}s",
        "",
        "| 任务 | 状态 | 尝试 | 最终验证退出码 | 轮次 |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.task.title} | **{result.status}** | {result.attempts} | "
            f"{result.last_verify_exit} | {', '.join(result.evidence)} |"
        )
    if totals.get("stopped"):
        lines += ["", f"> 提前停止：{totals['stopped']}"]
    blocked = [r for r in results if r.status == "BLOCKED"]
    if blocked:
        lines += ["", "## 未通过的任务", ""]
        for result in blocked:
            lines += [
                f"### {result.task.title}",
                "",
                f"- 验证命令：`{result.task.verify}`",
                f"- 残留失败：`{result.residual[:600]}`",
                "",
            ]
    lines += [
        "",
        "> 编排器只按验证命令判「机械通过」；**面向人的结论要 Codex 读 diff + 真机验证后给**。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description="批次编排：多任务、逐任务跑到通过")
    parser.add_argument("--queue", required=True, help="队列文件，如 .pair/queue/001.md")
    parser.add_argument("--budget", type=float, default=4.0, help="单轮预算（估算美元）")
    parser.add_argument("--total-cny", type=float, default=3.0, help="整批真实花费上限（CNY）")
    parser.add_argument("--total-wall", type=float, default=3600, help="整批墙钟上限（秒）")
    parser.add_argument("--max-turns", type=int, default=12, help="整批最多跑多少轮")
    parser.add_argument("--max-tasks", type=int, default=0, help="只跑前 N 个任务（0=全部）")
    parser.add_argument("--start-turn", type=int, default=0, help="从第几轮开始编号")
    parser.add_argument("--dry-run", action="store_true", help="只验管道，不调用模型")
    args = parser.parse_args(argv)

    if not Path(args.queue).exists():
        print(f"[error] 找不到队列文件：{args.queue}")
        return 2
    batch_id = Path(args.queue).stem
    results, totals = run_batch(args)
    path = write_summary(batch_id, results, totals, args)
    print(f"\n[orchestrate] 汇总 -> {path.relative_to(REPO_ROOT)}")
    for result in results:
        print(f"  {result.status:12} {result.task.title}（尝试 {result.attempts} 次）")
    return 0 if all(r.status in ("PASS", "NEEDS_HUMAN") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
