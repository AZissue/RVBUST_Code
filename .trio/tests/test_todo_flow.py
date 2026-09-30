#!/usr/bin/env python3
"""待办端到端：**真起 serve.py**（临时群日志）→ 页面看得见 → POST 勾掉 → 群里落一条消息。

为什么值得一个集成测试：T-007 那次"待办栏做好了人却看不见"，
根因是页面没刷新；但当时我连"点按钮到底会不会勾掉"都只手工验过一次。
现在 `serve.py --log-dir` 让这件事可以**重复跑、不碰真群日志**。

零成本：只起本地 HTTP 服务与子进程，不调任何模型。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TRIO = REPO / ".trio"
sys.path.insert(0, str(TRIO))

import bus  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_http(url: str, timeout: float = 15.0) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last = exc
            time.sleep(0.25)
    raise AssertionError(f"服务没起来：{last}")


class TodoEndToEnd(unittest.TestCase):
    """判据 5 + 6：临时群日志起服务，端到端勾掉一条待办。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmp.name)
        (self.log_dir / "raw").mkdir(parents=True, exist_ok=True)
        self.group_log = self.log_dir / "group.jsonl"
        # 先塞一条待办进去（服务端要读的是**这个**日志，不是仓库里的那份）
        self.todo_text = "端到端测试用的待办：按一下 Shift"
        entry = {
            "seq": 1,
            "ts": bus.now_iso(),
            "role": bus.A,
            "kind": "todo",
            "text": self.todo_text,
            "task": "T-TEST",
            "refs": [],
            "meta": {},
        }
        self.group_log.write_text(json.dumps(entry, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        self.port = free_port()
        self.server = subprocess.Popen(
            [sys.executable, str(TRIO / "serve.py"), "--port", str(self.port),
             "--log-dir", str(self.log_dir)],
            cwd=str(REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.base = f"http://127.0.0.1:{self.port}"
        self.page = wait_for_http(self.base + "/")

    def tearDown(self):
        self.server.terminate()
        try:
            self.server.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self.server.kill()
        self.tmp.cleanup()

    def read_log(self) -> list[dict]:
        lines = self.group_log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def test_page_shows_the_todo_with_a_done_button(self):
        self.assertIn("data-todos", self.page)
        self.assertIn('data-todo="1"', self.page)
        self.assertIn('data-done="1"', self.page)
        self.assertIn("完成", self.page)

    def test_api_events_carries_page_version_and_todos(self):
        raw = wait_for_http(self.base + "/api/events?since=0")
        data = json.loads(raw)
        self.assertIn("page_version", data, "判据 1：/api/events 要带页面版本")
        self.assertTrue(data.get("todos"), "未完成待办应当出现在 /api/events 里")

    def test_post_todo_done_closes_it_for_real(self):
        body = json.dumps({"todo_id": "1"}).encode("utf-8")
        request = urllib.request.Request(
            self.base + "/api/todo_done", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload.get("ok"))

        # 群里真的多了一条 HUMAN 的勾掉消息……
        messages = self.read_log()
        closing = [m for m in messages if m.get("kind") == "todo" and (m.get("meta") or {}).get("done")]
        self.assertEqual(len(closing), 1, f"应当只有一条勾掉消息：{messages}")
        self.assertEqual(closing[0]["role"], bus.HUMAN)
        self.assertEqual(str((closing[0].get("meta") or {}).get("todo_id")), "1")

        # ……而且这条待办不再算未完成
        original_log = bus.GROUP_LOG
        bus.GROUP_LOG = self.group_log
        try:
            self.assertEqual(bus.open_todos(), [], "勾掉之后 open_todos 不该再列它")
        finally:
            bus.GROUP_LOG = original_log

    def test_repo_log_untouched(self):
        """判据 5：--log-dir 是隔离的，不许碰仓库里的 .trio/log/。"""
        repo_log = REPO / ".trio" / "log" / "group.jsonl"
        if repo_log.exists():
            self.assertNotIn(
                self.todo_text, repo_log.read_text(encoding="utf-8", errors="replace")
            )


if __name__ == "__main__":
    unittest.main()
