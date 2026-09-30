#!/usr/bin/env python3
"""trio.py —— 把「三方协作框架」安装 / 同步到另一个项目目录。

为什么要有它（2026-09-29）
--------------------------
框架的脚本全部用 ``__file__`` 定位自己（``bus.py`` 的 ``TRIO_DIR``、
``router.py`` 的 ``REPO_ROOT``），所以 ``.trio/`` 必须**物理**长在每个项目里。
把 ``.trio`` 做成 junction / 软链会让 ``Path.resolve()`` 指回共享目录，
几个项目的 ``log/`` ``reports/`` ``tasks/`` 当场串味。

于是跨项目复用只剩一条干净的路：**一个源仓 + 一条幂等的同步命令**。
你只维护源仓一份代码，目标仓里的代码永远别手改；改框架 = 改源仓 → 重跑这条命令。

用法::

    python .trio/trio.py install D:\\path\\to\\project          # 首次安装 / 更新（幂等）
    python .trio/trio.py install <目标> --dry-run               # 只报告要做什么
    python .trio/trio.py install <目标> --kit <骨架仓的 .trio>  # 用别处的骨架仓当源

分工（这条是 ``PORTING.md`` §0 的机器化）
----------------------------------------
==============  ==========================================================
代码            脚本 / ``roles/`` / ``tests/`` / 四份文档 / ``start.cmd``
                ——**每次覆盖**，保证与源仓逐字节一致
状态            ``config.json``、``tasks/``、``solutions/``、``reports/``、``log/``
                ——**只在缺失时创建，永不覆盖**（抄过去只会串味）
缺失才补        ``tasks/TEMPLATE.md``、``.trio/KICKOFF.md``、
                ``AGENTS.md`` 里的框架指针、``.gitignore`` 的框架条目
==============  ==========================================================

只碰这三样，别的一律不动。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import sys
from pathlib import Path

# —— 源仓的 .trio 目录（默认就是本文件所在目录）
SOURCE_DIR = Path(__file__).resolve().parent

# 代码：每次覆盖
CODE_FILES = (
    "bus.py",
    "router.py",
    "as.py",
    "serve.py",
    "check.py",
    "verify.py",
    "a_ledger.py",
    "reproduce.py",
    "trio.py",
    "start.cmd",
)
CODE_DOCS = ("DESIGN.md", "PROTOCOL.md", "PORTING.md", "READINESS.md")
CODE_DIRS = ("roles", "tests")

# 状态：只在缺失时建。
# **刻意不预建 `reports/` 和 `log/`**：`tests/test_gitignore.py` 用
# "reports/ 存在却没有一个证据文件" 来点 A 的名（"是不是只把结论贴进群、没落文件？"）。
# 第一天还没有任务，预建一个空 reports/ 会把这条**真判断**变成一个假红灯。
# 两者都由框架在真的要写的时候自己建。
STATE_DIRS = ("tasks", "solutions")
STATE_FILES = (("tasks", "TEMPLATE.md"),)

# 端口登记表：**逐项目端口不能重复**（两个项目同时开着群界面时不能打架，
# PORTING.md §1 就是这么要求的）。只靠"探一下能不能 bind"不够——另一个项目
# 的界面此刻可能没在跑，bind 得到，等它起来就撞了。所以另记一份全局登记表。
PORT_REGISTRY = Path.home() / ".codex" / "trio-ports.json"

# .gitignore 里框架需要的条目（缺哪条补哪条，已有的行不动）
GITIGNORE_LINES = (
    "__pycache__/",
    "*.py[cod]",
    ".trio/log/",
    ".trio/reports/**/*.jsonl",
    ".trio/reports/*.jsonl",
    ".trio/reports/**/*.raw.json",
)

# 新项目缺 AGENTS.md 时补的一份「薄」指针。**刻意写得很短**：真正的规程在
# .trio/roles/ 里，抄两份只会不一致（见 .trio/tests/test_docs_agree.py 的由来）。
AGENTS_STUB = """# 仓库级说明

本仓库在跑「人 / A / B」三方协作框架，目录在 `.trio/`。
**你（Codex）在这套框架里的角色是 A：方案与验收负责人。** 开工前先读：

1. `.trio/roles/A.md` —— 你是谁、你的循环、你必须停下来问人的三件事
2. `.trio/roles/CONTRACT.md` —— 解决方案 / 任务书 / 交回 / 证据 的格式

群界面：**你不用管**——每次 `drive` 前 router 会自己确保它开着
（`ensure_group_ui()`：没跑就起一个，并把浏览器打开）。手动起只在调试时用，不是流程的一部分。
"""

# 新项目缺 KICKOFF.md 时补的一份。占位符用 @@PROJECT@@（不用 str.format，
# 免得文档里的花括号把自己坑了）。
KICKOFF_TEMPLATE = """# 会话开始提示词（@@PROJECT@@）

> 这份文件是给人看的说明书，**不是每轮都要贴的咒语**。

## 怎么在新项目里启用（两步）

1. 在**新项目目录下**开一个 Codex 会话；
2. 让它跑一次 `python .trio/router.py rotate-a` —— 把总线唤醒接到这个会话上。
   不换的话，B 交付 / 机械闸触发时**没人叫你**，那边静悄悄地停住。

本机的全局规则（`~/.codex/AGENTS.md`）已经写死：**只要仓库里存在
`.trio/roles/A.md`，Codex 就是这套协作里的 A**，会自己读下面那几份。
所以正常情况下你不用贴任何东西。

如果确实想显式说一句，贴这段就够：

> 用「人 / A / B」三方协作做这个仓库。你是 A。
> 先读 `.trio/roles/A.md` 与 `.trio/roles/CONTRACT.md`，
> 再 `python .trio/bus.py tail -n 30` 和 `python .trio/bus.py todos`，
> 最后 `python .trio/router.py rotate-a`。

## A 开工必读

- `.trio/roles/A.md` —— 你是谁、你的循环、你必须停下来问人的三件事
- `.trio/roles/CONTRACT.md` —— 解决方案 / 任务书 / 交回 / 证据 的格式
- `.trio/PORTING.md` §4 —— 已知边界（照搬，不用重新发现）
- `.trio/PORTING.md` §2 —— 闸门阈值**按项目重标**，别照抄源仓

## 群界面

**你不用管**——每次 `drive` 前 router 会自己确保它开着（`ensure_group_ui()`：
没跑就起一个，并把浏览器打开）。人在群里能看到实时活动条。

## 三条红线

1. **你不写实现代码**（实现是 B 的活；你有验收权，没有实现权）。
2. **判据权归你独占**（B 发不出 `verify` / `escalate` / `task` / `kill`，机制强制）。
3. **你不许撒手不管**（B 在跑的时候你要看得见它的动作——看台账与计数，
   不要去读 `.trio/log/raw/` 下的全量事件流）。
"""


def say(msg: str) -> None:
    print(msg)


def copy_file(src: Path, dst: Path, dry: bool) -> str:
    if dry:
        return f"覆盖 {dst}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return f"覆盖 {dst}"


def load_port_registry() -> dict:
    try:
        data = json.loads(PORT_REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def pick_port(target: Path) -> int:
    """给这个项目挑一个端口：起点由目标路径散列决定（可复现），跳过已登记的。"""
    registry = load_port_registry()
    taken = {int(port) for port, path in registry.items() if str(path) != str(target)}
    digest = hashlib.md5(str(target).encode("utf-8")).hexdigest()
    base = 8762 + (int(digest[:8], 16) % 300)
    for port in range(base, base + 600):
        if port in taken:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        registry[str(port)] = str(target)
        try:
            PORT_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
            PORT_REGISTRY.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except Exception:
            pass  # 登记不上也不该拦住安装
        return port
    return base


def detect_modules(root: Path) -> list[str]:
    """粗猜本项目该让 B 做 import 自检的模块：顶层包 + 它们的直接子模块。"""
    found: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        if entry.name in {".trio", "tests", "docs", "assets", "build", "dist"}:
            continue
        if not (entry / "__init__.py").exists():
            continue
        found.append(entry.name)
        for mod in sorted(entry.glob("*.py")):
            if mod.name.startswith("_"):
                continue
            found.append(f"{entry.name}.{mod.stem}")
    return found[:20]


def init_config(target: Path, dry: bool) -> str:
    """config.json 只在缺失时生成，且把**必须逐项目不同**的四项换成新项目的值。"""
    dst = target / ".trio" / "config.json"
    if dst.exists():
        return "保留（已存在）"
    source = SOURCE_DIR / "config.json"
    if not source.exists():
        return "跳过（源仓没有 config.json）"
    if dry:
        return f"生成 {dst}（新端口 / 空 a_session / 重猜 import 模块）"
    cfg = json.loads(source.read_text(encoding="utf-8"))
    cfg["group_port"] = pick_port(target)
    cfg["a_session"] = ""
    cfg["import_check_modules"] = detect_modules(target)
    cfg["test_baseline"] = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"生成 {dst}（端口 {cfg['group_port']}，a_session 空，import 模块 {len(cfg['import_check_modules'])} 个）"


def ensure_gitignore(target: Path, dry: bool) -> str:
    path = target / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [line for line in GITIGNORE_LINES if line not in existing.splitlines()]
    if not missing:
        return "已齐全"
    if dry:
        return f"补 {len(missing)} 条：{', '.join(missing)}"
    block = "\n# —— 三方协作框架（由 .trio/trio.py 补）\n" + "\n".join(missing) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(block)
    return f"补了 {len(missing)} 条"


def ensure_agents(target: Path, dry: bool) -> str:
    path = target / "AGENTS.md"
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        if ".trio/roles/A.md" in text:
            return "保留（已提到 .trio/roles/A.md）"
        if dry:
            return f"追加框架指针 → {path}"
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + AGENTS_STUB)
        return "追加了框架指针"
    if dry:
        return f"新建 {path}"
    path.write_text(AGENTS_STUB, encoding="utf-8")
    return "新建"


def ensure_kickoff(target: Path, dry: bool) -> str:
    path = target / ".trio" / "KICKOFF.md"
    if path.exists():
        return "保留（已存在）"
    if dry:
        return f"新建 {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        KICKOFF_TEMPLATE.replace("@@PROJECT@@", target.name), encoding="utf-8"
    )
    return "新建"


def install(target: Path, kit: Path, dry: bool) -> int:
    if not target.exists() or not target.is_dir():
        say(f"[trio] 目标不是目录：{target}")
        return 2
    if not (kit / "bus.py").exists():
        say(f"[trio] 源仓不像框架（没有 {kit / 'bus.py'}）；用 --kit 指对目录")
        return 2

    say(f"[trio] 源：{kit}")
    say(f"[trio] 目标：{target}{'（dry-run）' if dry else ''}")

    copied = 0
    for name in CODE_FILES:
        src = kit / name
        if not src.exists():
            say(f"  · 源缺 {name}，跳过")
            continue
        copy_file(src, target / ".trio" / name, dry)
        copied += 1
    for name in CODE_DOCS:
        src = kit / name
        if not src.exists():
            say(f"  · 源缺 {name}，跳过")
            continue
        copy_file(src, target / ".trio" / name, dry)
        copied += 1
    for name in CODE_DIRS:
        src = kit / name
        if not src.is_dir():
            say(f"  · 源缺 {name}/，跳过")
            continue
        for item in sorted(src.rglob("*")):
            if "__pycache__" in item.parts or not item.is_file():
                continue
            rel = item.relative_to(src)
            copy_file(item, target / ".trio" / name / rel, dry)
            copied += 1
    say(f"[trio] 代码：{copied} 个文件{'（dry-run 未写）' if dry else ''}已同步")

    for name in STATE_DIRS:
        path = target / ".trio" / name
        if not path.exists() and not dry:
            path.mkdir(parents=True, exist_ok=True)
    for parent, name in STATE_FILES:
        dst = target / ".trio" / parent / name
        src = kit / parent / name
        if dst.exists() or not src.exists():
            continue
        copy_file(src, dst, dry)

    say(f"[trio] config.json：{init_config(target, dry)}")
    say(f"[trio] .gitignore：{ensure_gitignore(target, dry)}")
    say(f"[trio] AGENTS.md：{ensure_agents(target, dry)}")
    say(f"[trio] KICKOFF.md：{ensure_kickoff(target, dry)}")

    if not (target / ".git").exists():
        say("[trio] 注意：目标不是 git 仓库——框架要提交证据，建议先 git init")
    if not dry:
        say("")
        say("[trio] 下一步（在**新项目目录**下开一个 Codex 会话，然后**按这个顺序**）：")
        say("  1. python .trio/router.py rotate-a      ← 必须最先做：**首次接线**，接上本仓最新的那个会话")
        say("       （同一仓同时开了不止一个会话时它会拒绝，改用 --show 看清 + --session <id>）")
        say("  2. python .trio/tests/run_all.py --fast ← 做完第 1 步才会全绿（自检守着 a_session 非空）")
        say("  3. python .trio/bus.py todos            ← 看有没有上个会话的交接")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把三方协作框架安装 / 同步到另一个项目")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inst = sub.add_parser("install", help="安装 / 更新目标项目")
    inst.add_argument("target", help="目标项目目录")
    inst.add_argument("--kit", default=None, help="骨架仓的 .trio 目录（默认=本文件所在目录）")
    inst.add_argument("--dry-run", action="store_true", help="只报告，不写任何东西")
    args = parser.parse_args(argv)

    if args.cmd == "install":
        kit = Path(args.kit).resolve() if args.kit else SOURCE_DIR
        return install(Path(args.target).resolve(), kit, args.dry_run)
    return 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
