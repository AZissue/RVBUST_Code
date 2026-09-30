#!/usr/bin/env python3
"""`router.py rotate-a` 的自测：**不调模型、不花钱、不碰真 config、不碰真 Codex 目录。**

这个命令值得有测试，不是因为它逻辑多，而是因为**它写坏的东西是静默的**：

``bus.config()`` 会把 ``JSONDecodeError`` 吞掉、回落到 ``DEFAULTS``，而 ``DEFAULTS`` 里
**没有** ``a_session``——于是 ``wake_a`` 永远返回 False、B 交付再也没人唤醒 A，
整条链上没有任何一步会报错（``bus.update_config`` 的 docstring 就是为这个写的）。
换会话原来是**人手改 config.json**，所以这道风险本来就在；``rotate-a`` 的价值全在
它比手改多出来的校验与回滚，所以这里逐条压那些校验：

* **cwd 校验**——``session_index.jsonl`` 是**机器全局**的（实测 24 条只有少数属于本仓），
  盲取最新 = 唤醒投到别的项目去。这里造的假索引就按真实比例来：新的那条在别的仓。
* **原子写 + 保键**——``_`` 注释键一个都不能丢（``test_group_ui_comes_up.py`` 用 utf-8
  读 config.json，写坏直接红）。
* **写后自检**——只信 ``update_config`` 的返回值不够，实测一遍 ``bus.config()``
  （那才是 ``wake_a`` 走的同一条路）才算数。
* **回滚**——任何一步失败都不许留半改状态。

最后一条收尾断言专门防"测试自己弄脏仓库"：``test_router.py:182`` 的 ``WhitelistIsTight``
**直接读真的 ``.trio/config.json``**，这里的测试要是把真文件改了，红的是别人。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TRIO_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TRIO_DIR.parent
sys.path.insert(0, str(TRIO_DIR))

import a_ledger  # noqa: E402
import bus  # noqa: E402
import router  # noqa: E402

#: 真 config.json 在**导入时**的样子。setUpModule 与收尾断言都拿它比。
REAL_CONFIG = (TRIO_DIR / "config.json").read_bytes()

CONFIG_BODY = {
    "_说明": "本文件覆盖 bus.py 里的 DEFAULTS。改动要保注释键。",
    "wall_seconds": 600,
    "task_cny": 1.5,
    "_a_session_说明": "A 的会话 id；B 交付时用它唤醒。",
    "a_session": "11111111-1111-1111-1111-111111111111",
    "b_allowed_tools": "Read,Glob,Grep",
    "_test_baseline_说明": "既有测试套数。",
    "test_baseline": 258,
}

HERE = "11111111-1111-1111-1111-111111111111"   # 当前会话
NEWER = "22222222-2222-2222-2222-222222222222"  # 本仓、比当前新 → 该被选中
OLDER = "33333333-3333-3333-3333-333333333333"  # 本仓、比当前老
OTHER = "44444444-4444-4444-4444-444444444444"  # **别的项目**、比谁都新
OTHER2 = "55555555-5555-5555-5555-555555555555"  # 别的项目、很老


class RotateATestCase(unittest.TestCase):
    """把 config / 会话索引 / rollout 树全指到临时目录——真东西一个都不碰。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "Repo"
        self.elsewhere = self.root / "Elsewhere"
        self.sessions = self.root / "sessions" / "2026" / "09" / "23"
        for path in (self.repo, self.elsewhere, self.sessions):
            path.mkdir(parents=True)

        self.cfg = self.root / "config.json"
        self.write_config(CONFIG_BODY)
        self.index = self.root / "session_index.jsonl"
        self.index.write_text("", encoding="utf-8")

        self._orig = (
            bus.CONFIG_PATH, router.REPO_ROOT, router.CODEX_SESSION_INDEX,
            a_ledger.ROLLOUT_DIR,
        )
        bus.CONFIG_PATH = self.cfg
        router.REPO_ROOT = self.repo
        router.CODEX_SESSION_INDEX = self.index
        a_ledger.ROLLOUT_DIR = self.root / "sessions"

    def tearDown(self):
        (bus.CONFIG_PATH, router.REPO_ROOT, router.CODEX_SESSION_INDEX,
         a_ledger.ROLLOUT_DIR) = self._orig
        self._tmp.cleanup()

    # ---- 帮手 ----

    def write_config(self, body: dict) -> None:
        self.cfg.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    def add_session(self, sid: str, cwd, at: str, name: str = "") -> None:
        """往假索引里加一条 + 造一个对应的 rollout 文件（首行带 cwd）。"""
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"id": sid, "thread_name": name, "updated_at": at}) + "\n")
        # 文件名里的时间戳只要形如 `2026-09-23T10-06-14`，取值不影响挑选（挑选看 updated_at）
        stamp = at.replace(":", "-")[:19]
        (self.sessions / f"rollout-{stamp}-{sid}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"cwd": str(cwd)}}) + "\n",
            encoding="utf-8")

    def run_rotate(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = router.main(["rotate-a", *argv])
        return code, buf.getvalue()

    @property
    def session_now(self):
        return json.loads(self.cfg.read_text(encoding="utf-8"))["a_session"]

    def assertConfigUntouched(self, why: str = ""):
        self.assertEqual(self.cfg.read_bytes(), self._snapshot, why)

    def snapshot(self):
        self._snapshot = self.cfg.read_bytes()


# ---------------------------------------------------------------- 候选挑选


class Picking(RotateATestCase):
    def test_newest_overall_is_another_project_so_it_must_fall_through(self):
        """**这是这个命令存在的理由。** 索引里最新的那条在别的仓，必须跳过它取本仓最新的。

        实测比例：`session_index.jsonl` 24 条横跨 4 个项目，rollout 文件 33 个里
        只有 5 个属于本仓。盲取最新 = 唤醒投到别的项目去，而这边静悄悄地没人管。
        """
        self.add_session(OTHER2, self.elsewhere, "2026-09-01T00:00:00Z")
        self.add_session(OLDER, self.repo, "2026-09-02T00:00:00Z")
        self.add_session(HERE, self.repo, "2026-09-03T00:00:00Z")        # 当前
        self.add_session(NEWER, self.repo, "2026-09-04T00:00:00Z")       # 该选这个
        self.add_session(OTHER, self.elsewhere, "2026-09-05T00:00:00Z")  # 最新，但不是本仓
        code, out = self.run_rotate()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.session_now, NEWER)
        self.assertNotIn(OTHER, self.session_now)

    def test_only_other_project_sessions_is_refused_without_writing(self):
        self.add_session(OTHER2, self.elsewhere, "2026-09-01T00:00:00Z")
        self.add_session(OTHER, self.elsewhere, "2026-09-04T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate()
        self.assertEqual(code, 2, out)
        self.assertIn("没有一个开在本仓", out)
        self.assertConfigUntouched()

    def test_explicitly_named_session_from_another_project_is_refused(self):
        """`--session` 是逃生口，**不是**绕过 cwd 校验的后门。"""
        self.add_session(OTHER, self.elsewhere, "2026-09-04T00:00:00Z")
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate("--session", OTHER)
        self.assertEqual(code, 1, out)
        self.assertIn("拒绝", out)
        self.assertIn(str(self.elsewhere), out)
        self.assertConfigUntouched()

    def test_explicit_session_not_in_index_errors(self):
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate("--session", OTHER2)
        self.assertEqual(code, 2, out)
        self.assertIn("没有", out)
        self.assertConfigUntouched()

    def test_cwd_comes_from_the_newest_rollout_file_of_that_session(self):
        """一个会话会换 rollout 文件续写——cwd 要取**最新那个文件的首行**。

        这条不是学究：旧文件可能是在别的目录开的（搬过仓），拿旧的就会误判。
        """
        self.add_session(OLDER, self.elsewhere, "2026-09-01T00:00:00Z")   # 旧：他仓
        # NEWER 会话：先在别处开过，后来在本仓续写（新的那个文件排后面）。
        # 当前会话 HERE **故意不放进索引**——不然"最新本仓会话"就是它，会走 no-op 那条路。
        self.add_session(NEWER, self.elsewhere, "2026-09-02T00:00:00Z")
        (self.sessions / f"rollout-2026-09-23T18-00-00-{NEWER}_99999999-9999-9999-9999-999999999999.jsonl"
         ).write_text(json.dumps({"type": "session_meta", "payload": {"cwd": str(self.repo)}}) + "\n",
                      encoding="utf-8")
        code, out = self.run_rotate()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.session_now, NEWER)


# ---------------------------------------------------------------- 写与不写


class Writing(RotateATestCase):
    def test_same_id_is_a_noop_and_the_file_is_byte_identical(self):
        """已经是最新会话 → **一个字都不写**。写一遍等于白白重排一遍人的文件。"""
        self.add_session(HERE, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate()
        self.assertEqual(code, 0, out)
        self.assertIn("一个字没动", out)
        self.assertConfigUntouched()

    def test_show_lists_candidates_and_writes_nothing(self):
        self.add_session(OTHER, self.elsewhere, "2026-09-04T00:00:00Z")
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.add_session(HERE, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate("--show")
        self.assertEqual(code, 0, out)
        self.assertIn("→ 当前", out)   # 当前会话被标出来
        self.assertIn("✗ 他仓", out)   # 别的项目也被标出来
        self.assertConfigUntouched()

    def test_write_keeps_every_comment_key_and_every_other_value(self):
        """`_` 注释键与其余键值**一个都不能变**——`bus.update_config` 的唯一职责。"""
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        code, out = self.run_rotate()
        self.assertEqual(code, 0, out)
        after = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(after["a_session"], NEWER)
        for key, value in CONFIG_BODY.items():
            if key != "a_session":
                self.assertEqual(after[key], value, f"{key} 被动了")
        self.assertEqual(list(after), list(CONFIG_BODY), "键顺序变了")
        self.assertIn("注释键无损", out)

    def test_missing_index_errors_and_writes_nothing(self):
        self.index.unlink()
        self.snapshot()
        code, out = self.run_rotate()
        self.assertEqual(code, 2, out)
        self.assertIn("session_index.jsonl", out)
        self.assertConfigUntouched()

    def test_config_without_a_session_is_refused_rather_than_created(self):
        """配置文件里没有 `a_session` = **这条链已经断了**，此时凭空补一个更坏。"""
        self.write_config({"_说明": "没写 a_session"})
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate()
        self.assertEqual(code, 2, out)
        self.assertIn("没有 a_session", out)
        self.assertConfigUntouched()

    def test_empty_explicit_session_is_refused_not_silently_auto_picked(self):
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate("--session", "")
        self.assertEqual(code, 2, out)
        self.assertIn("给空了", out)
        self.assertConfigUntouched()

    # ---- 首次接线（2026-09-29）---------------------------------------------
    # `.trio/trio.py install` 写下的 a_session 是**空串** = 「还没接过线」。
    # 这和「键不在 = config 坏了」必须分开，否则新项目装完框架第一步就被挡在门外。

    def _fresh_config(self) -> None:
        body = dict(CONFIG_BODY)
        body["a_session"] = ""
        self.write_config(body)

    def test_empty_a_session_is_a_first_bind_not_a_broken_config(self):
        self._fresh_config()
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        code, out = self.run_rotate()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.session_now, NEWER)
        self.assertIn("首次接线", out)

    def test_first_bind_refuses_to_guess_between_two_in_repo_sessions(self):
        """本仓候选不止一个就别猜——猜错的一样是"唤醒投给了另一个会话"。"""
        self._fresh_config()
        self.add_session(OLDER, self.repo, "2026-09-02T00:00:00Z")
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate()
        self.assertEqual(code, 2, out)
        self.assertIn("不替你猜", out)
        self.assertConfigUntouched()

    def test_first_bind_takes_an_explicit_session(self):
        self._fresh_config()
        self.add_session(OLDER, self.repo, "2026-09-02T00:00:00Z")
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        code, out = self.run_rotate("--session", OLDER)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.session_now, OLDER)

    def test_first_bind_still_refuses_a_session_from_another_repo(self):
        """首次接线不是"放行"：cwd 校验照旧，他仓的会话一律不接。"""
        self._fresh_config()
        self.add_session(OTHER, self.elsewhere, "2026-09-03T00:00:00Z")
        self.snapshot()
        code, out = self.run_rotate("--session", OTHER)
        self.assertEqual(code, 1, out)
        self.assertConfigUntouched()


# ---------------------------------------------------------------- 回滚


class Rollback(RotateATestCase):
    def test_failed_postwrite_selfcheck_rolls_back_to_the_old_session(self):
        """写后自检走 `bus.config()`——**那才是 wake_a 读 config 的同一条路**。

        `update_config` 自己也会重新读一遍，但它读的是文件；`config()` 还额外经过
        "坏文件静默回落 DEFAULTS" 那一层，所以两遍都得过。
        """
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        original_config = bus.config
        calls = {"n": 0}

        def flaky():
            """**只**让写后那一次读坏掉：开头的 `current` 那次必须是真的，
            否则走的是"config 里没有 a_session"那条早退，验不到回滚。"""
            calls["n"] += 1
            return original_config() if calls["n"] == 1 else {"a_session": None}

        try:
            bus.config = flaky
            code, out = self.run_rotate()
        finally:
            bus.config = original_config
        self.assertEqual(code, 1, out)
        self.assertIn("自检失败", out)
        self.assertIn("已回滚", out)
        self.assertConfigUntouched()
        self.assertEqual(self.session_now, HERE)

    def test_selftest_wake_failure_rolls_back(self):
        """`codex queue` 投不出去 = 这个会话 id 是死的 → 换过去等于主动熄火。"""
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        self.snapshot()
        original_wake = bus.wake_a
        try:
            bus.wake_a = lambda *a, **k: False
            code, out = self.run_rotate("--self-test")
        finally:
            bus.wake_a = original_wake
        self.assertEqual(code, 1, out)
        self.assertIn("唤醒自测发不出去", out)
        self.assertConfigUntouched()
        self.assertEqual(self.session_now, HERE)

    def test_selftest_wake_success_keeps_the_new_session(self):
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        seen = []
        original_wake = bus.wake_a
        try:
            bus.wake_a = lambda *a, **k: (seen.append(a) or True)
            code, out = self.run_rotate("--self-test")
        finally:
            bus.wake_a = original_wake
        self.assertEqual(code, 0, out)
        self.assertEqual(self.session_now, NEWER)
        self.assertTrue(seen, "自检没真发唤醒")
        self.assertIn("peek_codex_queue.py", out)   # 告诉人怎么确认被消费

    def test_without_selftest_it_says_delivery_is_unverified(self):
        """默认**不**花这笔钱，但也**不**假装验过了。"""
        self.add_session(NEWER, self.repo, "2026-09-03T00:00:00Z")
        original_wake = bus.wake_a
        try:
            bus.wake_a = lambda *a, **k: self.fail("没加 --self-test 却发了唤醒")
            code, out = self.run_rotate()
        finally:
            bus.wake_a = original_wake
        self.assertEqual(code, 0, out)
        self.assertIn("未验证", out)


# ---------------------------------------------------------------- 收尾


class TheRealConfigIsUntouched(unittest.TestCase):
    def test_repo_config_json_is_byte_identical_to_import_time(self):
        """测试自己不许弄脏仓库：`test_router.py:182` 的 `WhitelistIsTight` 直接读它。"""
        self.assertEqual((TRIO_DIR / "config.json").read_bytes(), REAL_CONFIG)

    def test_real_config_still_points_at_a_session(self):
        """顺带守住"静默熄火"那条：真 config 里 `a_session` 必须还在、还是非空的。"""
        body = json.loads(REAL_CONFIG.decode("utf-8"))
        self.assertTrue(str(body.get("a_session") or "").strip(),
                        "真 config.json 的 a_session 空了——B 交付将再也唤不醒 A")


if __name__ == "__main__":
    unittest.main(verbosity=2)
