"""编排器自己的测试（不调用模型）。

放在 `.pair/tests/` 下，跟产品测试分开跑：

    python -m unittest discover -s .pair/tests -t .pair
"""

import importlib.util
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

PAIR_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PAIR_DIR.parent

spec = importlib.util.spec_from_file_location("orchestrate", PAIR_DIR / "orchestrate.py")
orchestrate = importlib.util.module_from_spec(spec)
sys.modules["orchestrate"] = orchestrate
spec.loader.exec_module(orchestrate)  # type: ignore[union-attr]


QUEUE_SAMPLE = """# 批次 001

## 修 A 缺陷
- inbox: .pair/inbox/010.md
- verify: python -m unittest tests.test_a
- max_attempts: 2

## 补 B 文档
- inbox: .pair/inbox/011.md
- verify: python -c "print('ok')"

这些是补充说明，应并入 notes。

## 需要人听的部分
- inbox: .pair/inbox/012.md
- verify: manual
"""


class ParseQueueTests(unittest.TestCase):
    def test_parses_all_tasks_and_fields(self):
        tasks = orchestrate.parse_queue(QUEUE_SAMPLE)
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].title, "修 A 缺陷")
        self.assertEqual(tasks[0].inbox, ".pair/inbox/010.md")
        self.assertEqual(tasks[0].verify, "python -m unittest tests.test_a")
        self.assertEqual(tasks[0].max_attempts, 2)
        # 自由文本归属它所在的那个任务块（样例里那段话在任务 2 下面）
        self.assertIn("补充说明", tasks[1].notes)
        self.assertEqual(tasks[0].notes, "")

    def test_defaults_and_manual_detection(self):
        tasks = orchestrate.parse_queue(QUEUE_SAMPLE)
        self.assertEqual(tasks[1].max_attempts, 3, "默认 3 次尝试")
        self.assertFalse(tasks[1].manual)
        self.assertTrue(tasks[2].manual, "verify: manual 应被识别为需要人判断")

    def test_ignores_prose_before_first_task(self):
        tasks = orchestrate.parse_queue("# 标题\n\n一些说明\n\n## 任务一\n- inbox: x\n")
        self.assertEqual([t.title for t in tasks], ["任务一"])


class RetryInboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_retry_inbox_carries_failure_and_limits_scope(self):
        task = orchestrate.Task(title="修 A", inbox=".pair/inbox/010.md")
        path = orchestrate.build_retry_inbox(
            task, 2, "AssertionError: 3 != 2", 11, Path(self.tmp.name) / "011-retry.md"
        )
        text = path.read_text(encoding="utf-8")
        self.assertIn("AssertionError: 3 != 2", text, "必须带失败原文")
        self.assertIn(".pair/inbox/010.md", text, "必须指回原任务书")
        self.assertIn("不要扩大范围", text)
        self.assertIn("不改 `tests/`", text)
        self.assertIn("outbox/011.md", text)

    def test_failure_signature_is_stable_and_short(self):
        info = {
            "verify_exit": 1,
            "stdout": "line\nFAIL: test_x\nAssertionError: boom\nmore\n",
        }
        signature = orchestrate.failure_signature(info)
        self.assertEqual(signature, orchestrate.failure_signature(info))
        self.assertIn("AssertionError", signature)


class BatchLoopTests(unittest.TestCase):
    """用假的 run-turn 返回值验证"跑到通过 / 打转就停 / 人工项只跑一轮"。"""

    def run_batch_quietly(self, args):
        """编排器会往 stdout 打印进度；测试里静音，免得和测试输出混在一起。"""
        with contextlib.redirect_stdout(io.StringIO()):
            return orchestrate.run_batch(args)

    def setUp(self):
        self.original_call = orchestrate.call_run_turn
        self.calls = []
        self.original_next = orchestrate.next_turn_number
        # 这些测试不许往真实的 .pair/inbox、.pair/reports 里写东西
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_dirs = (
            orchestrate.INBOX_DIR,
            orchestrate.REPORT_DIR,
        )
        orchestrate.INBOX_DIR = Path(self.tmp.name) / "inbox"
        orchestrate.REPORT_DIR = Path(self.tmp.name) / "reports"
        orchestrate.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        orchestrate.REPORT_DIR.mkdir(parents=True, exist_ok=True)
        # 队列里写的 `.pair/inbox/004.md` 在这里落到临时目录，测试不依赖仓库里真有这个文件
        (orchestrate.INBOX_DIR / "004.md").write_text(
            "# 假任务书（测试用）\n", encoding="utf-8"
        )
        orchestrate.next_turn_number = lambda: 100  # type: ignore[assignment]
        self.addCleanup(setattr, orchestrate, "call_run_turn", self.original_call)
        self.addCleanup(setattr, orchestrate, "next_turn_number", self.original_next)
        self.addCleanup(setattr, orchestrate, "INBOX_DIR", self.original_dirs[0])
        self.addCleanup(setattr, orchestrate, "REPORT_DIR", self.original_dirs[1])

    def make_args(self, **overrides):
        class Args:
            queue = ""
            budget = 1.0
            total_cny = 100.0
            total_wall = 10**6
            max_turns = 50
            max_tasks = 0
            start_turn = 0
            dry_run = True

        args = Args()
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def queue_with(self, text: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        )
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        return handle.name

    def test_passes_on_second_attempt_and_writes_summary(self):
        outcomes = [
            {"verify_exit": 1, "stdout": "FAIL: test_a\nAssertionError: x", "cost": 0.1},
            {"verify_exit": 0, "stdout": "OK", "cost": 0.1},
        ]
        orchestrate.call_run_turn = lambda *a, **k: outcomes.pop(0)  # type: ignore[assignment]
        queue = self.queue_with("## 任务一\n- inbox: .pair/inbox/004.md\n- verify: check\n")
        args = self.make_args(queue=queue)
        results, totals = self.run_batch_quietly(args)
        self.assertEqual(results[0].status, "PASS")
        self.assertEqual(results[0].attempts, 2)
        self.assertAlmostEqual(totals["cost"], 0.2)

    def test_stops_when_same_failure_repeats(self):
        same = {
            "verify_exit": 1,
            "stdout": "FAIL: test_a\nAssertionError: same",
            "cost": 0.1,
        }
        orchestrate.call_run_turn = lambda *a, **k: dict(same)  # type: ignore[assignment]
        queue = self.queue_with(
            "## 任务一\n- inbox: .pair/inbox/004.md\n- verify: check\n- max_attempts: 4\n"
        )
        results, totals = self.run_batch_quietly(self.make_args(queue=queue))
        self.assertEqual(results[0].status, "BLOCKED")
        self.assertEqual(results[0].attempts, 2, "同一个失败重复出现就该停，不要硬撑到 4 次")
        self.assertIn("停止", totals["stopped"])

    def test_manual_task_runs_once_then_needs_human(self):
        orchestrate.call_run_turn = lambda *a, **k: {  # type: ignore[assignment]
            "verify_exit": None,
            "stdout": "",
            "cost": 0.0,
        }
        queue = self.queue_with("## 需要人听\n- inbox: .pair/inbox/004.md\n- verify: manual\n")
        results, _ = self.run_batch_quietly(self.make_args(queue=queue))
        self.assertEqual(results[0].status, "NEEDS_HUMAN")
        self.assertEqual(results[0].attempts, 1)

    def test_stops_before_next_task_when_current_blocked(self):
        orchestrate.call_run_turn = lambda *a, **k: {  # type: ignore[assignment]
            "verify_exit": 1,
            "stdout": "ERROR: boom",
            "cost": 0.0,
        }
        queue = self.queue_with(
            "## 任务一\n- inbox: .pair/inbox/004.md\n- verify: check\n- max_attempts: 1\n"
            "\n## 任务二\n- inbox: .pair/inbox/004.md\n- verify: check\n"
        )
        results, totals = self.run_batch_quietly(self.make_args(queue=queue))
        self.assertEqual(len(results), 1, "前一个任务没通过就不该继续下一个")
        self.assertEqual(results[0].status, "BLOCKED")
        self.assertIn("任务一", totals["stopped"])

    def test_missing_inbox_blocks_before_spending_anything(self):
        called = []
        orchestrate.call_run_turn = lambda *a, **k: called.append(1)  # type: ignore[assignment]
        queue = self.queue_with("## 任务一\n- inbox: .pair/inbox/nonexistent.md\n- verify: check\n")
        results, _ = self.run_batch_quietly(self.make_args(queue=queue))
        self.assertEqual(results[0].status, "BLOCKED")
        self.assertEqual(called, [], "任务书不存在时不该调用模型")


class SummaryTests(unittest.TestCase):
    def test_summary_lists_every_task_and_residuals(self):
        args = type("A", (), {"queue": ".pair/queue/001.md"})()
        results = [
            orchestrate.TaskResult(
                task=orchestrate.Task(title="甲", verify="cmd"),
                status="PASS",
                attempts=1,
                last_verify_exit=0,
                evidence=["turn-001"],
            ),
            orchestrate.TaskResult(
                task=orchestrate.Task(title="乙", verify="cmd2"),
                status="BLOCKED",
                attempts=2,
                last_verify_exit=1,
                residual="AssertionError: nope",
                evidence=["turn-002", "turn-003"],
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            orchestrate.REPORT_DIR = Path(tmp)
            path = orchestrate.write_summary("001", results, {"turns": 3, "cost": 0.3, "started": 0.0, "stopped": ""}, args)
            text = path.read_text(encoding="utf-8")
        self.assertIn("甲", text)
        self.assertIn("**BLOCKED**", text)
        self.assertIn("AssertionError: nope", text)
        self.assertIn("turn-002", text)


if __name__ == "__main__":
    unittest.main()
