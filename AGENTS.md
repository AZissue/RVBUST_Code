# AGENTS.md — 手眼标定数据收集助手（项目规则，每次会话自动加载）

> 本文件只放稳定不变的信息；详细状态/计划/需求按需读取下方索引，禁止一次全读。
> 双工作区：源码真源 = `AICode/handeye-calib-tool`；运行/构建副本 = `D:\MyCode\MyHandEyeTools`。
> 修改先在 AICode 完成并构建+单测全绿，再同步到 D 工作区构建+单测。

## 项目一句话

面向 RVC X1/X2 相机的 Windows 手眼标定数据采集桌面工具（Qt5/C++17）：
连接相机 → 采集 2D+3D → 标定板识别 → 数据保存/备份 → 辅助工具（测量、坐标转换、
像素→3D、标定计算、机器人通信），以绿色免安装包交付现场。

## 技术栈与常用命令

- 技术栈：C++17 / Qt 5.14.2 (msvc2017_64) / CMake + Visual Studio 2026 /
  RVC SDK / HandEyeSDK / RVBUST Vis(OSG) / Qt5 Network。
- 构建（AICode）：
  `cmake --build "C:\Users\rvbust\Documents\Codex\AICode\handeye-calib-tool\build" --config Release`
- 构建（运行工作区）：
  `cmake --build "D:\MyCode\MyHandEyeTools\build" --config Release`
- 测试（两处相同）：`ctest --test-dir <上述 build 目录> -C Release --output-on-failure`
- 运行：`D:\MyCode\MyHandEyeTools\build\src\Release\HandEyeCalibrationTool.exe`
  （或 D 工作区 `run.bat`）。
- 构建后必查：`$LASTEXITCODE` 为 0、exe 时间戳已刷新；测试 exe 是 GUI 子系统，
  stdout 不可见，失败详情用 `-o <文件>,txt` 输出查看。
- 同步：把改动文件（src/、tests/、CMakeLists.txt、文档）Copy-Item 到 D 工作区，
  再构建+ctest。

## 文档索引（按需读取，禁止一次全读）

| 文件 | 内容 | 何时读取 |
|---|---|---|
| STATUS.md | 交接块、当前进度、已知问题、失败方案 | 每次会话先读顶部交接块 |
| PLAN.md | 阶段步骤、DoD、验证、依赖、回退方案 | 开始当前阶段任务时读对应阶段 |
| PROJECT.md | 目标、红线、约束、非目标、验收标准、ADR、变更记录 | 涉及需求、边界、决策时读 |

## 硬约束（优先级最高，违反前必须停下说明）

- 不可修改的核心功能见 PROJECT.md 第 3 节：识别回退链、质量告警不拦截、检测缓存、
  3D 拾取异步化、3D 缩放深度自适应、保存路径回退、卡片格式校验、绿色版免安装、
  日志双轨、会话目录精简。
- Vis/3D 同步命令（GetCameraPose 等）绝不放 UI 线程（防整机挂死）。
- 不得在 AICode 项目目录内执行 `git init`（AICode 根是唯一仓库）；遵守
  AICode 根 AGENTS.md 与 docs/GOVERNANCE.md（冲突时以仓库规则为准）。
- 不提交密钥/大文件/构建产物/第三方 SDK 二进制：.env、build/、third_party/、
  tests/data/、*.log 等。
- UI 不做自动化测试；界面验证由 AI 输出「操作步骤+预期结果」清单，用户手动执行反馈。

## 记忆库 / 参考仓库工作流（Step 0，先查后做）

1. 新任务/BUG 先检索全局记忆库 `~/.codex/knowledge/`（已有条目如
   `robot-pose-format-conventions.md`、`rvc-handeye-fanuc-wpr-convention.md`）；
   命中直接引用，不重复搜索。
2. 再检索 AICode 仓库级参考 `AICode/docs/knowledge/` 与项目 git 历史。
3. 仍未命中再搜 GitHub（相似项目/疑似相同问题）；有价值的解法写入全局记忆库
   （只记公开来源与结论，禁止记录密钥/令牌）。

## 代码约定

- 纯函数先行：几何/解析/标定/像素反投影等可测逻辑放 `src/logic/`，UI 只是投影；
  先写单测再实现，新增纯逻辑必须注册进 tests/（CMakeLists.txt + test_main.cpp）。
- 提交前构建+ctest 全绿；两处工作区都验证。
- 单位约定：卡片与工具默认 mm + 度；FANUC WPR 按 RVC 导出实测顺序
  （WPR=绕 Z,Y,X，与标准手册相反，见 PROJECT.md ADR）。
- 提交信息：Conventional Commits，scope=`handeye-calib-tool`，身份 `AI-codex`；
  提交信息默认英文。

## 边界与禁止事项

- 不执行破坏性命令（git reset --hard、rm -rf、checkout -- 等），除非用户明确要求。
- 文档与代码矛盾时：以代码为准，停下向用户说明，并同步修正文档。
- 本地提交照常（每阶段可回溯）；只有用户明确说「推送」才 push GitHub。

## 会话仪式

- 开始：读 STATUS.md 交接块 → 读 PLAN.md 当前阶段与回退方案 → 复述理解 → 执行。
- 结束：更新 STATUS.md 交接块 → 同步 PROJECT/PLAN（如有必要）→ 构建+单测验证 →
  本地提交。
- 推送：仅当用户明确说「推送」时执行。
