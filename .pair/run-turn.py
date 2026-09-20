#!/usr/bin/env python3
"""一轮协作的执行器（runner）。

它只做"重复劳动"，**不做判断**：判断这一轮通不通过仍然是人的/Codex 的事。

流程：

1. 起本地实时视图服务（若端口空闲），全程把事件流喂给看板；
2. 用固定参数跑一轮 Claude（``--bare``、回合内硬预算、低思考强度、
   精确工具白名单、无人应答时直接拒绝而不是挂起）；
3. 把原始事件流写进 ``.pair/logs/turn-<N>.stream.jsonl``；
4. 回合结束自动跑仓库的验证命令，抓取结果、git diffstat、真实余额变化；
5. 生成证据包 ``.pair/reports/turn-<N>-verify.md``；
6. **关掉视图服务**（每轮结束就收，不长时间驻留）。

用法示例：

    python .pair/run-turn.py --turn 4 --inbox .pair/inbox/004.md
    python .pair/run-turn.py --turn 4 --dry-run        # 只验管道，不调用模型
"""

from __future__ import annotations

import argparse
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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PAIR_DIR = REPO_ROOT / ".pair"
LOG_DIR = PAIR_DIR / "logs"
REPORT_DIR = PAIR_DIR / "reports"
SESSION_FILE = LOG_DIR / "session-id"
CODEX_LOG = LOG_DIR / "codex.live.log"
DEFAULT_ALLOW = (
    "Read,Glob,Grep,Edit,Write,Bash(cmake --build:*)"
)
DEFAULT_VERIFY = (
    "cmake --build build --config Release && "
    "ctest --test-dir build -C Release --output-on-failure"
)


def _utf8_console() -> None:
    """Windows 控制台默认代码页会把中文打成乱码，统一成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def resolve_claude_launcher(explicit: str) -> list:
    """解析 Claude Code 的启动方式。

    Windows 上 PATH 里的 ``claude`` 是 npm 生成的 ``.cmd`` 垫片，
    ``subprocess`` 不能直接执行它（会 FileNotFoundError），而且走 ``cmd /c`` 会把
    带空格/中文的提示词搅乱。所以优先找垫片背后的**原生 exe** 直连。
    """
    if explicit and explicit != "claude":
        return [explicit]

    shim = shutil.which("claude") or shutil.which("claude.cmd")
    candidates = []
    if shim:
        shim_path = Path(shim)
        candidates.append(shim_path.with_suffix(".exe"))
        # npm 垫片里写着真实 exe 的路径，直接读出来最可靠
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
        # 兜底：走 cmd 垫片（提示词尽量避免特殊字符）
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", shim]
    return ["claude"]


# ----------------------------------------------------------------- 小工具


def clock() -> str:
    return time.strftime("%H:%M:%S")


def log_codex(text: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with CODEX_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{clock()}] [CODEX] {text}\n")


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_get(url: str, timeout: float = 5.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def deepseek_balance() -> float | None:
    """真实余额（CNY）。读本地 Claude 配置里的 token，绝不打印它。"""
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


# ----------------------------------------------------------------- 视图服务


class ViewServer:
    """按需起停的看板服务：这一轮需要它，轮次结束就收掉。"""

    def __init__(self, port: int, idle_exit: int):
        self.port = port
        self.idle_exit = idle_exit
        self.process: subprocess.Popen | None = None
        self.started_here = False

    def start(self) -> None:
        if port_open(self.port):
            print(f"[view] 端口 {self.port} 已有服务，复用它")
            return
        creation = 0
        if os.name == "nt":
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(PAIR_DIR / "live.py"),
                "--port",
                str(self.port),
                "--idle-exit",
                str(self.idle_exit),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
        )
        self.started_here = True
        for _ in range(40):
            if port_open(self.port):
                print(f"[view] 看板已起：http://127.0.0.1:{self.port}/")
                return
            time.sleep(0.25)
        print("[view] 看板没起来（继续跑，不影响回合）")

    def stop(self) -> None:
        if not self.started_here:
            return
        try:
            http_get(f"http://127.0.0.1:{self.port}/api/shutdown")
        except Exception:
            pass
        if self.process is not None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        print("[view] 看板已关闭（每轮结束都收掉，不常驻）")


# ----------------------------------------------------------------- 回合执行


def new_session_id() -> str:
    return subprocess.run(
        [sys.executable, "-c", "import uuid;print(uuid.uuid4())"],
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_command(args, launcher, prompt: str, sid: str, resume: bool) -> list:
    command = [*launcher, "--bare", "-p", prompt]
    command += ["--resume", sid] if resume else ["--session-id", sid]
    command += [
        "--append-system-prompt-file",
        str(PAIR_DIR / "PROMPT.md"),
        "--permission-mode",
        args.permission_mode,
        "--allowedTools",
        args.allow,
        "--permission-prompts",
        "none",
        "--effort",
        args.effort,
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-budget-usd",
        str(args.budget),
    ]
    return command


def invoke(command: list, args, stream_path: Path) -> tuple[int, str]:
    """跑一次 claude，事件流同时落盘；返回 (退出码, 全部输出文本)。"""
    collected: list = []
    timed_out = {"hit": False}

    def watch(process: subprocess.Popen, seconds: float) -> None:
        """墙钟硬闸：到点直接杀掉，别让一轮无上限地跑。"""
        deadline = time.time() + seconds
        while process.poll() is None:
            if time.time() > deadline:
                timed_out["hit"] = True
                process.kill()
                return
            time.sleep(1)

    with stream_path.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        threading.Thread(
            target=watch, args=(process, args.wall_timeout), daemon=True
        ).start()
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                sink.write(line)
                collected.append(line)
                if args.verbose_console and not re.search(
                    r'"subtype":"thinking_tokens"', line
                ):
                    sys.stdout.write(line)
            code = process.wait(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            process.kill()
            code = 124
    if timed_out["hit"]:
        code = 124
    return code, "".join(collected)


def run_claude(args, prompt: str) -> tuple[int, Path, str]:
    """跑一轮 Claude，事件流落盘。返回 (退出码, 日志路径, 状态说明)。

    若 ``--resume`` 的目标会话不存在（例如上一次尝试在会话建立前就失败了），
    自动改用新会话重试一次——这是实测踩过的坑。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stream_path = LOG_DIR / f"turn-{args.turn:03d}.stream.jsonl"
    launcher = resolve_claude_launcher(args.claude)
    sid = SESSION_FILE.read_text(encoding="utf-8").strip() if SESSION_FILE.exists() else ""
    if not sid:
        sid = new_session_id()
        SESSION_FILE.write_text(sid, encoding="utf-8")

    print(f"[turn] session={sid[:8]} budget=${args.budget} effort={args.effort}")
    print(f"[turn] launcher={launcher[0]}")
    print(f"[turn] 事件流 -> {stream_path.relative_to(REPO_ROOT)}")

    started = time.time()
    resume = True
    for attempt in (1, 2):
        code, output = invoke(build_command(args, launcher, prompt, sid, resume), args, stream_path)
        if resume and "No conversation found with session ID" in output:
            print("[turn] resume 的会话不存在，改用新会话重试一次")
            sid = new_session_id()
            SESSION_FILE.write_text(sid, encoding="utf-8")
            resume = False
            continue
        break

    elapsed = time.time() - started
    state = f"wall-timeout({args.wall_timeout:.0f}s)" if code == 124 else "completed"
    print(f"[turn] 结束：exit={code} 用时 {elapsed:.0f}s 状态={state}")
    return code, stream_path, state


RESULT_KEYS = ("subtype", "num_turns", "total_cost_usd", "is_error", "terminal_reason")


def summarize_stream(stream_path: Path) -> dict:
    """从事件流里抓最后一条 result（Claude 自报的回合结论）。"""
    summary: dict = {}
    if not stream_path.exists():
        return summary
    for line in stream_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "result":
            summary = {key: payload.get(key) for key in RESULT_KEYS}
    return summary


def run_verify(command: str, timeout: float) -> tuple[int, str]:
    print(f"[verify] {command}")
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 124, f"验证命令超时（>{timeout:.0f}s）"


def git_summary() -> str:
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip()

    return git("diff", "--stat") + ("\n" if git("diff", "--stat") else "") + git(
        "status", "--short"
    )


def tail(text: str, lines: int = 40) -> str:
    rows = text.strip().splitlines()
    return "\n".join(rows[-lines:])


def write_report(args, prompt, stream_path, code, state, summary, verify_code, verify_out, cost):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"turn-{args.turn:03d}-verify.md"
    body = f"""# turn {args.turn:03d} 证据包（runner 自动生成）

- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}
- inbox：`{args.inbox or '(命令行提示词)'}`
- 退出码：`{code}`，状态：`{state}`
- Claude 自报：`subtype={summary.get('subtype')}` `num_turns={summary.get('num_turns')}` \
`costUSD(估算)={summary.get('total_cost_usd')}` `terminal_reason={summary.get('terminal_reason')}`
- 真实花费：{(f'¥{cost:.2f}（余额 {cost} 差值，DeepSeek 实扣）' if cost is not None else '未取到余额')}
- 事件流：`{stream_path.relative_to(REPO_ROOT)}`
- 验证命令：`{args.verify}` → 退出码 `{verify_code}`

> runner 只收集证据；**通过与否由 Codex 读 diff + 跑真机验证决定**。

## 验证命令输出（末 40 行）

```text
{tail(verify_out)}
```

## 仓库改动

```text
{git_summary()}
```

## 本轮指令原文

```text
{prompt}
```
"""
    path.write_text(body, encoding="utf-8")
    print(f"[report] {path.relative_to(REPO_ROOT)}")
    return path


def main(argv=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description="跑一轮 Codex×Claude 协作回合")
    parser.add_argument("--turn", type=int, required=True, help="轮号（用于文件命名）")
    parser.add_argument("--inbox", default=None, help="任务文件，如 .pair/inbox/004.md")
    parser.add_argument("--prompt", default=None, help="直接给提示词（替代 --inbox）")
    parser.add_argument("--budget", type=float, default=4.0, help="回合内硬预算（估算美元）")
    parser.add_argument("--effort", default="low", choices=("low", "medium", "high"))
    parser.add_argument("--permission-mode", default="acceptEdits")
    parser.add_argument("--allow", default=DEFAULT_ALLOW, help="--allowedTools 白名单")
    parser.add_argument("--wall-timeout", type=float, default=900, help="回合最长秒数")
    parser.add_argument(
        "--verify",
        default=DEFAULT_VERIFY,
        help="回合结束后自动跑的验证命令",
    )
    parser.add_argument("--view-port", type=int, default=8760)
    parser.add_argument("--view-idle-exit", type=int, default=900)
    parser.add_argument("--keep-view", action="store_true", help="回合结束后不关看板")
    parser.add_argument("--no-view", action="store_true", help="不起看板")
    parser.add_argument("--no-cost", action="store_true", help="不查 DeepSeek 余额")
    parser.add_argument("--claude", default="claude", help="claude 可执行文件")
    parser.add_argument("--verbose-console", action="store_true", help="把事件流也打到控制台")
    parser.add_argument("--dry-run", action="store_true", help="只验管道，不调用模型")
    args = parser.parse_args(argv)

    if args.inbox:
        inbox_path = REPO_ROOT / args.inbox
        if not inbox_path.exists():
            print(f"[error] 找不到任务文件：{inbox_path}")
            return 2
        prompt = (
            f"执行 {args.inbox}。只做那一条任务，不要探查仓库，"
            f"最多 1 条语法自检。交回说明写到**任务书里指定的那个 outbox 文件**"
            f"（任务书没指定时才用 .pair/outbox/{args.turn:03d}.md）。"
        )
    elif args.prompt:
        prompt = args.prompt
    else:
        print("[error] 必须给 --inbox 或 --prompt")
        return 2

    log_codex(f"turn {args.turn:03d} 开始（inbox={args.inbox or 'inline'}，预算 ${args.budget}）")
    view = ViewServer(args.view_port, args.view_idle_exit)
    if not args.no_view:
        view.start()

    balance_before = None if (args.no_cost or args.dry_run) else deepseek_balance()

    stream_path = LOG_DIR / f"turn-{args.turn:03d}.stream.jsonl"
    try:
        if args.dry_run:
            print("[dry-run] 跳过模型调用，只验证管道")
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            stream_path.write_text("", encoding="utf-8")
            code, state, summary = 0, "dry-run", {}
        else:
            code, stream_path, state = run_claude(args, prompt)
            if state == "completed" and code != 0:
                state = "claude-exit-nonzero"
            summary = summarize_stream(stream_path)

        verify_code, verify_out = run_verify(args.verify, args.wall_timeout)
        balance_after = None if (args.no_cost or args.dry_run) else deepseek_balance()
        cost = None
        if balance_before is not None and balance_after is not None:
            cost = round(balance_before - balance_after, 2)

        write_report(
            args, prompt, stream_path, code, state, summary, verify_code, verify_out, cost
        )
        log_codex(
            f"turn {args.turn:03d} 结束：exit={code} verify_exit={verify_code} "
            f"claude自报costUSD={summary.get('total_cost_usd')} 真实≈"
            f"{'¥' + format(cost, '.2f') if cost is not None else 'n/a'}"
        )
        print(
            f"[summary] claude_exit={code} verify_exit={verify_code} "
            f"真实花费≈{'¥' + format(cost, '.2f') if cost is not None else 'n/a'}"
        )
        # 交回文件是否存在：这只是提示，不代替人工验收
        outbox = PAIR_DIR / "outbox" / f"{args.turn:03d}.md"
        print(f"[summary] outbox {'已生成' if outbox.exists() else '缺失'}：{outbox.name}")
    except Exception as exc:  # 回合执行本身失败也要留证据、也要关看板
        print(f"[error] 回合执行失败：{type(exc).__name__}: {exc}")
        write_report(
            args,
            prompt,
            stream_path,
            1,
            f"runner-error({type(exc).__name__})",
            {},
            1,
            f"runner 出错，未执行验证：{type(exc).__name__}: {exc}",
            None,
        )
        log_codex(f"turn {args.turn:03d} runner 出错：{type(exc).__name__}: {exc}")
        return 1
    finally:
        if not args.no_view and not args.keep_view:
            view.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
