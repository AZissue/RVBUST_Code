# STATUS.md — 进度状态（每次会话结束必须更新）

> 最后更新：2026-09-20
> 只保留「当前快照」，不积累历史；旧条目删除即可，git 历史里仍可追溯。

## ⏭ 交接块（新会话先读这里）

- **2026-09-20（第 5 回合：相机生命周期与配置批，待 Codex 验收）**
  - 规模：只做用户第 1、8、12 条（相机参数来源 / 流程自动化 / 相机可靠释放），
    其它条目未动。构建 `$LASTEXITCODE=0`，ctest **231 passed / 0 failed / 1 skipped（21 类）**。
  - 任务 1（默认用相机内部参数）：新增 `logic/CameraParamPolicy.h`（纯决策：用相机值 /
    下发保存值 / 操作员改过值，单测 9 项）；`AppConfig` 新增 `use_camera_params`（默认 true）；
    `CameraManager::applyConnectParams()` 是唯一决定"要不要下发"的地方，true 时
    **一个 setParameter 都不调用**，并把读回值写进 AppConfig；日志给出
    `[CAM] params: use_camera_params=1 → …不下发任何参数` 与
    `[CAM] effective params (camera-internal|saved-config): k=v…` 两行，来源可自查。
    设置页新增「当前相机参数 + 来源说明」「从相机读取当前参数（未连接时禁用）」
    「使用相机内部参数」勾选框；改动任一数值自动切到"使用保存的参数"并提示，绝不静默忽略。
  - 任务 2（流程自动化）：`logic/AutoFlowPolicy.h`（纯决策，单测 8 项）+
    `AppConfig` 三个键**默认全关**；自动保存走**同一个** `validateSaveInputs`，
    不满足就写一行 `自动保存跳过：…` 到操作日志（识别失败/超时/必填项缺失都有）；
    "拍照时自动读取机器人位姿"两个入口统一到 `auto_read_robot_pose`（工具面板复选框
    改为受控镜像，不再各写各的）。
  - 任务 3（相机可靠释放）：①正常关闭顺序固定为 停预览 → 有界等在飞线程(3 s) →
    `shutdown()`，`shutdown()` 由 `logic/CameraRelease.h::plan()` 改成状态驱动的幂等
    （重复调用只写一行 no-op，不重复 Close/Destroy/信号），日志
    `[CAM] release on close: N ms (preview stopped, captured=0, released=1)`；
    ②`WM_QUERYENDSESSION` 有界(1.5 s)释放后回 TRUE；③崩溃路径**改了**：不再弹模态框，
    先写异常码/模块/地址/时间到 runtime 日志，再在独立线程做一次 ≤2 s 释放尝试，然后
    `TerminateProcess` 立即退出（判定故障模块是 RVC/HandEyeSDK 时跳过 SDK 调用，
    理由见交付说明）；④`onHealthTick` 默认 5 s → **30 s**，空闲 60 s 自动暂停预览、
    有输入立即恢复，设置页新增「释放相机」一键清理；⑤连接失败分类为
    "被占用/未找到/不支持/SDK 错误"并给可读建议，重试 1/2/3 s（`connect_retry_count`）。
  - 测试注入点：`HEC_CRASH_INJECT=after-connect|after-capture` 触发空指针写
    （`logic/CrashInject.h`，未设变量时仅一次空串比较，不影响正常使用）。
  - **未验证（重要）**：本轮**没有启动过 GUI**（会话内启动 exe 需要交互授权，未获批准），
    所以关闭/空闲/设置页/崩溃注入的运行期行为**只有编译期与单测证据**；Codex 验收
    3.5 的 ①②③④ 四项（3 次正常关闭 / `taskkill /F` ×10 / 注入崩溃 / 双实例占用）
    需在真机跑。崩溃时不做 SDK 调用（故障模块是 SDK 时）是**有意的取舍**，见交付说明。
- **2026-09-18（打包 test2.0 测试包给现场试用）**
  - 按 `pack_portable.ps1` 打出 `dist/HandEyeCalibrationTool_test2.0/`（228.6 MB，
    200 个文件）+ `dist/HandEyeCalibrationTool_test2.0.zip`（85.1 MB）。
  - 脚本增强：新增 `-Name` 参数（留空仍为 `HandEyeCalibrationTool_v<Version>`），
    说明文件改名为 `使用说明.txt`，内容由 `packaging/README.txt` 模板注入版本与打包
    日期（`@VERSION@` / `@DATE@`）；脚本仍保持纯 ASCII（中文文件名用码点拼出）。
  - 验证：包内 exe 与 build 产物 SHA256 一致；在本机运行中的实例上枚举其同目录加载
    的 54 个模块，全部存在于包内（含 Qt5Network.dll）；`platforms/`（1 个）与
    `osgPlugins-3.6.5/`（77 个）齐全；ctest 1/1 通过。
  - 未做：没在「未装 RVC/VC++ 运行库」的干净机器上实测；打包时本机有实例正在运行，
    锁住了 `build/src/Release/vcruntime140_1.dll`，导致 CMake post-build 拷贝报
    `Permission denied`（关掉运行中的实例后重建即恢复，不影响本次包的内容）。
- **2026-09-17（v2.1 三项任务，Codex 验收 × Claude Code 实现的循环）**
  - 任务一（卡死）**已修复并验收**：①`CameraManager` 全部 RVC 设备访问收进一把
    `recursive_timed_mutex`，拍照改为"确定性等预览让位"（原来的"等 3 s 超时后照样并发进设备"
    会让 SDK 状态损坏/黑图）；②删掉拍照完成回调链路上延后一拍的
    `QFutureWatcher::setFuture()` 重置——它会拆掉 call-out 接口而 Qt 仍在投递完成事件，
    导致**每次拍照必崩 0xC0000005**（表现为弹「底层 SDK 崩溃」后只能重启）；③重负载缓冲改
    `FrameBuffer`（`shared_ptr<const vector>`）共享，去掉每次采集约 174 MB memcpy；
    ④去掉嵌套 `processEvents` 等待，Vis 初始化加哨兵（不会再建第二个 View）；
    ⑤新增 UI 停顿看门狗 `[WATCHDOG] UI stall …` 与按测试类分开的 ctest 报告文件。
    实测：12 次拍照 + 5 轮×10 次突发操作（含滚轮/质检/工具面板/撤销）**0 崩溃 0 卡死**，
    UI 停顿峰值 109 ms，句柄增速从 +25/循环 降到 ~+2/循环，内存稳定在 ~1.27 GB 平台期；
    连接相机的 2445 ms UI 阻塞已被看门狗正确报出。
  - 任务二（博纳斯机器人）**已实现并验收**：新增 `logic/NrcJsonReader`（厂商 `nrc_host.dll`
    抓包实测的 `Nf`+CRC32 JSON/TCP 协议，cmd 0x2002 握手 / 0x2F07 读当前 TCP 位姿），
    工具面板协议下拉新增「博纳斯(纳博特) JSON/TCP」（默认端口 6001），零新增二进制依赖。
    Codex 用自建 mock 控制器驱动真实 GUI 验收：发出的帧与厂商 SDK 抓包**逐字节一致**，
    「拍照位姿」「戳点位姿」分别把 111.500 222.250 333.750 … 填进两张卡片。
    **待实机**：应答 JSON 真实字段名（已做宽容解析 + 原始应答 hex/文本写 runtime 日志）。
  - 任务三（测量与可视化）**已实现，GUI 仅冒烟**：`logic/MeasureTools`（平面/平面度 LSQ+MZ/
    高度段差/面面距离夹角/圆拟合/PCA 包围盒/截面轮廓/重复性统计/稳健 ±3σ_MAD 色标）+ 21 项
    合成数据单测；工具面板新增「测量」页（2D 视图拖框 ROI → 6 种方法 → 结果表 → 加入重复性）；
    2D 视窗内可切换 `图像/偏差图/尺寸总图/截面轮廓/重复性趋势`；3D 视窗新增「偏差着色」与测量标注。
    **Codex 已验证**：构建 exit 0、ctest 193 passed/0 failed/1 skipped（17 类）、
    GUI 内确认上述页签与开关真实存在；**未做**：ROI 拖框→测量数值的人工闭环、与 Python 版
    同数据同 ROI 的数值对照（验收 A3.5 未完成）。
- **已知遗留（用户需知）**：①现场 2D 图像当前整幅黑图（环境光不足/遮挡，见下），
  同心圆识别因此 0 标记物，`识别→保存` 闭环与"5 轮突发都能识别保存"（A1.7）**未验证**；
  ②工作集在 ~1.27 GB 平台期偏高（多帧 68 万点云累积），现场若内存紧张需再压。

- 当前状态：完成阶段 8 UI 优化（2026-09-10）：①右侧面板重构为"操作日志"（合并原
  "操作提示/姿态引导/数据质检"与"标定注意事项"），启动时默认显示 [注意事项] 的四条
  建议（带颜色标签），后续 [提示]/[姿态引导]/[数据质检] 追加至同一可滚动日志区；
  原"文件预览"与"操作日志"平分竖直空间（去掉固定 220px 高度）。②修复主窗口前台激活
  行为：当 Windows 标记主窗口为 active 时调用 raise()，确保从任务栏或 Alt-Tab 选中后
  能正确置顶（解决嵌入 native Vis 3D 子窗口导致的 z-order 问题）。③修复启动时自动
  显示质检报告的问题：数据 dataChanged 信号时不再自动刷新质检，只在用户点击"运行质检"
  按钮时才刷新并追加报告（避免空数据状态下显示质检日志）。
- 下一步：用户按三阶段联测清单实测新 UI；验证前台激活与日志默认内容；继续真机 UR/
  Modbus 联调；阶段 5/6/9/10 未开工。
- 正在进行的文件：无（本轮 UI 改动已完成）。
- 卡点 / 风险：无新增。
- 上次会话结束已提交/推送：是。2026-09-11 三处推送：①AICode 的 HandEyeTools 分支强推为
  D 工作区原样历史（项目在仓库根，tip e9c01be；已清理 .vs 并写入 .gitignore）；②AICode
  main 同步当前版本，项目目录由 `handeye-calib-tool` 改名为 `handeye-tools`（符合公约
  小写+连字符命名）；③AZissue/RVBUST_Code 的 HandEyeTools 分支同样推为 D 工作区历史
  （该仓库约定「一个项目一个分支、项目放分支根」），并在其 main 的总览 README 登记。
  构建 + ctest 全绿。
- 文档约定：项目根目录只保留 `README.md` / `PLAN.md` / `PROJECT.md` / `STATUS.md` 四份
  md，外加项目规则文件 `AGENTS.md`（2026-09-11 清理其余 12 份后按用户要求恢复保留）。

## ✅ 已完成

- [x] 2026-09-11 精简项目根文档：删除 00_README、INDEX、START_HERE、SESSION_PROMPTS、
  PUSH_GUIDE 及各类代码审查 / 改进计划文档共 12 份（git 历史可回溯）；根目录保留
  README/PLAN/PROJECT/STATUS 四份 md 与项目规则文件 AGENTS.md。
- [x] 2026-09-11 推送当前版本到 AICode / RVBUST_Code 并改名项目：①AICode 的 HandEyeTools
  分支强推为 D 工作区历史（项目在仓库根）；②AICode main 同步当前版本，项目目录
  handeye-calib-tool → handeye-tools（根 README 索引、AGENTS/SESSION_PROMPTS 的 scope
  与构建路径同步更新）；③AZissue/RVBUST_Code 的 HandEyeTools 分支推为同一历史，并在其
  main 总览 README 登记该分支。同时清理 D 仓库 170 个 .vs 缓存（1.9 MB）并加入
  .gitignore，删除 AICode 本地过期分支 handeye-calib-tool/tools-panel（b7a78a4）与已被
  强推取代的 HandEyeTools（b6301b4）；构建 + ctest 全绿。
- [x] 2026-09-10 阶段 8 UI 优化与修复（前台激活+日志布局+启动默认显示）：①SidePanel
  布局从三卡片（时间线+折叠注意事项+预览）改为两主卡片（"操作日志"+"文件预览"等分空间，
  去掉固定 220px）；操作日志启动时默认显示 [注意事项] 四条建议，后续操作/引导/质检追加
  至同一滚动区（保留前置标签 [提示]/[姿态引导]/[数据质检]）；②MainWindow::changeEvent
  补充 QEvent::ActivationChange 分支，当 isActiveWindow() 时调用 raise()，修复嵌入 native
  Vis 子窗口导致的主窗前台置顶失效（Windows z-order 问题）；③移除 dataChanged lambda 中
  的自动 refreshQualityReport()，只在用户点击"运行质检"按钮时刷新（避免启动时空数据显示
  质检日志）。SidePanel.h 移除 m_notesCard/m_btnCollapseNotes/m_notesScroll/m_notesContent；
  SidePanel.cpp 启动日志追加四行注意事项并调整空间分配；MainWindow.cpp 补充激活事件处理与
  去掉 dataChanged 中的自动质检刷新。AICode 与 D 工作区构建成功。
- [x] 2026-09-09 联测反馈修复：①SidePanel 拥挤问题重构为三段式布局（时间线滚动区
  合并操作提示/姿态引导/数据质检 + 折叠式标定注意事项 + 固定高度文件预览）；
  ②新增 URRealtimeReader 支持 UR 30003 Primary/Realtime 推流协议（区别于 Modbus
  TCP，长度前缀+actual_tcp_pose 解析，xyz 米转毫米、rpy 保留轴角弧度不做欧拉角
  转换）；ToolsPanel 机器人通信页新增协议下拉（Modbus TCP / UR Realtime），
  MainWindow 按协议分流到对应 Reader；③修复真机联测暴露的两个 BUG：a) Qt 代理
  自动探测导致连接失败（"The proxy type is invalid for this operation"），两个
  Reader 的 connect() 均显式 setProxy(QNetworkProxy::NoProxy)；b) URRealtimeReader
  ::readPose 读取循环无条件调用 waitForReadyRead 导致数据已缓冲时仍误报超时，改为
  先查 bytesAvailable() 再决定是否等待。新增 URRealtimeReader mock server 单测
  （tests/test_robot_pose.cpp::urRealtimePose）。AICode 与 D 工作区构建+ctest 全绿。
- [x] 2026-09-08 阶段 8 其余 3 项（仅提示、不拦截）：①姿态引导 PoseGuide（平移≥50mm 且
  角度≥15° 双阈值 + 最小旋转角）+ 侧栏「姿态引导」文字卡；②数据质检 DataQualityCheck
  （五类全查 + 分级报告 + 总体结论）+ 侧栏「数据质检」卡+按钮，计算前自动跑一次不拦截；
  ③板位姿可视化 BoardPoseFit（质心+法向+面内轴 PCA 消歧）+ VisSceneView 半透明板平面
  +RGB 坐标轴 +「叠加历史」按钮（不同颜色+帧号）。三者均为纯函数 + QTest 单测，AICode
  与 D 工作区构建 + ctest 全绿。
- [x] 2026-09-08 联测反馈第 2 轮收尾：读取按钮文案去掉「读取」（「拍照位姿」「戳点位姿」），
  新增 secondaryButtonCompactStyle（padding 0 12px、最小宽 88）避免窄窗口字体截断；
  同步更新工具面板提示文案与注释；3D 复位按钮实测通过。AICode 与 D 工作区构建+单测全绿。
- [x] 2026-09-08 联测反馈第 2 轮：①读取拍照位姿/读取戳点位姿按钮并入主界面底部
  ActionButtons 同一行（与预览/拍照/计算同款 secondaryButtonStyle + 同高同字体），
  仅连接态显示、「读取戳点位姿」仅戳点标定+连接态显示；拍照时自动读取勾选迁回工具面板
  机器人通信页（新增 robotAutoReadToggled 信号）。②3D 复位按钮改为悬浮原生（WA_NativeWindow
  +WA_DontCreateNativeAncestors+WA_TranslucentBackground）无边框胶囊，重叠于场景左下角，
  场景充满整个视窗、不再有独立工具栏条。AICode 与 D 工作区构建+单测全绿。
- [x] 2026-09-08 联测反馈 4 项 UI 修正：①机器人通信面板从主界面 SidePanel 迁到
  工具面板「机器人通信」页，主界面仅在连接态显示「读取拍照位姿」+「拍照时自动读取」
  勾选，以及「读取戳点位姿」（仅戳点标定 + 已连接时）；新增「模拟连接成功」按钮供
  无真机测试读取按钮显示与样式；②窗口默认居中改为 showEvent 里按 frameGeometry +
  availableGeometry 居中并钳制，标题栏不再顶出屏幕；③窗口边缘缩放去卡顿（2D 快速
  最近邻 + 200ms 平滑重渲染；3D Vis 窗口 resize 改 80ms QTimer 去抖，避免 UI 线程
  每 tick 同步 WindowSetRectangle）；④2D/3D 视窗删除标题栏，标题改视窗内浮层标签，
  3D 复位工具栏透明无边框。AICode 与 D 工作区构建+单测全绿。
- [x] 2026-09-08 代码审查 + BUG 修复 + 去重造轮子：修复 4 处 BUG（AppConfig 载入默认值
  与 getter 不一致、CalibrationService 误差数组越界读、PlyPointReader 非 vertex 标量属性
  误收集、DetectionEngine::extractColors 未清空输出）；抽公共 countValidPoints2D 替换两处
  重复计数循环；RobotPose 手写大端字节解析改为 QDataStream（Float32 显式 SinglePrecision）；
  补 2 项回归单测，AICode 与 D 工作区构建+单测全绿。
- [x] 2026-08-25 文档体系按新模板重构：AGENTS/PROJECT/PLAN/STATUS + SESSION_PROMPTS，
  双工作区同步，git 首次文档提交（回退路线按 PLAN 各阶段）。
- [x] 2026-08-25 删除旧备忘 PROJECT_NOTES.md（半成品备忘已被新文档体系取代）。
- [x] 2026-08-24 阶段 8 机器人通信：RobotPose 统一接口 + ModbusTcpReader +
  独立线程 mock 单测全绿；SidePanel 通信卡默认关闭，不影响现有链路（4619dda）。
- [x] 2026-08-24 阶段 7 标定一体化：CalibrationService（staging+位姿规范化+
  SDK 封装+逐组误差）+ 主界面「计算」按钮 + SidePanel「标定结果」tab +
  工具面板离线页；单测全绿（4619dda）。
- [x] 2026-08-24 阶段 4 像素→3D：PixelTo3DTools/PlyPointReader + 在线点击回填 +
  离线页；单测 11 项全绿（4619dda）。
- [x] 2026-08-24 坐标转换/走点验证：真实数据复算 0.78~0.91mm，待 UI 实测。
- [x] 2026-08-24 工具板块 UX 定稿与 UI 细节（欧氏距离单框输入、单位下拉加宽等）。
- [x] 2026-08-24 三份文档体系建立（阶段 2；v1.0 及更早细节见 git 历史）。

## 🚧 进行中

- 用户联测阶段 3/4/7/8（清单见「下一步任务」）；反馈后修正。
- 阶段 8 三项顾问式功能待真机联测（纯函数已单测，UI 接线已构建通过）。
- 阶段 7 批量走点验证（VC/VR/VT 误差统计表）待补。

## 🐛 已知 BUG / 问题

| 问题 | 状态 | 备注 |
|---|---|---|
| 阶段 4 线扫不对齐离线反投影为近似（内参投影+最近邻） | 待真机验证 | 外参默认单位阵语义待线扫数据确认 |
| 阶段 7 计算前复制全部 png/ply 到临时目录（几百 MB） | 待优化 | 首次计算耗时明显；可改符号链接/规范命名 |
| 阶段 8 连接/读取为同步调用（超时 1.5s） | 待优化 | 点击时 UI 短暂停顿；真机验证后改异步 |
| 阶段 8 Modbus 寄存器布局/字节序 | 待真机确认 | 当前默认 Float32 大端，可配置 |
| 阶段 8 UR Realtime body 字段偏移仅参考单一来源确认 | 待真机确认 | timestamp+4×48 字节块布局未覆盖全部 UR 固件版本 |
| Vis 收尾偶发挂起/崩溃（0xC0000005/0xC0000374） | 已缓解 | 异步拾取+交互冷却；目标机需实测 |
| 相机连接失败提示通用 | 待细化 | 未区分驱动/网段/占用原因 |
| 3D 深放大手感 | 待确认 | 深度自适应 1~30× 已上，真机手感待确认 |
| 单日日志膨胀 | 搁置 | 日志按日期续写无大小上限 |

## ❌ 已尝试但失败的方案（附原因，防止重复踩坑）

| 方案 | 失败原因 | 当时条件（版本/环境） | 结论是否仍有效 |
|---|---|---|---|
| QToolTip 悬浮提示 | 原生 tooltip + 命中范围过大 | Qt5.14.2 | 否（改自绘 HoverTipLabel） |
| Vis 同步拾取（GetCameraPose 在 UI 线程） | 交互可能整机挂死 | RVBUST Vis | 否（改工作线程+冷却） |
| 3D 相机距离钳制定时器（150ms 轮询） | 持续同步往返卡 UI | RVBUST Vis | 否（已移除） |
| 滚轮固定 1~8× 补偿 | 深放大仍慢 | RVBUST Vis | 否（改深度自适应二次曲线） |
| settings.json 配置 | 实际不读取（真实配置在 %APPDATA% INI） | 早期版本 | 否（仅留模板） |
| Qt mock server 与客户端同线程 | 客户端 waitForReadyRead 不泵服务端事件，请求不到达 | Qt5.14.2 | 否（改独立线程 Winsock 阻塞服务器） |
| QTest 直接运行查看输出 | 测试 exe 为 GUI 子系统，stdout 丢弃 | MSVC 2026 | 否（用 `-o 文件,txt` 查看） |

## 🧭 近期技术决策（永久记录在 PROJECT.md 第 7 节）

- 2026-08-25 文档体系按新模板重构（4+1 份），理由见 PROJECT.md ADR。
- 2026-08-24 本地提交照常、push 需明确（用户确认）。
- 2026-08-24 FANUC WPR 按 RVC 导出实测顺序；像素→3D 走 SDK 对应关系；
  标定 staging 零填充；机器人通信统一接口+Modbus 先行。

## ▶️ 下一步任务

- [ ] 用户联测阶段 8 三项顾问式功能（姿态引导/数据质检/板位姿可视化）真机实测
- [ ] 用户联测阶段 4：在线点击取点回填、离线会话复算（对齐/线扫两模式）
- [ ] 用户联测阶段 7：主界面「计算」与工具面板「手眼标定」同数据一致性
- [ ] 用户联测阶段 8：Modbus 连接/读取/自动读取（真机到位后实测）
- [ ] 阶段 7 批量走点验证实现
- [ ] 阶段 5/6/9/10 开工

## 📦 清理规则

- 已完成且不再需要关注的条目从本文件删除（git 历史可追溯）。
- 旧 v1.0 细节、已归档修复不再回填本文件。
