#!/usr/bin/env python3
"""机械闸的自测：**不调用任何模型、不花一分钱。**

这些测试是"机制"能不能被相信的依据——上一版的教训正是"纪律写在提示词里，
没人验证机制到底拦不拦得住"。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TRIO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TRIO_DIR))

import router  # noqa: E402

CFG = {
    "repeat_threshold": 3,
    "no_progress_warn": 12,
    "no_progress_actions": 30,
    "stall_events_warn": 2000,
    "stall_events_kill": 8000,
    "wall_seconds": 600,
    "task_cny": 1.5,
    "session_cny": 3.0,
}


def tool(name: str, **inputs):
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": name, "input": inputs}]},
    }


def read(path: str):
    return tool("Read", file_path=path)


def write(path: str):
    return tool("Edit", file_path=path, old_string="a", new_string="b")


def bash(command: str):
    return tool("Bash", command=command)


def feed(watcher, events):
    """喂一串事件，返回第一个触发的结果（没有就 None）。"""
    for event in events:
        verdict = watcher.observe(event)
        if verdict:
            return verdict
    return None


class RepeatRule(unittest.TestCase):
    def test_same_command_three_times_fires(self):
        """「改一版跑一版」的指纹：同一条命令反复跑。"""
        watcher = router.GateWatcher(CFG, "T-001")
        verdict = feed(watcher, [bash("python -m pytest -q")] * 3)
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict["reason"], "repeat")

    def test_two_times_does_not_fire(self):
        watcher = router.GateWatcher(CFG, "T-001")
        self.assertIsNone(feed(watcher, [bash("ls")] * 2))

    def test_repeated_edits_are_not_repeat(self):
        """反复编辑同一个文件是**正常工作**，不是空转。"""
        watcher = router.GateWatcher(CFG, "T-001")
        events = [write("snake/core.py") for _ in range(10)]
        self.assertIsNone(feed(watcher, events))

    def test_repeated_reads_fire(self):
        watcher = router.GateWatcher(CFG, "T-001")
        verdict = feed(watcher, [read("snake/core.py")] * 3)
        self.assertEqual(verdict["reason"], "repeat")


class NoProgressRule(unittest.TestCase):
    def test_warns_before_it_kills(self):
        """两级：先软告警（不掐断），再硬掐断。"""
        watcher = router.GateWatcher(CFG, "T-001")
        # 只读到软告警线
        for index in range(CFG["no_progress_warn"]):
            verdict = watcher.observe(read(f"f{index}.py"))
            self.assertIsNone(verdict, "软告警阶段不应该掐断")
        warnings = watcher.pop_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["reason"], "no-progress-warn")

        # 继续读到硬闸
        verdict = None
        for index in range(CFG["no_progress_warn"], CFG["no_progress_actions"] + 1):
            verdict = watcher.observe(read(f"g{index}.py"))
            if verdict:
                break
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict["reason"], "no-progress")

    def test_a_write_resets_the_streak(self):
        watcher = router.GateWatcher(CFG, "T-001")
        for index in range(CFG["no_progress_actions"] - 1):
            self.assertIsNone(watcher.observe(read(f"f{index}.py")))
        watcher.observe(write("snake/core.py"))       # 写一下就归零
        for index in range(CFG["no_progress_actions"] - 1):
            self.assertIsNone(watcher.observe(read(f"h{index}.py")))


class StallEventsRule(unittest.TestCase):
    def test_event_volume_is_what_catches_the_real_blowup(self):
        """真出病时（一堆非动作事件夹着 12 次工具调用）由事件量兜底。"""
        watcher = router.GateWatcher(CFG, "T-001")
        chatter = {"type": "assistant", "message": {"content": []}}
        verdict = None
        # 12 次动作（**远低于无进展硬闸的 30 次**），中间夹着大量非工具事件
        for index in range(12):
            verdict = verdict or watcher.observe(read(f"f{index}.py"))
            for _ in range(700):
                verdict = verdict or watcher.observe(chatter)
        # 动作数这条路上什么都没发生——这正是要靠事件量兜底的原因
        self.assertLess(watcher.actions, CFG["no_progress_actions"])
        self.assertIsNotNone(verdict, "事件堆到硬闸了，居然没反应")
        self.assertEqual(verdict["reason"], "stall-events")
        # 且是两级：软告警先响过，硬掐断后到
        self.assertIn("stall-events-warn", [w["reason"] for w in watcher.warnings])

    def test_thinking_tokens_do_not_trip_the_event_gate(self):
        """思考增量不算"真动作"：本仓库实测一轮 14176 条事件里 13943 条是它。

        2026-09-23 改：旧口径把 `system/thinking_tokens` 也计入事件量，
        于是**每一轮正常交付**都吃一次 2000 事件的软告警——闸门响得越勤，越没人当真。
        """
        watcher = router.GateWatcher(CFG, "T-001")
        thinking = {"type": "system", "subtype": "thinking_tokens", "delta": "嗯"}
        verdict = None
        for _ in range(5000):
            verdict = verdict or watcher.observe(thinking)
        self.assertIsNone(verdict, "光是思考不该被掐断")
        self.assertEqual(watcher.warnings, [], "也不该发软告警")
        self.assertEqual(watcher.events_since_write, 0, "思考增量不该进事件量闸")
        self.assertEqual(watcher.events, 5000, "总事件数照样记（活动条要用）")

    def test_wall_and_cost_are_independent_gates(self):
        watcher = router.GateWatcher(CFG, "T-001", started=0)  # 很久以前开始
        self.assertEqual(watcher.check_wall()["reason"], "wall")
        self.assertIsNone(watcher.check_cost(1.0, 1.0))
        self.assertEqual(watcher.check_cost(1.6, 1.6)["reason"], "cost-task")
        self.assertEqual(watcher.check_cost(0.1, 3.1)["reason"], "cost-session")


class HealthyRoundDoesNotFire(unittest.TestCase):
    def test_interleaved_read_and_write_is_fine(self):
        watcher = router.GateWatcher(CFG, "T-001")
        events = []
        for index in range(20):
            events += [read(f"snake/{index}.py"), write("snake/core.py")]
        self.assertIsNone(feed(watcher, events))
        self.assertEqual(watcher.warnings, [])


class Fingerprint(unittest.TestCase):
    def test_bash_fingerprint_ignores_whitespace(self):
        left = router.tool_fingerprint({"name": "Bash", "input": {"command": "ls   -la"}})
        right = router.tool_fingerprint({"name": "Bash", "input": {"command": "ls -la"}})
        self.assertEqual(left, right)

    def test_edit_fingerprint_ignores_content(self):
        """改同一文件的不同内容，指纹相同——但 Edit 不参与重复计数。"""
        left = router.tool_fingerprint(
            {"name": "Edit", "input": {"file_path": "a.py", "new_string": "x"}}
        )
        right = router.tool_fingerprint(
            {"name": "Edit", "input": {"file_path": "a.py", "new_string": "y"}}
        )
        self.assertEqual(left, right)


class WhitelistIsTight(unittest.TestCase):
    def test_leaked_python_c_escape_hatch_is_gone(self):
        """上一版的白名单里开着 `Bash(python -c *)`——一把万能钥匙。它必须不在。"""
        import json

        configured = json.loads(
            (TRIO_DIR / "config.json").read_text(encoding="utf-8")
        )["b_allowed_tools"]
        self.assertNotIn("Bash(python -c *", configured)
        self.assertIn("check.py", configured)
        self.assertIn("as.py b", configured)

    def test_defaults_do_not_ship_the_escape_hatch_either(self):
        """默认值也不能留着那把钥匙——config.json 缺失时兜底的正是它。"""
        import bus

        defaults = bus.DEFAULTS["b_allowed_tools"]
        self.assertNotIn("Bash(python -c *", defaults)
        # 白名单里不该出现任何能跑测试/能起进程的命令
        for forbidden in ("pytest", "unittest", "python -m snake", "start "):
            self.assertNotIn(forbidden, defaults)


if __name__ == "__main__":
    unittest.main()
