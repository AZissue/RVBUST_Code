#!/usr/bin/env python3
"""群总线：人 / A / B 三方**唯一**的通信通道。

设计要点（详见 ``DESIGN.md``）：

* **唯一通道**：三方都只经过这里。A 想撒手不管，得先绕过总线——而它绕不过去。
  第一条红线是「一个懒惰的 A 也必须被机制兜住」。
* **权限是机制，不是提示词**：``post()`` 会**拒绝**越权的 (角色, 类型) 组合并抛异常，
  而不是"在提示词里请求它不要这么做"。上一版的教训正是"纪律写在提示词里、
  后门（``Bash(python -c *)``）写死在白名单里"。
* **谁能唤醒谁**（红线，对应 Q13）::

      HUMAN  --只能唤醒-->  A        （B 永远收不到人的消息）
      A      --只有 task/kill 唤醒-->  B
      B      --任何发言唤醒-->  A
      SYSTEM --gate 事件唤醒-->  A

* **双轨**（对应 Q9）：
    - ``group.jsonl``：**语义节点**，给人看（接单/技术方案/交付/验收/闸/升级）。
    - ``raw/*.jsonl``：**全量事件流**，给 A 和审计读，不做任何美化。
  两条流不混用——给 A 读的不美化，给人看的也永不当数据源。

命令行（A / 人在 shell 里用）::

    python .trio/bus.py post --role A --kind note --text "..."
    python .trio/bus.py tail -n 20
    python .trio/bus.py wait --role A --since 12 --timeout 600   # 被唤醒
    python .trio/bus.py roles                                    # 看权限矩阵
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import sys
import time
from pathlib import Path

TRIO_DIR = Path(__file__).resolve().parent
LOG_DIR = TRIO_DIR / "log"
GROUP_LOG = LOG_DIR / "group.jsonl"
RAW_DIR = LOG_DIR / "raw"
CONFIG_PATH = TRIO_DIR / "config.json"

HUMAN, A, B, SYSTEM = "HUMAN", "A", "B", "SYSTEM"
ROLES = (HUMAN, A, B, SYSTEM)

# ---------------------------------------------------------------- 权限矩阵
# (角色, 类型) -> 允许？这是**边界**，不是纪律。
PERMISSIONS: dict[str, frozenset[str]] = {
    # 人：发言、掐断、贴证据。不能发任务书，不能"验收"。
    HUMAN: frozenset({"say", "kill", "evidence", "todo"}),
    # A：方案与验收负责人。能发任务、能验收、能升级、能掐断、能发言。
    #   不能发 plan/deliver（那是 B 的活）。
    A: frozenset({"say", "task", "verify", "escalate", "note", "kill", "todo"}),
    # B：实现工程师。能交技术方案、能交付、能发言。
    #   不能发 verify/escalate/task/kill——**判据权与验收权归 A 独占**。
    B: frozenset({"say", "plan", "deliver", "note"}),
    # 机械闸与路由器（不用模型）。
    SYSTEM: frozenset({"gate", "kill", "note", "escalate"}),
}

# 语义节点类型 -> 人看的中文标签
KIND_LABEL = {
    "say": "发言",
    "task": "任务书",
    "plan": "技术方案",
    "deliver": "交付",
    "verify": "验收",
    "gate": "机械闸",
    "kill": "掐断",
    "evidence": "证据",
    "escalate": "升级给人",
    "note": "记录",
    "todo": "待办",
}

DEFAULTS: dict[str, object] = {
    # ---- Q14 数值闸（按 DeepSeek 真实单价计，不用 CLI 那个高估 35 倍的估算值）
    "wall_seconds": 600,          # 单回合墙钟
    "session_cny": 3.0,           # 单会话总花费硬顶
    "task_cny": 1.5,              # 单任务花费硬顶
    # ---- 机械闸触发条件（router.py 消费）
    "repeat_threshold": 3,        # 同一命令/工具重复次数
    "no_progress_turns": 2,       # 连续多少个回合没有任何文件写入
    "escalate_after_failures": 2, # 同一任务连续失败几次就升级给人
    # ---- 升级给人的三件事（对应 Q12）
    "escalate_on_ambiguity": True,
    "escalate_on_boundary_breach": True,
    # ---- 驱动 B（Claude Code）
    "b_budget_usd": 1.0,          # 给 B 的回合内硬预算（claude 侧闸）
    "b_effort": "low",
    "b_permission_mode": "acceptEdits",
    # 白名单：**没有跑测试**，也没有验证/真机命令——跑起来看看的权力归 A。
    # 三个入口各自把身份/用途写死，取代上一版那把万能钥匙 `Bash(python -c *)`：
    #   check.py 只能 import 检查，as.py 只能是 B 在说话，py_compile 只能编译。
    "b_allowed_tools": (
        "Read,Glob,Grep,Edit,Write,"
        "Bash(python -m py_compile *),"
        "Bash(python .trio/check.py *),Bash(python .trio\\check.py *),"
        "Bash(python .trio/as.py b *),Bash(python .trio\\as.py b *)"
    ),
    # B 的工作集之外一律不可写入（由 A 在任务书里声明，router 校验）
    "group_port": 8761,
    # ---- A 侧（Codex）台账
    "test_baseline": None,        # 游戏侧既有测试的**记录在案**套数；None = 没标定，verify.py 会响亮地失败
    "a_rotate_actions": 350,      # 会话累计动作数到此就建议换会话
    "a_rotate_context_mb": 4.5,   # 会话累计上下文字节（MB）到此就建议换会话
}


def config() -> dict:
    """默认值 + ``.trio/config.json`` 覆盖。"""
    merged = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                merged.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    return merged


def update_config(**changes) -> tuple[dict, dict]:
    """**唯一**的 config.json 写入器。原子写，保键，写后自检。返回 (旧, 新)。

    为什么要有这个函数，而不是各处自己 ``write_text``：``config.json`` 坏掉的代价是**静默的**——
    ``config()`` 会把 ``JSONDecodeError`` 吞掉、回落到 ``DEFAULTS``，而 ``DEFAULTS`` 里
    **没有** ``a_session``，于是 ``wake_a`` 永远返回 False、B 交付再也没人唤醒 A。
    ``bus.py`` 里调用 ``wake_a`` 的那处又不看返回值。整条链上没有任何一步会报错。

    所以写入必须是**一个**实现，并且它自己负责证明写对了：

    1. 拒绝在 config.json 不存在时凭空造一份（``DEFAULTS`` 不含 ``a_session``，
       造出来的会比原来更坏）；
    2. 读整份 dict → 只改指定键 → **断言其余键值逐一未变**（``_`` 开头的注释键也在其中）；
    3. 先写临时文件再 ``os.replace``（原子；半截文件同样会被 ``config()`` 静默吞掉）；
    4. 写后重新读一遍，确认改动生效，否则抛错。

    ``encoding="utf-8"`` 是必须的：Windows 上不指定会写成 cp936，
    而 ``tests/test_group_ui_comes_up.py`` 用 utf-8 读 config.json，会直接红。
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"{CONFIG_PATH} 不存在——不做凭空创建（DEFAULTS 里没有 a_session）")
    before = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(before, dict):
        raise ValueError(f"{CONFIG_PATH} 的顶层不是对象，拒绝改")
    unknown = set(changes) - set(before)
    if unknown:
        raise KeyError(f"这些键不在 config.json 里，拒绝新增：{sorted(unknown)}")

    after = dict(before)
    after.update(changes)

    # 只允许改指定的键：其余键值逐一比对，不等就不写。
    for key, value in before.items():
        if key not in changes and after[key] != value:
            raise AssertionError(f"改动波及了无关的键 {key!r}，拒绝写")

    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)

    reread = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if reread.get(key) != value:
            raise AssertionError(f"写后自检失败：{key} 应为 {value!r}，实为 {reread.get(key)!r}")
    return before, after


# ---------------------------------------------------------------- 基础设施


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


@contextlib.contextmanager
def _exclusive(path: Path, timeout: float = 10.0):
    """跨进程互斥（Windows 上没有可靠的 flock，用锁文件）。"""
    lock = path.with_name(path.name + ".lock")
    deadline = time.time() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:
                    lock.unlink()          # 陈旧锁（进程被强杀）
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                raise TimeoutError(f"取锁超时：{lock}")
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock.unlink()


def can_post(role: str, kind: str) -> bool:
    """这个角色能不能发这种消息——**机制判断**，任何调用方都不能绕过。"""
    return kind in PERMISSIONS.get(role, frozenset())


# ---------------------------------------------------------------- 唤醒 A
#
# 2026-09-23 实测：`codex queue --thread <会话 id> --message <文本>` **真能投进正在跑的
# Codex 会话**——投出去的那条自测消息确实出现在 A 的会话里（队列里那条也随之消失）。
# 于是"A 被总线唤醒、而不是靠人敲回车"从**待验证前提**变成了机制。
#
# 两个 id 不是一回事（我自己搞混过一次）：
#   * 唤醒用 `config.json` 里的 ``a_session``：**app 的会话 id**（也是
#     ``~/.codex/visualizations/.../<id>`` 用的那个），`codex queue` 认它；
#   * `~/.codex/thread_history_1.sqlite` 里 ``thread_turns.thread_id`` 是**另一套 id**：
#     它带着 A 的用量/动作数据，但喂给 `codex queue` 会石沉大海。

#: 哪几类消息值得把 A 叫醒。B 的 `plan`/`say` 不叫——A 下一轮读群时自然会看到，
#: 每叫醒一次都要花 A 的额度。
WAKE_KINDS = frozenset({"deliver", "gate", "escalate", "kill"})

#: 测试里关掉（`run_all.py` 会设 TRIO_NO_WAKE=1，`test_bus.py` 也会显式关）。
WAKE_ENABLED = os.environ.get("TRIO_NO_WAKE") != "1"


def wake_a(reason: str, detail: str = "", message: dict | None = None) -> bool:
    """把 A 叫醒。失败只返回 False，**绝不抛**——唤醒失败不该影响消息落库。

    唤醒文本里带上**群里那条消息的 seq 与 task**：A 醒来先看 seq 就知道
    "这条我是不是已经处理过了"。（2026-09-23 真踩到：T-011 的交付我在同一轮里
    已经验收完，那条唤醒照样投了过来——没有 seq 的话，A 只能重新读一遍群才知道是重复的。）
    """
    if not WAKE_ENABLED:
        return False
    cfg = config()
    session = cfg.get("a_session")
    if not session:
        return False
    command = cfg.get("a_wake_cmd") or "codex"
    text = f"[总线唤醒] {reason}"
    if message:
        seq = message.get("seq")
        task = message.get("task")
        text = f"[总线唤醒] seq={seq}"
        if task:
            text += f" task={task}"
        text += f" {reason}"
    if detail:
        text += f"：{detail}"
    try:
        import subprocess

        proc = subprocess.run(
            [command, "queue", "--thread", session, "--message", text],
            capture_output=True, text=True, timeout=30,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def wake_targets(message: dict) -> list[str]:
    """这条消息能唤醒谁。红线：HUMAN 永远唤不醒 B。"""
    role, kind = message.get("role"), message.get("kind")
    if role == HUMAN:
        return [A]
    if role == A:
        return [B] if kind in ("task", "kill") else []
    if role == B:
        return [A]
    if role == SYSTEM:
        return [A] if kind in ("gate", "escalate") else []
    return []


# ---------------------------------------------------------------- 读写


def post(
    role: str,
    kind: str,
    text: str,
    task: str | None = None,
    refs: list[str] | None = None,
    meta: dict | None = None,
) -> dict:
    """往群里发一条**语义节点**。越权直接抛 PermissionError，不静默降级。"""
    if role not in ROLES:
        raise PermissionError(f"未知角色：{role!r}（只允许 {ROLES}）")
    if not can_post(role, kind):
        allowed = sorted(PERMISSIONS.get(role, frozenset()))
        raise PermissionError(
            f"角色 {role} 不能发 {kind!r}。它只能发：{allowed}"
            + ("（判据权与验收权归 A 独占）" if role == B else "")
        )
    ensure_dirs()
    with _exclusive(GROUP_LOG):
        seq = _last_seq_unlocked() + 1
        message = {
            "seq": seq,
            "ts": now_iso(),
            "role": role,
            "kind": kind,
            "task": task,
            "text": text,
            "refs": list(refs or []),
            "meta": dict(meta or {}),
        }
        with GROUP_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")

    # 这条消息该不该把 A 叫醒？——叫醒是**投递之后**的事，失败不影响落库。
    # 只有"确实指向 A"且属于值得打断的那几类才叫（见 WAKE_KINDS 的注释）。
    if A in wake_targets(message) and kind in WAKE_KINDS:
        wake_a(f"{role}/{kind}", text[:120], message=message)
    return message


def _last_seq_unlocked() -> int:
    if not GROUP_LOG.exists():
        return 0
    last = 0
    with GROUP_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line).get("seq", last)
            except json.JSONDecodeError:
                continue
    return last


def last_seq() -> int:
    ensure_dirs()
    return _last_seq_unlocked()


def read(since: int = 0, limit: int | None = None) -> list[dict]:
    """读出 seq > since 的所有消息（按 seq 升序）。"""
    ensure_dirs()
    out: list[dict] = []
    if not GROUP_LOG.exists():
        return out
    with GROUP_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("seq", 0) > since:
                out.append(message)
    return out[-limit:] if limit else out


def tail(count: int = 20) -> list[dict]:
    messages = read(0)
    return messages[-count:]


def tasks() -> list[str]:
    seen: list[str] = []
    for message in read(0):
        task = message.get("task")
        if task and task not in seen:
            seen.append(task)
    return seen


# ---------------------------------------------------------------- 待办


TODO_KIND = "todo"


def open_todos() -> list[dict]:
    """还没勾掉的待办。

    规则（故意做得极简，机制上不依赖群界面）：

    * 发一条 ``kind=todo``、不带 ``meta.todo_id`` 的 = **新建**一条待办，它的 id 就是自己的 seq；
    * 发一条 ``kind=todo``、带 ``meta.todo_id`` 的 = **更新**那条待办，
      带 ``meta.done=true`` 就是勾掉。

    于是"人的待办"有了落脚点：A 写、人看得见、人做完勾掉，**而且不靠 A 记性**——
    A 换会话、被压缩，`as.py`/群界面照样能列出还欠着谁什么。
    """
    state: dict[str, dict] = {}
    for message in read(0):
        if message.get("kind") != TODO_KIND:
            continue
        meta = message.get("meta") or {}
        todo_id = str(meta.get("todo_id") or message.get("seq"))
        state[todo_id] = {
            "todo_id": todo_id,
            "seq": message.get("seq"),
            "role": message.get("role"),
            "task": message.get("task"),
            "text": message.get("text"),
            "ts": message.get("ts"),
            "done": bool(meta.get("done")),
            "done_by": message.get("role") if meta.get("done") else None,
        }
    return [item for item in state.values() if not item["done"]]


# ---------------------------------------------------------------- 全量事件流（给 A / 审计）


def append_raw(stream: str, payload) -> None:
    """把原始事件按行追加到 ``raw/<stream>.jsonl``——**不做任何美化**。"""
    ensure_dirs()
    if isinstance(payload, str):
        line = payload
    else:
        line = json.dumps(payload, ensure_ascii=False)
    path = RAW_DIR / f"{stream}.jsonl"
    with _exclusive(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip("\n") + "\n")


def read_raw(stream: str, since: int = 0, limit: int | None = None) -> list[dict | str]:
    path = RAW_DIR / f"{stream}.jsonl"
    if not path.exists():
        return []
    out: list[dict | str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if index < since:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append(line)
    return out[-limit:] if limit else out


# ---------------------------------------------------------------- 唤醒


def wait_for(role: str, since: int, timeout: float) -> dict | None:
    """阻塞等待一条能唤醒 ``role`` 的消息。超时返回 None。"""
    if role not in ROLES:
        raise ValueError(f"未知角色：{role!r}")
    deadline = time.time() + timeout
    cursor = since
    while True:
        for message in read(cursor):
            cursor = message.get("seq", cursor)
            if role in wake_targets(message):
                return message
        if time.time() > deadline:
            return None
        time.sleep(0.5)


# ---------------------------------------------------------------- 命令行


def _render(message: dict) -> str:
    label = KIND_LABEL.get(message.get("kind", ""), message.get("kind", "?"))
    task = f" [{message['task']}]" if message.get("task") else ""
    stamp = str(message.get("ts", ""))[11:19]
    return (
        f"#{message.get('seq'):<4} {stamp} {message.get('role'):<6} "
        f"{label:<8}{task} {message.get('text', '')}"
    )


def main(argv=None) -> int:
    # Windows 控制台默认 GBK，群里一条带 ¥ 的消息就能让 tail 崩在半路
    # （UnicodeEncodeError: 'gbk' codec can't encode character '\xa5'）。
    # 人要靠这个命令看群，它不能因为一个字符就死。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="三方群总线")
    sub = parser.add_subparsers(dest="command", required=True)

    p_post = sub.add_parser("post", help="发一条消息")
    p_post.add_argument("--role", required=True, choices=ROLES)
    p_post.add_argument("--kind", required=True)
    p_post.add_argument("--text", required=True)
    p_post.add_argument("--task")
    p_post.add_argument("--ref", action="append", default=[])

    p_read = sub.add_parser("read", help="读消息")
    p_read.add_argument("--since", type=int, default=0)
    p_read.add_argument("--limit", type=int)

    p_tail = sub.add_parser("tail", help="看最后几条")
    p_tail.add_argument("-n", type=int, default=20)

    p_wait = sub.add_parser("wait", help="等一条能唤醒该角色的消息")
    p_wait.add_argument("--role", required=True, choices=ROLES)
    p_wait.add_argument("--since", type=int, default=0)
    p_wait.add_argument("--timeout", type=float, default=600.0)

    sub.add_parser("roles", help="打印权限矩阵与唤醒规则")
    p_todos = sub.add_parser("todos", help="列出还没勾掉的待办")
    p_todos.add_argument("--all", action="store_true", help="连已完成的也列")
    p_raw = sub.add_parser("raw", help="看全量事件流")
    p_raw.add_argument("stream")
    p_raw.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    ensure_dirs()

    if args.command == "post":
        try:
            message = post(
                args.role, args.kind, args.text, task=args.task, refs=args.ref
            )
        except PermissionError as exc:
            print(f"[拒绝] {exc}", file=sys.stderr)
            return 3
        print(_render(message))
        return 0

    if args.command == "read":
        for message in read(args.since, args.limit):
            print(_render(message))
        return 0

    if args.command == "todos":
        items = open_todos()
        if not items:
            print("[待办] 没有未完成的待办")
            return 0
        for item in items:
            task = f" [{item['task']}]" if item.get("task") else ""
            print(f"#{item['todo_id']:<4} {item['role']:<6} {item.get('ts', '')[11:19]}{task} {item['text']}")
        return 0

    if args.command == "tail":
        for message in tail(args.n):
            print(_render(message))
        return 0

    if args.command == "wait":
        message = wait_for(args.role, args.since, args.timeout)
        if message is None:
            print("[超时] 没有能唤醒本角色的消息", file=sys.stderr)
            return 4
        print(json.dumps(message, ensure_ascii=False))
        return 0

    if args.command == "raw":
        for item in read_raw(args.stream, limit=args.limit):
            print(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))
        return 0

    if args.command == "roles":
        print("权限矩阵（谁能发什么）：")
        for role in ROLES:
            print(f"  {role:<6} {sorted(PERMISSIONS[role])}")
        print("\n唤醒规则（谁能叫醒谁）：")
        print("  HUMAN  -> A            （红线：B 永远收不到人的消息）")
        print("  A      -> B  仅限 task / kill")
        print("  B      -> A           （B 的任何发言都唤醒 A）")
        print("  SYSTEM -> A  仅限 gate / escalate")
        print("\n硬边界：B 不得发 verify / escalate / task / kill —— 判据权与验收权归 A 独占。")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
