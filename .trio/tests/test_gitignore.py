#!/usr/bin/env python3
"""把"什么进版本库"这条规则钉住。**不调模型、不花钱。**

为什么值得专门测：这条规则我今天写错过一次——整个 `reports/` 被挡掉了，
理由是"跑出来的不是写出来的"，而 `PROTOCOL.md` §3 里明明写着 reports/ 是"证据包"。
后果是 A 的真机截图和探针脚本全在版本库外面，`DESIGN.md` §6 第 4 条
"证据要能被人独立复现"就成了一句空话。

规则是**判据**，判据得能被判定。所以这里用 `git check-ignore` 真去问 git 一遍，
而不是靠人记得。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
GIT = shutil.which("git")


def ignored(rel: str) -> bool | None:
    """问 git：这个路径会不会被忽略。返回 None 表示问不了（不是 git 仓库等）。"""
    proc = subprocess.run(
        [GIT, "check-ignore", "-q", "--no-index", rel],
        cwd=str(REPO), capture_output=True,
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


@unittest.skipIf(GIT is None, "没有 git")
class WhatGoesIntoGit(unittest.TestCase):
    def setUp(self) -> None:
        if not (REPO / ".git").exists():
            self.skipTest("不是 git 仓库（比如从压缩包解开的副本）")

    def check(self, rel: str, expect_ignored: bool) -> None:
        got = ignored(rel)
        if got is None:
            self.skipTest("git check-ignore 跑不动")
        verb = "挡在外面" if expect_ignored else "进版本库"
        self.assertEqual(
            got, expect_ignored,
            f"{rel} 应该{verb}，实际{'被挡住了' if got else '会进库'}",
        )

    # ---- 证据：必须进版本库（这是 §6 第 4 条"人能独立复现"的物质基础）
    def test_evidence_scripts_are_tracked(self):
        self.check(".trio/reports/T-999/real_key_probe.py", False)

    def test_evidence_screenshots_are_tracked(self):
        self.check(".trio/reports/T-999/level1-real-window.png", False)

    def test_evidence_measurements_are_tracked(self):
        self.check(".trio/reports/T-999/tick-rate-level1.json", False)

    def test_gate_report_is_tracked(self):
        """机械闸的报告是每次运行的审计记录，小且有用。"""
        self.check(".trio/reports/T-999.json", False)

    def test_real_files_already_on_disk_are_tracked(self):
        """拿真的存在的那几个文件问一遍——A 写的东西不能躺在版本库外面。"""
        for rel in (
            ".trio/reports/tick_rate_probe.py",
            ".trio/reports/t003/real_key_probe.py",
            ".trio/reports/t003/level1-boosted-real-window.png",
        ):
            if (REPO / rel).exists():
                self.check(rel, False)

    # ---- 残渣：必须挡住
    def test_raw_event_streams_are_ignored(self):
        """单轮几百 KB～几 MB 的原始流，进库只会淹掉真正的记录。"""
        self.check(".trio/reports/T-999/raw-attempt1.jsonl", True)

    def test_log_dir_is_entirely_ignored(self):
        for rel in (
            ".trio/log/group.jsonl",
            ".trio/log/raw/b-T-999.jsonl",
            ".trio/log/kill.flag",
            ".trio/log/live.json",
            ".trio/log/spend.json",
            ".trio/log/b-session",
        ):
            self.check(rel, True)

    def test_bytecode_is_ignored(self):
        self.check(".trio/__pycache__/bus.cpython-314.pyc", True)

    # ---- 源码当然要进
    def test_source_is_tracked(self):
        for rel in (".trio/bus.py", ".trio/router.py", ".trio/serve.py",
                    ".trio/tests/page_render.mjs", "AGENTS.md"):
            self.check(rel, False)


@unittest.skipIf(GIT is None, "没有 git")
class EvidenceActuallyExists(unittest.TestCase):
    """规则对了，还得真有东西可进——不然这条规则是空转的。"""

    def test_reports_dir_has_evidence_on_disk(self):
        reports = REPO / ".trio" / "reports"
        if not reports.exists():
            self.skipTest("还没有 reports/（第一批任务之前是正常的）")
        evidence = [
            p for p in reports.rglob("*")
            if p.is_file() and p.suffix in (".py", ".png", ".md") and p.stat().st_size > 0
        ]
        self.assertGreater(
            len(evidence), 0,
            "reports/ 里一个证据文件都没有——A 是不是只把结论贴进群、没落文件？",
        )


if __name__ == "__main__":
    unittest.main()
