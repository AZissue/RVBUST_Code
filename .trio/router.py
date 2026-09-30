#!/usr/bin/env python3
"""路由器：机械闸 + B 的驱动。**不调用任何模型。**

对应 DESIGN.md 的"两道闸"里的第一道：

    机械闸（这里，不用模型、瞬时生效）
        │  发现异常 → 立刻停掉 B，并往群里发 SYSTEM/gate 唤醒 A
        ▼
    判断闸（在 A 里）
           回灌重试 / 换策略 / 升级给人

**分工不可倒置**：路由器只负责"发现异常并立刻停"，"接下来怎么办"永远由 A 决定。
这样"一个懒惰的 A"也拦不住机械闸——第一条红线就是这么落地的。

四条触发条件：

1. 同一命令 / 只读动作重复 ≥ ``repeat_threshold`` 次（Bash 命令、Read/Grep/Glob 的路径）
2. 连续 ``no_progress_actions`` 次动作没有任何文件写入（Edit/Write 才算写入）
3. 单回合墙钟 > ``wall_seconds``
4. 真实花费超过 ``task_cny`` / ``session_cny``（DeepSeek 余额差值，不是 CLI 的估算值）

命令行::

    # 真的驱动 B 跑一个任务
    python .trio/router.py drive --task T-001 --brief .trio/tasks/T-001.md

    # 零花费自检：把历史事件流喂给机械闸，看它会不会触发
    python .trio/router.py replay --stream .pair/logs/turn-001.stream.jsonl

    # 只验管道，不起任何进程
    python .trio/router.py drive --task T-001 --brief ... --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bus  # noqa: E402

try:  # A 侧台账（只读 Codex 自己的线程历史库）；读不到也不影响驱动
    import a_ledger  # noqa: E402
except Exception:  # pragma: no cover
    a_ledger = None

TRIO_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRIO_DIR.parent
REPORT_DIR = TRIO_DIR / "reports"
KILL_FLAG = bus.LOG_DIR / "kill.flag"
SPEND_FILE = bus.LOG_DIR / "spend.json"
SESSION_FILE = bus.LOG_DIR / "b-session"
LIVE_FILE = bus.LOG_DIR / "live.json"  # 实时活动条的唯一数据源（丢了不影响任何判定）
#: A 侧台账的**基线**：上一轮看到哪儿了。跑出来的、丢了不影响判定（丢了就当首次）。
A_LEDGER_FILE = bus.LOG_DIR / "a_ledger.json"

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}

#: 不算"真动作"的事件：流式的思考增量。一轮能顶几千条——2026-09-23 在本仓库实测
#: `b-T-005.jsonl` 14176 条里 13943 条（98.2%）是它、`b-T-006.jsonl` 3768/3847（97.9%）；
#: 而它对应的钱极少（知识库 2026-09-22 实测：被掐断那轮 8039 条里 8024 条是它，只花 ¥0.03）。
#: 拿它当"烧钱"的代理，等于拿"思考多久"当"花了多少"。
THINKING_SUBTYPES = ("thinking_tokens", "thinking")


def is_thinking_delta(event: dict) -> bool:
    """这条事件是不是流式思考增量（不算进事件量闸）。"""
    subtype = str(event.get("subtype") or "")
    return any(marker in subtype for marker in THINKING_SUBTYPES)


# ---------------------------------------------------------------- 基础设施


def clock() -> str:
    return time.strftime("%H:%M:%S")


def deepseek_balance() -> float | None:
    """真实余额（CNY）。读本地 Claude 配置里的 token，**绝不打印它**。"""
    try:
        settings = json.loads(
            (Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        token = (settings.get("env") or {}).get("ANTHROPIC_AUTH_TOKEN")
        if not token:
            return None
        request = urllib.request.Request(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        infos = payload.get("balance_infos") or []
        if not infos:
            return None
        return float(infos[0].get("total_balance", "nan"))
    except Exception:
        return None


def resolve_claude_launcher(explicit: str) -> list:
    """解析 Claude Code 的启动方式（沿用 .pair/run-turn.py 里验证过的做法）。

    Windows 上 PATH 里的 ``claude`` 是 npm 垫片，subprocess 不能直接执行，
    所以优先找垫片背后的原生 exe。
    """
    if explicit and explicit != "claude":
        return [explicit]

    shim = shutil.which("claude") or shutil.which("claude.cmd")
    candidates = []
    if shim:
        shim_path = Path(shim)
        candidates.append(shim_path.with_suffix(".exe"))
        cmd_shim = shim_path.with_suffix(".cmd")
        if cmd_shim.exists():
            try:
                text = cmd_shim.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"([A-Za-z]:\\[^\"]*claude\.exe)", text)
                if match:
                    candidates.append(Path(match.group(1)))
            except OSError:
                pass
        candidates.append(
            shim_path.parent
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "bin"
            / "claude.exe"
        )
    for candidate in candidates:
        if candidate and candidate.exists():
            return [str(candidate)]
    if shim:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", shim]
    return ["claude"]


# ---------------------------------------------------------------- 机械闸


def tool_fingerprint(block: dict) -> str:
    """把一个工具调用压成用于"重复计数"的指纹。"""
    name = block.get("name", "?")
    data = block.get("input") or {}
    if name == "Bash":
        return f"Bash: {' '.join(str(data.get('command', '')).split())}"
    for key in ("file_path", "path", "pattern"):
        if data.get(key):
            return f"{name}: {data[key]}"
    return name


def describe_action(block: dict) -> str:
    """把一次工具调用压成一行人话，给群界面的实时活动条看。"""
    name = block.get("name", "?")
    data = block.get("input") or {}
    if name == "Bash":
        return f"Bash  {str(data.get('command') or '')[:70]}"
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = str(data.get("file_path") or data.get("notebook_path") or "")
        return f"{name}  {path.replace(str(REPO_ROOT) + os.sep, '')[:70]}"
    if name in ("Grep", "Glob"):
        return f"{name}  {str(data.get('pattern') or '')[:50]}"
    return f"{name}  {str(data)[:60]}"


class GateWatcher:
    """机械闸。只看事件流，不理解语义——所以它不会被说服、不会疲劳。"""

    def __init__(self, cfg: dict, task: str, started: float | None = None):
        self.task = task
        self.repeat_threshold = int(cfg.get("repeat_threshold", 3))
        # 两级：先软告警（不掐断，只让 A 知道），再硬掐断
        self.no_progress_warn = int(cfg.get("no_progress_warn", 12))
        self.no_progress_actions = int(cfg.get("no_progress_actions", 30))
        self.wall_seconds = float(cfg.get("wall_seconds", 600))
        self.task_cny = float(cfg.get("task_cny", 1.5))
        self.session_cny = float(cfg.get("session_cny", 3.0))
        self.counts: dict[str, int] = {}
        self.actions = 0
        self.no_write_streak = 0
        # 事件量闸：**事件数≈烧掉的钱**（turn-001 有 22620 个事件、只有 12 次工具调用）。
        # 动作数看不出的空转，这一对看得见。
        self.stall_events_warn = int(cfg.get("stall_events_warn", 2000))
        self.stall_events_kill = int(cfg.get("stall_events_kill", 8000))
        self.events_since_write = 0
        self.round_started = started if started is not None else time.time()
        self.fired: dict | None = None
        self.timeline: list[dict] = []
        self.warnings: list[dict] = []
        self._warned = False
        self._stall_warned = False
        # 活动条用：最近一次工具调用、最后一次写入的时刻、总事件数
        self.last_action: str | None = None
        self.last_write_at: float | None = None
        self.events = 0
        self.warn_log: list[dict] = []

    # ---- 事件

    def pop_warnings(self) -> list[dict]:
        """取出软告警（不掐断，交给调用方往群里发，让 A 看见）。"""
        out, self.warnings = self.warnings, []
        return out

    def observe(self, event: dict) -> dict | None:
        """喂一个 stream-json 事件；返回触发原因（若这一刻触发）。"""
        if event.get("type") == "result":
            self.round_started = time.time()
            return None

        self.events += 1
        # 思考增量不计入事件量闸（见 is_thinking_delta）
        if not is_thinking_delta(event):
            self.events_since_write += 1
        if self.stall_events_kill and self.events_since_write >= self.stall_events_kill:
            return self._fire(
                "stall-events",
                f"距上次文件写入已累积 {self.events_since_write} 个事件（≈烧掉的钱）",
            )
        if (
            self.stall_events_warn
            and self.events_since_write >= self.stall_events_warn
            and not self._stall_warned
        ):
            self._stall_warned = True
            self.warnings.append(
                {
                    "reason": "stall-events-warn",
                    "detail": (
                        f"距上次文件写入已累积 {self.events_since_write} 个事件"
                        f"（硬闸在 {self.stall_events_kill}）"
                    ),
                    "at": clock(),
                    "actions": self.actions,
                }
            )
            self.warn_log.append(self.warnings[-1])

        if event.get("type") != "assistant":
            return None

        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") != "tool_use":
                continue
            self.actions += 1
            name = block.get("name", "?")
            fingerprint = tool_fingerprint(block)
            self.last_action = describe_action(block)

            if name in WRITE_TOOLS:
                self.events_since_write = 0
                self._stall_warned = False
                self.no_write_streak = 0
                self._warned = False
                self.last_write_at = time.time()
            else:
                self.no_write_streak += 1
                # 只对"命令"和"只读探查"计重复；反复编辑同一个文件是正常工作，不算
                if name == "Bash" or name in READ_TOOLS:
                    self.counts[fingerprint] = self.counts.get(fingerprint, 0) + 1
                    if self.counts[fingerprint] >= self.repeat_threshold:
                        return self._fire(
                            "repeat",
                            f"同一动作重复 {self.counts[fingerprint]} 次：{fingerprint}",
                        )
                # 第一级：软告警。只告诉 A "B 已经读了很多次、一个字没写"，不掐断——
                # 稍大的任务本来就需要先读一批文件，一刀切会误杀。
                if (
                    not self._warned
                    and self.no_write_streak >= self.no_progress_warn
                    and self.no_progress_warn < self.no_progress_actions
                ):
                    self._warned = True
                    self.warnings.append(
                        {
                            "reason": "no-progress-warn",
                            "detail": (
                                f"连续 {self.no_write_streak} 次动作没有任何文件写入"
                                f"（硬闸在 {self.no_progress_actions} 次）"
                            ),
                            "at": clock(),
                            "actions": self.actions,
                        }
                    )
                    self.warn_log.append(self.warnings[-1])
                # 第二级：硬掐断。
                if self.no_write_streak >= self.no_progress_actions:
                    return self._fire(
                        "no-progress",
                        f"连续 {self.no_write_streak} 次动作没有任何文件写入",
                    )
        return None

    # ---- 时间与花费（由主循环轮询）

    def check_wall(self) -> dict | None:
        elapsed = time.time() - self.round_started
        if self.wall_seconds and elapsed > self.wall_seconds:
            return self._fire("wall", f"单回合墙钟 {elapsed:.0f}s > {self.wall_seconds:.0f}s")
        return None

    def check_cost(self, spent_task: float | None, spent_session: float | None) -> dict | None:
        if spent_task is not None and self.task_cny and spent_task > self.task_cny:
            return self._fire(
                "cost-task", f"本任务真实花费 ¥{spent_task:.2f} > ¥{self.task_cny:.2f}"
            )
        if spent_session is not None and self.session_cny and spent_session > self.session_cny:
            return self._fire(
                "cost-session",
                f"本轮需求累计真实花费 ¥{spent_session:.2f} > ¥{self.session_cny:.2f}"
                "（量的是账户级余额差，别处的 DeepSeek 用量也会算进来）",
            )
        return None

    def _fire(self, reason: str, detail: str) -> dict:
        verdict = {
            "reason": reason,
            "detail": detail,
            "at": clock(),
            "actions": self.actions,
            "elapsed": round(time.time() - self.round_started, 1),
        }
        if self.fired is None:
            self.fired = verdict
            self.timeline.append(verdict)
        return verdict


# ---------------------------------------------------------------- 花费台账


def load_spend() -> dict:
    if SPEND_FILE.exists():
        try:
            return json.loads(SPEND_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"started": bus.now_iso(), "start_balance": None, "tasks": {}}


def save_spend(data: dict) -> None:
    bus.ensure_dirs()
    SPEND_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def session_spent(balance: float | None) -> float | None:
    data = load_spend()
    start = data.get("start_balance")
    if balance is None or start is None:
        return None
    return round(float(start) - balance, 4)


def a_ledger_snapshot() -> dict | None:
    """A 侧（Codex）的**会话级**台账快照。读不到就返回 None——**绝不影响驱动**。

    ⚠ 这里**必须**按 `config.json` 的 `a_session` 聚合，**不能用 `a_ledger.latest_thread()`**：
    后者返回的是 Codex 线程库里"最近活动过的任意线程"，横跨本机所有项目。2026-09-23 实测
    会话 `01a0cc03` 跨 2 个 rollout 文件（`01a0cc03` 5.85 MB + `01a0ccdb` 3.74 MB），
    单 thread 口径只看得见前者，而且**恰好在换文件那一刻归零**——那正是最该报警的时候。

    `a_session` 本身就是合法的 `thread_id`（实测匹配 5 轮），会话 id 与 thread id 都是带
    连字符的 UUID，所以按会话前缀在 rollout 文件名里找是安全的（见 `a_ledger.session_threads`）。
    """
    if a_ledger is None:
        return None
    try:
        session = bus.config().get("a_session")
        if not session:
            return None
        data = a_ledger.summary(str(session))
        return {
            "session": data["session"],
            "threads": data["threads"],
            "turns": data["turns"],
            "context_bytes": data["context_bytes"],
            "actions": data["actions"],
            "commands": data["commands"],
            "file_changes": data["file_changes"],
            "duration_s": data["duration_s"],
        }
    except Exception:  # noqa: BLE001 - 台账读不到不该拖累任何一次 drive
        return None


def report_a_ledger(snapshot: dict | None) -> list[str]:
    """把 A 侧台账的**增量**与**过阈值**提示算出来。返回给 A 看的几行（可能为空）。

    为什么要有基线文件：`summary()` 给的是**会话累计**，直接看它只会看到 9.58 MB 这个
    静态数字，答不出"这轮 drive 之间 A 又涨了多少"。相邻两轮相减才是可行动的信息。

    为什么同时发群：人只能靠浏览器页看见（`serve.py` 的 `/api/live`）。
    用 `note` 而**不是** `escalate`——`note` 不唤醒任何人，不会为"提醒换会话"再烧 A 一次额度。
    """
    if not snapshot:
        return []
    bus.ensure_dirs()
    previous = None
    if A_LEDGER_FILE.exists():
        try:
            previous = json.loads(A_LEDGER_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None

    lines: list[str] = []
    cfg = bus.config()
    mb = snapshot["context_bytes"] / 1e6
    delta_mb = delta_actions = None
    if previous and previous.get("session") == snapshot["session"]:
        delta_mb = mb - float(previous.get("context_bytes") or 0) / 1e6
        delta_actions = snapshot["actions"] - int(previous.get("actions") or 0)
        lines.append(
            f"A 侧台账：会话累计 {mb:.2f} MB / {snapshot['actions']} 动作"
            f"（这两轮之间 +{delta_mb:.2f} MB / +{delta_actions} 动作）"
        )
    elif previous:
        # 会话变了 = 人轮换过了（或 A 自己换了）。基线必须重置，否则增量是个负数。
        lines.append(
            f"A 侧台账：**检测到新会话** {snapshot['session'][:8]}…"
            f"（旧会话 {str(previous.get('session'))[:8]}…，基线已重置）"
            f"，当前 {mb:.2f} MB / {snapshot['actions']} 动作"
        )
    else:
        lines.append(f"A 侧台账：会话 {mb:.2f} MB / {snapshot['actions']} 动作（首次记录）")

    # 阈值：过了才提示。**不自动轮换**——轮换要开新会话、要接 todo，那是 A 和人做的决定，
    # 框架只负责把数摆出来（框架替 A 做决定 = 越权，见 DESIGN）。
    limit_mb = float(cfg.get("a_rotate_context_mb") or 0)
    limit_actions = int(cfg.get("a_rotate_actions") or 0)
    over = []
    if limit_mb and mb >= limit_mb:
        over.append(f"上下文 {mb:.2f} MB ≥ {limit_mb} MB")
    if limit_actions and snapshot["actions"] >= limit_actions:
        over.append(f"动作 {snapshot['actions']} ≥ {limit_actions}")
    hint = None
    if over:
        hint = (
            "**该轮换 A 的会话了**（" + "、".join(over) + "）："
            "收尾发 `python .trio/as.py a --kind todo --text \"…\" --ref reports/<任务>/verify.json`，"
            "然后 `python .trio/router.py rotate-a` 换到新会话，新会话第一件事读群 `todos`。"
        )
        lines.append(hint)

    A_LEDGER_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    for line in lines:
        print(f"[a_ledger] {line}")
    if hint:
        # 群界面那条**不带 `[a_ledger]` 前缀**——它是给人看的一句话，不是给 A 看的日志行。
        bus.post(bus.SYSTEM, "note", f"A 侧成本提醒：{hint}")
    return lines


# ---------------------------------------------------------------- 换 A 的会话


#: Codex app 的会话总表（**机器全局**——横跨本机所有项目，所以不能盲取最新）。
CODEX_SESSION_INDEX = Path.home() / ".codex" / "session_index.jsonl"


def _same_repo(cwd: str | None) -> bool:
    """这个会话是不是开在**本仓库**里的。大小写与斜杠按 Windows 语义归一后再比。"""
    if not cwd:
        return False
    return os.path.normcase(os.path.normpath(cwd)) == os.path.normcase(os.path.normpath(str(REPO_ROOT)))


def codex_sessions() -> list[dict]:
    """``session_index.jsonl`` 里的会话，``updated_at`` **新的在前**。

    ⚠ 这个文件是**机器全局**的。2026-09-23 实测 24 条横跨 4 个项目
    （HandEyeTools / PointCloudSearch×2 / CodexWithClaude / 一份翻译 PDF），
    rollout 文件层面 33 个里只有 5 个属于本仓。所以"取最新"= "本机最新开的任意
    Codex 会话"，**必须**再过一道 cwd 校验（见 `session_cwd`）。
    """
    if not CODEX_SESSION_INDEX.exists():
        raise FileNotFoundError(f"找不到 {CODEX_SESSION_INDEX}（Codex 没开过任何会话？）")
    entries: list[dict] = []
    for line in CODEX_SESSION_INDEX.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not row.get("id"):
            continue
        entries.append(
            {
                "id": str(row["id"]),
                "name": str(row.get("thread_name") or ""),
                "updated_at": str(row.get("updated_at") or ""),
                # 解析不出来的排最后：**宁可漏选，不可误选**（选错会话 = 唤醒投到别的项目）
                "_key": _stamp(row.get("updated_at")),
            }
        )
    entries.sort(key=lambda item: item["_key"], reverse=True)
    return entries


def _stamp(text) -> datetime:
    """``2026-09-23T02:06:52.5680052Z`` → datetime。解析不了给一个最小值。"""
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def session_cwd(session_id: str) -> str | None:
    """这个会话是在哪个目录开的。取它**最新那个 rollout 文件的第一行**。

    ``session_meta.payload.cwd`` 实测形如 ``D:\\MyCode\\CodexWithClaude``。
    只读第一行——rollout 文件动辄几兆，绝不能整份读进来（AGENTS.md 那条省上下文的规矩）。
    """
    if a_ledger is None:
        return None
    for path in reversed(a_ledger.rollout_files(session_id)):  # 新的在前
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                first = json.loads(handle.readline())
        except (OSError, json.JSONDecodeError):
            continue
        cwd = (first.get("payload") or {}).get("cwd")
        if cwd:
            return str(cwd)
    return None


def rotate_a(args) -> int:
    """把 ``config.json`` 的 ``a_session`` 换成 A 刚开的新会话——「换会话」的机制版。

    为什么它值得有一个命令：换会话原来是**人手改 config.json**。改错的代价是**静默的**：
    ``bus.config()`` 吞掉 ``JSONDecodeError`` 回落 ``DEFAULTS``，而 ``DEFAULTS`` 里没有
    ``a_session``，于是 ``wake_a`` 永远 False、B 交付再也没人唤醒 A，整条链上没有任何
    一步会报错（见 ``bus.update_config`` 的 docstring）。所以这个命令的**全部价值**在
    它比手改多出来的那几道校验与回滚，不在于它省了几次击键。

    四道校验，按严重度：

    1. **cwd**：候选会话必须开在本仓。``session_index.jsonl`` 是机器全局的，实测
       24 条里只有少数属于本仓——盲取最新就是唤醒投到别的项目去。
    2. **原子写**：走 ``bus.update_config``（唯一写入器：保键、临时文件 + ``os.replace``、
       写后逐键断言），``_`` 注释键与 utf-8 编码由它保证。
    3. **写后自检**：再用 ``bus.config()`` 读一遍——那是 ``wake_a`` 真正走的那条路。
       写坏了 ``config()`` 会**静默回落**，这一步才分得清"写进去了"和"看起来写进去了"。
    4. **回滚**：上面任何一步失败就退回原会话，不留半改状态。

    ``--self-test`` 是**要花钱**的：它真发一条唤醒，A 会因此醒来跑一轮。默认关。

    两种模式（2026-09-29 加）：

    * **换会话**——``config.json`` 里 ``a_session`` 是个 id：老行为，四道校验 + 回滚。
    * **首次接线**——``a_session`` 是**空串**（``.trio/trio.py install`` 刚生成的样子）：
      没有旧会话可回滚，cwd 校验照旧；而且**不替人猜**——最近 12 个会话里开在本仓的
      候选超过一个就拒绝，要求 ``--session <id>`` 明说接哪一个。
      注意"空串"和"键不在"是两回事：后者是坏 config（手写半成品），仍然拒绝。

    一个副作用要说明白：写入会**丢掉 config.json 里手工分组用的空行**
    （``bus.update_config`` 是读 dict → ``dumps``，唯一写入器，``verify.py --set-baseline``
    也一样）。键、值、``_`` 注释、顺序全都不变，变的只是空行。这是这个文件第一次被
    任何工具写时的既定代价，不是 rotate-a 引入的。
    """
    cfg = bus.config()
    current = cfg.get("a_session")
    first_bind = False
    if not current:
        # 「键不在」和「键在但为空」是**两件事**（2026-09-29 分开）：
        #   · 键不在 = 这份 config 是坏的 / 手写的半成品 → 拒绝，别在这里造
        #     （DEFAULTS 里没有这个键，造错了就是静默熄火）；
        #   · 键在但为空 = `.trio/trio.py install` 刚生成、**还没接过线** →
        #     允许「首次接线」。下面照样过 cwd 校验，只是没有旧会话可回滚。
        # 非要分开的理由是实测的：新项目装完框架，a_session 就是空的；不分开的话
        # rotate-a 第一步就把人挡在门外，报错还长得像"你配置写错了"——
        # 而真正的病是框架自己没给新项目留一条接线的路。
        try:
            present = json.loads(bus.CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            present = {}
        if not isinstance(present, dict) or "a_session" not in present:
            print(
                "[rotate-a] ✗ config.json 里没有 a_session 这个键——\n"
                "          「键不在」和「键是空串」是两回事，前者是坏 config。\n"
                "          先照 PORTING.md §1 手工补一条（值可以是空串 = 还没接线），\n"
                "          别在这里造——DEFAULTS 里没有这个键，造错了就是静默熄火，\n"
                "          整条链上没有任何一步会报错。"
            )
            return 2
        first_bind = True

    try:
        entries = codex_sessions()
    except FileNotFoundError as exc:
        print(f"[rotate-a] ✗ {exc}")
        return 2
    if not entries:
        print(f"[rotate-a] ✗ {CODEX_SESSION_INDEX} 里一条会话都读不出来")
        return 2

    # 每个候选都要读一次 rollout 首行。取前 12 个就够——更老的只会更不像"刚开的那个"。
    for entry in entries[:12]:
        cwd = session_cwd(entry["id"])
        entry["cwd"] = cwd
        entry["is_repo"] = _same_repo(cwd)
        entry["current"] = entry["id"] == current

    if args.show:
        print(f"[rotate-a] 本仓：{REPO_ROOT}")
        print(f"[rotate-a] 当前 a_session：{current or '（空 = 未接线）'}")
        print("  记号  会话 id（前 8 位）  更新于                开在哪个目录")
        for entry in entries[:12]:
            mark = "→ 当前" if entry["current"] else ("✓ 本仓" if entry["is_repo"] else "✗ 他仓")
            print(f"  {mark:<6} {entry['id'][:8]}…        {entry['updated_at'][:19]:<20} {entry['cwd'] or '（读不到）'}")
            if entry["name"]:
                print(f"           └ {entry['name'][:60]}")
        return 0

    want = getattr(args, "session", None)
    if want is not None and not want.strip():
        # `--session ""` 会**静默**落到自动挑选上去——显式给了空值就该报错，别猜。
        print("[rotate-a] ✗ --session 给空了。要么给一个会话 id，要么整个不写这个参数。")
        return 2
    if want:
        picked = next((e for e in entries if e["id"] == want), None)
        if picked is None:
            print(f"[rotate-a] ✗ session_index.jsonl 里没有 {want}")
            return 2
        if "is_repo" not in picked:  # 落在前 12 名之外：显式指定的要补校验
            cwd = session_cwd(picked["id"])
            picked.update(cwd=cwd, is_repo=_same_repo(cwd), current=picked["id"] == current)
    else:
        if first_bind:
            in_repo = [e for e in entries[:12] if e["is_repo"]]
            if len(in_repo) > 1:
                print(
                    f"[rotate-a] ✗ 首次接线，但最近 12 个会话里有 {len(in_repo)} 个开在本仓——\n"
                    "          不替你猜接哪一个。先 `--show` 看清楚，再 `--session <id>` 明说。"
                )
                return 2
        picked = next((e for e in entries[:12] if e["is_repo"]), None)
        if picked is None:
            print(
                "[rotate-a] ✗ 最近 12 个会话里没有一个开在本仓。\n"
                "          先在 Codex 里**在本仓库目录下**开一个新会话，再跑一次；\n"
                "          或者用 --session <id> 显式指定，并用 --show 确认它确实开在本仓。"
            )
            return 2

    if not picked["is_repo"]:
        print(
            f"[rotate-a] ✗ 拒绝：会话 {picked['id']} 开在 {picked['cwd'] or '（读不到）'}，"
            f"不是本仓 {REPO_ROOT}。\n"
            "          换过去 = B 交付时唤醒投到**别的项目**去，而这边静悄悄地没人管。"
        )
        return 1

    if picked["id"] == current:
        print(f"[rotate-a] 已经是最新会话 {current}，config.json **一个字没动**。")
        return 0

    before = bus.CONFIG_PATH.read_text(encoding="utf-8")
    comments_before = sum(1 for key in json.loads(before) if str(key).startswith("_"))
    try:
        bus.update_config(a_session=picked["id"])
    except Exception as exc:  # noqa: BLE001 - 写不进去就是没写，报清楚比抛栈有用
        print(f"[rotate-a] ✗ 写入失败，config.json 保持原样：{exc}")
        return 1

    def rollback(reason: str) -> int:
        try:
            bus.CONFIG_PATH.write_text(before, encoding="utf-8")
        except OSError as exc:
            print(f"[rotate-a] ✗✗ 回滚也失败了：{exc}\n          config.json 现在是 {picked['id']}，"
                  f"手工改回 {current}")
            return 1
        now = bus.config().get("a_session")
        if now != current:
            ok = f"**仍是 {now!r}——手工查一下**"
        elif current:
            ok = "已回到原会话"
        else:
            ok = "已回到「未接线」状态（a_session 还是那个空串）"
        print(f"[rotate-a] ✗ {reason}\n          已回滚：{ok}")
        return 1

    # 写后自检：走 `bus.config()` —— 那正是 `wake_a` 读 config 的同一条路。
    # 只信 `update_config` 的返回值不够：`config()` 会把坏文件**静默吞掉**回落 DEFAULTS。
    reread = bus.config().get("a_session")
    if reread != picked["id"]:
        return rollback(f"写后自检失败：bus.config() 读到 {reread!r}，应为 {picked['id']}")
    comments_after = sum(1 for key in json.loads(bus.CONFIG_PATH.read_text(encoding="utf-8"))
                         if str(key).startswith("_"))
    if comments_after != comments_before:
        return rollback(f"注释键从 {comments_before} 个变成 {comments_after} 个")

    print(f"[rotate-a] ✓ a_session：{current or '（空 = 未接线）'} → {picked['id']}")
    print(f"           （开在 {picked['cwd']}，更新于 {picked['updated_at'][:19]}；"
          f"{comments_before} 个注释键无损）")
    if first_bind:
        print("[rotate-a] ↑ **首次接线**：这份 config 之前没接过线"
              "（a_session 是安装器写的空串）。")

    if not getattr(args, "self_test", False):
        print("[rotate-a] 投递能力**未验证**——想验就跑 --self-test（要花钱：A 会醒来跑一轮）。")
        return 0

    marker = f"rotate-a 自检 {uuid.uuid4().hex[:8]}"
    print(f"[rotate-a] 发一条唤醒自测（marker={marker}）…")
    if not bus.wake_a(marker, detail=f"新会话 {picked['id'][:8]}…"):
        return rollback("唤醒自测发不出去（codex queue 失败）：这个会话 id 投不进东西")
    print(f"[rotate-a] ✓ codex queue 接受了。要确认 A 真收到，看队列里那条有没有被消费：\n"
          f"           python .trio/reports/readiness/peek_codex_queue.py \"{marker}\"\n"
          f"           （**行还在** = 还没被消费，不一定是投错——A 可能在忙；但一直不动就得查）")
    return 0


# ---------------------------------------------------------------- 掐断


def write_live(task: str, watcher: "GateWatcher", phase: str, **extra) -> None:
    """把"B 现在在干什么"落成一个小文件，给群界面的实时活动条读。

    **这是给眼睛用的，不是给闸门用的**——闸门的判据永远只从事件流来。
    所以这个文件丢了、坏了、写重了，都不影响任何一次判定。
    """
    bus.ensure_dirs()
    now = time.time()
    payload = {
        "task": task,
        "phase": phase,  # starting / running / done / gate / human-kill
        "router_pid": os.getpid(),
        "elapsed": round(now - watcher.round_started, 1),
        "events": watcher.events,
        "actions": watcher.actions,
        "last_action": watcher.last_action,
        "since_write_events": watcher.events_since_write,
        "since_write_seconds": (
            round(now - watcher.last_write_at, 1) if watcher.last_write_at else None
        ),
        "no_write_streak": watcher.no_write_streak,
        "warn_at": watcher.stall_events_warn,
        "kill_at": watcher.stall_events_kill,
        "no_progress_actions": watcher.no_progress_actions,
        "wall_seconds": watcher.wall_seconds,
        "warnings": [
            {"reason": w["reason"], "detail": w["detail"], "at": w["at"]}
            for w in watcher.warn_log[-3:]
        ],
        "updated_at": bus.now_iso(),
        "updated": now,
    }
    payload.update(extra)
    try:
        tmp = LIVE_FILE.with_name(LIVE_FILE.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, LIVE_FILE)
    except OSError:
        pass  # 活动条写不进去不该影响 B 的运行


def write_live_placeholder(phase: str, **extra) -> None:
    """B 没在跑的时候，活动条显示这个（群界面据此把活动条收起来）。"""
    bus.ensure_dirs()
    payload = {"phase": phase, "updated_at": bus.now_iso(), "updated": time.time()}
    payload.update(extra)
    try:
        tmp = LIVE_FILE.with_name(LIVE_FILE.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, LIVE_FILE)
    except OSError:
        pass


def port_alive(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def ensure_group_ui(cfg: dict, announce: bool = True) -> str:
    """确保群界面在跑；没跑就起一个，并把浏览器打开。**机制，不是纪律。**

    上一轮就是这里断的：界面建好了、30 条消息也全在，但**没有任何机制保证它被打开**，
    于是人成了瞎子——A 和 B 在群里说了 30 句、提交了 3 个 commit，人一句没看见。
    开界面这件事不能写在一句注释里求谁去做，得由 router 自己保证。
    """
    port = int(cfg.get("group_port", 8761))
    url = f"http://127.0.0.1:{port}/"
    if port_alive(port):
        if announce:
            print(f"[group] 群界面已经在跑：{url}")
        return url

    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    argv = [
        sys.executable,
        str(TRIO_DIR / "serve.py"),
        "--port", str(port),
        "--open",  # 人不用做任何事，浏览器自己弹出来
        "--idle-exit", str(int(cfg.get("group_idle_exit", 3600))),
    ]
    try:
        subprocess.Popen(
            argv,
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
        )
    except OSError as exc:
        print(f"[group] 群界面起不来（{exc}）；手动：python .trio/serve.py --open")
        return url

    for _ in range(48):  # 最多等约 12 秒
        if port_alive(port):
            if announce:
                print(f"[group] 群界面已起，浏览器应已自动打开：{url}")
            return url
        time.sleep(0.25)
    if announce:
        print(f"[group] 群界面还没就绪，稍后手动打开也行：{url}")
    return url


def kill_requested() -> dict | None:
    """人在群界面上按了掐断。"""
    if not KILL_FLAG.exists():
        return None
    try:
        return json.loads(KILL_FLAG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"task": None, "reason": "(标记文件无法解析)"}


def clear_kill_flag() -> None:
    try:
        KILL_FLAG.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 驱动 B


def build_argv(cfg: dict, launcher: list, prompt: str, session: str, resume: bool) -> list:
    argv = [
        *launcher,
        "--bare",
        "-p",
        prompt,
        "--append-system-prompt-file",
        str(TRIO_DIR / "roles" / "B.md"),
        "--permission-mode",
        str(cfg.get("b_permission_mode", "acceptEdits")),
        "--allowedTools",
        str(cfg.get("b_allowed_tools", "")),
        "--permission-prompts",
        "none",
        "--effort",
        str(cfg.get("b_effort", "low")),
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-budget-usd",
        str(cfg.get("b_budget_usd", 1.0)),
    ]
    argv += ["--resume", session] if resume else ["--session-id", session]
    return argv


def default_prompt(task: str, brief: str) -> str:
    return (
        f"执行 {brief}。只做那一条任务，不要探查仓库。\n"
        f"自检最多一次，且只能用 `python .trio/check.py <模块>` 或 "
        f"`python -m py_compile <文件>`——不要写测试、不要跑测试。\n"
        f"你只能在任务书声明的**工作集**内写文件，越界会被判失败。\n"
        f"开始实现、给出技术方案、交付、以及被卡住时，"
        f'用 `python .trio/as.py b --kind <plan|deliver|say> --task {task} --text "..."` '
        f"往群里说明。"
    )


def drive(args) -> int:
    cfg = bus.config()
    task = args.task
    brief_path = (REPO_ROOT / args.brief) if args.brief else None
    if brief_path and not brief_path.exists():
        print(f"[error] 找不到任务书：{brief_path}")
        return 2

    # 会话 id 必须是**带连字符的标准 UUID**：claude CLI 拒绝 32 位裸 hex，
    # 会以 `Error: Invalid session ID. Must be a valid UUID.` 立刻 exit=1。
    # （这条是 A 在 T-002 上撞出来的，原文见群里那条框架缺陷。）
    # 会话 id：**默认每次 drive 都开一个新会话**。
    #
    # 为什么改：沿用 `log/b-session` 里那个旧 id 再走 `--session-id` 建会话时，
    # claude CLI 会直接 `Error: Session ID ... is already in use.` 然后 exit=1。
    # 2026-09-23 每轮回灌都撞一次，A 只能每次手工传一个新 `--session` 绕过去。
    # 真想接着上一个会话聊（比如回灌时保留上下文），明说 `--resume`。
    if args.session:
        session = args.session
    elif args.resume and SESSION_FILE.exists():
        session = SESSION_FILE.read_text().strip()
    else:
        session = str(uuid.uuid4())
    prompt = args.prompt or default_prompt(task, args.brief or "(未提供任务书)")

    if args.dry_run:
        print("[dry-run] 不调用模型，只打印将要执行的 argv：")
        print("  " + " ".join(build_argv(cfg, resolve_claude_launcher(args.claude), prompt, session, args.resume)))
        return 0

    launcher = resolve_claude_launcher(args.claude)
    argv = build_argv(cfg, launcher, prompt, session, args.resume)
    clear_kill_flag()

    # 开界面这件事由机制保证，不由谁的记性保证——上一轮人成了瞎子就是栽在这里
    ensure_group_ui(cfg)

    spend = load_spend()
    balance_before = deepseek_balance()
    # 会话基线 = **这一轮需求**的起点。换任务（= 换一轮需求）就重开基线，旧基线进 history。
    #
    # 为什么改：原先只在**第一次 drive** 时写一次 `start_balance`、之后永不重置，
    # 于是「单会话 ¥3」量的其实是"自那以后账户余额掉了多少"。而余额是**账户级**的——
    # 本机任何 DeepSeek 用量（人在别的项目里跑 Claude Code）都会算进来。
    # 2026-09-23 真被咬了两次：B 还没动一下（0 动作、¥0.00），闸就报"本会话 ¥3.85 / ¥4.30"。
    if balance_before is not None and (
        args.reset_session or spend.get("task") != task
    ):
        if spend.get("start_balance") is not None:
            spend.setdefault("history", []).append(
                {
                    "task": spend.get("task"),
                    "started": spend.get("started"),
                    "start_balance": spend.get("start_balance"),
                    "last_balance": spend.get("last_balance"),
                    "session_spent": spend.get("session_spent"),
                    "closed_at": bus.now_iso(),
                    "note": "换任务（或 --reset-session）重开会话基线",
                }
            )
        spend["task"] = task
        spend["start_balance"] = balance_before
        spend["started"] = bus.now_iso()
        spend["last_balance"] = balance_before
        spend["session_spent"] = 0.0
        save_spend(spend)

    watcher = GateWatcher(cfg, task)
    state = {"code": None, "stopped": None}
    stop_flag = threading.Event()
    write_live(task, watcher, "starting")

    if args.inject:
        print(
            "[warn] --inject 需要先做一次付费验证（见 PROTOCOL.md 的「待验证前提」），"
            "当前按实验路径运行"
        )

    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    print(f"[router] 起 B：task={task} session={session[:8]} 墙钟{watcher.wall_seconds:.0f}s")
    process = subprocess.Popen(
        argv,
        cwd=str(REPO_ROOT),
        stdin=subprocess.PIPE if args.inject else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creation,
    )

    def reader() -> None:
        assert process.stdout is not None
        last_live = 0.0
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                bus.append_raw(f"b-{task}", line)
                continue
            bus.append_raw(f"b-{task}", event)
            verdict = watcher.observe(event)
            # 活动条：**节流到 0.6 秒一次**，别为了给人看而拖慢 B
            tick = time.time()
            if tick - last_live > 0.6:
                last_live = tick
                write_live(task, watcher, "running")
            for warning in watcher.pop_warnings():
                # 软告警不掐断，只往群里发——**让 A 有机会在烧完之前介入**
                bus.post(
                    bus.SYSTEM,
                    "note",
                    f"[软告警] {warning['detail']}",
                    task=task,
                    meta=warning,
                )
                print(f"[warn] {warning['detail']}")
            if verdict and state["stopped"] is None:
                state["stopped"] = verdict
                stop_flag.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    last_cost_poll = 0.0
    last_live_beat = 0.0
    spent_task = spent_session = None
    try:
        while True:
            if process.poll() is not None and not thread.is_alive():
                state["code"] = process.returncode
                break
            if stop_flag.is_set():
                break
            verdict = watcher.check_wall()
            if verdict:
                state["stopped"] = verdict
                break
            human = kill_requested()
            if human:
                state["stopped"] = {
                    "reason": "human-kill",
                    "detail": human.get("reason") or "人在群界面上掐断",
                    "at": clock(),
                }
                break
            now = time.time()
            if now - last_cost_poll > float(cfg.get("cost_poll_seconds", 60)):
                last_cost_poll = now
                balance = deepseek_balance()
                if balance is not None:
                    # 本轮需求累计：从**这一轮需求第一次 drive** 之前的余额算起
                    # （换任务会重开基线；余额是账户级的，见 drive() 里那段注释）
                    if spend.get("start_balance") is not None:
                        spent_session = round(float(spend["start_balance"]) - balance, 4)
                    # 本任务花费：从**本任务**的起点算。
                    # 这里原先是 `spent_task = spent_session`——拿会话总额去顶任务的闸，
                    # 于是「¥1.5/任务」这道闸量的是别的东西，等于半睡着。
                    if balance_before is not None:
                        spent_task = round(balance_before - balance, 4)
                verdict = watcher.check_cost(spent_task, spent_session)
                if verdict:
                    state["stopped"] = verdict
                    break
            # 心跳：B 闷头思考时事件还在流，但万一断了，活动条也得继续走
            beat = time.time()
            if beat - last_live_beat > 2.0:
                last_live_beat = beat
                write_live(task, watcher, "running")
            time.sleep(0.5)
    except KeyboardInterrupt:
        state["stopped"] = {"reason": "interrupted", "detail": "本地中断", "at": clock()}

    if state["stopped"]:
        with contextlib.suppress(Exception):
            process.kill()
        detail = state["stopped"]["detail"]
        cli_reason = f"[{state['stopped']['reason']}] 机械闸触发：{detail}"
        bus.post(bus.SYSTEM, "gate", cli_reason, task=task, meta=state["stopped"])
        print(f"[gate] {cli_reason}")
    else:
        state["code"] = process.returncode

    thread.join(timeout=5)
    clear_kill_flag()

    balance_after = deepseek_balance()
    cost = None
    session_spent = None
    spend = load_spend()
    # A 侧台账：**不放在下面的余额分支里**——它跟 DeepSeek 的余额接口毫无关系，
    # 余额读不到（接口挂了、token 没配）时照样该告诉 A 它的会话涨到多大了。
    # 先算增量并把提示打给 A（stdout）+ 人（群界面），快照本身进本轮账。
    a_snapshot = a_ledger_snapshot()
    report_a_ledger(a_snapshot)
    if balance_after is not None:
        if balance_before is not None:
            cost = round(balance_before - balance_after, 4)
        # 余额接口有滞后：一轮跑得短（几十秒）时，前后两次读数可能一模一样，
        # cost 就会是 0.00——那不是"没花钱"，是"还没反映出来"。
        # 本轮需求累计从"这一轮需求第一次 drive 之前"读到的余额算起，滞后小得多，
        # 才是可靠的那个数（换任务会重开基线）。
        if spend.get("start_balance") is not None:
            session_spent = round(float(spend["start_balance"]) - balance_after, 4)
        # 每轮都留一条账（别覆盖写）：同一个任务会有多次 drive（首次交付 + 若干回灌），
        # 覆盖写只剩下最后一轮的 0.14，事后根本答不出"回灌花掉的钱占多少"。
        rounds = spend.setdefault("tasks", {}).setdefault(task, [])
        if isinstance(rounds, (int, float)):  # 兼容老格式：一个数字
            rounds = spend["tasks"][task] = [rounds]
        rounds.append(
            {
                "at": bus.now_iso(),
                "cost_cny": cost,
                "session_spent_cny": spent_session,
                "session": session,
                "exit": state["code"],
                "stopped_by": (state["stopped"] or {}).get("reason"),
                "actions": watcher.actions,
                "events": watcher.events,
                # A 侧（Codex）台账快照：**会话级**累计的动作数/上下文/墙钟。
                # 相邻两轮相减 = A 在这轮之间干了多少。只看得到**代理指标**，本机读不出
                # Codex 的 token 费用；这是"两笔账"里 A 那笔唯一的可读口径，
                # 见 PROTOCOL §9 与 .trio/a_ledger.py。
                "a_ledger": a_snapshot,
            }
        )
        spend["last_balance"] = balance_after
        spend["session_spent"] = session_spent
        save_spend(spend)

    SESSION_FILE.write_text(session, encoding="utf-8")

    report = {
        "task": task,
        "brief": args.brief,
        "session": session,
        "exit_code": state["code"],
        "stopped_by": state["stopped"],
        "cost_cny": cost,
        "session_spent_cny": session_spent,
        "cost_note": "cost_cny 是单轮余额差，余额接口滞后时可能为 0.00；session_spent_cny 是会话累计",
        "real_balance_after": balance_after,
        "actions": watcher.actions,
        "repeat_counts": {k: v for k, v in watcher.counts.items() if v > 1},
        "raw_stream": f".trio/log/raw/b-{task}.jsonl",
        "finished_at": bus.now_iso(),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{task}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    stopped = (state["stopped"] or {}).get("reason")
    write_live(
        task, watcher, "gate" if state["stopped"] else "done",
        stopped_by=stopped, cost_cny=cost, session_spent_cny=session_spent,
    )

    # 单轮差值因滞后为 0 时，报会话累计——**不报一个自相矛盾的 0**
    shown = cost if (cost or 0) > 0 else session_spent
    summary = (
        f"task={task} exit={state['code']} "
        f"stopped_by={stopped or '-'} "
        f"动作={watcher.actions} 真实花费≈"
        + (f"¥{shown:.2f}" if shown is not None else "n/a")
        + ("（会话累计）" if shown is session_spent and shown else "")
    )
    bus.post(bus.SYSTEM, "note", summary, task=task, refs=[str(report_path.relative_to(REPO_ROOT))])
    print(f"[summary] {summary}")
    return 0


# ---------------------------------------------------------------- 零花费自检


def replay(args) -> int:
    """把一段历史事件流喂给机械闸，看它会不会触发、什么时候触发。**不调模型、不花钱。**"""
    cfg = bus.config()
    path = REPO_ROOT / args.stream
    if not path.exists():
        print(f"[error] 找不到事件流：{path}")
        return 2

    started = path.stat().st_mtime
    watcher = GateWatcher(cfg, args.task, started=started)
    events = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events += 1
            verdict = watcher.observe(event)
            if verdict:
                break

    print(f"[replay] {path.name}：{events} 个事件，{watcher.actions} 次动作")
    if watcher.warnings:
        print(
            f"[replay] 软告警会在第 {watcher.warnings[0]['actions']} 个动作处发出："
            f"{watcher.warnings[0]['detail']}"
        )
    if watcher.fired:
        fired = watcher.fired
        print(
            f"[replay] 机械闸**会触发**：{fired['reason']} —— {fired['detail']}\n"
            f"         发生在第 {fired['actions']} 个动作处"
        )
    else:
        print("[replay] 机械闸不会触发（这段事件流没有触到四条条件）")
    top = sorted(watcher.counts.items(), key=lambda kv: -kv[1])[:5]
    if top:
        print("[replay] 重复最多的动作：")
        for fingerprint, count in top:
            print(f"         {count:>3}× {fingerprint[:100]}")

    # --expect 让回放**能失败**。否则它只是在测"命令跑起来了没"——
    # 那种绿灯正是上一轮"组件全绿、人是瞎的"的病根。
    expect = getattr(args, "expect", None)
    if expect:
        want_fire = expect == "fire"
        got_fire = watcher.fired is not None
        if want_fire != got_fire:
            print(
                f"[replay] ✗ 期望{'触发' if want_fire else '不触发'}，"
                f"实际{'触发' if got_fire else '不触发'}"
            )
            return 1
        print(f"[replay] ✓ 符合预期（--expect {expect}）")
    return 0


# ---------------------------------------------------------------- 入口


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    bus.ensure_dirs()

    parser = argparse.ArgumentParser(description="路由器：机械闸 + B 的驱动")
    sub = parser.add_subparsers(dest="command", required=True)

    p_drive = sub.add_parser("drive", help="驱动 B 跑一个任务")
    p_drive.add_argument("--task", required=True)
    p_drive.add_argument("--brief", help="任务书路径（相对仓库根）")
    p_drive.add_argument("--prompt", help="直接给提示词（替代任务书模板）")
    p_drive.add_argument("--session", help="指定会话 id（缺省：这次 drive 开一个新会话）")
    p_drive.add_argument(
        "--resume",
        action="store_true",
        help="续用 log/b-session 里那个会话（缺省会另开新的，免得撞 already in use）",
    )
    p_drive.add_argument("--inject", action="store_true", help="长驻会话 + 中途注入（实验路径）")
    p_drive.add_argument("--claude", default="claude")
    p_drive.add_argument(
        "--reset-session",
        action="store_true",
        help="把「本轮需求花费」的基线重设成当前余额（怀疑账户里别处的用量"
             "把这道闸顶到 ¥3 以上时用；换任务本来就会自动重开）",
    )
    p_drive.add_argument("--dry-run", action="store_true", help="只验管道，不起进程")

    p_replay = sub.add_parser("replay", help="把历史事件流喂给机械闸（零花费自检）")
    p_replay.add_argument(
        "--expect", choices=["fire", "clean"],
        help="断言闸门该不该触发；不符则退出码 1（让回放能失败，而不是永远绿）",
    )
    p_replay.add_argument("--stream", required=True)
    p_replay.add_argument("--task", default="replay")

    p_rotate = sub.add_parser(
        "rotate-a", help="把 config.json 的 a_session 换成 A 刚开的新会话（「换会话」的机制版）"
    )
    p_rotate.add_argument("--show", action="store_true", help="只列候选，一个字不写")
    p_rotate.add_argument("--session", help="显式指定会话 id（跳过自动挑选；**仍然**校 cwd）")
    p_rotate.add_argument(
        "--self-test",
        action="store_true",
        help="写完后真发一条唤醒自测（**要花钱**：A 会因此醒来跑一轮）",
    )

    sub.add_parser("status", help="看一眼当前状态与花费")

    args = parser.parse_args(argv)
    if args.command == "drive":
        return drive(args)
    if args.command == "replay":
        return replay(args)
    if args.command == "rotate-a":
        return rotate_a(args)
    if args.command == "status":
        spend = load_spend()
        print(
            f"本轮需求基线：{spend.get('started')}  余额 {spend.get('start_balance')} → "
            f"{spend.get('last_balance')}   累计 ¥{spend.get('session_spent')}"
        )
        print("每个任务的每轮账（同一任务多次 drive = 首次交付 + 回灌）：")
        for task, rounds in (spend.get("tasks") or {}).items():
            if isinstance(rounds, (int, float)):  # 老格式
                print(f"  {task}: ¥{rounds}")
                continue
            total = sum(item.get("cost_cny") or 0 for item in rounds)
            last = rounds[-1] if rounds else {}
            print(
                f"  {task}: {len(rounds)} 轮  单轮合计 ¥{total:.2f}  "
                f"（最后一轮 {last.get('at', '?')[:19]} exit={last.get('exit')} "
                f"动作={last.get('actions')}）"
            )
        print(f"群消息：{bus.last_seq()} 条；任务：{bus.tasks()}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
