# AGENTS.md — PointCloudSearch 项目规则（每次会话自动加载）

> 本文件是唯一每次会话都会自动加载的文件，保持精简、只放稳定不变的信息。
> 详细信息按需读取，见下方“文档索引”。

## 项目一句话
模块化点云查找 / 分析桌面程序（节点式图形化流程编排）+ C++ SDK，面向 RVC 3D
相机客户，对标海康 VisionMaster / CloudCompare 的易用性与可扩展性。

## 技术栈与常用命令
- 技术栈：C++20 + CMake + Qt 6.8.3 + VTK 9.4 + PCL 1.13.0（OpenCV / RVC SDK
  后续接入），MSVC（VS2026）
- 配置 + 构建：`cmake -S . -B build && cmake --build build --config Release -j 8`
- 测试：`cd build && ctest -C Release --output-on-failure`
- 冒烟 / 演示：`start.bat --smoke <ply>`、`start.bat --demo <ply> --autoquit N`
- 一键启动：`start.bat`（无参数直接运行）

## 文档索引（按需读取，禁止一次全读）
| 文件 | 内容 | 何时读取 |
|---|---|---|
| STATUS.md | 当前快照、交接块、已知问题、失败方案 | 每次会话先读顶部交接块 |
| PLAN.md | 阶段步骤、DoD、验证方式、依赖、回退方案 | 开始当前阶段任务时读对应阶段 |
| PROJECT.md | 目标、红线、约束、非目标、验收标准、ADR | 涉及需求 / 边界 / 决策时读 |
| docs/SESSION_PROMPTS.md | 会话启用 / 收尾 / 推送提示词 | 新会话或收尾时按需使用 |

## 硬约束（优先级最高，违反前必须停下说明）
- **先记忆后检索**：改代码 / 修 BUG 前，先 `rg` 检索 `~/.codex/knowledge/`
  （本仓库相关条目：`pointcloudsearch-*`、`rvc-vision-studio-*`、`rvc-*`、
  `portable-windows-qt-deploy` 等），命中就直接引用结论，不重复检索。
- **再查参考**：首选本地参考仓库 `third_party/ref/RVBUST_Code-rvc-vision-studio/`
  （画布交互、属性面板、ROI、方案、RVC 相机等成熟实现，直接搬运改接口）；
  其次 GitHub 同类项目（QtNodes / CloudCompare / PCL 官方示例）。成熟方案优先
  整段移植再适配，不从头调试；只有确无参考时才自己写。
- **写回记忆库**：调研 / 排错得出的有价值结论，写入
  `~/.codex/knowledge/<主题短横线>.md`。
- 语言 C++20；内部坐标单位恒为 **mm**，单位换算只在 IO 层；所有结果保留
  原始点索引（`Region.indices` / `source_indices`）。
- 节点输入输出统一 `ObjectList`；新增节点先注册进 `registerCoreNodes()`；
  端口类型 cloud / region / any，类型不符禁止连线。
- 界面默认中文 + Dark 主题（蓝白磨砂玻璃风格），切换英文时才用英文；
  原有布局（左组件 / 画布 / 3D / 右参数+属性 / 底日志）不得破坏。
- 测试先行：核心逻辑补单测，UI 交互补 QtTest（`tests/app/test_node_flow.cpp`）；
  提交前 `ctest` 全绿 + 应用冒烟通过。
- 不可修改的核心功能清单见 PROJECT.md 第 3 节。

## 代码约定
- 源码统一 UTF-8（全局 `/utf-8` 编译选项）；中文路径统一 UTF-8 → 宽字符转换。
- 节点执行错误用 `std::runtime_error` 抛出，由 `Graph::execute` 捕获写入
  `lastError()`；UI 线程不直接抛异常。
- 新代码优先参考仓库中已有的同类实现，不自创风格。
- 提交信息遵循 Conventional Commits（如 `feat:` / `fix:` / `docs:`）。

## 边界与禁止事项
- 不提交 `.env`、密钥、构建产物（`build/`、`*.obj`、`*.log`）、大体积第三方
  目录（`third_party/ref/`、`vtk-*`、`qt-download/`、压缩包）与测试数据
  （`Data/`），具体见 `.gitignore`。
- 不执行破坏性命令（`git reset --hard`、`rm -rf` 等），除非用户明确要求；
  回退一律用 git 本地历史 / 分支。
- 文档与代码矛盾时：以代码为准，停下向用户说明，并同步修正文档。
- 在 AICode 仓库内工作时，同时遵守该仓库的 AGENTS.md 与 docs/GOVERNANCE.md
  （项目级规则更具体，两者冲突时以仓库规则为准）；AICode 内调研时还检索
  `AICode/docs/knowledge/`。

## 会话仪式
- 开始：读 STATUS.md 交接块 → 读 PLAN.md 当前阶段 → 直接执行下一步。
- 结束：更新 STATUS.md（交接块）→ 同步 PROJECT / PLAN（如有必要）→ 运行
  `ctest -C Release` 与冒烟 → 本地 git 提交。
- 提交：**本地提交照常**（便于逐阶段回溯与审计）；`git push` 只在用户明确
  说“推送”时执行。
