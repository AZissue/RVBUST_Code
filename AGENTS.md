# PointCloudSearch 项目工作流（固定流程，所有会话必须遵守）

## 改代码 / 修 BUG 之前，必须按顺序执行

1. **先查记忆**：`rg` 检索 `~/.codex/knowledge/`（本仓库相关条目：
   `pointcloudsearch-*`、`rvc-vision-studio-*`、`rvc-*`、`portable-windows-qt-deploy` 等），
   命中就直接引用结论，不重复检索。
2. **再查 GitHub / 本地参考仓库**：
   - 首选本地已拉取的旧项目 `third_party/ref/RVBUST_Code-rvc-vision-studio/`
     （画布交互、属性面板、ROI、方案、RVC 相机等都是成熟实现，直接搬运改接口）。
   - 其次 GitHub 上同类成熟项目（QtNodes / CloudCompare / PCL 官方示例等）。
3. **直接搬运或参考，不从头调试**：成熟方案优先整段移植再适配本项目接口；
   只有确无参考时才自己写。
4. **有价值的结论写入记忆库**：`~/.codex/knowledge/<主题短横线>.md`。

## 开发约束

- 语言：C++20；内部单位 mm；所有结果保留原始点索引。
- 节点输入输出统一 `ObjectList`；新增节点先注册进 `registerCoreNodes()`。
- 端口类型：cloud / region / any，类型不符禁连。
- 界面默认中文 + Dark 主题；切换英文时才用英文。
- 测试先行：核心逻辑补单测，UI 交互补 QtTest（`tests/app/test_node_flow.cpp`）。
- 提交前 `ctest` 全绿 + 应用冒烟通过。

## 文档维护约定

- 每完成一个阶段：**先验证结果，再更新 `STATUS.md`**。
- 需求或计划变化：同步更新 `PROJECT.md`（目标 / 约束 / 验收）和
  `PLAN.md`（阶段 / 验证 / 依赖）。
- 三份文档是项目的单一事实来源，改动前先看它们。
