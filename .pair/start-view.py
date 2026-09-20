#!/usr/bin/env python3
"""会话第 0 步用：确保看板服务在跑（幂等，不会起第二个）。

用法：``python .pair/start-view.py [--port 8760] [--idle-exit 3600]``

行为：

* 端口已经在跑 → 直接报告「已在运行」，不重复起；
* 没在跑 → 以脱离进程启动 ``live.py``，等端口就绪后报告 URL；
* 最后打印一行给 agent 看的提示：要不要把 URL 挂到右侧面板。

只读日志、不调用模型、不消耗 token。
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PAIR_DIR = Path(__file__).resolve().parent
REPO_ROOT = PAIR_DIR.parent


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="确保实时看板服务在运行（幂等）")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--idle-exit", type=int, default=3600)
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"

    if port_open(args.port):
        print(f"[view] 已在运行：{url}（未重复启动）")
    else:
        creation = 0
        if os.name == "nt":
            creation = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        subprocess.Popen(
            [
                sys.executable,
                str(PAIR_DIR / "live.py"),
                "--port",
                str(args.port),
                "--idle-exit",
                str(args.idle_exit),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creation,
            close_fds=True,
        )
        for _ in range(40):
            if port_open(args.port):
                break
            time.sleep(0.25)
        if port_open(args.port):
            print(f"[view] 已启动：{url}（空闲 {args.idle_exit}s 后自动退出）")
        else:
            print("[view] 启动失败，端口没有就绪")
            return 1

    print(f"[view] 下一步：把 {url} 挂到右侧面板（先用 listTabs 查，同 URL 标签存在就复用；")
    print("[view] 本会话最多新建一个标签）——agent 看不到用户自己开的标签，别重复开。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
