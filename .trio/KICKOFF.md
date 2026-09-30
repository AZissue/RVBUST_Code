# 会话开始提示词（MyHandEyeTools）

> 这份文件是给人看的说明书，**不是每轮都要贴的咒语**。

## 怎么在新项目里启用（两步）

1. 在**新项目目录下**开一个 Codex 会话；
2. 让它跑一次 `python .trio/router.py rotate-a` —— 把总线唤醒接到这个会话上。
   不换的话，B 交付 / 机械闸触发时**没人叫你**，那边静悄悄地停住。

本机的全局规则（`~/.codex/AGENTS.md`）已经写死：**只要仓库里存在
`.trio/roles/A.md`，Codex 就是这套协作里的 A**，会自己读下面那几份。
所以正常情况下你不用贴任何东西。

如果确实想显式说一句，贴这段就够：

> 用「人 / A / B」三方协作做这个仓库。你是 A。
> 先读 `.trio/roles/A.md` 与 `.trio/roles/CONTRACT.md`，
> 再 `python .trio/bus.py tail -n 30` 和 `python .trio/bus.py todos`，
> 最后 `python .trio/router.py rotate-a`。

## A 开工必读

- `.trio/roles/A.md` —— 你是谁、你的循环、你必须停下来问人的三件事
- `.trio/roles/CONTRACT.md` —— 解决方案 / 任务书 / 交回 / 证据 的格式
- `.trio/PORTING.md` §4 —— 已知边界（照搬，不用重新发现）
- `.trio/PORTING.md` §2 —— 闸门阈值**按项目重标**，别照抄源仓

## 群界面

**你不用管**——每次 `drive` 前 router 会自己确保它开着（`ensure_group_ui()`：
没跑就起一个，并把浏览器打开）。人在群里能看到实时活动条。

## 三条红线

1. **你不写实现代码**（实现是 B 的活；你有验收权，没有实现权）。
2. **判据权归你独占**（B 发不出 `verify` / `escalate` / `task` / `kill`，机制强制）。
3. **你不许撒手不管**（B 在跑的时候你要看得见它的动作——看台账与计数，
   不要去读 `.trio/log/raw/` 下的全量事件流）。
