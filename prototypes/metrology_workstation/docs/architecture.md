# 第一阶段架构说明

## 目标与边界

本阶段交付可运行的工业 UI 外壳，验证项目数据、统一场景、动态面板和模块导航的交互关系。目标是给后续采集、重建、CAD 和测量算法提供稳定接点，而不是在第一阶段模拟完成这些算法。

不接入正式 MultiCameraCalibration 工作区，不连接实体设备，不修改用户会话。原始数据节点默认锁定；项目树删除只移除项目引用，不删除文件。

## 方案选择

采用独立 PySide6 原型工程，而不是直接改动 `src/ui_v2/`。这样可验证新的测量工作流与视觉方向，同时不影响现有采集拼接软件。另一方案是直接集成正式 UI，但会把未确认的测量流程与现有设备生命周期耦合，本阶段不采用。

主窗口使用 Qt Dock 体系，而非固定三栏布局，以获得隐藏、浮动、拖放和布局恢复能力。三维区使用一个 `VTKViewport` 和一个 `SceneManager`，业务模块只改变可见对象与工具状态，禁止各自创建 Renderer。

## 数据与控制流

1. `AppState` 保存当前模块、工作模式、项目路径和保存状态，通过 Qt Signal 通知界面。
2. `ProjectTreeModel` 持有 `DataNode` 树；代理模型负责搜索过滤，视图只处理用户操作。
3. 树选择信号同时到达 `PropertyPanel` 与 `VTKViewport`，前者回填元数据，后者调整场景可见性。
4. 显示开关修改同一个 `DataNode.visible`，再经 `SceneManager` 更新 Actor，避免树和场景各存一份互相矛盾的状态。
5. `ProjectRepository` 以原子替换方式读写 JSON；项目树递归序列化，关闭再打开可恢复节点、元数据和锁定状态。
6. `TaskManager` 将耗时函数交给 `QThreadPool`，结果通过 Signal 回到 GUI 线程。算法实现不得在 UI 主线程执行。

## 后续接点

- 第二阶段用 SQLite Repository 替换或扩展 JSON Repository，并为 PLY/STL Reader 创建 Actor；保持 `DataNode.node_id` 与 `SceneManager` 键一致。
- 设备通信放入独立设备服务，UI 只订阅状态和结果，不直接调用 SDK。
- 点云与网格算法通过 `TaskManager.submit()` 执行，输出新数据版本，不覆盖原始节点。
- STEP/IGES 由 OCP 在算法层解析并转为可视化数据，UI 不直接处理 CAD 拓扑。
- 基准特征对齐与最佳拟合使用不同命令和结果类型，不能共用一个含义模糊的“对齐”状态。
- 测量结果关联来源数据 ID、参数、单位、公差和任务 ID，报告模块只消费可追溯结果。

## 验收记录

- `python -m unittest discover -s tests -v`：10 项通过。
- 真实 Windows 桌面启动正常，VTK 9.5.2 实际渲染；1600×950 截图位于根目录 `outputs/metrology_studio/ui_shell.png`。
- 已验证模块切换共享视口、属性切换、显示/隐藏、工程师参数、Dock 恢复和窗口缩放。
- 未验证实体设备、真实测量精度、算法性能、独立 Python 3.11 环境与安装包。
