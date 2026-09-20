#!/usr/bin/env python3
"""实时工作视图（只读，**单窗口合并视图**）。

把两个 agent 的动作放在**同一根时间轴**上，用固定角色的前缀区分"谁在干什么"：

```
15:24:03 CLAUDE | [TOOL] Edit: snake/audio.py
15:31:00 CODEX  | 验收：173 tests OK，回灌 inbox/003
```

数据源（都只读、不改任何东西）：

* CLAUDE：最新的 ``.pair/logs/turn-*.stream.jsonl``（Claude Code 的事件流，
  跳过 thinking 噪声，只留文本 / 工具调用 / 工具结果 / 回合结束）
* CODEX：``.pair/logs/codex.live.log``（Codex 自己追加的工作记录）

参数 ``--role all``（默认）＝合并；``--role claude|codex`` ＝只看一侧。
Ctrl+C 退出。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / ".pair" / "logs"
CODEX_LOG = LOG_DIR / "codex.live.log"

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREY = "\033[90m"

CLOCK_RE = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")


def enable_ansi() -> None:
    if os.name == "nt":
        os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def clip(value, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def now_clock() -> str:
    return time.strftime("%H:%M:%S")


def event_clock(obj: dict) -> str:
    """事件自带的时间戳（UTC -> 本地），没有就用当前时间。"""
    raw = obj.get("timestamp")
    if isinstance(raw, str) and raw:
        try:
            moment = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return moment.astimezone().strftime("%H:%M:%S")
        except ValueError:
            pass
    return now_clock()


def describe_tool(block: dict) -> str:
    name = block.get("name", "?")
    data = block.get("input") or {}
    detail = ""
    for key in ("file_path", "path", "command", "pattern", "query", "url"):
        if data.get(key):
            detail = clip(data[key], 120)
            break
    if not detail and data:
        detail = clip(json.dumps(data, ensure_ascii=False), 120)
    return f"{name}: {detail}" if detail else name


def structured_claude_entries(obj: dict) -> list:
    """一个 stream-json 事件 -> [(clock, kind, 纯文本)]（跳过 thinking 等噪声）。

    kind ∈ {``sys``, ``text``, ``tool``, ``res``, ``err``, ``done``}；
    终端渲染（ANSI）和浏览器页面（HTML）都基于这一份解析，避免两套逻辑走偏。
    """
    kind = obj.get("type")
    clock = event_clock(obj)
    out = []

    if kind == "system":
        if obj.get("subtype") == "init":
            out.append(
                (
                    clock,
                    "sys",
                    f"会话开始 model={obj.get('model')} "
                    f"mode={obj.get('permissionMode')} "
                    f"session={str(obj.get('session_id'))[:8]}",
                )
            )
        return out

    if kind == "assistant":
        for block in (obj.get("message") or {}).get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text = clip(block.get("text", ""), 260)
                if text:
                    out.append((clock, "text", text))
            elif btype == "tool_use":
                out.append((clock, "tool", f"[TOOL] {describe_tool(block)}"))
        return out

    if kind == "user":
        for item in (obj.get("message") or {}).get("content") or []:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                failed = item.get("is_error")
                flag = "ERROR" if failed else "ok"
                out.append(
                    (
                        clock,
                        "err" if failed else "res",
                        f"[RESULT] {flag}: {clip(item.get('content'), 130)}",
                    )
                )
        return out

    if kind == "result":
        subtype = obj.get("subtype")
        out.append(
            (
                clock,
                "done",
                f"[DONE] subtype={subtype} turns={obj.get('num_turns')} "
                f"costUSD(估算)={obj.get('total_cost_usd')} "
                f"{obj.get('duration_ms')}ms",
            )
        )
        return out

    return out


KIND_COLORS = {
    "sys": GREY,
    "text": GREEN,
    "tool": GREY,
    "res": DIM,
    "err": RED,
    "done": CYAN,
}


def claude_entries(obj: dict) -> list:
    """一个 stream-json 事件 -> [(clock, 带 ANSI 的文本)]。"""
    rendered = []
    for clock, kind, text in structured_claude_entries(obj):
        color = KIND_COLORS.get(kind, RESET)
        bold = BOLD if kind == "done" else ""
        rendered.append((clock, f"{color}{bold}{text}{RESET}"))
    return rendered


def newest_turn_file():
    candidates = sorted(
        LOG_DIR.glob("turn-*.stream.jsonl"), key=lambda p: p.stat().st_mtime
    )
    return candidates[-1] if candidates else None


class Source:
    """跟踪一个文件：只读新增的完整行，顺便把文件切换记下来。"""

    def __init__(self, picker, label: str):
        self.picker = picker
        self.label = label
        self.path = None
        self.offset = 0
        self.buffer = b""
        self.notice = None

    def poll(self):
        """返回 [(clock, 已渲染文本)]，可能包含"切换文件"的提示行。"""
        target = self.picker()
        lines = []
        if target != self.path:
            self.path = target
            self.offset = 0
            self.buffer = b""
            if target is not None:
                lines.append((now_clock(), f"{DIM}-- 跟踪 {target.name} --{RESET}"))
        if self.path is None or not self.path.exists():
            return lines

        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except OSError:
            return lines

        if not chunk:
            return lines
        self.buffer += chunk
        pieces = self.buffer.split(b"\n")
        self.buffer = pieces.pop()
        for raw in pieces:
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                lines.extend(self.decode(text))
        return lines

    def decode(self, text: str):
        raise NotImplementedError


class ClaudeSource(Source):
    def decode(self, text: str):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        return claude_entries(payload)


class CodexSource(Source):
    def decode(self, text: str):
        match = CLOCK_RE.search(text)
        clock = match.group(1) if match else now_clock()
        body = CLOCK_RE.sub("", text, count=1).strip()
        body = body.replace("[CODEX]", "", 1).strip()
        return [(clock, f"{MAGENTA}{body}{RESET}")]


def render_line(clock: str, role: str, text: str) -> str:
    if role == "CLAUDE":
        tag = f"{GREEN}{BOLD}CLAUDE{RESET}"
    elif role == "CODEX ":
        tag = f"{MAGENTA}{BOLD}CODEX {RESET}"
    else:
        tag = f"{GREY}{role}{RESET}"
    return f"{GREY}{clock}{RESET} {tag} {DIM}|{RESET} {text}"


def settle(entries) -> None:
    """按时间排序后打印这一批事件。"""
    for clock, role, text in sorted(entries, key=lambda item: item[0]):
        print(render_line(clock, role, text), flush=True)


def build_sources(role: str):
    sources = []
    if role in ("all", "claude"):
        sources.append(("CLAUDE", ClaudeSource(newest_turn_file, "claude")))
    if role in ("all", "codex"):
        sources.append(
            ("CODEX ", CodexSource(lambda: CODEX_LOG if CODEX_LOG.exists() else None, "codex"))
        )
    return sources


def follow(role: str) -> None:
    title = {
        "all": "Codex x Claude 实时工作（合并视图）",
        "claude": "CLAUDE 实时工作流",
        "codex": "CODEX 实时工作流",
    }[role]
    print(f"{CYAN}{BOLD}== {title} =={RESET}")
    print(
        f"{GREY}   CLAUDE 源: .pair/logs/turn-*.stream.jsonl    "
        f"CODEX 源: .pair/logs/codex.live.log    (只读，Ctrl+C 退出){RESET}"
    )

    sources = build_sources(role)
    idle_notice = False
    while True:
        batch = []
        for label, source in sources:
            for clock, text in source.poll():
                batch.append((clock, label, text))
        if batch:
            settle(batch)
            idle_notice = False
        elif not idle_notice:
            print(f"{GREY}{now_clock()}      | （等待新事件…）{RESET}", flush=True)
            idle_notice = True
        time.sleep(0.35)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex x Claude 实时工作合并视图（只读）")
    parser.add_argument(
        "--role", choices=("all", "claude", "codex"), default="all"
    )
    args = parser.parse_args()
    enable_ansi()
    try:
        follow(args.role)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
