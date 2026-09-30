#!/usr/bin/env python3
"""A 侧**唯一**的验收入口：把任务书 §2 的判据表跑成一次调用。

**它治的是什么，说清楚**（2026-09-23 实测标定）：

不是"少跑命令"——全库 3445 条 A 命令里，跑测试只占 **1.5%**、跑探针 **2.5%**，
真正的开销大头是 A **读源码**（**60.5%**，2083 条 / 7.89 MB 输出）。
所以这个工具**不会**让 A 的总动作数明显下降，**不许把它宣传成那样**。

它治的是**回灌**：T-005 交付 5 次、回灌 4 次，每一轮 A 都要把判据面**重新探索一遍**。
判据一旦落成文件，"这一轮到底哪条没过、实测值是多少"就是一次调用 + 一份 `verify.json`，
回灌时可以带原文，A 不必重新走一遍。

用法::

    python .trio/verify.py T-005           # 跑判据 + 基线自检
    python .trio/verify.py T-005 --pre     # 发任务书之前跑：期望判据全红
    python .trio/verify.py T-005 --json

判据文件 ``.trio/tasks/<任务号>.checks.py`` 是**纯数据**，A 不写逻辑::

    MANUAL = [11]                      # 人眼判的判据号——列进报告，不被悄悄跳过

    CHECKS = [
        # ① 命令型
        {"n": 10, "name": "既有测试一项不少", "cmd": [...], "exit": 0, "stdout_has": "OK"},
        # ② 数值型（声明式）——一条判据可挂多个条件
        {"n": 2, "name": "不再步进", "json": "reports/t005/smoothness.json",
         "all": [{"path": "c2_step_px.p50", "le": 6,  "unit": "px"},
                 {"path": "c2_step_px.p95", "le": 13, "unit": "px"}]},
        # ③ 带容差的约等于
        {"n": 1, "name": "逻辑拍不变", "json": "...",
         "all": [{"path": "tick_ms", "approx": 167, "tol": 0.10}]},
    ]

**没有 `run` callable 形态**，故意的：Windows 上没有 `SIGALRM`，**callable 无法超时**，
而 `cmd` 形态有 subprocess timeout 兜底；in-process 执行还会串味（`check.py --smoke`
真建 Tk 窗口，前一条判据留下的全局状态会污染后一条）；而且 `AttributeError` 与
"行为真的不对"在 callable 里不可区分。装不下的判据请写成**独立脚本**，
用 `cmd` 形态调——顺带满足 `roles/A.md` 那条"探针要写成文件，不要用一次性命令"。

退出码：0 = 全过；1 = 有判据没过；2 = **checks 文件本身有问题**（写错了 / 缺文件 / 编号乱）。
把 1 和 2 分开，是为了不让"判据没过"和"判据写错了"混成同一个结论。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import py_compile
import re
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

TRIO_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRIO_DIR.parent
TASK_DIR = TRIO_DIR / "tasks"
REPORT_DIR = TRIO_DIR / "reports"

# 模块级就要把 `.trio/` 挂上 sys.path：`bus` 是本目录的平级模块。
# 只写在 `__main__` 里的话，测试 import 本模块时 `import bus` 会炸。
if str(TRIO_DIR) not in sys.path:
    sys.path.insert(0, str(TRIO_DIR))

# 输出有界——**截的是失败原文，不是汇总**：每条的「名字 + ✓/✗」那一行永远完整，
# 否则 A 看不见"到底哪几条没过"，就得再跑一次，正好把省下的又还回去。
# 有界性是**结构性**的（不靠一个总长度阀门）：汇总行数 = 判据条数，失败原文封顶
# MAX_INLINE_FAILURES × MAX_DETAIL_CHARS，其余全部落到 verify.json 里。
MAX_DETAIL_CHARS = 2000      # 单条失败原文的上限
MAX_INLINE_FAILURES = 3      # 内联几条失败原文；其余只进 verify.json


# ---------------------------------------------------------------- 判据执行


def _num(value) -> float | None:
    """把 JSON 里的数转成 float；转不了就返回 None。

    注意**不能用 `value or fallback`**——`0.0` 是合法实测值（拍边界偏差正好 0.0），
    会被当成假值。（`reproduce.py` 写这句话时真踩过一次。）
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_path(data, dotted: str):
    """按点号取嵌套键。取不到返回 ``(False, None)``——**取不到算失败，不算通过**。"""
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit():
            index = int(part)
            if not -len(cur) <= index < len(cur):
                return False, None
            cur = cur[index]
        else:
            return False, None
    return True, cur


def eval_condition(cond: dict, data) -> tuple[bool, str]:
    """判一条 ``{"path": ..., "le"|"lt"|"ge"|"gt"|"eq"|"approx"+, "unit": ...}``。"""
    path = cond.get("path", "")
    unit = cond.get("unit", "")
    found, value = get_path(data, path)
    if not found:
        return False, f"{path} 取不到（探针没吐这个键？）"

    if "approx" in cond:
        want = _num(cond["approx"])
        tol = _num(cond.get("tol")) or 0.0
        got = _num(value)
        if want is None or got is None:
            return False, f"{path} = {value!r}，不是数"
        lo, hi = want * (1 - tol), want * (1 + tol)
        ok = lo <= got <= hi
        return ok, f"{path} = {got:g}{unit}（期望 {want:g}±{tol:.0%}，即 {lo:g}~{hi:g}）"

    if "eq" in cond:
        want = cond["eq"]
        # `eq` 允许比非数值——`frozen = True`、`status = "ok"` 都是合法判据。
        # 只有两边都是真正的数时才走数值比较（顺带避开 `True == 1` 这种 Python 陷阱）。
        both_numbers = _num(want) is not None and _num(value) is not None
        ok = (_num(value) == _num(want)) if both_numbers else (value == want)
        shown = f"{_num(value):g}" if both_numbers else repr(value)
        wanted = f"{_num(want):g}" if both_numbers else repr(want)
        return ok, f"{path} = {shown}{unit if both_numbers else ''}（期望 = {wanted}）"

    for op, symbol in (("le", "≤"), ("lt", "<"), ("ge", "≥"), ("gt", ">")):
        if op in cond:
            want = _num(cond[op])
            got = _num(value)
            if want is None:
                return False, f"{op} 的期望值 {cond[op]!r} 不是数"
            if got is None:
                return False, f"{path} = {value!r}，不是数"
            table = {"le": got <= want, "lt": got < want,
                     "ge": got >= want, "gt": got > want}
            return table[op], f"{path} = {got:g}{unit}（期望 {symbol} {want:g}）"

    return False, f"{path} 没给比较算子（le/lt/ge/gt/eq/approx）"


def run_cmd(argv: list[str], timeout: int) -> tuple[int, str]:
    """跑一条命令，**合并 stdout 与 stderr**。

    必须合并：unittest 的汇总（``Ran N tests`` / ``OK``）写在 **stderr** 上，
    只抓 stdout 会把"全绿"误报成失败。（`reproduce.py` 的注释记着这个坑。）
    """
    try:
        proc = subprocess.run(argv, cwd=str(REPO_ROOT), text=True, encoding="utf-8",
                              errors="replace", capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return 127, f"找不到命令：{argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"超时（{timeout}s）：{' '.join(argv)}"
    return proc.returncode, ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()


def _load_json(rel: str):
    """读一份 JSON 证据。成功返回解析后的对象，失败返回**原因字符串**。

    相对路径先按 ``.trio/`` 解析、再按仓库根解析。为什么这么定：
    `roles/CONTRACT.md` §4 给证据文件举的例子就是 ``reports/T-005/...``（``.trio/`` 相对），
    而 `router.py` 写进群里的 ``refs`` 是仓库根相对（``.trio/reports/...``）。
    两种写法在本仓都真实存在，所以两条都试，**不猜**——都没命中就把两个候选都报出来。
    """
    candidates = [TRIO_DIR / rel, REPO_ROOT / rel]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return f"读不到 {rel}：{type(exc).__name__}: {exc}"
    tried = "、".join(_show(p) for p in candidates)
    return f"读不到 {rel}（找过 {tried}）——探针没跑？还是路径写错了？"


def _show(path: Path) -> str:
    """给人看的路径：能缩成相对路径就缩，缩不了（在仓库外）就用绝对路径。

    `relative_to` 在路径不在仓库下时会**抛 ValueError**——而已配置的证据目录
    未必都在仓库里，所以这里不能裸调。
    """
    for base in (REPO_ROOT, TRIO_DIR):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def run_check(check: dict, timeout: int) -> dict:
    """跑一条判据，返回 ``{n, name, ok, detail}``。"""
    n = check.get("n")
    name = check.get("name") or f"判据 {n}"
    result = {"n": n, "name": name, "ok": False, "detail": ""}

    conds = check.get("all") or [check]
    if "json" in check or any("json" in c for c in conds):
        # 一条判据可以跨**多个**证据文件：每条条件能自带 ``json`` 覆盖（例如
        # "第 1 关 ≥5 帧/拍、第 3 关加速态 ≥2 帧/拍"读的是两份探针输出）。
        cache: dict[str, object] = {}
        details, ok = [], True
        for cond in conds:
            rel = cond.get("json", check.get("json"))
            if not rel:
                ok = False
                details.append("这条条件没说读哪个 json 文件")
                continue
            if rel not in cache:
                cache[rel] = _load_json(rel)
            data = cache[rel]
            if isinstance(data, str):        # 字符串 = 失败原因
                ok = False
                details.append(data)
                continue
            good, text = eval_condition(cond, data)
            ok = ok and good
            details.append(("✓" if good else "✗") + " " + text)
        result["ok"] = ok
        result["detail"] = "\n".join(details)
        return result

    if "cmd" in check:
        argv = [str(x) for x in check["cmd"]]
        rc, text = run_cmd(argv, timeout)
        want_exit = int(check.get("exit", 0))
        ok = rc == want_exit
        if ok and check.get("stdout_has") is not None:
            ok = str(check["stdout_has"]) in text
        result["ok"] = ok
        result["detail"] = (f"$ {' '.join(argv)}\n退出码 {rc}（期望 {want_exit}）\n"
                            + "\n".join(text.splitlines()[-20:]))
        return result

    result["detail"] = "这条判据既没有 cmd 也没有 json——不知道该怎么跑它"
    return result


# ---------------------------------------------------------------- checks 文件


def load_checks(task: str):
    """加载 ``tasks/<task>.checks.py``。返回 ``(module, None)`` 或 ``(None, 错误消息)``。

    **先 py_compile**：`.trio/tasks/*.checks.py` 不在任何既有的语法检查范围内
    （`tests/run_all.py` 只 glob `.trio/` 根下的 `*.py`），
    而"checks 文件写错了"和"判据没过"是两个完全不同的结论，不能混。
    """
    path = TASK_DIR / f"{task}.checks.py"
    if not path.exists():
        return None, (f"没有 {path.relative_to(REPO_ROOT)}。\n"
                      f"  把任务书 §2 的判据表落成这个文件（格式见本文件开头）。\n"
                      f"  这是 A 的活：判据只有 A 能写。")
    try:
        py_compile.compile(str(path), doraise=True, cfile=str(Path(tempfile.gettempdir()) / "verify_checks.pyc"))
    except py_compile.PyCompileError as exc:
        return None, f"{path.relative_to(REPO_ROOT)} **语法就是错的**（这不是判据没过）：\n{exc}"

    spec = importlib.util.spec_from_file_location(f"_checks_{task.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - 如实报告
        return None, (f"{path.relative_to(REPO_ROOT)} 导入就炸了（这不是判据没过）：\n"
                      f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
    return module, None


def validate_checks(checks: list[dict], manual: list[int]) -> str | None:
    """编号不许重复、不许断档。返回错误消息或 None。"""
    numbers = []
    for check in checks:
        n = check.get("n")
        if not isinstance(n, int):
            return f"有一条判据没给整数判据号 n：{check.get('name')!r}"
        numbers.append(n)
    if len(set(numbers)) != len(numbers):
        dupes = sorted({x for x in numbers if numbers.count(x) > 1})
        return f"判据号重复：{dupes}"
    if manual:
        overlap = sorted(set(numbers) & set(manual))
        if overlap:
            return f"这些号既在 CHECKS 又在 MANUAL 里：{overlap}"
    expected = set(range(1, max(numbers + list(manual) or [0]) + 1))
    missing = sorted(expected - set(numbers) - set(manual))
    if missing:
        return (f"判据号断档：{missing} 既没有自动判据也没标进 MANUAL。\n"
                f"  每条判据都得有归宿——要么写成 check，要么写进 MANUAL（人眼判）。")
    return None


# ---------------------------------------------------------------- 基线


def parse_ran(text: str) -> int | None:
    match = re.search(r"^Ran (\d+) tests?", text, re.MULTILINE)
    return int(match.group(1)) if match else None


def baseline(timeout: int) -> list[dict]:
    """既有测试基线。**两套都跑**。

    游戏侧套数要和 ``config.json`` 的 ``test_baseline`` 对上；
    框架侧只要求退出码 0——**但不能漏**：``discover -s tests`` 不覆盖 `.trio/`，
    而这次改的恰恰是 `.trio/`。
    """
    import bus  # 同目录，延迟导入以免 --json 等路径也付出代价

    cfg = bus.config()
    want = cfg.get("test_baseline")
    results: list[dict] = []

    rc, text = run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], timeout)
    ran = parse_ran(text)
    if want is None:
        results.append({"name": "游戏侧既有测试", "ok": False,
                        "detail": ("config.json 里没有 test_baseline —— **基线缺失必须响亮地失败**，\n"
                                   "  不许默认成 0（那会让这条判据悄悄变成永真）。\n"
                                   "  实测当前值填进去：python .trio/verify.py <任务号> --set-baseline")})
    elif rc != 0:
        results.append({"name": f"游戏侧既有测试（{ran if ran is not None else '?'} 项）", "ok": False,
                        "detail": "\n".join(text.splitlines()[-20:])})
    elif ran != int(want):
        results.append({"name": f"游戏侧既有测试：{ran} 项，基线 {want}", "ok": False,
                        "detail": (f"测试数和基线对不上。\n"
                                   f"  · 掉到 {ran}：多半是真退化了，去看上面哪一项红了；\n"
                                   f"  · 你**故意**重构了测试（比如把 20 个方法并成 1 个参数化）\n"
                                   f"    导致计数合法下降：改 config.json 的 test_baseline（现在是 {want}），\n"
                                   f"    或跑 `python .trio/verify.py <任务号> --set-baseline`。\n"
                                   f"  · 不许为了让这条变绿而把基线调低却说不清理由。")})
    else:
        results.append({"name": f"游戏侧既有测试 {ran} 项（= 基线）", "ok": True, "detail": ""})

    rc2, text2 = run_cmd([sys.executable, str(TRIO_DIR / "tests" / "run_all.py"), "--fast"], timeout)
    results.append({"name": "框架侧零成本自检", "ok": rc2 == 0,
                    "detail": "" if rc2 == 0 else "\n".join(text2.splitlines()[-20:])})
    return results


# ---------------------------------------------------------------- 主流程


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="A 侧唯一的验收入口")
    parser.add_argument("task", help="任务号，例如 T-005")
    parser.add_argument("--pre", action="store_true",
                        help="发任务书之前跑：期望新行为的判据全红（见条目的 pre 键）")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--set-baseline", type=int, metavar="N", help="把游戏侧测试基线重设为 N")
    parser.add_argument("--no-baseline", action="store_true", help="跳过既有测试基线")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    import bus

    if args.set_baseline is not None:
        old, _ = bus.update_config(test_baseline=args.set_baseline)
        print(f"test_baseline: {old.get('test_baseline', '(未设)')} → {args.set_baseline}")
        return 0

    module, error = load_checks(args.task)
    if error:
        print(f"[checks] {error}")
        return 2

    checks = list(getattr(module, "CHECKS", []))
    manual = list(getattr(module, "MANUAL", []))
    problem = validate_checks(checks, manual)
    if problem:
        print(f"[checks] {problem}")
        return 2

    # --pre 只跑标了 pre 的：red = 实现前必须失败，green = 实现前也必须通过的不变量。
    if args.pre:
        selected = [(c, c.get("pre")) for c in checks if c.get("pre") in ("red", "green")]
        if not selected:
            print("[pre] 没有任何判据标了 pre 键——全红断言没地方落。")
            print("      给新行为的判据加 \"pre\": \"red\"，给不变量加 \"pre\": \"green\"。")
            return 2
        results = [{**run_check(c, args.timeout), "pre": pre} for c, pre in selected]
        surprises = [r for r in results
                     if (r["pre"] == "red" and r["ok"]) or (r["pre"] == "green" and not r["ok"])]
        for r in results:
            mark = "✓" if r["ok"] else "✗"
            tag = "提前绿" if (r["pre"] == "red" and r["ok"]) else ""
            print(f"  {mark} [判据 {r['n']}] {r['name']} {tag}")
        print()
        if surprises:
            for r in surprises:
                if r["pre"] == "red":
                    print(f"  ⚠ [判据 {r['n']}] {r['name']} 在**实现之前就是绿的**——"
                          f"它测的不是新行为，改判据。")
                else:
                    print(f"  ⚠ [判据 {r['n']}] {r['name']} 标了 pre=green 但不变量已经破了。")
            _write_report(args.task, "pre", [], [], results, 1)
            return 1
        print(f"  ✓ {len(results)} 条断言全红（red 的都红、green 的都绿）——可以发任务书了")
        _write_report(args.task, "pre", [], [], results, 0)
        return 0

    base = [] if args.no_baseline else baseline(args.timeout)
    results = [run_check(c, args.timeout) for c in checks]

    for r in base:
        print(f"  {'✓' if r['ok'] else '✗'} 基线：{r['name']}")
    for r in results:
        print(f"  {'✓' if r['ok'] else '✗'} [判据 {r['n']}] {r['name']}")
    if manual:
        print(f"  ⚪ 需人工（**不计入自动通过**）：判据 {manual}")

    failed = [r for r in base + results if not r["ok"]]
    if failed:
        print(f"\n{'─' * 60}\n失败原文（前 {min(len(failed), MAX_INLINE_FAILURES)} 条，其余见 verify.json）：")
        shown, truncated = 0, 0
        for r in failed:
            if shown >= MAX_INLINE_FAILURES:
                truncated += 1
                continue
            detail = r["detail"][:MAX_DETAIL_CHARS]
            if len(r["detail"]) > MAX_DETAIL_CHARS:
                detail += f"\n  …（原文 {len(r['detail'])} 字符，已截断）"
            print(f"\n  ✗ {r['name']}\n    " + detail.replace("\n", "\n    "))
            shown += 1
        if truncated:
            print(f"\n  还有 {truncated} 条失败的原文没内联——都在 verify.json 里。")

    verdict = 0 if not failed else 1
    path = _write_report(args.task, "verify", base, manual, results, verdict)
    print(f"\n{'✓ 全部通过' if verdict == 0 else f'✗ {len(failed)} 项没过'}")
    print(f"  证据：{_show(path) if path else '(未写)'}")
    return verdict


def _write_report(task: str, mode: str, base: list[dict], manual: list[int],
                  results: list[dict], verdict: int) -> Path | None:
    """写 ``reports/<任务号小写去连字符>/verify.json``，例如 T-005 → ``reports/t005/``。

    目录名**一律小写、并去掉连字符**。两条理由：
    · Windows 上 `reports/T-005/` 和 `reports/t-005/` 是同一个目录，看着没事；
      搬到 Linux 会分叉成两个，git 会当成两份证据。
    · 去掉连字符是为了**对齐已有的证据目录**（`t002 t005 t008 t012` … 都是这个写法）——
      新写的代码跟着既有的来，别自己另立一套。
    """
    out_dir = REPORT_DIR / task.lower().replace("-", "")
    payload = {
        "task": task,
        "mode": mode,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict,
        "manual": manual,          # 人眼判的，永远不算自动通过
        "baseline": base,
        "checks": results,
    }
    with contextlib.suppress(OSError):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "verify.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path
    return None


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.path.insert(0, str(TRIO_DIR))
    sys.exit(main())
