#!/usr/bin/env python3
"""文档之间不许自相矛盾。**很窄：只查"群界面由谁打开"这一条。**

为什么值得单独一个文件：这类矛盾今天咬了两次，两次都是同一个形状——
**同一件事，两处写法不一致，而人只读了其中一处**。

  1. `.gitignore` 说 `reports/` 是"跑出来的"（挡掉），
     `PROTOCOL.md` §3 说它是"证据包"（该进库）。→ A 的真机证据全在版本库外面。
  2. `PROTOCOL.md` §10 改成了"router 保证打开"，
     但 `AGENTS.md` 里还留着"群界面：双击 `.trio/start.cmd`"。
     **而 `AGENTS.md` 恰恰是 Codex 每次必读、优先级最高的那份**——
     改了低优先级的不改高优先级的，等于没改。

第 2 条的形状特别毒：文档之间不一致时，起作用的往往是**读得最多的那一份**，
而不是写得最对的那一份。

只钉两条不变量，都作用在**操作性文档**上（今天就要照着干活的那些）：

  甲、操作性文档要把机制说清楚——否则读者只学到旧规矩。
  乙、谁提手动开界面，谁就得同时说清机制会自己开。不是禁止提手动路径
      （调试时它有用），是禁止**只**提它，那会让人以为"没开就是我忘了"，
      而真问题在别处。

`DESIGN.md` 明确不在范围内：它是决策记录，职责就是叙述当时的（错的）设计。
拿现行流程去要求一份历史文档，只会逼着人去篡改记录。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# 机制的名字。改实现请顺手改这里，测试会提醒你哪几份文档要跟着动。
MECHANISM = "ensure_group_ui"

# 说的方式不限，意思到了就行。"router 会自己确保它开着"对 A 是够用的——
# 记着一行字的名字不是目的，别让文档去背实现细节。
ROUTER_GUARANTEE = re.compile(r"router[^。\n]{0,24}(确保|自动|自己起|会起|保证)")

# 今天就要照着干活的文档。**必须**说清界面怎么开。
OPERATIONAL_DOCS = (
    "AGENTS.md",
    ".trio/KICKOFF.md",
)

# 会谈到界面的操作性文档。提到手动路径的，同一份里必须也说清机制。
ALL_OPERATIONAL_DOCS = (
    "AGENTS.md",
    ".trio/KICKOFF.md",
    ".trio/PROTOCOL.md",
    ".trio/roles/A.md",
    ".trio/roles/CONTRACT.md",
)

MANUAL_MARKERS = ("start.cmd", "serve.py --open")


def read(rel: str) -> str | None:
    p = REPO / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


def conveys_mechanism(text: str) -> bool:
    return MECHANISM in text or bool(ROUTER_GUARANTEE.search(text))


class OperationalDocsConveyTheMechanism(unittest.TestCase):
    def test_each_operational_doc_says_who_opens_the_ui(self):
        for rel in OPERATIONAL_DOCS:
            text = read(rel)
            if text is None:
                self.skipTest(f"{rel} 不存在")
            self.assertTrue(
                conveys_mechanism(text),
                f"{rel} 没说清界面由谁打开（既无 {MECHANISM}，也没说 router 会确保）。\n"
                "它是最该讲清这件事的一份——AGENTS.md 就在这里犯过错：\n"
                "只写了一句「群界面：双击 .trio/start.cmd」，于是新会话学到的就是旧规矩。",
            )


class ManualPathMustComeWithTheMechanism(unittest.TestCase):
    def test_no_doc_offers_the_manual_path_alone(self):
        offenders = []
        for rel in ALL_OPERATIONAL_DOCS:
            text = read(rel)
            if text is None:
                continue
            if any(m in text for m in MANUAL_MARKERS) and not conveys_mechanism(text):
                offenders.append(rel)
        self.assertEqual(
            offenders, [],
            f"这些文档提到了手动开界面，却没说要靠机制保证：{offenders}。\n"
            "读者大概率只会照做，然后在下一次失败时找不到北。",
        )


if __name__ == "__main__":
    unittest.main()
