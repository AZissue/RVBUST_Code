# 台账（MyHandEyeTools × Codex/Claude 双智能体协作）

每轮一行：日期 · 轮次 · Claude 做了什么 · Codex 的独立验证结论 · 真实花费。
只看 Codex 亲自复现过的证据；`outbox/` 里 Claude 的说法不算数。

| 轮次 | 日期 | inbox | Claude 交付 | Codex 验证 | 结论 |
|---|---|---|---|---|---|
| 000 | 2026-09-20 | — | — | 基线：`cmake --build build --config Release` 退出码 0；`ctest -C Release` 2/2 通过（unit_tests 1.15s、measurement_truth 0.40s）；工作区干净（HEAD `9e18f3b`，分支 `HandEyeTools`，领先 `AICode/HandEyeTools` 5 个提交） | 基线绿 |

## 成本记录（真实扣费 vs Claude Code 估算）

| 时点 | DeepSeek 余额 | 说明 |
|---|---|---|
| 协作开始前（2026-09-20） | ¥8.35 | 基线 |

## 接入说明（本项目与上一版脚手架的差异）

- 脚手架来自 `D:\MyCode\CodexWithClaude\.pair`（Python 项目），本项目为 C++/Qt/CMake：
  - `run-turn.py` 默认验证命令改为 `cmake --build build --config Release && ctest --test-dir build -C Release --output-on-failure`；
  - 默认工具白名单改为 `Read,Glob,Grep,Edit,Write,Bash(cmake --build:*)`（只放行一次编译自检，不放行 ctest/GUI/git）。
- 双工作区事实（2026-09-20 核对）：`D:\MyCode\MyHandEyeTools`（分支 `HandEyeTools`）为当前最新工作区；
  `C:\Users\rvbust\Documents\Codex\AICode\handeye-tools` 落后（src 73 vs 84 个文件，最后写入 2026-09-11）。
  本轮起以本工作区为准，待用户拍板后再决定是否回归 AICode。

## 真机环境基线（用户 2026-09-20 提供，反馈 11）

| 项 | 值 | 备注 |
|---|---|---|
| 测试相机 | RVC M2600，序列号 `G2GM620B101` | 与第 8 回合验收用的 RVC-M2600-ML2 是同一台 |
| 机器人 | UR（优傲） | 用户给的端口是 **3003**，代码里 UR Realtime 写的是 **30003** —— 待确认 |
| 拍摄场景 | 一个同心圆 | 与校准板 `markerType=1`（同心圆）一致 |

> 真机验收的证据（截图 / 原始输出 / 命令）一律写进 `.pair/reports/`，不留在会被 gitignore 的目录里。
