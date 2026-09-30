#!/usr/bin/env python3
"""`verify.py` 的自测：**不调模型、不花一分钱、不碰真 config、不碰真 reports/**。

这个文件要证明的是**判据引擎本身可信**——它是 A 验收的裁判，
裁判自己错判（把红看成绿、把"取不到"看成通过）比没有裁判更坏。

所以重点压在三类"假绿"上：
  1. **取不到**（探针没吐那个键 / 文件不在）必须判红，不许静默通过；
  2. **`0.0`** 是合法实测值，不许被 `value or fallback` 那类写法当假值；
  3. **多条件里的某一条**没过，整条判据就得红——不能只看第一条。

另外，`.trio/tasks/*.checks.py` 不在任何既有的语法检查范围内，所以这里也盯着
"checks 文件写错了"（退出码 2）和"判据没过"（退出码 1）**是两种结论**。
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
sys.path.insert(0, str(TRIO_DIR))

import verify  # noqa: E402

_HEADER = "import sys\n"


class VerifyTestCase(unittest.TestCase):
    """把 TASK_DIR / REPORT_DIR 指到临时目录——**绝不碰仓库里的真东西**。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tasks = self.root / "tasks"
        self.reports = self.root / "reports"
        self.data = self.root / "evidence"
        for path in (self.tasks, self.reports, self.data):
            path.mkdir(parents=True)
        self._orig = (verify.TASK_DIR, verify.REPORT_DIR, verify.REPO_ROOT)
        verify.TASK_DIR = self.tasks
        verify.REPORT_DIR = self.reports
        verify.REPO_ROOT = self.root      # 证据文件按 `evidence/...` 相对这条路走

    def tearDown(self):
        verify.TASK_DIR, verify.REPORT_DIR, verify.REPO_ROOT = self._orig
        self._tmp.cleanup()

    # ---- 帮手 ----

    def evidence(self, name: str, payload) -> str:
        (self.data / name).write_text(json.dumps(payload), encoding="utf-8")
        return f"evidence/{name}"

    def checks(self, task: str, body: str, manual: str = "[]"):
        (self.tasks / f"{task}.checks.py").write_text(
            f"{_HEADER}MANUAL = {manual}\nCHECKS = {body}\n", encoding="utf-8")

    def run_verify(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = verify.main(list(argv))
        return code, buf.getvalue()

    def report(self, task: str) -> dict:
        return json.loads((self.reports / task.lower().replace("-", "") / "verify.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 数值型判据


class NumberChecks(VerifyTestCase):
    def test_nested_path_passes_when_within_bound(self):
        rel = self.evidence("m.json", {"a": {"b": [7, 3]}})
        self.checks("T-1", f'[{{"n": 1, "name": "嵌套", "json": {rel!r}, "all": '
                           f'[{{"path": "a.b.1", "le": 3}}]}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 0, out)

    def test_zero_is_a_legal_measurement_not_a_falsey_value(self):
        """拍边界偏差实测正好 0.0 —— 它必须是**通过**，不是"没量到"。

        `reproduce.py` 写 `num()` 时踩过这个：`value or fallback` 会把 0.0 吞成 fallback。
        """
        rel = self.evidence("m.json", {"parity": 0.0})
        self.checks("T-1", f'[{{"n": 1, "name": "零偏差", "json": {rel!r}, "all": '
                           f'[{{"path": "parity", "le": 1}}]}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 0, out)

    def test_missing_key_is_red_not_silently_green(self):
        """探针没吐那个键 = 判红。**静默通过是最坏的失败方式。**"""
        rel = self.evidence("m.json", {"has": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "缺键", "json": {rel!r}, "all": '
                           f'[{{"path": "missing", "le": 1}}]}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 1, out)
        self.assertIn("取不到", out)

    def test_missing_file_is_red(self):
        self.checks("T-1", '[{"n": 1, "name": "缺文件", "json": "evidence/nope.json", '
                           '"all": [{"path": "x", "le": 1}]}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 1, out)
        self.assertIn("读不到", out)

    def test_one_failing_condition_reds_the_whole_check_and_shows_every_value(self):
        """判据 2 有三个阈值：p50 ≤ 6、p95 ≤ 13、max < 26。**只违反中间那条必须判红**。"""
        rel = self.evidence("m.json", {"p50": 1.59, "p95": 20.21, "max": 9.47})
        self.checks("T-1", f'[{{"n": 1, "name": "三条件", "json": {rel!r}, "all": ['
                           f'{{"path": "p50", "le": 6}}, {{"path": "p95", "le": 13}}, '
                           f'{{"path": "max", "lt": 26}}]}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 1, out)
        # 失败详情要**逐条**给实测值，不能只说"判据 2 失败"
        self.assertIn("p50 = 1.59", out)
        self.assertIn("p95 = 20.21", out)
        self.assertIn("max = 9.47", out)

    def test_approx_tolerance_boundary(self):
        """≈167ms ±10%：正好差 10% 算过，差 10.1% 算红。"""
        for value, expected_code in ((167 * 1.10, 0), (167 * 1.101, 1)):
            with self.subTest(value=value):
                rel = self.evidence("m.json", {"tick_ms": value})
                self.checks("T-1", f'[{{"n": 1, "name": "容差", "json": {rel!r}, "all": '
                                   f'[{{"path": "tick_ms", "approx": 167, "tol": 0.10}}]}}]')
                code, out = self.run_verify("T-1", "--no-baseline")
                self.assertEqual(code, expected_code, out)

    def test_eq_works_on_booleans(self):
        """`frozen = True` 是合法判据——`eq` 不能只认数字。"""
        rel = self.evidence("m.json", {"frozen": True})
        self.checks("T-1", f'[{{"n": 1, "name": "布尔", "json": {rel!r}, "all": '
                           f'[{{"path": "frozen", "eq": True}}]}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 0, out)


# ---------------------------------------------------------------- 命令型判据


class CommandChecks(VerifyTestCase):
    def test_command_exit_code_and_stdout_are_both_honoured(self):
        py = sys.executable
        self.checks("T-1", f'[{{"n": 1, "name": "绿", "cmd": [{py!r}, "-c", "print(\'OK\')"], '
                           f'"exit": 0, "stdout_has": "OK"}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 0, out)

    def test_missing_stdout_marker_is_red_even_when_exit_code_is_zero(self):
        """退出码 0 但输出里没有那个标记 —— 必须红。"""
        py = sys.executable
        self.checks("T-1", f'[{{"n": 1, "name": "标记不在", "cmd": [{py!r}, "-c", "print(\'nope\')"], '
                           f'"exit": 0, "stdout_has": "OK"}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 1, out)


# ---------------------------------------------------------------- checks 文件本身


class ChecksFileProblems(VerifyTestCase):
    def test_syntax_error_exits_2_and_says_so(self):
        """**退出码 2 而不是 1**：'判据写错了'和'判据没过'是两个结论。"""
        (self.tasks / "T-1.checks.py").write_text("CHECKS = [ this is not python\n", encoding="utf-8")
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 2, out)
        self.assertIn("语法就是错的", out)

    def test_missing_checks_file_exits_2_and_names_the_path(self):
        code, out = self.run_verify("T-404", "--no-baseline")
        self.assertEqual(code, 2, out)
        self.assertIn("T-404.checks.py", out)

    def test_duplicate_judgement_number_is_refused(self):
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "甲", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}},'
                           f' {{"n": 1, "name": "乙", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 2, out)
        self.assertIn("重复", out)

    def test_gap_in_judgement_numbers_is_refused(self):
        """判据 2 既没写成 check 也没进 MANUAL —— 它会被**悄悄跳过**，那正是要堵的。"""
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "甲", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}},'
                           f' {{"n": 3, "name": "丙", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]')
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 2, out)
        self.assertIn("断档", out)


# ---------------------------------------------------------------- 需人工 / --pre


class ManualAndPre(VerifyTestCase):
    def test_manual_judgement_is_listed_but_never_counts_as_passed(self):
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "自动", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]',
                    manual="[2]")
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 0, out)
        self.assertIn("需人工", out)
        self.assertEqual(self.report("T-1")["manual"], [2])

    def test_pre_flags_a_judgement_that_is_green_before_the_work(self):
        """发任务书之前就绿的断言测的不是新行为——必须指名道姓。"""
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "应该还没实现", "pre": "red", "json": {rel!r}, '
                           f'"all": [{{"path": "x", "le": 5}}]}}]')
        code, out = self.run_verify("T-1", "--pre")
        self.assertEqual(code, 1, out)
        self.assertIn("提前", out)
        self.assertIn("应该还没实现", out)

    def test_pre_passes_when_the_new_behaviour_is_not_there_yet(self):
        rel = self.evidence("m.json", {"x": 99})
        self.checks("T-1", f'[{{"n": 1, "name": "新行为", "pre": "red", "json": {rel!r}, '
                           f'"all": [{{"path": "x", "le": 5}}]}}]')
        code, out = self.run_verify("T-1", "--pre")
        self.assertEqual(code, 0, out)

    def test_pre_green_marks_an_invariant_and_is_not_judged_red(self):
        """标了 `pre: green` 的是**不变量**（实现前也必须成立），--pre 下绿是对的。"""
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "不变量", "pre": "green", "json": {rel!r}, '
                           f'"all": [{{"path": "x", "le": 5}}]}}]')
        code, out = self.run_verify("T-1", "--pre")
        self.assertEqual(code, 0, out)

    def test_pre_without_any_pre_key_is_refused(self):
        """没有 pre 键就等于"全红断言"没地方落——与其假装通过，不如说清楚。"""
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "没标", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]')
        code, out = self.run_verify("T-1", "--pre")
        self.assertEqual(code, 2, out)
        self.assertIn("pre", out)


# ---------------------------------------------------------------- 基线


class Baseline(VerifyTestCase):
    def _patch(self, ran: int, rc: int = 0, framework_rc: int = 0):
        calls = []

        def fake_run_cmd(argv, timeout):
            calls.append(argv)
            if "unittest" in argv:
                return rc, f"....\nRan {ran} tests in 1.2s\n\n" + ("OK" if rc == 0 else "FAILED")
            return framework_rc, "框架自检"

        self._orig_run_cmd = verify.run_cmd
        verify.run_cmd = fake_run_cmd
        self.addCleanup(lambda: setattr(verify, "run_cmd", self._orig_run_cmd))
        return calls

    def _patch_config(self, baseline):
        import bus
        self._orig_config = bus.config
        bus.config = lambda: {"test_baseline": baseline}
        self.addCleanup(lambda: setattr(bus, "config", self._orig_config))

    def test_matching_count_passes_and_both_suites_are_run(self):
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "自动", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]')
        calls = self._patch(ran=258)
        self._patch_config(258)
        code, out = self.run_verify("T-1")
        self.assertEqual(code, 0, out)
        # 两套都跑：游戏侧 + 框架侧。`discover -s tests` 不覆盖 .trio/，不能只跑前面那套。
        self.assertTrue(any("unittest" in c for c in calls), calls)
        self.assertTrue(any("run_all.py" in " ".join(c) for c in calls), calls)

    def test_count_drift_says_which_line_to_edit_instead_of_just_failing(self):
        """计数合法下降（重构测试）时，要给出**改哪一行**的指令，不能只是判死。"""
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "自动", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]')
        self._patch(ran=239)
        self._patch_config(258)
        code, out = self.run_verify("T-1")
        self.assertEqual(code, 1, out)
        self.assertIn("test_baseline", out)

    def test_missing_baseline_fails_loudly_rather_than_defaulting_to_zero(self):
        """基线缺失 = 这条判据会悄悄变成永真。必须响亮地失败。"""
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-1", f'[{{"n": 1, "name": "自动", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]')
        self._patch(ran=258)
        self._patch_config(None)
        code, out = self.run_verify("T-1")
        self.assertEqual(code, 1, out)
        self.assertIn("test_baseline", out)


# ---------------------------------------------------------------- 证据落盘


class EvidenceIsWritten(VerifyTestCase):
    def test_report_lands_in_a_lowercase_task_directory(self):
        """小写去连字符：Windows 上大小写不敏感看着一样，搬到 Linux 会分叉成两份证据；
        去连字符是对齐既有的 `t002/t005/t008` 那批目录。"""
        rel = self.evidence("m.json", {"x": 1})
        self.checks("T-7", f'[{{"n": 1, "name": "自动", "json": {rel!r}, "all": [{{"path": "x", "le": 5}}]}}]')
        code, out = self.run_verify("T-7", "--no-baseline")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.reports / "t7" / "verify.json").exists())
        data = self.report("T-7")
        self.assertEqual(data["verdict"], 0)
        self.assertEqual(data["task"], "T-7")

    def test_summary_line_survives_when_many_judgements_fail(self):
        """截的是**失败原文**，不是汇总——否则 A 看不见哪几条没过，还得再跑一次。"""
        rel = self.evidence("m.json", {"x": 99})
        body = ",".join(
            f'{{"n": {i}, "name": "判据{i}", "json": {rel!r}, "all": [{{"path": "x", "le": 1}}]}}'
            for i in range(1, 9))
        self.checks("T-1", f"[{body}]")
        code, out = self.run_verify("T-1", "--no-baseline")
        self.assertEqual(code, 1, out)
        for i in range(1, 9):
            self.assertIn(f"[判据 {i}] 判据{i}", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
