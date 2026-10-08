# STATUS.md — 进度状态（每次会话结束必须更新）

> 最后更新：2026-10-08
> 只保留「当前快照」，不积累历史；旧条目删除即可，git 历史里仍可追溯。

## ⏭ 交接块（新会话先读这里）

- **2026-10-08（之七：圆环拟合/孔径 已知真值回归 —— 现场"误差较大"已复现并定位）**
  - **阶段状态不变**（之六的表仍是唯一权威口径）；本块只更新**阶段 10 的内容**。
  - **新增测试目标 `circle_truth`**（`tests/circle_truth.cpp`，已注册进 ctest，约 28 s）：
    不需要相机/SDK，用**针孔相机 + 倾斜平面**程序化生成"已知半径"的点云与**合成图像**
    （可调：模糊 σ、灰度噪声、倾角、离轴量、镜头畸变 k1、孔口倒角、环形台阶/沉孔）。
    这是 T-013/T-012 的判据工具，也是本次唯一新增的代码。
  - **结论：现场"误差较大"复现了，主因只有一个 —— 边缘选择（原方案的 L2）**。
    工件在材料边界之内还有第二道跃变（台阶/槽/沉孔）时，两个工具都**停在靠里那一道**，
    且**照报 `reliable = yes`**：
    | 场景（图纸 Ø） | 实测 | 误差 |
    |---|---|---|
    | 圆盘 Ø26，内圈 R12 有台阶 | 23.9998 | **−7.69%** |
    | 圆盘 Ø26，内圈 R10 有台阶 | 20.0008 | **−23.07%** |
    | 孔 Ø9，孔口沉孔到 R6 | 8.9995（孔壁） | **−25.00%** |
    | 孔 Ø9，孔口沉孔到 R5.5 | 8.9995（孔壁） | **−18.19%** |
  - **其余全部在 0.5% 判据内**：平面+圆边界 0.003–0.05%；blur 1 px + 噪声 2 级 ≤0.03%；
    **离轴 25 mm + 畸变 k1=0.15 只有 0.11%**；无图像时孔走 3D 兜底 0.07–0.19%。
    → 原方案排在前面的 **L1（仿射 vs 单应）、L3（平滑）、L4（亚像素步长）实测收益极小，
    全部降级**；**L2 升级为唯一主因**。
  - **另一个独立缺陷**：**没有可用图像时，圆环拟合返回"找不到材料边界"，一个数都给不出**
    （`contour3d` 只在 `if (map.ok)` 里构造，而 `map.ok` 需要有效图像；孔有 `holeBoundary`
    兜底所以孔有数）。`results.json` 里 `disc_d63_5` 的"没有读到任何读数"很可能就是它。
  - **新增报告 `reports/阶段10-圆环拟合与孔径-真值回归结论.md`**（含原始输出
    `reports/阶段10-圆环拟合与孔径-真值回归.txt`）：给出 P1 重做边缘选择（列全部候选、
    按"最外材料边界"挑、歧义时报出来让人定）、P2 参数暴露清单（按实测影响排序）、
    P3 修 3D 兜底、P4 给 `reliable` 加"歧义"维度。
  - **8 个已确认缺陷场景保留在 `isKnownDefect()` 名单里**（不删、不掩盖，ctest 保持全绿；
    修好一个会自动打印 `*** FIXED — drop from isKnownDefect() ***`）。
  - **还需要用户给一组真件数据**才能坐实（详见报告 §4）：一个带台阶/沉孔/倒角的真件 +
    卡尺或三坐标量出的实际尺寸 + 助手对同一次采集的读数。**本回归测的是算法，
    测不到真机图像质量/点云飞点/图像-点云配准误差。**
  - **同步的口径修正**：`reports/阶段10-测量功能优化方案.md` 顶部已加警示（L1–L6 为推测，
    已被实测改判；其 §1 三个全局问题与 §3 仍然有效）；
    `reports/CODE-MAP.md` 的测量两行改为指向新报告与 `circle_truth`。
  - **尚未实现任何产品代码改动**（本次只加测试与文档）。

- **2026-10-08（之六：README 重写 + T-012 判据改 0.5% + 阶段状态全面重写）**
  - **本块是"阶段状态"的唯一权威口径**。此前的说法（「阶段 5/6/9/10 未开工」
    「阶段 3/4/7/8 待联测」）**已作废**。用户 2026-10-08 逐阶段核定如下，
    已写进 PLAN.md（逐节）+ PROJECT.md（§2 需求表、§6 完成标准、§7 ADR、§8 变更记录）：
    | 阶段 | 新状态 | 依据 |
    |---|---|---|
    | 3 坐标转换 | **已完成** | 用户核定：已实现并测试完成通过 |
    | 4 像素→3D | **已完成** | 用户核定：已实现并联测完成通过（对齐/线扫各一轮） |
    | 5 棋盘格 | 未开工 | 用户确认；全仓 grep 无棋盘格代码 |
    | 6 标定优化 | 未开工，**目标待重新定义** | 用户问「要优化什么」→ 文档原文指的是**鲁棒标定求解**（研究型），与用户说的「优化程序功能和使用」不是一回事；已把原文一字不改留在 PLAN 里，并列出三选一待用户定 |
    | 7 标定一体化 | **已完成** | 用户核定：已实现并测试完成通过。两条 DoD 子项（与 SDK 逐元素一致 / 批量走点验证）**未做**，判定"不必做"（前者自比自无意义，后者无人要求） |
    | 8 采集提质 | **已完成** | 用户核定：已实现并测试通过。Modbus 真机项**转为独立待证实项**，不阻塞本阶段 |
    | **9 数据管理与交付** | **已完成（范围收窄关闭）** | 用户判定：现有功能基本够用，会话浏览器/合并/报告导出/专属位姿文件导出**不再实现**。实际具备的是保存/导出 4 文件/JSON 备份恢复/路径回退/离线复算/新建会话 |
    | **10 相机与场景工具** | **部分实现** | 2D 测量/标注**已具备**（8 方法 + ROI + 5 个 2D 页签 + `codex_testData` 真值回归 + `PixelTo3DService`）；「参数档案」**已决定不做**（2026-09-21 程序不下发拍摄参数）；「2D 内参标定(张正友)」未做 |
    | **11 v2.0 打包与发布** | **未完成** | 用户判定：打包机制已跑通（`pack_portable.ps1` + `dist/...test2.0` 打过），但**V2.0 要有的功能未收口**。依赖表已修正：阶段 5/6 **不阻塞** v2.0；真实依赖 = 3/4/7/8/9 + 阶段 10 收口 + T-012/T-013 |
    | 12 合并 main | 未开始 | 当前在 `HandEyeTools` 分支 |
  - **新增 PLAN.md 一节「阶段之外的增量（v2.0 期间）」**：把这批**不属于任何阶段**
    的工作集中登记（帮助窗、新建会话、AppInfo 版本单一来源、模式判据收成一处、
    两个 BUG 修复、测量体系、NRC/埃夫特协议、T-004…T-011 八条、删内置拍摄参数、
    窗口可缩放、卡死崩溃治理）。**这就是"阶段看着没动、程序却长了一大截"的原因** ——
    以后不必再问"这些算哪一阶段"。
  - **已提交，未推送**：`7dd8e75`（T-012 判据 0.5%）、`452879d`（README 重写）、
    本次（阶段状态重写）。**AICode 工作区仍分叉**（用户指示继续挂着，不同步）。
  - **阶段 7 的两条子项已澄清**（用户 2026-10-08）：①「与官方 HandEyeSDK
    同数据集结果一致」**已做** —— 用户用同一组标定数据在助手和官方 SDK 各算一遍，
    结果一致（我上一版误判为"自比自无意义"并撤除该条，已更正回 §6 的验收标准）；
    ②「批量走点验证（VC/VR/VT 误差统计表）」用户**明确不做**，已从待办移除。
  - **机器人通信真机联测：暂时挂起**（用户 2026-10-08：现在无法立刻进场做真机验证）。
    处理方式：**不删任务书、不凭猜改代码**，四项待证实项照原样留在本文件「已知问题」表
    与 PLAN 阶段 8 里；**将来看到或测到就回来补结论**。任何人（含后续会话）在拿到
    现场证据前都不得改 `RobotPose.*` / `URRealtimeReader.*` / `NrcJsonReader.*` /
    `EfortPoseReader.*`。
  - **新增两份方案讨论文档**（2026-10-08，待用户拍板，尚未实现任何代码）：
    `reports/阶段10-测量功能优化方案.md`（按 8 个测量功能逐个给优化项）、
    `reports/阶段6-鲁棒标定方案讨论.md`（先量后改的三段式方案）。

- **2026-10-08（之五：人工验证收口 + 真机联测任务书 + 更正一条错话）**
  - **之四的 6 条人工验证已全部通过**（用户 2026-10-08 反馈「人工手动验证已经测试完，
    全部通过」）。帮助窗（顶栏「帮助」/ F1、9 章、互链、末章 V2.0、非模态、F1 不叠窗）
    收口，无需再验。
  - **更正一条错话（重要）**：本文件此前写着「阶段 8 Modbus 寄存器布局/字节序 …
    **当前默认 Float32 大端，可配置**」—— **代码里没有任何字序/字节序开关**。
    `logic/RobotPose.cpp::parseRegisters()` 只有 `QDataStream::BigEndian` 一条路径，
    `ModbusConfig` 可配的只有 `startAddress / format / scale / unitId / timeoutMs`。
    该行已改（见「已知问题」表）。
  - **新增真机联测任务书**：`reports/机器人通信真机联测任务书.md` v1
    （对应程序 2.0）—— 四项互不依赖：A Modbus 寄存器布局/字节序、B UR Realtime
    位姿字段偏移、C 博纳斯/纳博特 NRC 取证、D 埃夫特单位与角度约定。
    每项都带操作步骤 / 预期结果 / 判定表（看到什么 → 我改什么）/ 记录表，
    末尾第 7 节写明**拿到结果后我要完成的任务**与预估工时。
  - **新增两个只读探针脚本**（`reports/tools/`，随任务书一起交给现场）：
    `probe_modbus_pose.py`（FC03 读保持寄存器；按 Float32/Int32×系数/Int16×系数 ×
    ABCD/CDAB/DCBA 全排列试解；内置 x=100/200/300,A=10/20/30 时的期望寄存器对
    `42C8/4348/4396/4120/41A0/41F0` 供比对）、
    `probe_ur_offset.py`（连 30003 读一个包；解偏移 200 那个块；用示教器坐标做
    **三连命中**搜索定位真实偏移，单个值巧合命中不足为凭）。
    两者都有 `--selftest`（本机已跑通，exit 0），并把输出同时落一份 **UTF-8 的 txt**
    （现场控制台多为 GBK 代码页，直接贴中文会乱码 —— 以 txt 为准）。
  - **下一步**：等用户按任务书做真机联测并回传证据（txt + `logs/runtime_<日期>.log`
    里的 `[NRC]` 行 + 记录表）。在此之前，机器人通信这一块**不要凭猜改代码**。

- **2026-10-08（之四：完整使用说明窗口）**
  - 来源：用户第三条要求的落地 —— 原来「帮助」只弹一个只写版本信息的
    `QMessageBox::about`，用户要的是把"标定方式介绍、按钮功能、界面内容"都写进去。
    方案经用户确认：左侧章节 + 右侧正文、内容用 C++ 纯数据表、「关于」并入帮助窗。
  - **新增 `src/logic/HelpContent.h`**（header-only 纯数据，仿 `MeasureMethods.h`）：
    9 章正文 + `renderBody()` + `changelog()`。三个刻意的设计：
    ① **测量方法一章是生成的**（`buildMeasureChapter()` 直接遍历
    `MeasureMethods.h` 的 `methodSpecs()`），所以页面上每个方法的用途/ROI/输出/
    可信度/常见错法/「这组数说明了什么」与日志里的 `[测量-说明]`/`[测量-结果]`
    **是同一份文案**，不会各说各的；
    ② **版本号不写死**：正文用 `%CURRENT_VERSION%` 占位符，界面拿 `AppInfo::version()`
    替换 —— 之三刚因为版本号硬编码在三处出过事，说明里不再挖一遍同样的坑；
    ③ 正文里界面元素一律用「」括起来（半角双引号在 C++ 字面量里是结束符，
    这也是写正文时最容易踩的一脚）。
  - **新增 `src/ui/HelpDialog.{h,cpp}`**：非模态、首次打开才创建、之后常驻一份
    （同 `ToolsPanel` 的路数）。左 `QListWidget` 章节 + 右 `QTextBrowser`（`setMarkdown`，
    Qt 5.14 起支持）；正文里的 `[某章](#id)` 互链由 `anchorClicked` 接管，`setOpenLinks(false)`
    防止浏览器被拉走。控件给了稳定 objectName（`help_chapter_list` / `help_browser`）。
  - **接线**：`MainWindow::showHelp(chapterId)` 统一入口 —— 顶栏「帮助」按钮与
    **F1**（`QKeySequence::HelpContents`）都走它；`QMessageBox::about` 删除，
    原来的「关于」内容并入帮助窗（`AppInfo::summary()` 现在是说明窗口的标题行）。
  - **测试**：新增 `tests/test_help_content.{h,cpp}`（6 例）—— 章节完整且 id 是稳定
    ASCII 且唯一、`chapterById`/`chapterIndexOf` 往返且未知 id 返回 -1/ nullptr、
    **测量方法一章覆盖 `methodSpecs()` 里每一个方法的 name/purpose/outputs**、
    正文不含 `V1.0` 且占位符只在版本一章出现、**`changelog()[0].version ==
    AppInfo::version()`**（升版本忘写更新记录会断）、changelog 每条 version/date
    必须出现在正文里。注册在 `tests/CMakeLists.txt` + `test_main.cpp`。
  - **验证**：D 工作区构建 exit 0、主 exe 10:48:22 刷新、`ctest` **2/2 通过**
    （`unit_tests_report.help_content.txt` 8 PASS，全部测试类 0 failed）。
  - **本次人工验证清单**：
    1. 点顶栏「帮助」和按 F1：预期都打开使用说明窗（左侧 9 章、右侧正文）。
    2. 左侧逐章点：预期 9 章都能打开、正文不为空；**「测量方法」一章里能看到 8 个
       测量方法的名字与说明**（它是从方法表生成的）。
    3. 正文里的蓝色互链（如「安装方式与标定方法」）：预期跳到对应章节、左侧选中项跟着变。
    4. 最后一章「版本与更新记录」：预期写的是 **V2.0**（不是 V1.0），并有 2.0/1.0
       两条记录。
    5. 说明窗开着的时候主界面**仍可操作**（非模态）：连续采一组数据不被挡住。
    6. 反复按 F1：预期只是把窗口抬到前面，不会叠出第二个说明窗。
  - **下一步（待用户确认）**：帮助内容里凡是我按代码推断、但只能靠真机确认的措辞
    （例如“识别失败会让「保存」变灰”的具体触发条件）请用户照清单过一遍；其余待办
    见文件末尾的「下一步任务」。

- **2026-10-08（之三：读位姿按钮模式盲 + 版本号；帮助窗已定方案待做）**
  - 来源：用户三条 —— ①眼在手外+戳点时「拍照位姿」按钮没隐去；②界面还显示 V1.0；
    ③帮助功能太薄，要写完整使用说明（出了方案，见下）。
  - **①根因**：`MainWindow::updateRobotReadBar()` 里「戳点位姿」判了模式
    （`m_robotConnected && tcp`），「拍照位姿」**只判了连接**（`m_robotConnected`），
    所以机器人一连上（真机或模拟）它就出现 —— 哪怕本模式根本没有"拍照位姿"这一列。
    **这已经是那条"眼在手外+戳点不采拍照位姿"规则的第五个副本**，而且漏了。
  - **改法（把判据收成一处，不再各写一遍）**：`models/CalibrationMode.h` 新增
    `needsCapturePose(eyeHand, calibType)` / `needsRobotTarget(calibType)` 两个
    **free function**（另有同名成员函数转发）。五处全部改成调用它：
    保存校验（`CaptureFlow::validateSaveInputs`，原来的 `mode.isEyeInHand()` 换成
    `mode.needsCapturePose()`，语义等价）、卡片显隐（`DataInputArea::updateVisibility`）、
    文件预览 tab（`SidePanel::updateFilePreview`）、质检数据源
    （`DataQualityCheck::sourceFor` 现在**委托**给它）、读位姿按钮
    （`MainWindow::updateRobotReadBar`）。
    **同源缺陷一并修掉两处**：拍照前自动读位姿（`MainWindow::onCapture`）在本模式下
    不再发请求；`onRobotPoseReady` 的拍照位姿分支加兜底早退 —— 否则会往一张看不见的
    卡片里写值，再顺着记录存进一个本模式不用的列。
  - **②版本号**：`V1.0` 原来硬编码在三处（窗口标题、顶栏标题、帮助弹框）。
    新增 **`src/AppInfo.h`**（`name()` / `version()` / `title()` / `summary()`），
    三处都改成引用它；`CMakeLists.txt` 的 `project(... VERSION 1.0.0)` 一并改 2.0.0
    （它目前没被任何地方读取，改的是防止将来两边对不上）。
  - **测试**：新增 `tests/test_app_info.{h,cpp}`（3 例，钉住"标题由 name+version 拼出、
    帮助那句以 title 起头"，升版本时不用改测试）；`test_data_quality_check` 的
    `sourceForFollowsCalibrationMode` 扩写 —— 四种模式组合的期望值**写死**在测试里，
    再断言"质检选列 ≤ needsCapturePose()"两两一致（防止再有人手写第六份副本）。
  - **验证**：D 工作区构建 exit 0、主 exe 10:43:18 刷新、`ctest` **2/2 通过**
    （`unit_tests_report.app_info.txt` 5 PASS、`...data_quality_check.txt` 22 PASS，
    全部测试类 0 failed）。
  - **本次人工验证清单**：
    1. 眼在手外 + 戳点 + 同心圆，连机器人（真机或模拟）：预期动作栏**只有「戳点位姿」**，
       没有「拍照位姿」。
    2. 切到眼在手上（或标定板）：预期「拍照位姿」出现，标定板模式**不出现「戳点位姿」**。
    3. 断开机器人：预期两个按钮都消失。
    4. 眼在手外+戳点下开「设置 → 自动读取机器人位姿」，然后拍照：预期不会去读拍照位姿
       （日志里没有这条读取）。
    5. 窗口标题、顶栏标题、帮助弹框**都显示 V2.0**。
  - **③帮助窗（方案已定，尚未实现）**：新建 `ui/HelpWindow.{h,cpp}`（独立窗口，
    左侧章节列表 + 右侧 `QTextBrowser`），内容放 `logic/HelpContent.h`（仿
    `MeasureMethods.h` 的**纯数据表**，可单测 + 可加"每个测量方法都必须在帮助里出现"
    的一致性测试）；「帮助」按钮改为开这个窗口、`QMessageBox::about` 并入其中；
    再绑 `F1`。9 个章节：快速上手 / 安装方式与标定方法 / 主界面导览 / 采集流程详解 /
    工具面板 / 测量方法（由 `MeasureMethods.h` 生成）/ 输出文件与目录结构 / 常见问题 /
    版本与更新记录。→ **已实现，见上面的之四**（实际文件名是 `ui/HelpDialog.*`）。

- **2026-10-08（之二：补「新建会话」入口）**
  - 来源：用户反馈 —— 程序开着的时候，标定完一组想再采一组，**没有入口，只能退出重开**。
    （用户已确认前两条 BUG 的修复在真机上符合预期；计算能正常出结果，数值正确性交给
    HandEye SDK 的既有流程。）
  - **根因**：`MainWindow::resetSession()` 是全程序唯一开新会话的函数，只有两个调用点 ——
    启动（`MainWindow.cpp:208`）与 `onModeChanged()` 里 `typeChanged` 为真的分支
    （`MainWindow.cpp:756`）。界面没有菜单栏、动作栏没有「新建」、快捷键只有
    Ctrl+S/Ctrl+Z/F5/F11，所以**开新会话只能靠"启动"或"切标定类型"两个副作用触发**。
    不是状态锁死，是缺功能。
  - **改法**（用户选定：入口放顶部导航栏；本次只做「新起一组」，不做会话历史列表）：
    - `ui/TopNavBar.{h,cpp}`：进度条右侧、设置/帮助之前加「新建会话」（主色描边，
      右侧分组），信号 `newSessionClicked()` + `setNewSessionEnabled()`。
    - `app/MainWindow::onNewSessionRequested()`（新槽）：有记录时确认，措辞点明
      **"记录不会从磁盘删除"**（数据其实一直在 `calibration_data_<时间戳>/` 里，含 backup），
      模态返回后 `m_watchdog.reset()`；确认才 `resetSession()`。
    - 按钮 enabled = 有记录 **且** 非 busy：接在 `dataChanged`、`setBusy`、`setConnectBusy`、
      `clearBusy` 四处 —— 计算跑一半换掉会话目录会让结果串掉。
    - `resetSession()` 补两处清理：`m_sidePanel->setCalibrationResult(QString())`
      （原来不清，新会话还挂着上一组的结果）与 `m_toolsPanel->clearSessionData()`。
    - `ui/ToolsPanel::clearSessionData()`（新增）：清 `m_sessionActive` 与缓存的三列
      + hint + 结果框。**不清的话「用当前会话 → 计算」会拿上一组的位姿配上这一组的目录**，
      数字错而界面看不出来。
  - **验证**：D 工作区构建 exit 0、主 exe 时间戳刷新（10:01:43）、`ctest` 2/2 通过。
    改动 6 个文件（88 行新增，无删除），未提交时工作树只有这 6 个文件。
  - **人工验证（6 条：按钮启用时机 / 确认框取消无副作用 / 新建后各处清空且新目录为新时间戳 /
    再采一组的计算基于新数据 / 工具页会话缓存失效 / busy 期间禁用）**。
  - **人工验证结果（用户 2026-10-08 反馈）**：上述 6 条**全部通过**。✅ 已收口。
  - **未做/待办**：双工作区仍分叉（用户指示继续挂着，不同步）；本次改动已本地提交（`9f94c23`），未推送。

- **2026-10-08（之一：修两个 BUG + 出代码地图）**
  - 来源：用户明确说「你来修改就可以了，不用管三方协作」（`.trio/` 流程本次**不适用**），
    并批准把代码地图落成文件。两条 BUG：
  - **BUG 1「运行质检」出假报告**：眼在手外 + 戳点标定 + 同心圆，静止连采 15 组一样的数据，
    质检却报「拍照位姿的近重复 / 离群 / 单帧误差 / 分散度全部正常」。
    **根因**：`MainWindow::refreshQualityReport()` 无条件用 `robotCapturePose` 建记录，
    而该模式这一列**根本没有**（`hidePose = !eyeInHand && !isMarkerCalib`），
    于是所有基于位姿的检查都在**空索引集**上跑，一律"通过"。
  - **BUG 2「计算」报错**：同场景点计算 → `标定失败:第1组机器人拍照位姿格式无效(应为6个数值)`。
    **根因**：两个 UI 入口都无条件调 `CalibrationService::calibrateMarker()`，
    戳点标定该走 `HandEyeCalibrationTcpTouch`。
    两条 BUG 同一类病根：**除 `CaptureFlow::validateSaveInputs` 与 `DataInputArea::updateVisibility`
    之外，没有任何链路看 `CalibType`**。
  - **改法**：
    - `logic/DataQualityCheck.h`：新增 `PoseSource`/`sourceFor()`/`sourceHasOrientation()`/`sourceName()`，
      "用哪一列判定"变成显式参数，报告新增「数据源」一行；新增 `Level::NotApplicable`
      （"没数据可判"再也不显示"通过"）；新增**相机目标点离群**与**标记点数一致性**两项检查
      （后者是同心圆模式下唯一可用的单帧信号）；明细行封顶 12 条 + 计数照实报（15 组相同 = 105 对）。
      另外 `Record` 加 `cameraXyz`/`hasCameraTarget`，`Params` 加 `source`、相机离群阈值。
    - `logic/CalibrationService.{h,cpp}`：入口收敛成 `calibrate()`，按 `Params::calibType` 分派；
      新增 `calibrateTcpTouch()`（进 SDK 前逐组逐列中文校验）、戳点专用返回码表 `tcpErrorText()`
      （与标定板的 `errorText()` 表**不通用**，同为 -2 含义不同）；`success2D/3D` 对戳点**留空**
      （SDK 文档写明无意义，照抄会让 `formatResult` 把每组标成"识别失败"）。
    - `sdk/HandEyeSDKBridge.cpp`：眼在手外时拍照位姿文件传 **nullptr** 而非空串（`HandEye.h` 的要求）。
    - `app/MainWindow.{h,cpp}`：`updatePoseGuide()` 改为无参、由模式决定读哪张卡片；
      `refreshQualityReport()` 按源建记录 + 补 8 行 + `NotApplicable` 灰色标签；
      `onCalibrate()` / `onCalibrationSessionRequested()` 三列**不过滤**（下标必须对齐）传下去。
    - `ui/ToolsPanel.{h,cpp}`：离线标定页加「标定方式」下拉 + 相机点位文件 / 戳点文件两行（按方式显隐）。
    - `ui/DataInputArea.{h,cpp}`：参数名 `markerType` → `isMarkerCalib`（消歧义，判据不变）。
    - 单测新增 14 条（质检 9 + 标定 5），全部**在设计上不进 DLL**（用空/坏行卡在前置校验）。
  - **验证**：D 工作区构建 exit 0、三个 exe 时间戳刷新、`ctest` **2/2 通过**；
    `build/unit_tests_report.data_quality_check.txt` 22 PASS、`...calibration_service.txt` 12 PASS。
  - **人工验证（4 条：15 组相同数据的质检如实报错 / 同场景计算走戳点路径 / 工具页按方式显隐 /
    眼在手上标定板回归）→ 用户 2026-10-08 反馈「全部通过，且符合实际」**；
    计算能正常出结果，**戳点标定的最终数值也已真机验证通过**（数值正确性交给 HandEye SDK 的既有流程）。
    ✅ 本次两处修复**已收口**。
  - **未做/待办**：①`reports/CODE-MAP.md`（本次新写，改代码的导航图）已落盘并提交；
    ②双工作区**仍分叉**（AICode 停在 09-18，2026-10-08 的全部改动只在 `D:\MyCode\MyHandEyeTools`），
    **用户明确指示继续挂着不同步**；③所有提交均未推送。

- **2026-09-30（2.0 批次：8/10 完成，走「人 / A / B」三方协作）**
  - 来源：用户 09-30 的两条指令 —— ①按 A 的代码审查做完 8 条优化（一任务一验收一提交，
    全部做完再统一汇报）；②新加两条 2.0 需求（测量精度 / 测量界面参数化）。
    **任务表与逐项状态全在 `.trio/tasks/BACKLOG-2.0.md`**，本块只记结论。
  - **已完成并提交（8 条，全部双证：真机/探针 + 既有测试）**：PLY 头部点数超文件大小不再 `bad_alloc`、
    导出写失败不再"假成功"、PLY x/y/z 按声明类型解码、机器人四协议分派收敛成 `robotReaderFor()` 一处、
    包三段清理（SDK 异常不冒充"参数无效" / 标定正文收敛到 `formatResult` / 品牌色收敛到 `Theme::withAlpha()`）、
    机器人通道搬进专属线程 `RobotWorker`（原 UI 冻 1.5 s）、浮层模糊加开销仪表（实测 median 148.8 µs，结论"不用优化"）、
    相机析构等预览 worker。逐条 hash 与细节见 git 历史（`7c7bf88`..`b9e9cdc`）。
  - **待用户拍板的（卡在这里，两条都等人）**：
    - **T-012 测量精度**（用户的 2.0 第 9 条）：Ø9/Ø5/Ø6/Ø26/Ø63.5 要 ≤0.2%×标称。
      真机基线：**Ø6=6.2648**（标称 6）、**Ø5=4.7370**（标称 5）、**Ø63.5=48.2832**（真值的 76%）、
      **Ø26 与 Ø9 测不出读数**；网格点距 0.0755 mm（Ø6 的容差只有 0.16 个点距）。
      三个选项：①继续投亚像素/图像边缘 ②放宽到 0.5% ③用已知件做一次性系统偏差补偿（A 建议 ③）。
      现状与数据：`reports/T-012/BASELINE.md`；升级记录：群里 bus #88。
      **B 改到一半的代码已作为 WIP 检查点提交**（`c8d375b`，提交消息里写明"不是验收产物"）。
      经过：本来留在工作树里没提交；后来发现 **T-008 r3 与 T-009 两次提交是按文件名 `git add` 的**，
      而 `ToolsPanel.cpp` / `MainWindow.cpp` 里当时已经混着 T-012 的改动 —— 于是 HEAD 拿到了
      调用 `setMeasurementImage()` / `MeasurePage::setImage()` 的代码，而这两个声明还躺在
      未提交的头文件里，**HEAD 编不过**（`ctest` 看不见：测试目标不编界面）。
      为了让 HEAD 重新自洽，把剩下的 WIP 一起提交成检查点：**能编、能跑，但算法未经验收**，
      Ø6 读数从 6.2648 退到 2.0647。重开 T-012 时从这里接着改。
      （教训：提交只 add 本次任务真正改过的**行**所属文件也要当心——同一个文件里混着上一个未完成任务的改动时，
      要么先把它拆出来，要么把整个任务一起提交。以后凡是文件里混着未验收的改动，就整组提交或先 stash。）
    - **T-013 测量界面参数化**（用户的 2.0 第 10 条）：依赖 T-012 定下来的算法入口与参数。
  - **其他现状**：①双工作区仍分叉（AICode 停在 09-18、D 已到 09-30），按用户指示先不动，
    **所有提交都未推送**；②`.trio/verify.py` 的"既有测试基线"通道写死 python unittest、
    在本仓不适用，所有任务统一带 `--no-baseline`，真正管"测试别退化"的是各任务判据里的 `ctest`
    （缺口分析见 `reports/T-008/FRAMEWORK-NOTE.md`）；③A 的会话台账已达 9.8 MB / 350 动作，
    建议换会话后再继续（新会话先读 `.trio/tasks/BACKLOG-2.0.md` 与 bus 的 `todos`）。

- **2026-09-21（第 12 回合：任务 01 删掉内置拍照参数 + 任务 02 所有窗口可缩放/可滚动）**
  - 来源：用户反馈 —— ①程序内的拍照参数功能不完善，成像不好却不好调，不如干脆不在助手内调参数，
    只在相机厂商的软件里调好再用助手；②设置窗口内容一多，窗口就跟着变高，确定按钮被任务栏挡住、
    点不到，也改不了窗口尺寸。
  - **任务 01（严格无参）**：删掉 `logic/CameraParamPolicy.h`（连同 `tests/test_camera_param_policy.*`）、
    `AppConfig` 的 `camera_params`/`use_camera_params`（默认值块 + 4 个读写函数）、`CameraManager` 的
    全部参数 setter 与 `cameraParamRange`、`SettingsDialog` 整个「拍摄参数」分组。
    预览与拍照改用 SDK **无参**重载：`Capture2D()` / `Capture2D(cid)` / `Capture2D(rightId)` / `Capture()`。
    用户明确选择「两处自动覆盖相机的兜底都删」：预览/拍照不再强制 `use_projector_capturing_2d_image=false`；
    连接时不再 `applyPreferredCaptureMode()` 强制非线扫；不再设 `transform_to_camera`。
    **保留只读镜像**：`loadCameraOptionsLocked()` + `cameraCaptureSummary()` + `logCameraOptions()` ——
    包络判定（`gridAligned` / `correspond2d` / 对应图）仍要读相机当前值，且每次连接与拍照把实际取值
    写进 `[CAM]` 日志，便于现场排查"拍出来黑/有条纹/没有深度"。
  - **任务 02**：`SettingsDialog` 重写为「内容进 `QScrollArea`、`QDialogButtonBox` 留在滚动区外」，
    `setMinimumSize(520, 360)`；`ToolsPanel` 每个工具页各套一层滚动区（`wrapScrollable()`，6 处调用点），
    `setMinimumSize(640, 440)`；`DeviceListDialog` 最小尺寸降到 420x260。三个窗口都补了
    `Qt::WindowMinMaxButtonsHint`（此前只有主窗口能最大化）。
  - 数值证据（本机）：`ctest` **2/2 通过**；`unit_tests` **24 类 / 270 passed / 0 failed / 1 skipped**
    （与改动前持平，删掉 `camera_param_policy` 一类、`TestCameraManagerRelease` 换成 `captureSummaryEmptyBeforeConnect`）。
    界面自检 `.pair/tools/ui_check_012.py`（UIA，JSON 与截图在 `.pair/shots/round12/`）：
    - 设置：`maximize_box=true`、`thick_frame=true`；600x560 → 560x400 后 `inside_work_area=true`、
      OK/Cancel 矩形 [1050,561,1127,598] / [1133,561,1210,598] → `buttons_inside_window=true`、
      `buttons_above_taskbar=true`、`scrollbar_after_shrink=true`；`设置_small.png` 可见内容在滚动、按钮钉在底部。
    - 工具：`maximize_box=true`、`thick_frame=true`；缩到最小 656x479（客户区 640x440，Qt 的最小尺寸约束）
      后 15 个页签逐个切换无异常；逐页量「内容底边 vs 客户区底边」溢出 **-246 px**（都装得下），`bad_pages=[]`。
  - **未验证**：①`DeviceListDialog` 只做了代码层修改，没有自动化验证（要相机处于扫描/占用态才会弹）；
    ②最小尺寸下没有任何工具页装不下，所以**工具页的滚动条这次没被真正触发过** —— 滚动通路靠
    `SettingsDialog` 同一套 `QScrollArea` 用法佐证，建议现场把某个工具页的内容做多再看一眼。
  - **风险 / 维护成本评估（任务 01 明确要求）**：
    - 净减代码：删掉一整套「参数来源二选一」策略（策略头 + 单测）、4 个配置项、12 个 setter、1 个 UI 分组。
      旧配置文件里的 `camera_params` / `use_camera_params` 键**不再被读取**，成为死数据，不报错。
    - 风险 1（已接受，用户拍板）：预览不再强制关投影仪图案。若相机里存的是"2D 图叠加投影条纹"，
      预览会变慢、标定板 2D 图上带条纹 —— 要去厂商软件改。
    - 风险 2（已接受）：连接时不再强制非线扫模式。若相机里存的是 `SwingLineScan` 且 `correspond2d=0`，
      现在会照做 → 点云与图像不对齐；代码仍据此走 `GetCorrespondMap()`，但**拍不出深度/深度很差时，
      第一件事是去看相机里的采集模式**。
    - 风险 3（已接受）：`transform_to_camera` 不再由程序设置，点云坐标系随相机里保存的值。
      现场若发现点云"方向不对"，症状从"程序行为不一致"变成"取决于相机当前状态"。
    - 成本：今后任何新增参数需求，都要先判断"该不该由助手下发"；若将来又要下发，需要重新引入
      一层配置 + 单测（约 1 天）。
  - 提交：本回合一个提交，subject = `refactor(handeye-tools): drop in-app capture parameters,
    make every dialog resizable`（**未推送**，用户未说「推送」）。哈希见 `git log -1`
    —— 写死哈希会因本文件也在提交里而每次 amend 后失效，所以这里只用 subject 定位。

- **2026-09-20（第 11 回合：反馈 4/5/6/7/9 双智能体循环，Codex 验收通过并提交）**
  - 协作设施：首次把 `.pair/`（Codex 拆解/验收 × Claude 实现）接入本仓库，入口
    `.pair/PROTOCOL.md`、任务书 `.pair/inbox/NNN.md`、台账 `.pair/ledger.md`、
    证据 `.pair/reports/`。**新会话开始时先跑 `python .pair/start-view.py` 并把
    http://127.0.0.1:8760/ 挂到右侧面板**（看板只读日志、不烧 token）。
  - 交付（按用户反馈编号）：
    - **反馈 6**：`logic/PixelTo3DService.{h,cpp}` 抽出「像素→3D」共享服务；工具页删掉自带
      `Image2DView`，加「在线/离线」开关（默认离线）；离线时主 2D 视窗临时显示所加载 png、
      点击回填工具页，关工具即恢复实时图；**在线**时主 2D 左键 → 工具页结果可复制 + 3D 标记。
    - **反馈 5**：测量说明移出工具窗口，`[测量-说明]` 含「用途/怎么用/输出/怎么看结果」，
      `[测量-结果]` 末尾补「这组数说明：…」。
    - **反馈 4**：2D/3D 视窗的标签与工具栏按钮改为无边框 + 半透明底（alpha 0.20/0.28/0.30）。
    - **反馈 9**：手眼标定页新增「用当前会话」一键算，界面显示所用路径与组数。
    - **反馈 7**：埃夫特（EFORT）协议接入（`cmake/FindEfortSDK.cmake` + `logic/EfortPoseReader.*`
      + 协议项 + log4cpp.conf 部署 + CWD 切换）。
  - 数值证据：`unit_tests` 由 23 类/255 passed → **25 类/279 passed / 0 failed**（新增
    `TestPixelTo3DService`、`TestEfortPoseReader`，并给测量说明加了逐方法断言）；
    `ctest` 2/2 通过。真机：真实相机 RVC-M2600-ML2 / 序列号 **M2GM620B417**（不是 G2GM620B101，
    那台当前不在设备列表里）、真实界面驱动取点与样式回归，截图与命令原文在 `.pair/reports/`。
  - **修掉两个现场级缺陷**：①埃夫特连接让整个程序崩溃（SDK 的 C++ 异常穿出 Qt 槽，
    `SEH 0xE06D7363`）——现已包住异常，失败给可读中文；②SDK 按当前工作目录找 `log4cpp.conf`
    （`run.bat` 的 cwd 是仓库根）——现由代码临时切换 CWD 解决。
  - **未验证（需人看/需场景）**：①3D 视窗上那个取点球（2mm 黄球，与识别圆心 1mm 绿球同量纲）
    在截图里找不到，请肉眼确认够不够显眼；②标定「用当前会话」的端到端算结果需要 ≥3 组已保存记录
    （本轮造数据时点「保存」没进记录，进度停在 0/15，值得现场排查）；③反馈 4 的观感。
  - 提交：`f6f1a5d`(接入 .pair) `9874176`(共享服务) `d059578`(离线走主视窗) `a668180`(在线取点)
    `8eba311`(测量说明进日志) `e5c8dfb`(视窗样式) `ce19475`(一键标定) `ec111d6`(埃夫特)。
    **均未推送**（用户未说「推送」）。

- **2026-09-20（测量可信度批：P1–P4，**已通过 Codex 运行期验收并提交**）**
  - 来源：用户现场联测反馈第 10、2、3、5 条 —— ①造已知真值的数据并做成可复现校验；②修"测圆孔错得离谱"；
    ③把测量方法拆成独立工具条目、按方法限制 ROI；④每个方法带说明、关键数值进操作日志。
  - 交付（文件级）：`logic/MeasureMethods.h`（方法目录=名字/ROI 需求/说明文案/拖框策略，纯数据）；
    `ui/MeasurePage.{h,cpp}` + `ui/MeasurePages.{h,cpp}`（8 个方法页，**取点走产品同一条链路**
    `roiImageToGrid → pointsInRoiIndexed`）；`ui/ToolsPanel` 左侧 8 个独立条目 + 唯一一份 ROI/重复性状态；
    `ui/Image2DView` 工具栏「清除 ROI」；`logic/MeasureTools::holeBoundary()` 孔洞边界法；
    `tests/measure_truth*.{h,cpp}`（生成器+校验器，注册为 **ctest 用例 `measurement_truth`**）+
    `codex_testData/`（11 场景 / 20 文件 / `manifest.json` 含真值/公差/该用哪个方法/该画哪个 ROI + `README.md`）；
    `logic/LogPresentation.h` + `SidePanel::appendLog()` + `MainWindow` 的 `logAdded` 转发（P4 返工）。
  - 数值证据：`unit_tests` **23 类 / 255 passed / 0 failed / 1 skipped**；`measurement_truth`
    **11 场景 / 20 文件 / 78 条检查 / 失败 0**。孔洞：旧「圆环拟合」偏差 **+1.17 ~ +4.70 mm（全为正）**，
    新「孔洞边界法」偏差 **0.014 ~ 0.54 mm**，9/9 落在公差内且都 ≤ 旧法一半；`roi_map_boss`（图像 2× 网格）
    9 条全 PASS → **映射无缩放/偏移问题**。
  - Codex 真机验收（2026-09-20 13:10–13:45，真实相机 RVC-M2600-ML2 / G2GM620B101）：8 条目、ROI 需求文案、
    第 1/2/3 次拖框行为、2D 工具栏「清除 ROI」（含 enable/disable）、5 个页签、3D 工具栏、真实点云上跑平面度、
    两条测量日志**落面板 + 落文件**——全部通过；3 次连拍成功（约 66.8 万点/次）、正常关闭 2.3 s 退出、
    `taskkill /F` 后重启可重连并采集。**首验发现 P4 不通过**（`MainWindow.cpp` 的 `logAdded` 是空 lambda，
    日志只进文件不上面板）与 W1（第 2 次拖框后提示滞后），返工后复验通过。见 `.codex-loop/ACCEPTANCE-RUN.md`。
  - **未验证（重要）**：①真实相机点云上的**孔径**——现场这帧点云稀疏破碎、2D 图像近全黑、没有已知真值的孔，
    需用户给场景/工件；②3D 偏差着色的观感一致性需人眼判断。
  - **新发现（下一批优先级最高）**：`use_camera_params=0`（用保存的参数）时**拍照必失败**
    （`capture FAILED: 3D采集失败: Failed to capture2d!`，两次独立复现）；切回 `use_camera_params=1`
    并重连后同一台相机立刻成功。另：连续连接失败后设备列表显示「占用」（未坐实）。详见 `.codex-loop/DIALOG.md`
    回合 9 条目的 F2/F3 与 `RISKS.md`。
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

## 🚧 进行中（2026-10-08 按核定后的阶段状态重排）

- **阶段 10 的收口部分**：测量精度（T-012）与测量界面参数化（T-013）。
  这是唯一"正在进行"的阶段 —— 其余各阶段已核定完成或未开工。
  **2026-10-08 之七已把"误差较大"复现并定位到"边缘选择"一条**，
  下一步是 P1（重做边缘选择）→ P2（参数暴露）；详见
  `reports/阶段10-圆环拟合与孔径-真值回归结论.md`。
- **机器人通信四个协议的真机假设待证实**（Modbus 字节序 / UR 偏移 / NRC 字段名 /
  埃夫特单位）：不阻塞任何阶段，但**拿到现场证据前不要凭猜改那四个 reader**。
- ~~用户联测阶段 3/4/7/8~~ → **用户已核定全部通过，收口**。
- ~~阶段 8 三项顾问式功能待真机联测~~ → **2026-10-08 已实测一轮并通过**（用户核定）。
- ~~阶段 7 批量走点验证（VC/VR/VT 误差统计表）待补~~ → **未做，判定为不必做**，
  已在 PLAN 阶段 7 就地注明；如需再单开条目。

## 🐛 已知 BUG / 问题

| 问题 | 状态 | 备注 |
|---|---|---|
| **圆环拟合/孔径 在多跃变工件上选错边缘（2026-10-08 实测确认）** | **待修（P1）** | 工件在材料边界内还有台阶/槽/沉孔时，扫描"遇到第一道跃变就停"：圆盘 Ø26 撞到 R12 台阶 → 报 23.9998（−7.69%）；撞到 R10 → 20.0008（−23.07%）；孔 Ø9 沉孔到 R6 → 报孔壁 8.9995（−25.00%）。**且照报 `reliable=yes`**。复现见 `tests/circle_truth.cpp`，方案见 `reports/阶段10-圆环拟合与孔径-真值回归结论.md` §3 P1/P4 |
| **无图像时圆环拟合给不出任何读数** | **待修（P3）** | `contour3d`（外缘的 3D 轮廓兜底）只在 `if (map.ok)` 内构造，而 `map.ok` 需要有效图像 → 返回"找不到材料边界"。孔分支有 `holeBoundary` 兜底故孔有数。`results.json` 里 `disc_d63_5` 的"没有读到任何读数"很可能即此 |
| 阶段 4 线扫不对齐离线反投影为近似（内参投影+最近邻） | 保留为可优化项 | **2026-10-08 更新**：阶段 4 已由用户核定联测通过（对齐/线扫各一轮），本条不再是验收阻塞项；外参默认单位阵语义仍待线扫数据确认 |
| 阶段 7 计算前复制全部 png/ply 到临时目录（几百 MB） | 待优化 | 首次计算耗时明显；可改符号链接/规范命名 |
| ~~阶段 8 连接/读取为同步调用（超时 1.5s）~~ | **已修复** | T-009（`14157d6`）已把机器人通道整体搬进 `RobotWorker` 线程。此行 2026-10-08 核实后更正，原文"待优化"已不成立 |
| 阶段 8 Modbus 寄存器布局/字节序 | 待真机确认 | **2026-10-08 更正**：原文"可配置"是错的 —— 代码里**没有**字序/字节序开关。`RobotPose.cpp::parseRegisters()` 只有 `QDataStream::BigEndian` 一条路，`ModbusConfig` 仅 `startAddress/format/scale/unitId/timeoutMs` 可配。任务书 §2 负责证实它 |
| 阶段 8 UR Realtime body 字段偏移仅参考单一来源确认 | 待真机确认 | `kPoseOffset = 8 + 48*4 = 200`（`URRealtimeReader.cpp`，注释自称 empirically confirmed 但仓库无证据文件）。任务书 §3 负责证实，含固件版本差异 |
| 阶段 8 博纳斯/纳博特 NRC 应答字段名未经真机确认 | 待真机取证 | `NrcJsonReader.cpp` 候选表 13 个名字全是猜的，仓库里从未出现过一条能解析出位姿的真实应答。任务书 §4 |
| 阶段 8 埃夫特 EfortSDK 单位与欧拉约定未经真机确认 | 待真机确认 | `EfortPoseReader.cpp` 写死 `normalizePose(raw, true, true, ...)`＝mm+度+静态XYZ，原文注释即自认未经确认。任务书 §5 |
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

## ▶️ 下一步任务（2026-10-08 盘点，按来源）

**立刻要做的**

- [ ] **机器人通信真机联测 —— 暂时挂起**（用户 2026-10-08：现在无法立刻进场）。
      照 `reports/机器人通信真机联测任务书.md` 做四项（A Modbus 布局/字节序、
      B UR 偏移、C NRC 取证、D 埃夫特单位）。做哪项算哪项，回来时带 txt +
      `logs/runtime_<日期>.log` 的 `[NRC]` 行 + 记录表。
      **在此之前不要凭猜改 `src/logic/RobotPose.*` / `URRealtimeReader.*` /
      `NrcJsonReader.*` / `EfortPoseReader.*`。**

**功能/联测**

- [ ] **T-012 测量精度**：**判据已由人改判 0.2% → 0.5%×标称**（2026-10-08，
      三选一中选②；A 原建议③偏差补偿，未采纳）。判据本体已同步到
      `T-012.checks.py` / `T-012.md` / `reports/T-012/accuracy_probe.py`。
      **但改判没关掉本任务**：真机基线 Ø6=6.2648（+4.46%，是新容差的 9 倍）、
      Ø5=4.7370、Ø63.5 只有真值 76%、Ø26 与 Ø9 测不出读数 ——
      两个真缺陷（孔径法量到孔壁/倒角、缺"从外往内"的外缘边界能力）与容差宽窄无关。
      工程内容仍是原来那两条（边界按边缘量 + 亚像素到 0.01 mm 量级），靶心挪到 0.5%。
      数据在 `reports/T-012/BASELINE.md`（末尾「判据变更」）。**这是最大的一条。**
      - **2026-10-08 之七的实测补充（把上面"两个真缺陷"钉死成一个）**：
        `tests/circle_truth.cpp` 已用已知真值复现 —— **主因是边缘选择**（多跃变工件
        选到靠里那一道，−7.7% ~ −25%，且照报 `reliable=yes`）；
        而**亚像素与映射不是问题**（离轴 25 mm + 畸变 k1=0.15 也只有 0.11%）。
        工程入口因此收窄为 **P1 重做边缘选择 → P2 参数暴露**（原 L1/L3/L4 降级）。
        **P1 之前仍建议先跑一次真机 L0**（回归测的是算法，测不到真机图像/点云质量）。
- [ ] **P1 重做边缘选择**：列出全部候选跃变 → 按"最外材料边界"挑 → 歧义时报候选
      （见报告 §3）。判据 = `circle_truth` 里 `isKnownDefect()` 的 6 个场景回到 0.5% 内，
      其余场景不变差；修好会打印 `*** FIXED ***`。
- [ ] **P3 修无图像时圆环拟合的 3D 外缘兜底**（见「已知问题」表）。
- [ ] T-013 测量界面参数化（依赖 T-012）—— 参数清单已按**实测影响**排序，见报告 §3 P2。

**未开工 / 未完成的阶段（2026-10-08 核定）**

- [ ] 阶段 5 棋盘格标定 —— 未开工。开工前先出「不引第三方库能不能做」的结论
      （原 PLAN 里"或引入 OpenCV"**已作废**，本项目不引 OpenCV/Eigen）。
- [ ] 阶段 6 相机好机器人差的标定优化 —— 未开工，**目标待用户重新定义**：
      文档原文指的是**鲁棒标定求解**（RANSAC 离群剔除 / 加权求解 AX=XB 噪声，
      研究型），与用户说的"优化程序功能和使用"不是同一件事。三选一（保留原定义 /
      判定不需要并关闭 / 改写成别的目标）待定。
- [ ] 阶段 10 剩余部分：**2D 内参标定（张正友法）** —— 未做。是否要做待用户定。
      （同节的 2D 测量已具备；相机参数配置档案已决定不做。）
- [ ] 阶段 11 v2.0 打包与发布 —— **未完成**（用户判定：V2.0 要有的功能未收口）。
      打包机制本身已跑通（`pack_portable.ps1` + `dist/HandEyeCalibrationTool_test2.0`），
      缺的是 3 条验证 DoD 与"功能收口"这个前置。**含未装 RVC/VC++ 的干净机实测**（至今没做过）。
- [ ] 阶段 12 合并 main 与收尾（当前在 `HandEyeTools` 分支，main 未合）

**已关闭、不再做（别再挂回待办）**

- ~~阶段 9 数据管理与交付~~ → 2026-10-08 用户判定现有功能够用，**关闭**。
- ~~阶段 7 批量走点验证（VC/VR/VT 误差统计表）~~ → 未做，判定不必做。
- ~~阶段 10 相机参数配置档案~~ → 2026-09-21 起程序不下发拍摄参数，**决定不做**。

## 📦 清理规则

- 已完成且不再需要关注的条目从本文件删除（git 历史可追溯）。
- 旧 v1.0 细节、已归档修复不再回填本文件。
