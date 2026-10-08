# CODE-MAP — 改代码时的导航图

> 用途：**下次要改某个行为，直接跳到对应片段**，不用从头读一遍。
> 只写"东西在哪、改哪里、别踩什么"，不写业务需求（那在 `PROJECT.md` / `PLAN.md`）。
> 行号会漂，这里只写**函数名 / 类名 / 文件**；括号里的行号是 2026-10-08 的快照，仅供参考。
> 规则：纯逻辑在 `src/logic/`，UI 只是投影；新增可测逻辑必须注册进 `tests/CMakeLists.txt`。

---

## 0. 三条最容易踩的全局约定

1. **`CalibType`（标定板 / 戳点）是分叉的主轴**。想知道"这个功能有没有按标定方式分派"，
   就 grep 这两个名字：`CalibType::TcpTouch`、`eyeInHand`。
   2026-10-08 修掉的两个 BUG（质检假报告、计算报"第 1 组机器人拍照位姿格式无效"）
   根因都是"某条链路忘了看 CalibType"。
2. **模式 → 数据列**（唯一的权威表，改这里就要同步改其余三处）：

   | 安装方式 | 标定方式 | 机器人拍照位姿 `robot_capture_pose` | 机器人目标点 `robot_target_xyz` | 相机目标点 `camera_target_xyz` |
   |---|---|---|---|---|
   | 眼在手上 | 标定板 | 必填（6 值） | 不采 | 必填 |
   | 眼在手外 | 标定板 | 必填（6 值） | 不采 | 必填 |
   | 眼在手上 | 戳点 | 必填（6 值） | 必填（3 值） | 必填 |
   | 眼在手外 | 戳点 | **没有这一列** | 必填（3 值） | 必填 |

   四个落地处，判据必须逐字一致（都是 `!eyeInHand && !isMarkerCalib`）：
   - `src/logic/CaptureFlow.cpp` → `validateSaveInputs()`（保存拦截）
   - `src/ui/DataInputArea.cpp` → `updateVisibility()`（卡片显隐）
   - `src/logic/DataQualityCheck.h` → `sourceFor()`（质检用哪一列判定）
   - `src/ui/SidePanel.cpp` → `updateFilePreview()`（文件预览显隐）
   有一条单测钉住 `sourceFor` 与卡片判据一致：`test_data_quality_check.cpp::sourceForFollowsCalibrationMode`。
3. **单帧误差 `cameraErrorPct` 只对黑底白圆标定板存在**。同心圆 / 戳点标定它是 `-1`，
   表示"不适用"，不是"0，很好"。任何读它的地方都要先判 `< 0`。

---

## 1. 分层的骨架

```
src/main.cpp                  → QApplication + MainWindow
src/app/MainWindow.{h,cpp}    → 装配器/信号适配（~2100 行）。业务在 CaptureFlow，设置窗在 SettingsDialog
src/logic/                    → 可测逻辑（纯函数优先，多数 header-only）
src/ui/                       → 控件与视图（不做自动化测试；改动要出人工验证清单）
src/sdk/                      → 唯一直接调第三方 DLL 的地方（HandEye / Vis / RVC）
src/models/                   → CalibrationMode.h（三个枚举）、CaptureRecord.h（一帧记录）
tests/                        → unit_tests（QtTest）+ measure_truth（已知真值测量比对）
```

`MainWindow` 之外的三个"住得比较远"的类：
- `RobotWorker`（`MainWindow.h` 里定义）—— 机器人四协议 reader **整体住在 `m_robotThread` 上**（T-009）。
  任何新的机器人阻塞调用都必须加进它，不许在 UI 线程直调（防整机挂死）。
- `ToolsPanel`（`src/ui/ToolsPanel.*`）——「工具」面板：像素→3D、手眼标定、坐标转换、
  机器人通信、8 个测量方法页（`MeasurePage` 基类 + `MeasurePages.cpp`）。
- `CaptureFlow`（`src/logic/CaptureFlow.*`）—— 拍照→识别→保存→撤销的状态机与校验。

---

## 2. "我要改 X，去哪"

| 想改的东西 | 去哪 |
|---|---|
| 采集/保存的必填项校验、报错文案 | `logic/CaptureFlow.cpp::validateSaveInputs()` |
| 拍照 → 识别 → 保存 的流程顺序、自动保存策略 | `logic/CaptureFlow.cpp::save()/undo()/applyDetectionResult()`；开关策略在 `logic/AutoFlowPolicy.h` |
| 识别回退链、同心圆/标定板的检测调用 | `logic/DetectionEngine.cpp`（回退链是硬约束，见 PROJECT.md 第 3 节） |
| 保存目录、导出文件（`pose.txt` / `cameraCapturePointXyz.txt` / `tcp.txt`）、备份 JSON | `logic/DataManager.cpp`：`writeHandEyeOutput()` → `writeMarkerOutput()` / `writeTcpOutput()` / `writeBackup()` / `loadBackup()` |
| 一帧记录的字段 | `models/CaptureRecord.h`；落盘字段名在同文件 + `DataManager::loadBackup()`（键名 `marker_count` 等） |
| 手眼标定计算（两个方法 + 返回码文案 + 结果排版） | `logic/CalibrationService.{h,cpp}`；入口是 `calibrate()`，按 `Params::calibType` 分派 |
| SDK 崩溃/返回码的最底层包装 | `sdk/HandEyeSDKBridge.{h,cpp}`（`safeCall` + `kSdkInternalError`） |
| 质检（数量/近重复/离群/分散度/相机目标点/标记点数） | `logic/DataQualityCheck.h`（header-only 纯逻辑）；UI 侧只负责组装 `Record` 与渲染 HTML |
| 「当前位姿 vs 最近已采」引导 | `logic/PoseGuide.h`（判定）+ `MainWindow::updatePoseGuide()`（选卡片、写文案） |
| 测量算法（8 个方法） | `logic/MeasureTools.*`（kernel）+ `logic/MeasureMethods.h`（方法目录/ROI 需求）+ `ui/MeasurePages.cpp`（每页的 `compute()`） |
| 像素→3D | `logic/PixelTo3DService.{h,cpp}`（共享服务）、`logic/PixelTo3DTools.h`（纯换算） |
| 坐标转换 / 走点验证 | `logic/TransformTools.h` |
| 机器人四协议的读位姿 | `logic/RobotPose.*`、`URRealtimeReader.*`、`NrcJsonReader.*`、`EfortPoseReader.*`；分派在 `RobotWorker::readerFor()` |
| 界面配色/字号/按钮样式 | `ui/Theme.h`（别在页面里写死色值） |
| 操作日志上屏规则 | `logic/LogPresentation.h::shouldShowInPanel()` 唯一判据；`LogManager` 只管落文件 |
| 启动/连接/释放相机的顺序与兜底 | `logic/CameraManager.*` + `logic/CameraRelease.h`（`shutdown()` 幂等）；Windows 注销路径在 `MainWindow::nativeEvent()` |

---

## 3. 手眼标定：两个方法的完整链路（2026-10-08 修复后）

```
采集阶段
  卡片（DataInputArea） ─┬─ camera_target_xyz   必填（两种方式都要）
                        ├─ robot_capture_pose  除「眼在手外+戳点」外必填
                        └─ robot_target_xyz    仅戳点
  保存      CaptureFlow::save() → validateSaveInputs() → DataManager::addRecord()
            → writeHandEyeOutput()
                标定板模式 → <会话目录>/pose.txt
                戳点模式   → cameraCapturePointXyz.txt + tcp.txt
                             （+ cameraCaptureRobotPose.txt 仅眼在手上）

计算（三个入口，全部走同一个分派）
  主界面「计算」      MainWindow::onCalibrate()            三列原样带下标对齐
  工具页「用当前会话」ToolsPanel::useCurrentSession()      ← MainWindow::onCalibrationSessionRequested()
  工具页「计算」      ToolsPanel::updateCalibrationResult() 手工读文件（按方式只读该读的那几列）
  ────────────────────────────────────────────────────────
  → CalibrationService::calibrate(folder, cameraLines, poseLines, tcpLines, params)
      ├─ calibType == Marker  → calibrateMarker()      folder 里的 1.png/1.ply + pose.txt
      └─ calibType == TcpTouch→ calibrateTcpTouch()    三列写进临时目录再调 SDK
                                 （眼在手外：拍照位姿传空串 → 桥接层翻成 nullptr）
  → HandEyeSDKBridge::handEyeCalibrationMarker / handEyeCalibrationTcpTouch
```

**两个方法的 SDK 返回码不通用**（`HandEye.h` 里的表不一样）：
`CalibrationService::errorText()`（标定板）/ `tcpErrorText()`（戳点）。
同为 `-2`：标定板是"有效数据不足 6 组"，戳点是"相机点位数据无效"。
`calibrateTcpTouch()` 还**在进 SDK 之前**做一遍逐组逐列的字段校验，
因为 SDK 只会说"数据无效"，现场看不出是哪一列哪一组。

**戳点结果里 `success2D/success3D` 必须留空**：SDK 文档写明这两个字段对 TcpTouch 无意义
（"ignore this field"），照抄进 `Result` 会让 `formatResult()` 把每一组都标成"（识别失败）"。

---

## 4. 硬约束（改代码前先看一眼，来自 PROJECT.md 第 3 节 / AGENTS.md）

- Vis/3D 同步命令（`GetCameraPose` 等）**绝不**放 UI 线程。
- 质量告警只报告、**不拦截**保存/标定。
- 识别回退链、检测缓存、3D 拾取异步化、3D 缩放深度自适应、保存路径回退、卡片格式校验、
  绿色版免安装、日志双轨、会话目录精简 —— 都是不可修改的核心功能。
- 测试 exe 是 GUI 子系统，stdout 看不见：失败详情用 `ctest ... --output-on-failure`，
  或用 `unit_tests.exe -o <文件>,txt`。构建后必查 `$LASTEXITCODE == 0` 且 exe 时间戳刷新。

---

## 5. 构建/测试/运行

```bash
cmake --build "D:/MyCode/MyHandEyeTools/build" --config Release
ctest --test-dir "D:/MyCode/MyHandEyeTools/build" -C Release --output-on-failure
D:/MyCode/MyHandEyeTools/build/src/Release/HandEyeCalibrationTool.exe
```
测试报告是按类分文件的：`build/unit_tests_report.<类名>.txt`（例如
`unit_tests_report.data_quality_check.txt` 里能直接看到每个用例 PASS/FAIL）。

双工作区：源码真源 = `AICode/handeye-tools`，运行/构建副本 = `D:\MyCode\MyHandEyeTools`。
**截至 2026-10-08 两者仍是分叉的**（AICode 停在 09-18，D 已到 10-08），按用户指示先不动。

---

## 6. 2026-10-08 这次修复留下的"路标"

- `DataQualityCheck::PoseSource` / `sourceFor()` / `sourceHasOrientation()`：
  质检"用哪一列判定"变成显式参数，报告里新增「数据源」一行写明用的是哪一列。
  `Level::NotApplicable` 与 `Level::Pass` 分开 —— "没数据可判"再也不显示"通过"。
- `Level` 新增成员后，**所有 switch over Level 都要补 case**（目前只有
  `MainWindow::refreshQualityReport()` 里的 `levelColor` / `levelTag` 两个 lambda）。
- 明细行封顶 12 条（`addDetail`）：15 组相同的位姿会产生 105 对重复，
  计数说真话、明细不铺满面板。
- `CalibrationService::Params` 多了 `calibType`；**新加调用点时别忘了它决定走哪个 SDK 接口**。
- `ToolsPanel` 手眼标定页多了「标定方式」下拉框 + 「相机点位文件」/「戳点文件」两行，
  按方式显隐（`updateCalibrationModeVisibility()`）。行显隐用 `QFormLayout::labelForField()`
  连标签一起隐藏（Qt 5.14 没有 `setRowVisible`）。
- `MainWindow::updatePoseGuide()` 改成无参：读哪张卡片由 `sourceFor()` 决定。
