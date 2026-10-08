# 手眼标定数据收集助手

面向 **RVC X1 / X2** 系列 3D 相机的 Windows 桌面工具（C++17 / Qt 5.14.2）。
现场做一次手眼标定需要的东西都在这里：连相机 → 采 2D + 3D → 识别标定板 / 戳点 →
存成 HandEyeManager 兼容的数据文件，外带测量、坐标转换、像素→3D、标定计算、
机器人通信等辅助工具。以**绿色免安装包**交付现场。

- 当前版本：**2.0**（版本号的唯一出处是 `src/AppInfo.h`，界面与标题都引用它）
- 主程序：`build/src/Release/HandEyeCalibrationTool.exe`
- 完整使用说明（含分章节的操作手册）：**程序内按 `F1`**，或点顶栏「帮助」

> 本文是**入口文档**：讲清"怎么跑、界面长什么样、文件存在哪"。
> 当前进度、已知问题、下一步计划分别在 `STATUS.md` / `PLAN.md` / `PROJECT.md`。

---

## 1. 快速开始

```bat
:: 运行（源码工作区）
run.bat
:: 或
D:\MyCode\MyHandEyeTools\build\src\Release\HandEyeCalibrationTool.exe
```

```bash
# 构建
cmake --build "D:/MyCode/MyHandEyeTools/build" --config Release

# 测试（两个目标：单元测试 + 已知真值测量比对）
ctest --test-dir "D:/MyCode/MyHandEyeTools/build" -C Release --output-on-failure
```

**绿色版**（免装 VC++ / RVC / HandEyeSDK，全部 DLL 内置）：

```powershell
powershell -File pack_portable.ps1 -Version 2.0
# 产出 dist\HandEyeCalibrationTool_v2.0\ 与同名 .zip，拷到目标机解压双击即用
```

---

## 2. 功能总览

| 板块 | 能做什么 |
|---|---|
| **采集** | 连相机 / 预览 / 拍照 / 识别 / 保存 / 撤销；自动识别结果可直接填卡片 |
| **标定数据** | 按「安装方式 × 标定方法」收集对应数据列，导出与 HandEyeManager 兼容的文件；JSON 自动备份与恢复 |
| **标定计算** | 主界面「计算」或工具页离线计算，输出 4×4 矩阵 + 总平均误差 + 逐组误差 |
| **辅助工具** | 欧氏距离、像素→3D（在线/离线）、坐标转换、机器人通信 |
| **测量** | 8 个方法：平面度 / 高度段差 / 面面距离夹角 / 圆环拟合 / 孔径(孔洞边界法) / 包围盒 / 截面轮廓 / 重复性 |
| **机器人通信** | 4 种协议读 TCP 位姿：Modbus TCP、UR Realtime、博纳斯(纳博特) JSON/TCP、埃夫特(EfortSDK) |
| **质量辅助** | 姿态引导（当前位姿 vs 最近已采）、数据质检（5 类，只报告不拦截）、标定板位姿 3D 可视化 |
| **帮助** | 程序内完整使用说明（9 章），`F1` 随时打开 |

---

## 3. 界面地图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TopNavBar  [手眼标定数据收集助手 V2.0]  [已采集 0/15 组数据 ▓░░░░]  ● 未连接   │
│                                          [连接] [新建会话] [设置] [帮助]        │
├──────────────────────────────────────────────────────────────────────────────┤
│ ModeSelector  [工具]  手眼模式：[眼在手外|眼在手上]                             │
│              标定方法：[标记物标定|戳点标定]                                    │
│              标记物类型：[同心圆|黑底白圆]  规格：[4×11]  尺寸：[A9]   ← 按模式显隐 │
├──────────────────────────────────────────────┬───────────────────────────────┤
│ 左列（可拖动分隔条）                          │ 右侧面板                       │
│ ┌─────────────────────┬────────────────────┐ │ ┌───────────────────────────┐ │
│ │ Image2DView         │ VisSceneView       │ │ │ 操作日志      [运行质检]   │ │
│ │ 「2D 实时图像」      │  （无标题栏）       │ │ │  [注意事项] 标定过程中…    │ │
│ │ 缩放：适应 / 百分比  │  悬浮工具栏：       │ │ │  [提示] …                  │ │
│ │ [图像][偏差图]       │  [复位][叠加历史]   │ │ │  [姿态引导] …              │ │
│ │ [尺寸总图][截面轮廓] │  [偏差着色]        │ │ │  [数据质检] …              │ │
│ │ [重复性趋势]        │                    │ │ ├───────────────────────────┤ │
│ │ [清除 ROI]          │                    │ │ │ 文件预览                   │ │
│ ├─────────────────────┴────────────────────┤ │ │ [相机目标点][机器人位姿]    │ │
│ │ DataInputArea  固定高度，3 张卡片          │ │ │ [机器人TCP点][标定结果]     │ │
│ │  [相机目标点坐标] [机器人拍照位姿]         │ │ │  （文本预览区）             │ │
│ │  [机器人目标点坐标]                      │ │ │                            │ │
│ ├──────────────────────────────────────────┤ │ │                            │ │
│ │ ActionButtons  [预览][拍照][识别][保存]    │ │ │                            │ │
│ │                [计算][撤销]               │ │ │                            │ │
│ │   连接机器人后追加：[拍照位姿] [戳点位姿]  │ │ │                            │ │
│ └──────────────────────────────────────────┘ │ └───────────────────────────┘ │
└──────────────────────────────────────────────┴───────────────────────────────┘
```

几个界面要点：

- **没有状态栏**。相机连接状态与采集进度在顶栏；瞬时反馈是顶栏下方的浮动提示（Toast），
  历史反馈是右侧「操作日志」卡片。
- **2D 与 3D 是左右并列**的（在左侧列里），不是上下堆叠。
- 左右两列之间是**可拖动的分隔条**（默认约 3:1）。
- 「文件预览」的 4 个 tab 按模式显隐；「机器人拍照位姿」卡片在**眼在手外 + 戳点**时隐藏。

### 三个按钮的启用时机（现场最常问）

| 按钮 | 什么时候可用 |
|---|---|
| 预览 | 相机已连接 |
| 拍照 | 相机已连接 |
| 识别 | 刚拍完一张（有图可识别） |
| 保存 | **识别成功之后** |
| 计算 | 已保存 ≥1 组数据 |
| 撤销 | 已保存 ≥1 组数据 |
| 拍照位姿 | 机器人已连接 **且** 本模式需要这一列（眼在手外+戳点为**无**） |
| 戳点位姿 | 机器人已连接 **且** 标定方法为戳点 |

### 模式 → 采集哪些数据列

| 安装方式 | 标定方法 | 机器人拍照位姿 | 机器人目标点 | 相机目标点 |
|---|---|---|---|---|
| 眼在手上 | 标记物 | 必填 | 不采 | 必填 |
| 眼在手外 | 标记物 | 必填 | 不采 | 必填 |
| 眼在手上 | 戳点 | 必填 | 必填 | 必填 |
| 眼在手外 | 戳点 | **没有这一列** | 必填 | 必填 |

这条规则的唯一判据在 `src/models/CalibrationMode.h` 的 `needsCapturePose()` /
`needsRobotTarget()`；界面显隐、保存校验、质检、文件预览、读位姿按钮都调它。

---

## 4. 一次典型标定流程

1. 顶栏「连接」→ 在设备列表里选相机（显示名称 / 序列号 / 是否被占用）。
2. 选模式：手眼模式 + 标定方法（+ 标记物类型与规格/尺寸）。
3. 摆好标定板 → 「预览」对焦 →「拍照」。
4. 「识别」：成功后「相机目标点坐标」自动填入；
   此时若需要机器人位姿，点「拍照位姿」（或手动填「机器人拍照位姿」）。
5. 「保存」：必填项缺失会拦下并说明原因；**质量告警只提示，不拦保存**。
6. 移动机器人到不同位姿，重复 3–5，建议采集 **15–20 组**（顶栏进度条按 15 组显示）。
   - 右侧「姿态引导」会显示"当前位姿 vs 最近已采"的差异与建议；
   - 「运行质检」可随时检查数量/近重复/离群/分散度等 5 类问题。
7. 「计算」：输出 4×4 矩阵 + 总平均误差 + 逐组误差，可复制。
8. 数据同时落在会话目录里（见下节），可直接交给 HandEyeManager 流程。

> 换一组标定：顶栏「新建会话」。**已采集的记录留在磁盘上不会删除**，
> 界面换到新的时间戳目录。

---

## 5. 工具面板

顶栏模式栏最左边的「工具」按钮打开。左侧列表共 13 项：

| # | 工具 | 说明 |
|---|---|---|
| 1 | 欧氏距离 | 两点距离，单位可选 mm / cm / m |
| 2 | 像素→3D | **在线**（相机实时，主 2D 视窗点击取点）或**离线**（加载含 png+ply 的会话文件夹，用主 2D 视窗取点）；离线对齐数据免内参，线扫需内参 |
| 3 | 手眼标定 | 离线算：选会话文件夹 + 标定方式 + 安装方式，输出矩阵与逐组误差 |
| 4 | 坐标转换 | 走点验证：标定矩阵 + 相机系点 → 机械臂位姿；**7 种姿态格式**（RPY/WPR/ZYX/两种四元数/旋转矩阵/轴角） |
| 5 | 机器人通信 | 4 种协议连机器人读 TCP 位姿（见下） |
| 6 | 平面度 | 测量方法，ROI A = 被测面 |
| 7 | 高度段差 | 测量方法，ROI A = 基准面，ROI B = 被测面 |
| 8 | 面面距离夹角 | 测量方法，ROI A = 面 A，ROI B = 面 B |
| 9 | 圆环拟合 | 测量方法，ROI A = 环形材料（**实心件外缘目前不适用**，见 `reports/T-012/BASELINE.md`） |
| 10 | 孔径(孔洞边界法) | 测量方法，ROI A = 孔 + 约 2 个点距的材料 |
| 11 | 包围盒 | 测量方法，ROI A = 整个物体 |
| 12 | 截面轮廓 | 测量方法，ROI A = 被测区域 |
| 13 | 重复性 | 测量方法，**不需要 ROI**（用重复性序列统计） |

**测量方法的通用操作**：先在主窗口「拍照」，再在工具页选方法 → 在 2D 视图上拖框选
ROI（需要两个 ROI 的方法依次拖两次）→ 点「测量」。结果表 5 列（方法/数值/单位/点数/可信度），
同时写进「操作日志」的 `[测量-说明]` / `[测量-结果]` 两行。
「加入重复性」把当前读数并入序列；2D 视图还有偏差图 / 尺寸总图 / 截面轮廓 / 重复性趋势四个页签。

**机器人通信页**：

| 协议 | 端口（默认） | 读数单位 / 说明 |
|---|---|---|
| Modbus TCP | 502 | 格式可选 Float32 / Int32×系数 / Int16×系数，可填起始寄存器与站号 |
| UR Realtime (30003) | 30003 | 机器人主动推流；姿态是**轴角(弧度)**，位置**米**（程序已换算成 mm） |
| 博纳斯(纳博特) JSON/TCP | 6001 | 读 x y z rx ry rz（mm/度）；应答字段名未知时自动试常见名字并**把原始应答写进运行日志** |
| 埃夫特（EfortSDK） | 由 SDK 决定（端口框隐藏） | 读基坐标下的 TCP 位姿 |

连不上可真机时点「模拟连接成功」验证按钮显示与样式。
**四种协议的真机约定仍有 4 项待实测**，见 `reports/机器人通信真机联测任务书.md`。

---

## 6. 输出文件与目录

每次「新建会话」建一个时间戳目录（默认在设置里的保存路径下）：

```
<保存路径>/calibration_data_20261008_141412_254/
├── 1.png                     # 每帧的 2D 图（序号即组号）
├── 1.ply                     # 每帧的 3D 点云
├── pose.txt                  # 标记物标定：机器人拍照位姿
├── cameraCapturePointXyz.txt # 戳点标定：相机目标点
├── tcp.txt                   # 戳点标定：机器人目标点
└── cameraCaptureRobotPose.txt# 戳点标定 + 眼在手上：机器人拍照位姿
```

标定板模式写 `pose.txt`；戳点模式写相机点位 + 戳点文件，
（眼在手上时多一份 `cameraCaptureRobotPose.txt`）——即"只写本模式真正采集的列"。

**保存路径回退链**（绿色包换机时的关键）：设置里的目录不可用（不存在 / 不可写）时，
自动退到 `<exe目录>/data`，再退到 `文档\HandEyeCalibData`，并把修正后的路径存回配置，
启动时用浮动提示告知。

**日志**（都在 exe 目录的 `logs\` 下，按日期分文件）：

| 文件 | 内容 |
|---|---|
| `logs\runtime_<日期>.log` | 技术运行日志：连接 / 采集 / 识别 / 崩溃 / `[NRC]` 原始应答等 |
| `logs\app_<日期>.log` | 操作日志：用户做了什么 |

**备份**：会话记录自动写 JSON 备份（限流 1 次/秒），设置里可「从备份恢复」。

---

## 7. 快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+S` | 保存当前数据 |
| `Ctrl+Z` | 撤销上一次保存 |
| `F5` | 刷新相机预览（已连接时） |
| `F11` | 全屏切换 |
| `F1` | 打开使用说明 |

---

## 8. 目录架构

```
MyHandEyeTools/
├── CMakeLists.txt              # 根：Qt5 + RVC + HandEyeSDK + EfortSDK + RVBUSTVis(可选)
├── cmake/                      # FindRVC / FindRVBUSTVis / FindHandEyeSDK 等自定义模块
├── src/
│   ├── main.cpp                # 启动引导 + SEH 崩溃兜底 + runtime 日志重定向
│   ├── AppInfo.h               # 程序名 / 版本号的唯一出处（界面别写死）
│   ├── app/MainWindow.{h,cpp}  # UI 装配 + 信号接线（业务在 CaptureFlow）
│   ├── models/                 # CalibrationMode.h（枚举+needs* 判据）、CaptureRecord.h
│   ├── logic/                  # 可测逻辑（多数 header-only）
│   │   ├── CameraManager / CameraRelease       # RVC 连接、预览、采集、释放
│   │   ├── CaptureFlow / AutoFlowPolicy        # 拍照→识别→保存 状态机与校验
│   │   ├── DetectionEngine                     # 检测回退链（RVC 原生 → HandEyeSDK）
│   │   ├── DataManager                         # 记录 CRUD + 导出 + JSON 备份/恢复
│   │   ├── CalibrationService / BoardPoseFit   # 标定计算与结果排版 / 板位姿拟合
│   │   ├── RobotPose / URRealtimeReader / NrcJsonReader / EfortPoseReader
│   │   ├── DataQualityCheck / PoseGuide        # 质检 5 类 / 姿态引导
│   │   ├── MeasureTools / MeasureMethods       # 测量内核 + 方法目录
│   │   ├── PixelTo3DService / PixelTo3DTools   # 像素→3D（在线/离线共用）
│   │   ├── TransformTools / ToolInputParser    # 坐标转换 / 工具页输入解析
│   │   ├── HelpContent.h                       # 使用说明的正文（纯数据表）
│   │   ├── LogManager / RuntimeLog / LogPresentation  # 双日志 + 上屏规则
│   │   └── AppConfig / FrameBuffer / UiStallWatchdog / GeometryTools / PointCloudUtils
│   ├── sdk/HandEyeSDKBridge.{h,cpp}   # 唯一直接调 HandEyeSDK 的地方（safeCall + SEH）
│   └── ui/                     # 控件与视图（不做自动化测试，改动出人工验证清单）
│       ├── TopNavBar / ModeSelector / ActionButtons / DataInputArea / DataInputCard
│       ├── SidePanel / Image2DView / VisSceneView / ToastOverlay / Theme
│       ├── ToolsPanel / MeasurePage / MeasurePages    # 工具面板与 8 个测量页
│       ├── SettingsDialog / DeviceListDialog / HelpDialog
│       └── ArrowComboBox / ViewOverlay
├── tests/                      # Qt Test 单测（unit_tests）+ measure_truth 真值比对
├── codex_testData/             # measure_truth 的合成数据（只入库 manifest/README）
├── third_party/                # RVC / HandEyeSDK / EfortSDK / Vis / OSG / Qt5（运行库）
├── packaging/README.txt        # 绿色版给现场看的说明
├── pack_portable.ps1           # 绿色包打包脚本 → dist/
├── dist/                       # 打包产出（不入库）
├── build/                      # CMake 构建输出（应用在 build/src/Release）
├── data/                       # 默认保存目录（每会话一个子目录）
├── config/settings.json        # 模板（程序不读取；真实配置在 %APPDATA% INI）
├── reports/                    # 分析报告、探针脚本、真机联测任务书
└── run.bat                     # 启动脚本（首次会顺带部署 Qt 运行库）
```

---

## 9. 依赖与构建

| 依赖 | 版本 | 用途 |
|---|---|---|
| Qt5 | 5.14.2 (msvc2017_64) | GUI（Widgets / Core / Gui / Concurrent / **Network**） |
| RVC SDK | — | 3D 相机预览、采集、原生检测 |
| HandEyeSDK | — | 标定计算（C API，SEH 隔离） |
| EfortSDK | — | 埃夫特机器人位姿 |
| RVBUST Vis + OSG | Vis / OSG 3.6.5 | 3D 点云可视化（**可选**，`find_package(... QUIET)`） |
| CMake | 3.20+ | 构建系统 |
| Visual Studio | **2026** | 编译器（C++17，`/utf-8`） |

> 项目**不再依赖 OpenCV / Eigen**（早期 README 写过，那两行已作废）。
> Qt 用的虽是 `msvc2017_64` 官方包，但构建工具链是 VS 2026，二者兼容。

```bash
cmake --build "D:/MyCode/MyHandEyeTools/build" --config Release
```

构建后自检：`$LASTEXITCODE` 为 0、exe 时间戳已刷新。

### 测试

两个 ctest 目标，共 28 个测试类：

```bash
ctest --test-dir "D:/MyCode/MyHandEyeTools/build" -C Release --output-on-failure
```

| 目标 | 内容 |
|---|---|
| `unit_tests` | QtTest 单元测试（纯逻辑为主），每个类单独出一份报告 `build/unit_tests_report.<类名>.txt` |
| `measurement_truth` | 已知真值测量比对：ROI 像素矩形 → 网格 → 测量算法，全部对照 `codex_testData/manifest.json` |

> 测试 exe 是 **GUI 子系统，stdout 看不见**。要看失败详情用
> `--output-on-failure`，或 `unit_tests.exe -o <文件>,txt`。

---

## 10. 开发约定（细则见 `AGENTS.md`）

- **纯函数先行**：可测逻辑放 `src/logic/`，UI 只是投影；新增纯逻辑必须注册进
  `tests/CMakeLists.txt` + `test_main.cpp`，并先写单测再实现。
- **UI 不做自动化测试**：界面改动由 AI 输出「操作步骤 + 预期结果」清单，人工执行。
- **双工作区**：源码真源 = `AICode/handeye-tools`，运行/构建副本 = `D:\MyCode\MyHandEyeTools`。
- **单位约定**：卡片与工具默认 **mm + 度**；FANUC WPR 按 RVC 导出实测顺序（绕 Z,Y,X）。
- **不可修改的核心功能**见 `PROJECT.md` 第 3 节（识别回退链、质量告警不拦截、检测缓存、
  3D 拾取异步化、保存路径回退、绿色版免安装、双日志等）。
- **Vis/3D 同步命令**（`GetCameraPose` 等）绝不放 UI 线程；机器人阻塞调用只在
  `RobotWorker` 线程上。
- 程序名 / 版本号只在 `src/AppInfo.h` 改；界面配色/字号只在 `src/ui/Theme.h` 改。

---

## 11. 文档索引

| 文件 | 内容 |
|---|---|
| `AGENTS.md` | 项目规则与硬约束（每次会话自动加载） |
| `STATUS.md` | 当前进度、交接块、已知问题、失败方案 |
| `PLAN.md` | 阶段步骤、DoD、验证、依赖、回退方案 |
| `PROJECT.md` | 目标、红线、约束、非目标、验收标准、ADR、变更记录 |
| `reports/CODE-MAP.md` | 改代码的导航图："我要改 X，去哪" |
| `reports/机器人通信真机联测任务书.md` | 机器人通信四项待实测的现场测试书 |
| `reports/T-012/BASELINE.md` | 测量精度基线与判据变更记录 |

---

## 12. 描述需求的小模板

```
【组件】: 明确组件名（如 TopNavBar / SidePanel / ActionButtons，见 §3 界面地图）
【位置】: 在窗口中的哪个区域
【当前行为】: 现在是什么样的
【期望行为】: 你希望改成什么样
【触发条件】: 什么操作后生效（切换模式 / 点击按钮 / 窗口缩放 / 始终）
```

示例：

> 【组件】ActionButtons
> 【位置】主界面底部按钮栏
> 【当前行为】「计算」在保存 1 组数据后就可用
> 【期望行为】改成保存满 6 组才可用
> 【触发条件】保存/撤销后
