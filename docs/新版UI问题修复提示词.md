# 主程序新版 UI 问题修复提示词

> 用途：把本文件作为提示词/任务说明交给编码代理执行修复。
> 问题来源：2026-10-21 对 v1.12.18 新版 UI 的离线预览实测 + 离屏回归（14 个脚本全绿，以下 3 项为确认问题）。
> 约束：遵守 `AGENTS.md` / `CONTRIBUTING.md`；修复涉及 `src/` 与测试脚本，按 PATCH 升版并同步 `CHANGELOG.md`。

## 运行环境与统一判据

- 解释器：`D:\Program Files\Anaconda\envs\rvc\python.exe`（conda rvc 3.10.20）。
- 离屏：`QT_QPA_PLATFORM=offscreen`；**禁止初始化相机 SDK、连接实体设备、修改设备网络**。
- 走查入口：`python main.py --offline-preview mobile_chain`（凳子离线数据，不连相机）。
- 回归命令（全部退出码 0 为通过，修复后复跑）：

```bash
QT_QPA_PLATFORM=offscreen python test_ui_frame_database.py
QT_QPA_PLATFORM=offscreen python test_ui_offline_preview.py
QT_QPA_PLATFORM=offscreen python test_ui_industrial.py
QT_QPA_PLATFORM=offscreen python test_ui_ribbon.py
python test_ui_industrial_gpu.py            # 修复后期望离屏也能通过（见问题 3）
```

---

## 问题 1：右键删除未选中帧时仍触发大点云预览加载

- **现象**：DB 树中右键点击一个未选中的帧打开上下文菜单时，右侧 3D 视图立即加载该帧（500 万点），与代码注释"只选中不启动大 PLY 预览"的意图相反。批量右键删除多个帧时每次都要白白等待加载。
- **根因**：`src/ui_v2/frame_database.py` 的 `FrameBrowser` 未重写 `mousePressEvent`。鼠标右键按下时 `QTreeWidget` 默认先改变当前项并发出 `currentItemChanged` → `_selected()` 发出 `frame_selected` 开始后台加载；`_context_menu()` 里的 `blockSignals + setCurrentItem` 发生在选中之后，挡不住已经发出的信号。
- **修复要求**：
  1. 在 `FrameBrowser` 中重写鼠标按下处理（如 `mousePressEvent`/`mouseReleaseEvent` 或 `contextMenuEvent` 前置拦截）：当按下的是右键且落点在**未选中**的帧/分组行上时，先把该行置为当前项并选中（`blockSignals` 包住），**不**触发 `frame_selected`；已选中的行右键保持现有行为。
  2. 左键点击选帧预览的行为完全不变。
  3. 不改动 `FrameBrowser` 对外信号契约（`frame_selected` / `delete_requested` 等）与 `FrameDatabaseController` 的接线。
- **验收判据**：
  - 新增/扩展离屏测试：模拟对未选中帧行发送右键按下事件，断言 `frame_selected` 未发出、该行已被选中；再对选中行右键，行为不变。
  - 上述回归命令全绿。

## 问题 2：删除 DB 数据确认框按钮未中文化

- **现象**：删除 DB 数据确认框显示英文 **Yes / No**，同项目 `src/ui_v2/session_projects.py` 已统一使用 `ChineseMessageBox` / `localize_buttons`（中文按钮），新版 UI 内文案风格不一致。
- **根因**：`src/ui_v2/frame_database.py:332` 附近使用原生 `QMessageBox.question(..., QMessageBox.Yes | QMessageBox.No, ...)`。
- **修复要求**：
  1. 复用 `src/ui_v2/dialogs.py` 的 `ChineseMessageBox` / `localize_buttons`（参照 `session_projects.py:11,132-137` 的用法）替换该处原生调用，按钮显示"是/否"。
  2. 顺手检查 `src/ui_v2/` 内其余原生 `QMessageBox.question/warning` 调用点，同一批次统一替换（若有第三处以上，在 CHANGELOG 中说明数量）。
  3. 返回值比较逻辑同步改为本地化后的等价常量，保持默认焦点为"否"。
- **验收判据**：
  - 离屏测试断言确认框按钮文本为中文（可直接断言 `localize_buttons` 被调用或对按钮 `text()` 断言）。
  - 上述回归命令全绿。

## 问题 3：`test_ui_industrial_gpu.py` 离屏环境直接崩溃

- **现象**：`QT_QPA_PLATFORM=offscreen python test_ui_industrial_gpu.py` 抛 `AttributeError: 'CloudCanvas' object has no attribute '_ready'`（exit 1）。项目约定"无显示器/CI → offscreen"，该脚本目前假设一定能拿到 `GpuCloudCanvas`。
- **根因**：脚本未检测平台与画布工厂的回退结果（offscreen 下 `create_canvas` 返回软件 `CloudCanvas`），直接访问 GPU 专有属性。
- **修复要求**：
  1. 脚本开头检测 `QApplication.platformName()`（offscreen/minimal）或画布工厂实际返回类型；无 GL 能力时打印 `[GPU SKIPPED]` 并以 **exit 0** 退出（与仓库其他可选能力测试的 skip 语义一致）。
  2. 有 GL 能力的原生环境保持现有检查逻辑与断言强度不变。
  3. 不引入新的第三方依赖。
- **验收判据**：
  - `QT_QPA_PLATFORM=offscreen python test_ui_industrial_gpu.py` → exit 0 且输出 `[GPU SKIPPED]`。
  - 其余回归命令全绿。

---

## 边界（不要做的事）

- 不改 DB 树结构、分组、删除/回收语义与 `core/frame_database.py` 的存储行为。
- 不改 ribbon/presentation 布局与其他工作区行为。
- 不为通过测试而放宽现有断言；新增 skip 仅限问题 3 的环境门控。
- 未实测的能力（实体相机、客户机安装包）不得写成已验证。

## 交付要求

1. 按 AGENTS.md 步骤执行：`src/version.py` 升 PATCH、`CHANGELOG.md` 记录版本/日期/修改/验证，只暂存本任务文件，`git diff --check` 通过后提交并推送 `origin/MultiCameraCalibration`。
2. CHANGELOG 中明确：修复 3 项、各自验证命令与退出码；注明"原生 GPU 路径未在本机复验（离屏 skip）"等未验证事项。
