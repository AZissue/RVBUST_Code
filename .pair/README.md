# Codex × Claude 协作循环（本项目）

## 角色

| 角色 | 只做这些 |
|---|---|
| **你（人）** | 只跟 Codex 对话：提需求、实测结果、反馈体验与问题 |
| **Codex** | 理解需求 → 拆成大小合适的任务 → 写验收判据 → 驱动 Claude → **独立测试/审查/验证** → 通过后才汇报 |
| **Claude** | 只做 `inbox/` 里那一条任务的**实现**，不自测、不验收 |

## 一轮的完整链路

```
你提需求
  → Codex 写 .pair/inbox/0NN.md（任务 + 判据 + 明确不做 + 交回格式）
  → Codex 驱动 Claude（headless，单轮、有硬预算）
  → Claude 写 .pair/outbox/0NN.md 并改代码（不写测试、不提交 git）
  → Codex 跑测试 / 读 diff / 自己复现（验收在 Codex，不在 Claude）
  → 不通过：Codex 写 0NN+1（只回灌失败原文 + 一个小要求）继续
  → 通过：Codex 提交 git 并向你汇报
  → 你实测 → 反馈 → Codex 重新定边界 → 下一轮
```

## 目录约定

- `inbox/`：Codex 写给 Claude 的任务（进入 Claude 的唯一入口）。
- `outbox/`：Claude 的交付说明（代码之外的口头部分）。
- `logs/`：每轮的原始事件流（不进 git，体积大）。
- `ledger.md`：每轮台账：改了什么、Codex 的验证结论、token/余额。

## 实时视图（一个视图，两个 agent）

**单窗口合并视图**：同一根时间轴、按角色分列——`CLAUDE` 绿色、`CODEX` 品红，
时间戳在最左列，所以"谁在干什么"是列结构，不靠猜。

| 方式 | 怎么开 | 说明 |
|---|---|---|
| 应用右侧面板·浏览器标签 | 由 Codex 打开 `http://127.0.0.1:8760/` | 可常驻；刷新自动、只读 |
| 应用右侧面板·终端 | 在面板终端里粘一行 `python .pair\view.py --role all` | Codex 对面板终端**只有读权限**，无法代你启动 |
| 独立窗口 | 双击 `.pair\open-view.cmd` | 方案 A 的"看得见"兜底 |

视图服务：`python .pair\live.py --port 8760`（后台跑；只读日志，不驱动任何进程）。
数据源始终是 Claude Code 的会话事件流 `logs/turn-*.stream.jsonl` 与 `logs/codex.live.log`。

## 硬规则

1. **交接物是代码 + commit**，不是对话。Codex 通过才提交。
2. Claude 一轮只做一件事；**禁止自写自测、禁止长自主循环**（上一版就是死在这）。
3. 每轮 Claude 调用都有回合内硬预算（`--max-budget-usd`，超限立即中止）。
4. 被拒的权限请求：Claude 只记录、不绕过；由 Codex 在下一轮决定是否放行。
5. 测试与验收永远在 Codex 侧（`tests/` 由 Codex 独占，Claude 不改）。

## 为什么这次不一样（对照上一版）

- 不再自建日志镜像/上色查看器：用 Claude Code 的事件流 + 会话 transcript 作为数据源，
  人在 Codex 这一侧看，Claude 的原始事件同时落盘 `logs/`。
- 不再让 Claude 长时间自主自测：它只做实现，验收权在 Codex。
- 不再靠"白名单 + 心跳 + 锁"手搓治理：用官方 `--max-budget-usd`（回合内硬中止）、
  `--permission-mode`、`--allowedTools`、`--permission-prompts`。
- 交接用 git 分支/diff，而不是把对话当交接物。
