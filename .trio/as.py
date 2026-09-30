#!/usr/bin/env python3
"""以**固定身份**往群里发言的薄壳。

为什么需要它：如果直接允许 B 跑 ``bus.py post --role B ...``，那条命令里的 ``--role``
就是一个可以改成 ``A`` 的参数——B 能冒充 A，判据权和验收权当场失效。

所以给每个角色一个**把身份写死**的入口，白名单里只放这个入口::

    python .trio/as.py b --kind deliver --task T-001 --text "..."
    python .trio/as.py a --kind task --task T-001 --text "..."

``as.py`` 不接受 ``--role``，身份由子命令决定，冒充在机制上不可能。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bus  # noqa: E402  （必须在 sys.path 调整之后导入）


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="以固定身份往群里发言")
    sub = parser.add_subparsers(dest="role", required=True)

    for role in ("a", "b"):
        child = sub.add_parser(role, help=f"以 {role.upper()} 的身份发言")
        child.add_argument("--kind", required=True, help=f"消息类型，见 bus.KIND_LABEL")
        child.add_argument("--text", required=True)
        child.add_argument("--task")
        child.add_argument("--ref", action="append", default=[])
        # 待办（kind=todo）：新建时不带 --todo-id；勾掉时带上它的 id 与 --done
        child.add_argument("--todo-id", help="要更新的待办 id（新建时不填）")
        child.add_argument("--done", action="store_true", help="把这条待办勾掉")

    args = parser.parse_args(argv)
    role = args.role.upper()

    meta = None
    if args.todo_id or args.done or args.kind == bus.TODO_KIND:
        meta = {}
        if args.todo_id:
            meta["todo_id"] = args.todo_id
        if args.done:
            meta["done"] = True

    try:
        message = bus.post(
            role, args.kind, args.text, task=args.task, refs=args.ref, meta=meta
        )
    except PermissionError as exc:
        print(f"[拒绝] {exc}", file=sys.stderr)
        return 3

    print(f"#{message['seq']} {role} {message['kind']}: {message['text'][:120]}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
