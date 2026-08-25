# 手眼标定数据收集助手 (Hand-Eye Calibration Data Collection Assistant)

C++/Qt5 桌面应用，用于手眼标定数据采集。支持标记物标定和 TCP 戳点标定两种模式，输出与 HandEyeManager.exe 兼容的标定数据文件。

本项目从 Python/PyQt5 完整移植到 C++，消除 Python 中间层，直接调用 RVC X2 C++ SDK、HandEyeSDK C API 和 RVBUST Vis 引擎，同时获得编译期类型安全和更优性能。

## 目录架构

```
MyHandEyeTools/
├── CMakeLists.txt                    # Root: Qt5 + RVC + HandEyeSDK + RVBUSTVis
├── cmake/
│   ├── FindRVC.cmake                 # Custom module for RVC X2 C++ SDK
│   ├── FindRVBUSTVis.cmake           # Custom module for RVBUST Vis C++ lib (optional)
│   └── FindHandEyeSDK.cmake          # Custom module for HandEyeSDK .lib
├── src/
│   ├── CMakeLists.txt                # 源码清单、链接依赖、post-build DLL 部署
│   ├── main.cpp                      # 启动引导 + SEH 崩溃兜底 + 运行日志重定向
│   ├── app/
│   │   └── MainWindow.h / .cpp       # UI 装配 + 信号接线（业务在 CaptureFlow）
│   ├── models/
│   │   ├── CaptureRecord.h           # 头文件内联结构体
│   │   └── CalibrationMode.h         # 枚举：EyeHandMode / CalibType / MarkerType
│   ├── logic/
│   │   ├── AppConfig.h / .cpp        # QSettings 封装（真实配置在 %APPDATA%\RVBUST\HandEyeTool.ini）
│   │   ├── LogManager.h / .cpp       # 用户操作日志 → logs/app_<date>.log
│   │   ├── RuntimeLog.h / .cpp       # 技术运行日志 → logs/runtime_<date>.log
│   │   ├── CameraManager.h / .cpp    # RVC SDK：预览/采集/连接/自动重连
│   │   ├── CaptureFlow.h / .cpp      # 拍照→识别→保存业务流（含检测缓存/质量阈值）
│   │   ├── DetectionEngine.h / .cpp  # 同心圆/黑底白圆检测（RVC 原生→HandEyeSDK 回退）
│   │   ├── PointCloudUtils.h / .cpp  # 点云过滤/颜色/投影纯函数（可单测）
│   │   └── DataManager.h / .cpp      # 记录 CRUD + HandEyeManager 导出 + JSON 备份
│   ├── sdk/
│   │   └── HandEyeSDKBridge.h / .cpp # HandEyeSDK 直接链接 + 边界保护
│   └── ui/
│       ├── Theme.h / .cpp            # 颜色/字体/QSS
│       ├── TopNavBar.h / .cpp        # 标题/进度/相机连接状态
│       ├── ModeSelector.h / .cpp     # 手眼模式 + 标定方法 + 标记物类型
│       ├── DeviceListDialog.h / .cpp # 相机选择对话框
│       ├── SettingsDialog.h / .cpp   # 保存路径/相机参数/识别阈值/备份恢复
│       ├── DataInputCard.h / .cpp    # 数据卡片（坐标输入）
│       ├── DataInputArea.h / .cpp    # 卡片容器
│       ├── ActionButtons.h / .cpp    # [预览][拍照][识别][保存][撤销]
│       ├── SidePanel.h / .cpp        # 操作提示 + 文件预览
│       ├── ToastOverlay.h / .cpp     # 浮动通知
│       ├── Image2DView.h / .cpp      # 2D 可视化（画布缓存）
│       └── VisSceneView.h / .cpp     # 3D 点云可视化 + 识别点选择填充
├── third_party/
│   ├── RVC/                          # RVC SDK 头/库/运行 DLL
│   ├── HandEyeSDK/                   # HandEyeSDK 头/库/运行 DLL
│   ├── Vis/                          # RVBUST Vis 头/库
│   ├── OSG/                          # OSG 3.6.5 运行 DLL
│   └── Qt5/                          # Qt 运行 DLL + 平台插件
├── tests/                            # Qt Test 单测（unit_tests）
│   └── data/                         # 检测回归样本（0.png/0.ply、4x11A9）
├── data/                             # 标定数据默认保存目录（每会话一个子目录）
├── logs/                             # 程序运行日志（runtime_/app_ 按日期分文件）
├── config/
│   └── settings.json                 # 模板（程序不读取；真实配置在 %APPDATA% INI）
├── build/                            # CMake 构建输出（应用在 build/src/Release）
├── build_old/                        # 旧机器构建备份（可随时找回旧版本）
└── run.bat                           # Convenience launcher
```

## 依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Qt5 | 5.14.2 | GUI 框架 (Widgets, Core, Gui) |
| OpenCV | 4.7.0 | 图像处理 (core, imgproc, calib3d) |
| RVC X2 SDK | C++ | 3D 相机预览与采集 |
| HandEyeSDK | 3.5.0 | 标定计算 (C API, SEH 隔离) |
| RVBUST Vis | (optional) | 3D 点云可视化引擎 (Phase 2: 直接 OSG 嵌入) |
| Eigen3 | 3.4 | 线性代数 (header-only) |
| CMake | 3.20+ | 构建系统 |
| MSVC | 2017 | 编译器 (C++17) |

## 构建

```bash
cd MyHandEyeTools
mkdir build && cd build
cmake .. -G "Visual Studio 15 2017 Win64"
cmake --build . --config Release
```

构建完成后，`build/bin/` 目录会自动部署 RVC 和 HandEyeSDK 的 runtime DLL。

## 运行

```bash
cd build/bin
.\HandEyeCalibrationTool.exe
```

或直接运行 `run.bat`（如果配置了路径）。

## UI 布局

```
┌────────────────────────────────────────────────────────────────────┐
│ TopNavBar          顶部导航栏 (fixH=48)                            │
│   [标题 "手眼标定数据收集助手 V1.0"] [进度] [相机状态] [设置][帮助]  │
├────────────────────────────────────────────────────────────────────┤
│ ModeSelector       模式选择栏 (单行3组)                             │
│   [手眼模式: 眼在手外|眼在手上] [标定方法: 标记物|戳点] [标记物类型]  │
├──────────────────────────┬─────────────────────────────────────────┤
│ 左侧面板                  │ 右侧面板 SidePanel (fixW=408)           │
│ ┌──────────────────────┐ │ ┌─────────────────────────────────────┐ │
│ │ Image2DView          │ │ │ TipsCard "当前操作提示" (70~140px)  │ │
│ │ 标题(28px悬浮)        │ │ ├─────────────────────────────────────┤ │
│ │ 2D图像 (缩放/拖拽)    │ │ │ NotesCard "标定注意事项" (可折叠)   │ │
│ └──────────────────────┘ │ ├─────────────────────────────────────┤ │
│ ┌──────────────────────┐ │ │ PreviewCard "文件预览" (弹性)       │ │
│ │ VisSceneView         │ │ │ [相机目标点][机器人位姿][TCP点]     │ │
│ │ 标题(28px悬浮)        │ │ │ 文本预览区                         │ │
│ │ 3D渲染区              │ │ └─────────────────────────────────────┘ │
│ │ 工具栏(28px悬浮)       │ │                                        │
│ │ [复位][前视][俯视]     │ │                                        │
│ │ [右视][地面][拾取]     │ │                                        │
│ │ [菜单]                │ │                                        │
│ └──────────────────────┘ │                                        │
├──────────────────────────┤                                        │
│ DataInputArea (fixH=140) │                                        │
│  3 张 DataInputCard:     │                                        │
│  [相机目标点坐标]        │                                        │
│  [机器人拍照位姿]        │                                        │
│  [机器人目标点坐标]      │                                        │
├──────────────────────────┤                                        │
│ ActionButtons (minH=56)  │                                        │
│  [预览][拍照][识别][保存][撤销]                                     │
└──────────────────────────┴─────────────────────────────────────────┘
```

**关键设计决策：**
- DataInputArea 固定高度 140px，永不变化。卡片通过 layout stretch 自适应，保证 2D/3D 可视化视图在模式切换时尺寸不变。
- VisSceneView 的标题栏和工具栏为悬浮覆盖层（半透明背景），不占用 3D 渲染区域。
- SidePanel 中 NotesCard 可折叠，TipsCard 弹性高度 (70~140px)，PreviewCard 使用剩余空间。

## 组件索引

| 组件 | 源文件 | 说明 |
|------|--------|------|
| MainWindow | app/MainWindow.h/.cpp | 总控制器，所有 signal/slot 连接 |
| TopNavBar | ui/TopNavBar.h/.cpp | 标题、进度条、相机连接状态、设置/帮助按钮 |
| ModeSelector | ui/ModeSelector.h/.cpp | 手眼模式 + 标定方法 + 标记物类型 (单行) |
| Image2DView | ui/Image2DView.h/.cpp | 2D 实时图像，支持滚轮缩放和拖拽平移 |
| VisSceneView | ui/VisSceneView.h/.cpp | 3D 点云可视化，悬浮标题栏+工具栏 |
| DataInputArea | ui/DataInputArea.h/.cpp | 卡片容器，固定高度 140px |
| DataInputCard | ui/DataInputCard.h/.cpp | 单个坐标输入卡片，自适应字体+居中 |
| ActionButtons | ui/ActionButtons.h/.cpp | 操作按钮组 |
| SidePanel | ui/SidePanel.h/.cpp | 操作提示、可折叠注意事项、文件预览 |
| ToastOverlay | ui/ToastOverlay.h/.cpp | 浮动通知 |
| Theme | ui/Theme.h/.cpp | 全局颜色/字体/QSS 工厂方法 |

## 命名约定（用于需求描述）

| 你说 | 对应组件 | 源文件 |
|------|---------|--------|
| 顶部导航栏 / 顶栏 | TopNavBar | ui/TopNavBar.h/.cpp |
| 模式选择栏 / 切换按钮 | ModeSelector | ui/ModeSelector.h/.cpp |
| 2D视图 / 左图 / 图像区 | Image2DView | ui/Image2DView.h/.cpp |
| 3D视图 / 点云区 | VisSceneView | ui/VisSceneView.h/.cpp |
| 输入区 / 坐标卡片 | DataInputArea / DataInputCard | ui/DataInputArea.h/.cpp |
| 底部按钮栏 / 操作栏 | ActionButtons | ui/ActionButtons.h/.cpp |
| 右侧面板 / 信息面板 | SidePanel | ui/SidePanel.h/.cpp |
| 悬浮提示 | ToastOverlay | ui/ToastOverlay.h/.cpp |

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+S` | 保存当前数据 |
| `Ctrl+Z` | 撤销上一组数据 |
| `F5` | 刷新相机预览 |
| `F11` | 全屏切换 |

## 已完成优化

- [x] Python → C++ 完整移植 (19 个 .h/.cpp pairs + main.cpp)
- [x] CMake 构建系统 + 3 个自定义 Find*.cmake 模块
- [x] 窗口默认 3/4 屏幕大小，居中，最小 1280×720
- [x] 模式切换时 2D/3D 视图尺寸不变 (DataInputArea 固定 140px)
- [x] DataInputCard 自适应字体 (std::clamp(height/3, 11, 14)) + 垂直居中
- [x] VisSceneView 悬浮标题栏+工具栏（半透明覆盖层，不占用渲染空间）
- [x] SidePanel: TipsCard 弹性高度 (70~140px), NotesCard 可折叠
- [x] 模式选择器单行布局 (3组并列)
- [x] 预览按钮从 TopNavBar 迁移到 ActionButtons
- [x] LoadTest 按钮移除
- [x] 模式切换取消恢复逻辑 (从 config 读取旧值)
- [x] 后构建自动部署 RVC + HandEyeSDK runtime DLL
- [x] SEH 崩溃隔离 (__try/__except 替代子进程)
- [x] 编译期信号/槽类型检查 (Qt5 functor syntax)
- [x] 忙碌状态防护 (操作期间禁用按钮)
- [x] HandEyeSDK C API 直接 .lib 链接 (消除 ctypes)
- [x] 窗口最小化时暂停相机预览
- [x] 数据采集 JSON 自动备份 (限流 1次/秒)

## 待完成项

### Phase 2 (OSG 深度集成)
- [ ] VisSceneView 直接 OSG embedding (替代当前 HWND 方式)
- [ ] OSG camera manipulator 定制: 右键缩放→平移

### 功能增强
- [ ] 戳点标定 TCP 触测自动记录
- [ ] 多相机支持
- [ ] 标定结果可视化 (精度热力图等)
- [ ] 国际化 (English/中文切换)
- [ ] 自动化测试套件

## 需求描述模板

当你需要描述 UI 修改需求时，可以按以下格式说明，帮助准确理解：

```
【组件】: 明确组件名（如 TopNavBar, SidePanel, DataInputCard 等，见上方命名约定）
【位置】: 在窗口中的哪个区域
【当前行为】: 现在是什么样的
【期望行为】: 你希望改成什么样
【触发条件】: 什么操作后生效 (切换模式/点击按钮/窗口缩放/始终)
```

示例：
> 【组件】SidePanel 的 TipsCard
> 【位置】右侧面板最上方
> 【当前行为】最小高度 70px，字色灰色
> 【期望行为】最小高度改为 50px，标题字色改为橙色
> 【触发条件】始终

## 开发说明

- **检测优先级**: RVC 原生 API (ConcentricCircle) > OpenCV (findCirclesGrid) > HandEyeSDK
- **坐标体系**: 应用层 mm，Vis 引擎 m，接口自动转换
- **崩溃隔离**: HandEyeSDK 调用由 SEH `__try/__except` 保护，崩溃不传播到主进程
- **备份策略**: 最近 10 份 JSON 备份于 `save_dir/backup/`，关闭时 force 写入
- **信号连接**: 使用 Qt5 functor syntax `connect(sender, &Sender::signal, this, [this](args){...})`，编译期类型检查
