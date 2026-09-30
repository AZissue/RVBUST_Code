# 把这套框架搬到另一个仓库（2026-09-23 定稿）

> 写给"下一个项目第一天"的自己用。目标：**不重新踩今天踩过的坑**。
> 配套阅读：`PROTOCOL.md`（规程）、`READINESS.md`（能不能上生产的判定）、`DESIGN.md`（为什么这么设计）。

> **这条清单已经机器化了（2026-09-29）**：`python .trio/trio.py install <目标仓>`
> 幂等地把**代码**同步过去（脚本 / `roles/` / `tests/` / 四份文档 / `start.cmd`），
> **从不碰** `config.json`、`tasks/`、`solutions/`、`reports/`、`log/` 里的东西，
> 缺什么补什么（`KICKOFF.md`、`AGENTS.md` 的框架指针、`.gitignore` 的框架条目）。
> 下面这张表是那条命令的**说明书**：它为什么这么分、哪些字段必须逐项目不同。
> 你要手工做也可以，但**别让目标仓里的代码和源仓分叉**——改框架改源仓，然后重跑命令。

## 0. 搬什么、不搬什么

| 搬 | 不搬 |
|---|---|
| `.trio/` 整个目录（bus / router / as / serve / check / verify / a_ledger / reproduce / config / roles / docs / tests） | `log/`（跑出来的，两边混一起没法查） |
| `AGENTS.md` 里"你是 A"的那段（或等价物） | `reports/`、`tasks/`（含 `*.checks.py`）、`solutions/`（上一个项目的任务与证据，留着只会干扰） |
| — | `config.json` 里前三行之外的**项目相关**字段（见 §1） |
| — | `.trio/tasks/T-*.checks.py`（**判据是逐项目的**，抄过去就是假判据） |

## 1. `config.json` 必须改的四处

| 字段 | 为什么 | 怎么填 |
|---|---|---|
| `import_check_modules` | B 的 import 自检要覆盖**本项目**的模块 | 列本项目的顶层模块名（`myapp.core` 之类） |
| `b_allowed_tools` | B 的命令白名单**就是边界本身** | 默认只放 `check.py` / `py_compile` / `as.py`。想加别的 = 放宽边界，先想清楚值不值 |
| `group_port` | 两个项目同时开着时不打架 | 换一个端口 |
| `a_session` | **唤醒投给谁** | A（Codex）在当前会话的 app 会话 id。**别手抄**：在 Codex 里于**本仓库目录下**开好新会话，然后 `python .trio/router.py rotate-a`（`--show` 只看候选）。它自己会读 `~/.codex/session_index.jsonl` 并**校过 `cwd` 是不是本仓**——那个文件是**机器全局**的，实测 24 条横跨 4 个项目，盲取最新 = 唤醒投到别的项目去。**不换 = B 交付时没人叫 A，而这边没有任何一步会报错** |

## 1.1 之后每次换会话都走 `rotate-a`

会话不能无限续：A 的花费 ≈ **动作数 × 上下文大小**，每条动作都重发整段上下文，所以是**二次**的。
换会话的两步（**缺一不可**）：收尾把欠的事落成 `python .trio/as.py a --kind todo --text "…"`，
新会话第一件事 `python .trio/bus.py todos` 接上，然后 `rotate-a` 把唤醒指过来。
阈值在 `config.json` 的 `a_rotate_context_mb` / `a_rotate_actions`——**按项目重标**，见 §2。
为什么"交接"用现成的 `todo` 而不是另建 `HANDOFF.md`：见 `PROTOCOL.md` §9.2 末段。

## 2. 闸门阈值按项目重标（别照抄）

- `stall_events_warn` / `stall_events_kill`：**只数真动作**（思考增量不计）。跑两轮真实任务，
  看"一轮正常交付"的非思考事件量，按 **6~30 倍余量**定；小项目 300/1200 只是本仓的标定值。
- `no_progress_warn` / `no_progress_actions`：B 连续多少个动作没写文件。项目越大，
  "先读一批再动手"越正常，这两个值要跟着放宽。
- `task_cny` / `session_cny`：**注意口径**——`cost-session` 量的是**账户级**余额差，
  本机别处的用量也会算进来，所以它**会误杀**；`router.py drive --reset-session` 是逃生口。
  详见 `PROTOCOL.md` §5 与 §9.1。
- `a_rotate_context_mb` / `a_rotate_actions`：**会话级**上下文/动作的轮换提示线。
  本仓标定值 4.5 MB / 350 是照"实测会话总量 7.4–9.9 MB"取的中位。
  换项目**必须重标**，做法：新项目上跑两轮真实任务，`python .trio/a_ledger.py --session <a_session>`
  看一轮正常交付会让会话涨多少，再乘上一个你愿意忍受的回灌次数。
  注意它数的是**字节**（rollout 的累计偏移量），而字节里 **55% 是 A 的推理文本**——
  框架管不着那部分，所以别指望这个阈值能精确对应钱。
  **它只是提示**：过线只发 `SYSTEM/note`，`note` 不唤醒任何人，也不自动换会话。

## 3. 第一天该做的事（**按这个顺序**）

0. **先把框架装进来**：`python <骨架仓>/.trio/trio.py install <本仓>`（幂等，可反复跑）。
   它同步代码、生成 `config.json`、补 `.gitignore` / `AGENTS.md` / `KICKOFF.md`，
   **不碰** `log/ tasks/ solutions/ reports/` 里的东西。
1. **把唤醒接过来**：在**本仓目录下**开一个 Codex 会话，跑 `python .trio/router.py rotate-a`。
   新项目第一次跑它是**首次接线**（`a_session` 是安装器写的空串，不是坏 config）：
   它接上本仓最新的那个会话；但**同一仓开了一个以上会话时它会拒绝**，
   要你 `--show` 看清后 `--session <id>` 明说——**不替人猜**。
   **必须最先做**，两个理由：`a_session` 空着时 `run_all` 会红（自检守着"静默熄火"这条）；
   而且 B 交付 / 机械闸触发时**没人叫 A**，这边**没有任何一步会报错**——最坏的那种失败。
2. `python .trio/tests/run_all.py --fast` —— 全绿才有资格开始（它含"群界面真渲染"这条人这一侧的测试）。
3. **机械闸回放**：拿本项目自己的历史日志跑 `router.py replay --stream <文件> --expect fire|clean`，
   确认"会拦、不误报"。没有历史日志就制造一份（跑一轮小任务，日志自然就有了）。
4. **第一个任务故意切小**：一条能独立验收的用户可见路径。任务书按 `roles/CONTRACT.md` §2 写，
   **必须有工作集与契约冻结**——今天所有"没跑飞"都靠这两块。

## 4. 已知边界（照搬，不用重新发现）

1. **A 侧只有代理指标**：本机读不出 Codex 的 token 费用，只有每轮时长 + 逐条动作数
   （`python .trio/a_ledger.py`）。两笔账要分开看（`PROTOCOL.md` §9.1）。
   **量它必须按"会话"而不是"线程"**：一个 app 会话会**换 rollout 文件续写**
   （`rollout_ordinal` 跨文件连续可证：`[1..1705]` → `[1703..3658]`），
   单文件口径既漏计、又**恰好在换文件那一刻归零**——那正是最该报警的时候。
   所以用 `a_ledger.summary(<会话 id>)`（各文件 `max(rollout_end_byte_offset)` **相加**），
   别用 `ledger(<thread id>)`。实测：单线程 5.85 MB vs 会话 9.58 MB。
2. **两个 id 不是一套——但坑在函数，不在格式**（2026-09-23 逐条核对过，原文写反了）：
   `codex queue` 认 app 会话 id；`thread_history_1.sqlite` 的 `thread_id` 只带用量数据，
   投给它石沉大海。但 **`config.json` 里的 `a_session` 可以直接当 `thread_id` 用**（实测匹配 5 轮），
   不需要任何映射。真正的坑是 `a_ledger.latest_thread()`——它返回**库里最近活动过的任意线程**，
   不一定是 A 当前这条。所以唤醒只用 `a_session`（`rotate-a` 维护它），
   用量口径只用 `a_ledger.summary(a_session)`（跨 rollout 文件聚合，见下面第 1 条）。
3. **唤醒文本带 `seq`**：A 醒来先比 seq，已经处理过的就回一条 note、**别重跑**（`roles/A.md`）。
4. **A 的节奏**：发任务 → `drive` → **结束这一回合**；B 交付时总线把你叫回来，那一轮再验收。
   原地等会吃两次重复唤醒（今天就吃了两次）。
5. **机械闸的成本闸会误杀**（账户级余额差）——写进 `PROTOCOL.md` §5，别当它准。
6. **大仓三个风险没被小项目验过**：上下文预算 / 耦合 / 拆解粒度，只有真在"超出单个上下文窗口"的仓上
   才会暴露；`READINESS.md` 的判定线就是为它们写的。
7. **B 的自检要含实例化冒烟**：`check.py --smoke`（真建窗口、走一帧、数 item）。
   今天 B 弄丢过 `_build_items` 这个方法名，`py_compile` 与"只 import"都看不出来，就它抓住了。

## 5. 跑起来之后：按 READINESS 的四条判定线评估

见 `.trio/READINESS.md` §4：两条真需求走完 + 至少一次**真掐断**被人看见 + 花费有可信口径 +
三个大仓风险至少暴露一个并被 §8 的对策接住。四条都满足才叫"能上"。
