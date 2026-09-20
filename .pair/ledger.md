# 台账（MyHandEyeTools × Codex/Claude 双智能体协作）

每轮一行：日期 · 轮次 · Claude 做了什么 · Codex 的独立验证结论 · 真实花费。
只看 Codex 亲自复现过的证据；`outbox/` 里 Claude 的说法不算数。

| 轮次 | 日期 | inbox | Claude 交付 | Codex 验证 | 结论 |
|---|---|---|---|---|---|
| 000 | 2026-09-20 | — | — | 基线：`cmake --build build --config Release` 退出码 0；`ctest -C Release` 2/2 通过（unit_tests 1.15s、measurement_truth 0.40s）；工作区干净（HEAD `9e18f3b`，分支 `HandEyeTools`，领先 `AICode/HandEyeTools` 5 个提交） | 基线绿 |
| 001 | 2026-09-20 | 001 | 新增 `logic/PixelTo3DService.{h,cpp}`（像素→3D 共享服务，对应图 > 对齐直查 > 投影 的分派）；`ToolsPanel::updatePixelTo3DResult()` 改走服务；`src/CMakeLists.txt` 加一行 | 既有测试全绿且**总数上升**：23 类/255 passed → **24 类/270 passed**（新增 15 条都是 Codex 写的 `TestPixelTo3DService`）；`rg` 复核 `src/ui/` 已无直接取点调用；**真机**：真实 exe + 真实界面，探针点云（索引可反推）三处取点与真值逐位一致（`5,7`→`453.125, 906.250, 1359.375`），越界像素正确报错。证据 `.pair/reports/turn-001-acceptance.md`、`ui-app-turn001.png` | **通过**，已提交 |
| 002 | 2026-09-20 | 002 | 工具页删除内嵌 `Image2DView`；加「在线/离线」开关（默认离线）；`Image2DView` 增 `setFrozenImage/clearFrozenImage/frozen`；离线时主 2D 视窗显示所加载文件图像、点击回填工具页；手动输入目录即刷新图像列表；外参非法不再静默忽略 | 机械全绿（24 类/270）。真机：离线取点 `5,7`→`453.125, 906.250, 1359.375`；点击主视窗→像素 `31,24`→`1567.125, 3134.250, 4701.375`；关工具窗恢复实时图（亮度 35.73→0.00）。**不通过**：重开工具窗（停在别的页）也会冻结主视窗，切页不解冻 | 不通过 → 回灌 003 |
| 003 | 2026-09-20 | 003 | 冻结判据收敛成唯一入口 `updateOfflineFreeze()`（面板可见 + 当前页==像素→3D + 离线 + 图像有效），五个状态入口全部汇到它 | 真机五连测：未开面板 0.00 / 开面板停在别页 0.00 / 像素→3D 离线 35.73 / 切走 0.00 / 切回 35.73 / 停在别页关面板 0.00 / 重开 0.00；离线数值与点击回填无回归 | **通过**（与 002 一并提交 `d059578`） |
| 004 | 2026-09-20 | 004 | `MainWindow::on2dPixelPicked()` 改走 `PixelTo3DService`（对齐/对应图两种帧），新增 `queryPixelFromCurrentFrame()`；在线模式下把结果推给工具页（新信号 `pixelTo3DOnlineQueryRequested` + 槽 `setOnlinePixelResult`）；在线模式禁用文件输入、提示改为"在主 2D 视窗左键取点" | 机械全绿（24 类/270），`rg "PixelTo3DTools::" src/app/MainWindow.cpp` 无匹配。**真机（真相机 RVC-M2600-ML2 / M2GM620B417，拍照后）**：点击→工具页 `-117.686, -88.235, 468.162`（像素 359,236）；另一像素→`35.558, 59.817, 492.682`；手输同一像素点「计算」得同一值；「复制」进剪贴板内容与结果行逐字相同；2D 视窗留下十字标记；日志两条 [提示] 落面板。**未确认**：3D 视窗上那个取点黄球在截图/像素扫描里找不到（识别圆心用的是同一套 1mm 绿球，取点用 2mm 黄球），列 NEEDS_HUMAN 请用户肉眼确认 | 核心链路**通过**，3D 标记可见性 NEEDS_HUMAN |
| 005 | 2026-09-20 | 005 | 删掉 `MeasurePage` 里的「说明」GroupBox（`measure_spec_<id>`）；`methodExplainLine()` 补成 `用途：…；怎么用：ROI 怎么画：…；输出：…；怎么看结果：可信度：…；常见错法：…`；`resultLine()` 末尾补 `；这组数说明：<reading>`（数值格式一字未动）；`MethodSpec` 增 `reading` 字段 | 机械：24 类/**271 passed**（Codex 新增 `everyMethodStatesWhatTheNumbersMean`：逐个方法断言四个小标题 + 结果行末尾必须真有一句解释 + 数值格式不变）；静态：`MeasurePage.cpp` 已无 `measure_spec_`。真机：选中 平面度 / 孔径(孔洞边界法) 后操作日志出现 `[测量-说明]` 且四个小标题齐全；窗口里已看不到原「说明」块（`005-measure-page.png`、`005-log-tail.txt`） | **通过** |
| 006 | 2026-09-20 | 006 | `Theme` 新增 `viewOverlayLabelStyle()` / `viewOverlayButtonStyle()`（`border: none` + `background-color: rgba(0,0,0,0.20)`，hover 0.28、pressed/checked 0.30），2D 视窗的标题/缩放标签与页面栏、3D 视窗工具栏与占位文字全部改用它 | 机械：24 类/271 passed，ctest 2/2。静态：两个函数存在且 alpha ≤0.30。真机：截图 `006-views.png` / `006-2d-devpage.png` 显示按钮与标签已无实心底色、无边框；点 偏差着色（CheckBox）与 偏差图（RadioButton）状态切换正常、点回 图像 正常 | **通过** |

## 成本记录（真实扣费 vs Claude Code 估算）

| 时点 | DeepSeek 余额 | 说明 |
|---|---|---|
| 协作开始前（2026-09-20） | ¥8.35 | 基线 |

## 接入说明（本项目与上一版脚手架的差异）

- 脚手架来自 `D:\MyCode\CodexWithClaude\.pair`（Python 项目），本项目为 C++/Qt/CMake：
  - `run-turn.py` 默认验证命令改为 `cmake --build build --config Release && ctest --test-dir build -C Release --output-on-failure`；
  - 默认工具白名单改为 `Read,Glob,Grep,Edit,Write,Bash(cmake --build:*)`（只放行一次编译自检，不放行 ctest/GUI/git）。
- 双工作区事实（2026-09-20 核对）：`D:\MyCode\MyHandEyeTools`（分支 `HandEyeTools`）为当前最新工作区；
  `C:\Users\rvbust\Documents\Codex\AICode\handeye-tools` 落后（src 73 vs 84 个文件，最后写入 2026-09-11）。
  本轮起以本工作区为准，待用户拍板后再决定是否回归 AICode。

## 真机环境基线（用户 2026-09-20 提供，反馈 11）

| 项 | 值 | 备注 |
|---|---|---|
| 测试相机 | RVC M2600，序列号 `G2GM620B101` | 与第 8 回合验收用的 RVC-M2600-ML2 是同一台 |
| 机器人 | UR（优傲） | 用户给的端口是 **3003**，代码里 UR Realtime 写的是 **30003** —— 待确认 |
| 拍摄场景 | 一个同心圆 | 与校准板 `markerType=1`（同心圆）一致 |

> 真机验收的证据（截图 / 原始输出 / 命令）一律写进 `.pair/reports/`，不留在会被 gitignore 的目录里。
