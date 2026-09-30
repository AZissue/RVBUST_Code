#!/usr/bin/env python3
"""保住那条**断了就让人变瞎子**的机制：界面必须真的起来，浏览器必须真的被叫到。

上一轮就是这里断的。A 和 B 在群里说了 30 句、提交了 3 个 commit，人一句没看见——
不是没建界面，界面早就建好了、30 条消息一条不少，**是没人在监听 8761**。
病根是当时把"建好了"当成了"会打开"：`KICKOFF.md` 让 Codex 别碰浏览器，
让用户自己去双击 `start.cmd`。规则写在文档里求谁去做，就没有任何东西保证它成立。

所以这里不查源码字符串，**真起一个进程、真占一个端口、真问它要页面、真看浏览器有没有被叫**。

两个坑（都踩过）：
  * `BROWSER` 必须在 **import webbrowser 之前**设进环境，惰性注册才不会漏读；
    这里靠子进程继承环境来满足——子进程是干净的，它自己 import。
  * BROWSER 里**要用正斜杠**。`GenericBrowser` 走 `shlex.split`，POSIX 模式下
    `\\` 是转义符，`C:\\Python314\\python.exe` 会被啃成 `C:Python314python.exe`，
    然后静默失败——`webbrowser.open()` 照样返回 True，浏览器却没开。
    （这正是"返回 True 不等于开了"的实例，所以下面断言的是**记录文件**，不是返回值。）

零成本：本地端口 + 假浏览器，不调任何模型。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

TRIO = Path(__file__).resolve().parent.parent
REPO = TRIO.parent
sys.path.insert(0, str(TRIO))
sys.path.insert(0, str(REPO))

# 页面里必须有这些东西，少一个都说明服务起来的不是我们的群界面
PAGE_MARKERS = ("三方工作群", "renderLive", "api/live", "掐断")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def alive(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wait_alive(port: int, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if alive(port):
            return True
        time.sleep(0.2)
    return False


class GroupUiColdStart(unittest.TestCase):
    """冷路径：端口上什么都没有 → 起来 → 开浏览器。热路径：别重复起。"""

    def setUp(self) -> None:
        self.port = free_port()
        self.tmp = tempfile.TemporaryDirectory()
        self.record = Path(self.tmp.name) / "opened.txt"
        recorder = Path(self.tmp.name) / "rec.py"
        recorder.write_text(
            "import sys, pathlib\n"
            f"pathlib.Path(r'{self.record}').open('a', encoding='utf-8')"
            ".write('OPENED ' + ' '.join(sys.argv[1:]) + '\\n')\n",
            encoding="utf-8",
        )
        # 正斜杠！反斜杠会被 shlex 吃掉（见文件头）
        self._old_browser = os.environ.get("BROWSER")
        os.environ["BROWSER"] = (
            f"{Path(sys.executable).as_posix()} {recorder.as_posix()} %s"
        )
        self.spawned = []

    def tearDown(self) -> None:
        for proc in self.spawned:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                pass
        if self._old_browser is None:
            os.environ.pop("BROWSER", None)
        else:
            os.environ["BROWSER"] = self._old_browser
        self.tmp.cleanup()

    def _cfg(self) -> dict:
        cfg = json.loads((TRIO / "config.json").read_text(encoding="utf-8"))
        cfg["group_port"] = self.port
        cfg["group_idle_exit"] = 30  # 万一漏杀，它自己也会退
        return cfg

    def test_cold_start_raises_the_ui_and_calls_a_browser(self):
        import router

        real_popen = router.subprocess.Popen

        def spy(*a, **k):
            proc = real_popen(*a, **k)   # 真跑，只是留个句柄好清理
            self.spawned.append(proc)
            return proc

        router.subprocess.Popen = spy
        try:
            url = router.ensure_group_ui(self._cfg())
            self.assertEqual(url, f"http://127.0.0.1:{self.port}/")
            self.assertTrue(
                wait_alive(self.port, 15),
                f"ensure_group_ui 返回了 {url}，但 {self.port} 上没人监听——"
                "正是上一轮让人变成瞎子的那个失败",
            )
        finally:
            router.subprocess.Popen = real_popen

        # 页面得真的是我们的群界面
        with urllib.request.urlopen(url, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            page = resp.read().decode("utf-8", "replace")
        for marker in PAGE_MARKERS:
            self.assertIn(marker, page, f"页面里没有 {marker!r}，起的不是群界面")

        # 浏览器得真被叫到。断言的**不是返回值**——返回 True 而不开是已知的假绿。
        deadline = time.time() + 10
        while time.time() < deadline and not self.record.exists():
            time.sleep(0.2)
        self.assertTrue(
            self.record.exists(),
            "serve.py 起来了但 webbrowser.open 没被叫到——界面还是没人看得见",
        )
        self.assertIn(
            url, self.record.read_text(encoding="utf-8"),
            "浏览器被叫了，但打开的不是群界面那个地址",
        )

    def test_warm_call_does_not_start_a_second_server(self):
        import router

        real_popen = router.subprocess.Popen
        calls = []

        def spy(*a, **k):
            calls.append(a)
            proc = real_popen(*a, **k)
            self.spawned.append(proc)
            return proc

        router.subprocess.Popen = spy
        try:
            first = router.ensure_group_ui(self._cfg())
            self.assertTrue(wait_alive(self.port, 15), "第一次就没起来")
            second = router.ensure_group_ui(self._cfg())
        finally:
            router.subprocess.Popen = real_popen

        self.assertEqual(first, second)
        self.assertEqual(
            len(calls), 1,
            f"热路径又起了一个：起了 {len(calls)} 次。"
            "router 每个任务都会调它，重复起会攒一堆进程",
        )


if __name__ == "__main__":
    unittest.main()
