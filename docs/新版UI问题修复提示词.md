# 主程序新版 UI 问题修复提示词

> 用途：记录问题、修复方案与验收判据。三项问题已在 v1.12.22 修复，具体实测结果见 CHANGELOG 对应条目。
> 问题来源：2026-10-21 对 v1.12.18 新版 UI 的离线预览实测 + 离屏回归（当时记录 14 个脚本通过，不包含失败的原生 GPU 脚本；以下 3 项为确认问题）。
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
QT_QPA_PLATFORM=offscreen python test_ui_industrial_gpu.py  # 明确输出 GPU SKIPPED；不代表 GPU 验收
```

---

## 问题 1：右键删除未选中帧时仍触发大点云预览加载

- **现象**：DB 树中右键点击一个未选中的帧打开上下文菜单时，右侧 3D 视图立即加载该帧（500 万点），与代码注释"只选中不启动大 PLY 预览"的意图相反。批量右键删除多个帧时每次都要白白等待加载。
- **根因**：`src/ui_v2/frame_database.py` 中内部 `QTreeWidget` 的鼠标事件未在选中前拦截。`FrameBrowser` 是外层 QWidget，仅重写其 `mousePressEvent` 不能可靠拦截子树点击。鼠标右键按下时 `QTreeWidget` 默认先改变当前项并发出 `currentItemChanged` → `_selected()` 发出 `frame_selected` 开始后台加载；`_context_menu()` 里的 `blockSignals + setCurrentItem` 发生在选中之后，挡不住已经发出的信号。
- **修复要求**：
  1. 在内部树的 viewport 上安装事件过滤器，于右键按下时处理目标选择，并拦截默认右键按下/释放逻辑。未选中的帧、点云/图像子项、分组先用 `QSignalBlocker` 设为当前和选中项，不发出 `frame_selected` 或 `component_selected`；已选中行右键保留多选集合和当前项。上下文菜单请求也复用同一选择方法。
  2. 左键点击选帧预览的行为完全不变。
  3. 不改动 `FrameBrowser` 对外信号契约（`frame_selected` / `delete_requested` 等）与 `FrameDatabaseController` 的接线。
- **验收判据**：
  - 离屏测试发送真实鼠标按下/释放及上下文菜单事件，覆盖帧、点云/图像子项和分组；断言预览信号均不发出、目标选中、删除按钮更新、多选右键保留当前项，左键仍只分发一次预览。
  - 上述回归命令全绿。

## 问题 2：删除 DB 数据确认框按钮未中文化

- **现象**：删除 DB 数据确认框显示英文 **Yes / No**，同项目 `src/ui_v2/session_projects.py` 已统一使用 `ChineseMessageBox` / `localize_buttons`（中文按钮），新版 UI 内文案风格不一致。
- **根因**：`src/ui_v2/frame_database.py` 的 `FrameDatabaseController.remove()` 中使用原生 `QMessageBox.question(..., QMessageBox.Yes | QMessageBox.No, ...)`。
- **修复要求**：
  1. 复用 `src/ui_v2/dialogs.py` 的 `ChineseMessageBox` / `localize_buttons`（参照 `session_projects.py:11,132-137` 的用法）替换该处原生调用，按钮显示"是/否"。
  2. 顺手检查 `src/ui_v2/` 内其余原生 `QMessageBox.question/warning` 调用点，同一批次统一替换（若有第三处以上，在 CHANGELOG 中说明数量）。
  3. 本地化仅改变按钮文本，继续使用同一套 Qt 标准返回值常量，DB 删除默认焦点保持为"否"；其他弹窗保留各自原有默认按钮。
- **验收判据**：
  - 离屏测试断言确认框按钮文本为中文（检查实际按钮 `text()`、默认焦点和返回值，而非仅检查辅助函数被调用）。
  - 上述回归命令全绿。

## 问题 3：`test_ui_industrial_gpu.py` 离屏环境直接崩溃

- **现象**：`QT_QPA_PLATFORM=offscreen python test_ui_industrial_gpu.py` 抛 `AttributeError: 'CloudCanvas' object has no attribute '_ready'`（exit 1）。项目约定"无显示器/CI → offscreen"，该脚本目前假设一定能拿到 `GpuCloudCanvas`。
- **根因**：脚本未检测平台与画布工厂的回退结果（offscreen 下 `create_canvas` 返回软件 `CloudCanvas`），直接访问 GPU 专有属性。
- **修复要求**：
  1. 创建 QApplication 后检测 `platformName()`，仅 offscreen/minimal 平台打印 `[GPU SKIPPED]` 并以 **exit 0** 退出；该结果记为环境跳过，不计为 GPU 渲染通过。原生平台仍要求 GPU 画布，意外回退软件时测试失败，避免隐藏回归。
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
2. CHANGELOG 中明确：修复 3 项、各自验证命令与退出码；区分离屏环境跳过、原生路径实测结果及未验证事项，原生失败如实记录。

## 本次实现与验证补充（2026-10-21）

- 中文化覆盖 4 个原先使用原生弹窗的模块，共 17 处 question/warning 调用；同时覆盖这些模块的 information/critical 及 BackendBridge 两处实例弹窗。保留按钮语义和默认选择。
- 增加真实 DB 删除确认框和四种标准弹窗的按钮文字、默认焦点与返回值测试。
- 在不包含其他并行改动的当前提交副本中应用本任务补丁进行离屏回归，避免混入标记显示等其他工作。
- 原生 GPU 脚本实测在退出最大化后的 `sidebar.isVisible()` 旧断言处失败；未修复的 97afd9e（v1.12.20）干净副本也在同一断言失败，属于已有独立问题。本批保留该断言，没有以环境跳过掩盖失败。
- 未验证实体相机、客户显卡及安装包；离屏 skip 不能作为原生 GPU 验收结果。
