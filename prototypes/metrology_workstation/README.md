# Metrology Studio

半自动三维测量工作站的第一阶段 UI 外壳。工程位于 `prototypes/`，不修改或依赖正式工作区的相机、会话与业务流程。

## 当前范围

- `QMainWindow` 工业深色主窗口，支持窗口缩放、Dock 隐藏/恢复及布局持久化。
- 七个业务模块共用同一个持久化 VTK 视口，切换模块不会重新创建渲染窗口。
- `QTreeView + QAbstractItemModel` 项目树，支持搜索、展开、重命名、删除确认、内部拖拽排序、显示/隐藏、锁定和右键菜单。
- 动态属性面板，按点云、网格、CAD、测量等对象显示元数据；工程师模式显示高级参数。
- 项目新建、打开、保存和关闭；第一阶段使用 `project.json` 保存项目树。
- 任务队列、运行日志、系统内存状态和 `QThreadPool + QRunnable` 后台任务接口。
- 真实 VTK 示例场景、标准视角、适应窗口、网格和实体/线框/顶点显示。

示例项目、演示设备和示例测量数值仅用于界面验证，不代表真实采集或检测结果。文件导入目前只登记文件路径和元数据，不解析三维文件；SQLite、真实设备、点云算法、STEP 解析、尺寸计算及报告生成不属于本阶段。

## 环境

目标平台为 Windows 11、Python 3.11+。依赖版本见 `requirements.txt`。本机验收使用现有 RVC 环境的 Python 3.10.20、PySide6 6.11.0、VTK 9.5.2；源码兼容该环境，但新部署建议使用 Python 3.11 或更高版本。

```bat
cd D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\metrology_workstation
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

也可直接使用已有环境：

```bat
"D:\Program Files\Anaconda\envs\rvc\python.exe" main.py
```

VTK 部件优先使用 `QVTKOpenGLNativeWidget`；当前 VTK 发行包缺少该模块时，回退到 `QVTKRenderWindowInteractor`，两者均使用真实 VTK Renderer。

## 操作

- `Ctrl+N`：新建项目；`Ctrl+O`：打开项目；`Ctrl+S`：保存项目。
- `Ctrl+I`：导入数据；`F`：三维场景适应窗口。
- 三维视图：左键旋转、中键平移、滚轮缩放。
- 双击数据对象：进入对应模块并显示对象属性。
- 「视图」菜单：隐藏或恢复项目数据库、属性与参数、任务中心，或恢复默认布局。
- 启动后自动保存主窗口几何与 Dock 状态到 `QSettings`。

保存实际界面截图：

```bat
python main.py --screenshot ..\..\outputs\metrology_studio\ui_shell.png
```

## 验证

```bat
python -m unittest discover -s tests -v
```

测试会短暂创建真实窗口。VTK 的 Windows OpenGL 后端不能在当前 `QT_QPA_PLATFORM=offscreen` 环境中创建像素格式，因此界面测试不使用离屏平台插件。

当前验收：10 项测试通过；已在本机真实桌面检查 1600×950 窗口、三维渲染、模块切换、项目树选择、属性回填和任务显示。未验证 Python 3.11 独立虚拟环境、实体相机、真实算法和客户机打包。

## 目录

```text
metrology_workstation/
├── main.py                 # 启动入口
├── requirements.txt
├── app/
│   ├── application.py      # QApplication 与 OpenGL 格式
│   ├── app_state.py        # 全局模块、模式、项目状态
│   └── main_window.py      # 主窗口组合与交互接线
├── core/
│   ├── data_model.py       # 项目数据节点与序列化
│   ├── project.py          # 项目文件存取
│   ├── scene_manager.py    # 统一三维对象生命周期
│   └── tasks.py            # 后台任务框架
├── ui/
│   ├── project_tree.py     # DB 树模型、代理与视图
│   ├── viewport.py         # 持久化 VTK 视口
│   ├── property_panel.py   # 动态属性与参数
│   ├── task_center.py      # 任务、日志、系统状态
│   ├── dialogs.py          # 新建项目对话框
│   ├── icons.py            # 统一矢量图标
│   └── theme.py            # 设计令牌与 QSS
├── tests/
└── docs/architecture.md
```
