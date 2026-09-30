#!/usr/bin/env python3
"""A 侧（Codex）台账：从 Codex 自己的线程历史库里数"我这轮干了多少"。

为什么有这个东西：框架原来只管 B（DeepSeek 余额）。真实项目里人的总花费是**两笔账**
（A 的 Codex + B 的 DeepSeek），只看得见一笔就等于没有预算控制。

2026-09-23 实测（`.trio/reports/readiness/peek_codex_thread.py`）：
`~/.codex/logs_2.sqlite` 里**没有任何 token/cost 列**，读不出钱；
但 `~/.codex/thread_history_1.sqlite` 的 `thread_turns` / `thread_items`
能数出**每轮时长与逐条动作**（`commandExecution` / `fileChange` / `reasoning` / `agentMessage` …）。
所以这份台账给的是**代理指标**——和 B 侧"事件量≈烧掉的钱"同一种东西，不是账单。

**只读**：以 `mode=ro` 打开，任何写入都会失败。

用法::

    python .trio/a_ledger.py                 # 最近 10 轮
    python .trio/a_ledger.py --turns 30 --json
    python .trio/a_ledger.py --thread 01a0cc03-7649-7c30-b3c0-18431eb6c490
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

CODEX_DIR = Path.home() / ".codex"
DB = CODEX_DIR / "thread_history_1.sqlite"
ROLLOUT_DIR = CODEX_DIR          # rollout-*.jsonl 在这棵树里的某处（用 rglob 找）


def connect() -> sqlite3.Connection:
    return sqlite3.connect("file:" + DB.as_posix() + "?mode=ro", uri=True, timeout=5)


def latest_thread(con: sqlite3.Connection) -> str | None:
    row = con.execute(
        "select thread_id from thread_turns order by started_at desc limit 1"
    ).fetchone()
    return row[0] if row else None


def ledger(thread: str, turns: int) -> dict:
    con = connect()
    try:
        rows = con.execute(
            "select turn_id, status, started_at, duration_ms from thread_turns "
            "where thread_id = ? order by started_at desc limit ?",
            (thread, turns),
        ).fetchall()
        per_turn = []
        for turn_id, status, started_at, duration_ms in reversed(rows):
            counts = Counter(
                item_type
                for (item_type,) in con.execute(
                    "select item_type from thread_items "
                    "where thread_id = ? and turn_id = ?",
                    (thread, turn_id),
                )
            )
            per_turn.append(
                {
                    "at": datetime.fromtimestamp(started_at).strftime("%H:%M:%S"),
                    "duration_s": round((duration_ms or 0) / 1000.0, 1),
                    "status": status,
                    "actions": counts.get("commandExecution", 0)
                    + counts.get("fileChange", 0)
                    + counts.get("mcpToolCall", 0)
                    + counts.get("collabAgentToolCall", 0),
                    "commands": counts.get("commandExecution", 0),
                    "file_changes": counts.get("fileChange", 0),
                    "reasoning": counts.get("reasoning", 0),
                    "messages": counts.get("agentMessage", 0),
                }
            )
    finally:
        con.close()
    totals = {
        key: sum(turn[key] for turn in per_turn)
        for key in ("duration_s", "actions", "commands", "file_changes", "reasoning", "messages")
    }
    return {"thread": thread, "turns": per_turn, "totals": totals, "database": str(DB)}


#: ``rollout-<时间戳>-<会话id>[_<thread_id>].jsonl`` —— 会话 id 与 thread_id
#: 都是带连字符的 UUID（不含 ``_``），所以按 ``_`` 切是安全的。
#:
#: ⚠ 尾部的 id **必须按 UUID 的固定形状**匹配，不能用 ``(.+)$`` 那种懒写法：
#: 时间戳本身也是"数字与连字符"，一个**全由数字组成的** UUID（十六进制里合法，
#: 概率约 1e-7）会让 ``[\d-]+`` 把 id 一起吞掉，于是这个会话的文件一个都收不到。
#: 自测里用全数字假 UUID 就是为了钉住这条（``test_rotate_a.py``）。
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ROLLOUT_NAME = re.compile(rf"rollout-.*?({_UUID}(?:_{_UUID})?)$")


def rollout_files(session_id: str) -> list[Path]:
    """这个 **app 会话** 在磁盘上的所有 rollout 文件（按文件名 = 时间排序）。

    一个会话会**换 rollout 文件续写**，新文件的 ``thread_id`` 跟会话 id 不一样。
    实测：会话 ``01a0cc03-…`` 有两段——``01a0cc03``（5 轮 / 5.85 MB）和
    ``01a0ccdb``（10 轮 / 3.74 MB）。真正的上下文是 **9.58 MB**，不是 5.85 MB。

    而且要看出来它是"换文件续写"而不是"压缩重写"：``rollout_ordinal`` 是**跨文件连续**的
    （``[1..1705]`` → ``[1703..3658]``）。压缩重写会让序号重新从 1 开始。
    这决定了聚合方式是**求和**——压缩的话求和就高估了。

    单个 rollout 时文件名里没有 ``_``，此时 thread_id 就是会话 id。
    """
    found: list[Path] = []
    if ROLLOUT_DIR.exists():
        for path in ROLLOUT_DIR.rglob("rollout-*.jsonl"):
            match = ROLLOUT_NAME.match(path.stem)
            if match and match.group(1).split("_")[0] == session_id:
                found.append(path)
    return sorted(found)


def session_threads(session_id: str) -> list[str]:
    """把上面那些 rollout 文件对应的 ``thread_id`` 收齐（``summary()`` 按它查库）。"""
    threads = set()
    for path in rollout_files(session_id):
        match = ROLLOUT_NAME.match(path.stem)
        if match:
            threads.add(match.group(1).split("_")[-1])
    return sorted(threads) or [session_id]


def summary(session_id: str) -> dict:
    """整条**会话**的累计量 + 上下文规模。这是 A 侧成本闸该看的量。

    > ⚠ **`context_bytes` 的口径**：各 rollout 文件里 ``rollout_end_byte_offset`` 的
    > **max 之后再求和**。不是 ``sum()``——那是对每轮的**累计偏移量**相加，毫无意义
    > （现有 ``ledger()`` 的 ``totals`` 就是这么干所有键的，所以 ``context_bytes``
    > **不能塞进那个键元组**）；也不是单文件的 max——会话换文件时会归零。
    """
    threads = session_threads(session_id)
    totals = dict.fromkeys(
        ("duration_s", "actions", "commands", "file_changes", "reasoning", "messages"), 0)
    context_bytes = 0
    turns = 0
    con = connect()
    try:
        for thread in threads:
            rows = con.execute(
                "select duration_ms, rollout_end_byte_offset from thread_turns where thread_id = ?",
                (thread,),
            ).fetchall()
            if not rows:
                continue
            turns += len(rows)
            totals["duration_s"] += round(sum((r[0] or 0) for r in rows) / 1000.0, 1)
            context_bytes += max((r[1] or 0) for r in rows)
            counts = Counter(
                item_type
                for (item_type,) in con.execute(
                    "select item_type from thread_items where thread_id = ?", (thread,))
            )
            totals["actions"] += (counts.get("commandExecution", 0)
                                  + counts.get("fileChange", 0)
                                  + counts.get("mcpToolCall", 0)
                                  + counts.get("collabAgentToolCall", 0))
            totals["commands"] += counts.get("commandExecution", 0)
            totals["file_changes"] += counts.get("fileChange", 0)
            totals["reasoning"] += counts.get("reasoning", 0)
            totals["messages"] += counts.get("agentMessage", 0)
    finally:
        con.close()
    return {"session": session_id, "threads": threads, "turns": turns,
            "context_bytes": context_bytes, "database": str(DB), **totals}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="A 侧（Codex）台账（只读）")
    parser.add_argument("--thread", help="线程 id（缺省：最近一轮所在的那个）")
    parser.add_argument("--session", help="**会话 id**（config.json 的 a_session）：按会话聚合，推荐")
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not DB.exists():
        print(f"找不到 {DB}")
        return 2

    if args.session:
        data = summary(args.session)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        print(f"A 侧台账（**会话** {args.session[:8]}…，跨 {len(data['threads'])} 个 rollout 文件；只读）")
        print(f"  轮次 {data['turns']} · 动作 {data['actions']}"
              f"（命令 {data['commands']} / 改文件 {data['file_changes']}）"
              f" · 墙钟 {data['duration_s']}s")
        print(f"  上下文 {data['context_bytes'] / 1e6:.2f} MB"
              f"（= 各 rollout 文件 max(rollout_end_byte_offset) 之和）")
        print("  注意：这是**代理指标**（动作数/时长/字节），不是账单。")
        return 0

    con = connect()
    try:
        thread = args.thread or latest_thread(con)
    finally:
        con.close()
    if not thread:
        print("这个库里没有任何线程")
        return 2

    data = ledger(thread, args.turns)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"A 侧台账（线程 {thread[:8]}…，来自 {DB.name}；**只读**）")
    print("  时刻      时长s  动作  命令  改文件  思考  消息  状态")
    for turn in data["turns"]:
        print(
            f"  {turn['at']}  {turn['duration_s']:>5}  {turn['actions']:>4}  "
            f"{turn['commands']:>4}  {turn['file_changes']:>6}  {turn['reasoning']:>4}  "
            f"{turn['messages']:>4}  {turn['status']}"
        )
    t = data["totals"]
    print(
        f"  合计：{t['duration_s']}s 墙钟、{t['actions']} 个动作"
        f"（命令 {t['commands']} / 改文件 {t['file_changes']}）、思考 {t['reasoning']} 条"
    )
    print("  注意：这是**代理指标**（动作数/时长），不是账单——本机读不出 Codex 的 token 费用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
