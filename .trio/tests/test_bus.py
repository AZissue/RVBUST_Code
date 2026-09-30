#!/usr/bin/env python3
"""总线的自测：**不调用任何模型。**

重点测的是"边界是不是机制"——尤其是那条红线：**人的消息永远唤不醒 B**。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TRIO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TRIO_DIR))

import bus  # noqa: E402


class BusTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (bus.LOG_DIR, bus.GROUP_LOG, bus.RAW_DIR)
        # 自检里**不许真去唤醒 A**：`bus.post` 见到 B/deliver 这类消息会调
        # `codex queue`，那是真开销、还会把 A 叫起来好几次。
        self._wake_orig = bus.WAKE_ENABLED
        bus.WAKE_ENABLED = False
        log_dir = Path(self._tmp.name)
        bus.LOG_DIR = log_dir
        bus.GROUP_LOG = log_dir / "group.jsonl"
        bus.RAW_DIR = log_dir / "raw"

    def tearDown(self) -> None:
        bus.WAKE_ENABLED = self._wake_orig
        bus.LOG_DIR, bus.GROUP_LOG, bus.RAW_DIR = self._orig
        self._tmp.cleanup()


class Permissions(BusTestCase):
    def test_b_cannot_verify(self):
        """B 夺不走验收权。"""
        with self.assertRaises(PermissionError):
            bus.post(bus.B, "verify", "我觉得我做完了")

    def test_b_cannot_escalate_or_task_or_kill(self):
        for kind in ("escalate", "task", "kill"):
            with self.assertRaises(PermissionError):
                bus.post(bus.B, kind, "x")

    def test_b_can_deliver_and_plan(self):
        for kind in ("plan", "deliver", "say", "note"):
            message = bus.post(bus.B, kind, "ok")
            self.assertEqual(message["kind"], kind)

    def test_human_cannot_post_task(self):
        """人不能绕过 A 直接下任务。"""
        with self.assertRaises(PermissionError):
            bus.post(bus.HUMAN, "task", "去做这个")

    def test_human_can_say_and_kill(self):
        self.assertEqual(bus.post(bus.HUMAN, "say", "你好")["role"], bus.HUMAN)
        self.assertEqual(bus.post(bus.HUMAN, "kill", "停")["kind"], "kill")

    def test_unknown_role_rejected(self):
        with self.assertRaises(PermissionError):
            bus.post("C", "say", "我是谁")


class WakeRules(BusTestCase):
    def test_human_only_wakes_a_never_b(self):
        """★ 红线：B 永远收不到人的消息。"""
        message = bus.post(bus.HUMAN, "say", "这个功能改成这样")
        targets = bus.wake_targets(message)
        self.assertEqual(targets, [bus.A])
        self.assertNotIn(bus.B, targets)

    def test_only_task_and_kill_wake_b(self):
        self.assertEqual(bus.wake_targets({"role": bus.A, "kind": "task"}), [bus.B])
        self.assertEqual(bus.wake_targets({"role": bus.A, "kind": "kill"}), [bus.B])
        self.assertEqual(bus.wake_targets({"role": bus.A, "kind": "verify"}), [])
        self.assertEqual(bus.wake_targets({"role": bus.A, "kind": "say"}), [])

    def test_b_wakes_a(self):
        self.assertEqual(bus.wake_targets({"role": bus.B, "kind": "say"}), [bus.A])
        self.assertEqual(bus.wake_targets({"role": bus.B, "kind": "deliver"}), [bus.A])

    def test_system_gate_wakes_a_not_b(self):
        self.assertEqual(bus.wake_targets({"role": bus.SYSTEM, "kind": "gate"}), [bus.A])
        self.assertEqual(bus.wake_targets({"role": bus.SYSTEM, "kind": "note"}), [])

    def test_wait_for_skips_messages_it_cannot_act_on(self):
        bus.post(bus.HUMAN, "say", "只给 A 的")
        # B 不该被人的消息唤醒；这里用 0 超时，立刻返回 None
        self.assertIsNone(bus.wait_for(bus.B, since=0, timeout=0.1))


class Sequencer(BusTestCase):
    def test_seq_increments_and_read_filters(self):
        first = bus.post(bus.A, "note", "1")
        second = bus.post(bus.A, "note", "2")
        self.assertEqual(second["seq"], first["seq"] + 1)
        self.assertEqual([m["text"] for m in bus.read(since=first["seq"])], ["2"])
        self.assertEqual(bus.last_seq(), second["seq"])

    def test_tasks_collects_ids(self):
        bus.post(bus.A, "task", "a", task="T-001")
        bus.post(bus.B, "deliver", "b", task="T-001")
        bus.post(bus.A, "task", "c", task="T-002")
        self.assertEqual(bus.tasks(), ["T-001", "T-002"])

    def test_raw_stream_is_append_only(self):
        bus.append_raw("b-T-001", {"type": "assistant"})
        bus.append_raw("b-T-001", "not json at all")
        items = bus.read_raw("b-T-001")
        self.assertEqual(items[0], {"type": "assistant"})
        self.assertEqual(items[1], "not json at all")


class WakeA(BusTestCase):
    """唤醒 A：该叫的才叫、叫法正确、叫不动也不影响消息落库。"""

    def setUp(self) -> None:
        super().setUp()
        self.calls: list[list[str]] = []
        self._orig_config = bus.config

        def fake_run(argv, **kwargs):
            self.calls.append(list(argv))

            class Done:
                returncode = 0

            return Done()

        import subprocess

        self._orig_run = subprocess.run
        subprocess.run = fake_run  # type: ignore[assignment]
        bus.config = lambda: {"a_session": "test-session-id", "a_wake_cmd": "codex"}  # type: ignore[assignment]

    def tearDown(self) -> None:
        import subprocess

        subprocess.run = self._orig_run  # type: ignore[assignment]
        bus.config = self._orig_config  # type: ignore[assignment]
        super().tearDown()

    def test_b_deliver_wakes_a_with_queue(self):
        bus.WAKE_ENABLED = True
        bus.post(bus.B, "deliver", "交付：改完了")
        self.assertEqual(len(self.calls), 1, f"应当叫醒一次：{self.calls}")
        argv = self.calls[0]
        self.assertEqual(argv[0], "codex")
        self.assertIn("queue", argv)
        self.assertIn("--thread", argv)
        self.assertEqual(argv[argv.index("--thread") + 1], "test-session-id")

    def test_b_plan_does_not_wake_a(self):
        """B 的技术方案不打断 A：下一轮读群自然会看到，叫醒一次是要花钱的。"""
        bus.WAKE_ENABLED = True
        bus.post(bus.B, "plan", "我打算这么改")
        self.assertEqual(self.calls, [])

    def test_human_todo_does_not_wake_a(self):
        bus.WAKE_ENABLED = True
        bus.post(bus.HUMAN, "todo", "记得按一下 Shift")
        self.assertEqual(self.calls, [])

    def test_wake_failure_does_not_break_posting(self):
        bus.WAKE_ENABLED = True

        def boom(argv, **kwargs):
            raise OSError("codex 不在 PATH 上")

        import subprocess

        subprocess.run = boom  # type: ignore[assignment]
        message = bus.post(bus.B, "deliver", "交付：改完了")
        self.assertEqual(message["kind"], "deliver", "叫醒失败也必须把消息落库")
        self.assertEqual([m["text"] for m in bus.read(0)], ["交付：改完了"])


class Todos(BusTestCase):
    """待办：A 能开、人也能开与勾；勾掉之后 open_todos 不再列它。"""

    def test_who_can_post_todos(self):
        self.assertTrue(bus.can_post(bus.A, "todo"))
        self.assertTrue(bus.can_post(bus.HUMAN, "todo"))
        self.assertFalse(bus.can_post(bus.B, "todo"), "B 不该能给人派活")

    def test_open_until_someone_closes_it(self):
        created = bus.post(bus.A, "todo", "按住 Shift 确认加速", task="T-003")
        self.assertEqual(
            [item["todo_id"] for item in bus.open_todos()], [str(created["seq"])]
        )
        bus.post(
            bus.HUMAN, "todo", "按过了",
            meta={"todo_id": created["seq"], "done": True},
        )
        self.assertEqual(bus.open_todos(), [], "勾掉之后不该再列出来")

    def test_two_todos_are_independent(self):
        first = bus.post(bus.A, "todo", "第一件")
        bus.post(bus.A, "todo", "第二件")
        bus.post(bus.A, "todo", "第一件做完", meta={"todo_id": first["seq"], "done": True})
        self.assertEqual([item["text"] for item in bus.open_todos()], ["第二件"])

    def test_todo_has_a_label(self):
        self.assertEqual(bus.KIND_LABEL["todo"], "待办")


class PermissionMatrixIsComplete(BusTestCase):
    def test_every_pair_is_decidable(self):
        """矩阵必须覆盖所有角色——靠 get() 的默认空集合兜底。"""
        for role in bus.ROLES:
            self.assertIn(role, bus.PERMISSIONS)
            for kind in bus.KIND_LABEL:
                bus.can_post(role, kind)  # 不抛异常即算覆盖

    def test_b_kinds_are_exactly_the_safe_ones(self):
        self.assertEqual(
            sorted(bus.PERMISSIONS[bus.B]), ["deliver", "note", "plan", "say"]
        )


if __name__ == "__main__":
    unittest.main()
