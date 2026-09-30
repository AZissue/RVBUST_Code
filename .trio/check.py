#!/usr/bin/env python3
"""B 侧唯一允许的"导入级自检"入口。

为什么需要它：上一版给 B 的白名单里有 ``Bash(python -c *)``——那是一把**万能钥匙**，
任意 Python 代码都能走，于是"禁止自写自测"这条纪律在机制上形同虚设。

收紧之后，B 能跑的 Python 只有三条：
    1. ``python .trio/check.py <模块>``   ← 本文件，只能做 import
    2. ``python -m py_compile <文件>``    ← 只能做语法检查
    3. ``python .trio/as.py b ...``       ← 只能在群里以 B 的身份发言

用法::

    python .trio/check.py snake.appstate snake.audio
    python .trio/check.py --all            # 按 config.json 里的清单全查

退出码 0 = 全部可导入；1 = 有失败。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import sys
import traceback
from pathlib import Path

TRIO_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRIO_DIR.parent


def load_targets() -> list[str]:
    """从 config.json 读 ``import_check_modules``（默认空）。"""
    path = TRIO_DIR / "config.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    value = data.get("import_check_modules") or []
    return [str(item) for item in value]


def check(modules: list[str]) -> int:
    if not modules:
        print("[check] 没有给出模块，也没有在 config.json 里配置 import_check_modules")
        return 1
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    failures = 0
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - 这里就是要抓住一切并如实报告
            failures += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
        else:
            print(f"[ok]   {name}")
    print(f"[check] {len(modules) - failures}/{len(modules)} 可导入")
    return 1 if failures else 0


def smoke() -> int:
    """实例化级冒烟：真建一个隐藏窗口、走一帧、看该有的 canvas item 都在。

    为什么加这一条（2026-09-23，T-011 试点）：B 把 ``Renderer._build_items`` 的名字
    弄丢了（合并进新写的 ``_build_border``），而 ``py_compile`` 与 ``--all``（只 import）
    **都看不出来**——那要**实例化**才会炸：``AttributeError: 'Renderer' object has no
    attribute '_build_items'``。于是 A 的验收才发现，白跑一轮。

    无显示环境自动跳过（返回 0 并说明），不假装绿。
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        import tkinter as tk

        probe = tk.Tk()
        probe.destroy()
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] 跳过：本机没有可用显示环境（{exc}）")
        return 0

    from snake import app as app_module
    from snake import render
    from snake.audio import AudioEngine

    app = app_module.SnakeApp(seed=0, level=1, audio=AudioEngine(enabled=False))
    try:
        app.root.update()
        border = len(app.canvas.find_withtag(getattr(render, "TAG_BORDER", "border")))
        checks = {
            "窗口构造出来": True,
            "蛇身 item 数 = 蛇长": len(app.canvas.find_withtag(render.TAG_SNAKE)) == app.game.length,
            "食物 item 在": bool(app.renderer._food_item),
            "奖励 item 在": bool(app.renderer._reward_item),
            "外圈墙 2*(宽+高) 块": border == 2 * (app.game.width + app.game.height),
        }
        app.renderer.update(0.5)  # 插值路径
        app._tick()               # 逻辑拍 + 终态重绘
        for name, passed in checks.items():
            print(f"[{'ok' if passed else 'FAIL'}]   {name}")
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            print(f"[smoke] {len(failed)} 项不通过：{'、'.join(failed)}")
            return 1
        print("[smoke] 实例化冒烟通过")
        return 0
    except Exception as exc:  # noqa: BLE001 - 这里就是要抓住一切并如实报告
        print(f"[smoke] 实例化就炸了：{type(exc).__name__}: {exc}")
        traceback.print_exc(limit=4)
        return 1
    finally:
        with contextlib.suppress(Exception):
            app.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导入级自检（B 侧唯一允许的自检）")
    parser.add_argument("modules", nargs="*", help="要导入的模块名")
    parser.add_argument("--all", action="store_true", help="用 config.json 里的清单")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="实例化级冒烟：真建一个隐藏窗口、走一帧、看该有的 canvas item 都在",
    )
    args = parser.parse_args(argv)

    if args.smoke:
        return smoke()
    modules = load_targets() if args.all else list(args.modules)
    return check(modules)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
