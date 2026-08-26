# STATUS.md — 进度状态（每次会话结束必须更新）

> 最后更新：2026-08-25
> 只保留“当前快照”，不积累历史；旧条目删除即可，git 历史里仍可追溯。

## ⏭ 交接块（新会话先读这里）
- 当前状态：阶段 2「节点逐个完善」进行中；本会话完成**节点 I/O / 批量 / 显示统一约定**
  （PROJECT.md §8，用户逐项确认）。要点：ObjectList 载体 + cloud/region/any 端口 +
  zip 批量语义（1:1 / 1:N / 一帧多盒 F×M 对齐）+ 分块执行（K=1 逐帧默认 / K=10 限量 /
  K=N 全量）+ 性能内存约定（视口上限 3000 万点 = 相机 500 万 × 6 帧预留，实际密度按
  硬件档位自适应）+ 视窗多图层显示模型（多 display3d 叠加、latest-wins、图层级增量）。
- 本轮已完成并提交（2026-08-26，b0e0040）：**3D 视窗 ↔ 点云属性面板联动**——
  Cloud Properties 面板改为展示**选中节点的输入 + 输出**（按端口分组、逐帧列出
  Object/Points/Kind/Source），多选（ExtendedSelection）驱动 3D 视窗只显示选中帧
  （输出选中优先，否则输入；默认全选输入，源节点无输入时全选输出）；Box ROI 的
  初始框 / 重置包围盒按**选中输入帧**计算 AABB；box_roi 新增 **frame_filter** 参数
  （属性面板选中输入帧自动写入，空/全选=全部），未选中帧 1:1 透传、region 行带
  无效盒，下游 roi_crop 随之透传；配套 pipeline 单测（裁剪/透传/无效 token）。
- 本轮第二批已完成并提交（2026-08-26，2240786）：**参数中文 + 联动置灰 + 运行拆分 +
  分块累积**——所有节点参数（含新增参数）与枚举值中文显示（Select All/Clear 中文）；
  Chunk Size 仅当 Read Mode=chunked 时可编辑（其余模式置灰，ParamDef 依赖机制）；
  Box ROI「重置包围盒」按钮移入 3D 视窗工具栏专门区域（node action 区，后续节点
  功能按钮复用）；运行拆成「运行全部 / 运行到当前节点」两个按钮（Graph 拓扑截断 +
  dirty 增量：改中间节点后再运行到当前只重跑改动点及下游）；分块/流式执行结束后
  **源节点输出累积为完整帧列表**（属性面板与 3D 可见全部已加载帧，不再只有最后一块）。
  注意：中间节点（如 box_roi）输出仍保留最后一块（内存考量），如需全量累积可后续加开关。
- 手动验证清单（VTK/UI 交互无法 QtTest 断言）：加载多帧文件夹 → 选中 load_cloud
  → 属性面板输出组逐帧列出 → 单选/多选帧 → 3D 只显示选中帧 → 选中 box_roi 输入帧
  → ROI 框按选中帧 AABB 放置 → 运行后输出面板可见"仅选中帧被裁剪、其余透传"。
- 上轮功能已完成并提交：Box ROI W/E 快捷键（9ada27b）等 ROI 交互工作已提交并推送
  `origin/pointcloud-search`；ctest 6/6 + smoke/demo 通过。交互统一（左旋 / 滚轮缩放 /
  右键平移）与滚轮步进 1.25 手感已确认；“三色边框 + 只留 XYZ 三轴”确认不做。
- 本轮完成并已推送：**load_cloud 文件夹批量 + 读取模式（stream/chunked/all）+ 引擎
  分块执行**（47bb5a6，附 74cf11d 清理临时调试输出）。IO 新增 listPointCloudFiles
  （自然排序）、Node 批处理上下文、Graph::executeChunked、save_cloud 空输入传播、
  engine_runner 接入批量执行；配套 batch/solution E2E 单测；ctest 6/6 + smoke 通过。
- 本轮已完成并提交（PROJECT §9 前 7 项，逐项配套单测）：
  ① ✅ load_cloud 文件夹批量（47bb5a6）；② ✅ display3d 多图层 + latest-wins +
  视口预算 + 硬件档位（9189417，端口改 any）；③ ✅ RoiBox.label + box_roi 一帧多盒
  （box_count + boxes_json，F×M 对齐）+ region 坍缩 / provenance 修复（d6ece80）；
  ④ ✅ save_cloud 零填充帧名 + 多盒命名，三模式命名一致（d98b212）；
  ⑤ ✅ roi_crop 按索引对齐 + alignInputs 助手 + §8.8 批量 E2E（ce9323d）。
- 下一步（下会话，重点）：
  - §9 剩余第 8 项：输入端口 optional 标志（Node API），roi_crop 等 optional 端口
    按文档化默认行为执行；
  - 逐个节点按 §8.8 补批量 E2E（平面 / 聚类 / Z 过滤 / 下采样 / ROI Crop 目前仅
    单对象或部分批量覆盖）；
  - display3d 直播流式刷新（块进度已通）+ LOD 密度自适应（硬件档位 API 已就绪，
    默认仍为 Low 150 万保红线）为后续优化方向。
- 正在进行的文件：`modules/pipeline/src/nodes/core_nodes.cpp`、
  `modules/pipeline/include/pcsearch/pipeline/nodes/node_utils.h`、
  `app/src/point_cloud_view.cpp`
- 卡点 / 风险：ROI 交互 / 多图层显示为 VTK 行为，QtTest 无法断言，只能手动验证；
  核显 / 远程桌面必须保持显示降采样（3000 万为视口上限，实际密度按硬件档位自适应）。
- 远程协作：项目已上传 `github.com/AZissue/RVBUST_Code` 的 `pointcloud-search`
  分支（main 总览 README 已登记）；本地 master 跟踪 `origin/pointcloud-search`，
  提交后直接 `git push`。本机 GitHub 直连超时，需走代理：
  http `127.0.0.1:10809` / socks5 `127.0.0.1:10808`。
- 上次会话结束已提交：是（ROI W/E、体素修复与本会话文档约定均已推送）

## ✅ 已完成（近期；更早历史见 git）
- [x] 2026-08-26 参数中文（含枚举）+ Chunk Size 联动置灰；节点功能按钮区；
  运行全部 / 运行到当前（增量）；分块执行后源节点输出累积全部帧
- [x] 2026-08-26 3D 视窗 ↔ 点云属性面板联动：选中节点输入/输出逐帧展示 + 多选帧
  驱动 3D 显示；ROI 基准按选中输入帧；box_roi frame_filter（仅裁剪选中帧）
- [x] 2026-08-25 「加载 → Box ROI → 保存」三节点批量架构：load 文件夹批量 + 读取模式 +
  引擎分块执行；display3d 多图层 + latest-wins + 视口预算 + 硬件档位；RoiBox label +
  一帧多盒（F×M 对齐）+ region 坍缩 / provenance 修复；save 零填充 / 多盒命名；
  alignInputs 助手 + §8.8 批量 E2E（PROJECT §9 前 7 项）
- [x] 2026-08-25 完成节点 I/O / 批量 / 分块 / 显示统一约定（PROJECT §8 + §9 待修清单），
  含一帧多盒、文件夹批量读取模式、视窗多图层显示模型
- [x] 2026-08-25 修复本地一键构建：CMake 复用 RvcVisionStudio 自编译 VTK（带 GUISupportQt）解决 PCL 1.13.0 捆绑 VTK 缺 Qt 支持问题；start.bat 自动探测本机 Qt/PCL 路径；ctest 6/6 + autoquit 冒烟通过
- [x] 2026-08-25 修复体素下采样：改用真实三维网格坐标作 key，消除旧 scalar XOR 哈希的静默碰撞；用 computeBounds 跳过 NaN/Inf 保证 RVC 空洞点云不污染体素原点；输出按 first_index 排序保证跨平台一致；补 2 个回归测试；ctest 6/6 全绿
- [x] 2026-08-25 Box ROI 编辑态快捷键 W/E：W=可操作包围盒、E=仅查看（SetProcessEvents
  0/1）；快捷键仅在编辑态启用；构建/ctest/smoke/demo 通过
- [x] 2026-08-25 交互统一为左旋/滚轮缩放/右键平移（3D 视窗 + ROI 包围盒）；滚轮步进
  1.25/格；定位“放大后变慢”根因；构建/ctest/smoke/demo 通过
- [x] 2026-08-25 ROI 交互升级：单面缩放(MoveFaces)、去掉右键整体缩放、选中
  box_roi 自动进入编辑、关闭米字线、外框细化(线宽 1.2px/面 0.06)；构建/ctest/smoke/demo 通过
- [x] 2026-08-25 修复 ROI 操控“双包围盒”：box_roi 编辑态只显示 vtkBoxWidget2
  交互框，隐藏静态预览框，退出编辑恢复预览；构建 / ctest / smoke / demo 通过
- [x] 2026-08-25 补齐 random_downsample / euclidean_cluster / plane_detect 节点级
  E2E 单测（走 Graph 全链路 + source_indices 溯源）；`ctest` 6/6 全绿
- [x] 2026-08-25 项目文档按新模板迁移（AGENTS / PROJECT / PLAN / STATUS +
  docs/SESSION_PROMPTS.md）；git 初始化基线提交
- [x] 2026-08-24 Box ROI 全套：OBB 旋转、8 角点位姿读取、重置包围盒（AABB，
  跳过 NaN/Inf）、拖动松手才刷新（不卡顿不刷屏）
- [x] 2026-08-24 显示降采样 ≤150 万点 + 单精度顶点；QThread 取消机制；
  File 参数类型闪退修复
- [x] 2026-08-24 保存节点改为“输出文件夹 + 文件名”，auto → PLY、自动建目录
- [x] 2026-08-20 画布交互（连线跟随 / 右键删除断开 / 背景风格）、默认中文 +
  Dark、方案 JSON、多视窗

## 🚧 进行中
- 阶段 2（主线 ROI BOX → 批量语义落地）：§9 前 7 项批量架构已完成（加载 → Box ROI →
  保存三节点）；本轮完成属性面板 ↔ 3D 视窗帧联动。下一步：§9 第 8 项 optional
  端口标志 + 其余节点按 §8.8 补批量 E2E。

## 🐛 已知 BUG / 问题
| 问题 | 状态 | 备注 |
|---|---|---|
| 本机 ctest 直启 QtTest 卡死（PCL DLL ALPC 等待） | 已绕开 | `cmake -P` 包装 + 显式 PATH；换机器需复查 |
| 端口圆心贴节点边缘，精确点击可能不命中 | 已缓解 | boundingRect +4px；点圆内部即可 |
| 右键断开菜单 `menu.exec` 阻塞，QtTest 未覆盖 | 搁置 | 仅直接调用 removeEdge 的用例 |
| 切换语言后部分控件不即时重刷 | 搁置 | 低优先级 |
| 参数枚举值保持英文 | 已中文化 | 2026-08-26 修复（逐帧/分批/全部等） |
| `rot_y=±90°` 欧拉角万向锁（角度跳变，裁剪正确） | 已定位 | 后续可换四元数 |
| ROI 交互回归只能手动验证 | 已知 | 手动测试清单：加载 → 框选 → 拖 / 缩 / 旋转 → 重置 → 保存 |
| 关窗时单节点执行 >30s 会阻塞等待 | 已定位 | 取消在节点间生效，单节点内不可中断 |

## ❌ 已尝试但失败的方案（附原因，防止重复踩坑）
| 方案 | 失败原因 | 当时条件（版本 / 环境） | 结论是否仍有效 |
|---|---|---|---|
| ctest 直启 QtTest exe | 进程卡死（ALPC） | 本机 PCL 加载 | 是（换机器复查） |
| `cmd /c` 作为 ctest 命令 | 引号拼接语法错 | ctest CreateProcess | 是 |
| `windeployqt --no-compiler-runtime` | 仍带旧 MSVC 运行库 | Qt 6.8.3 | 是（POST_BUILD 清理） |
| Qt6_DIR 两级路径找 bin | 指向 lib/bin | Qt 6.8.3 | 是（三级） |
| 拖拽连线 `scene->items()` 命中 | 边界不稳定 | 画布 v1 | 是（改端口距离吸附） |
| `GetTransform` 读取盒子中心 | GetPosition = R·c 偏 | VTK 9.4 原点居中放置 | 是（改 8 角点） |
| 多图层重排 RemoveViewProp 后再 AddViewProp | 堆损坏 0xC0000374（demo 崩溃） | VTK 9.4 vtkNew 只留 renderer 引用 | 是（图层容器改 vtkSmartPointer 自持引用） |
| std::min/max 全量算包围盒 | NaN/Inf 污染 | RVC 点云空洞 | 是（改 allFinite） |
| 参数默认只写 description | 实际默认 0 / 类型错 | Params v1 | 是（加 default_value） |
| 直接销毁运行中 QThread | Qt6 fail-fast 0xC0000409 | 5M 流程中退出 | 是（加取消 + wait） |
| 保存单“输出路径”框 | 文件夹被当文件名 | 保存节点 v1 | 是（拆文件夹 + 文件名） |

## 🧭 近期技术决策（永久记录在 PROJECT.md 第 7 节）
- 2026-08-18 ~ 2026-08-25 的决策已全部归档到 PROJECT.md §7 ADR 表，此处不重复。

## ▶️ 下一步任务
- [x] ① load_cloud 文件夹批量 + 读取模式（all / chunked / stream，默认逐帧）
- [x] ② display3d 多图层叠加 + latest-wins + 视口 3000 万点预算与硬件档位（3D 视窗刷新）
- [x] ③ RoiBox 加 label；box_roi 一帧多盒（盒列表节点级共享，输出 F×M 对齐；配套修 region 坍缩 / provenance）
- [x] ④ save_cloud 零填充 / 多盒命名；点云批量保存
- [x] ⑤ roi_crop 按索引对齐 + 抽 alignInputs 助手 + 批量 E2E 单测（§8.8，贯穿各步）
- [ ] 输入端口 optional 标志（Node API，PROJECT §9 第 8 项）
- [ ] 平面检测 / 聚类 / Z 过滤 / 下采样 / ROI Crop 节点按新约定补 E2E
- [ ] display3d 直播流式刷新 + LOD 密度自适应（硬件档位 API 已就绪）
- [x] 3D 视窗 ↔ 点云属性面板联动（输入/输出逐帧展示、多选显示、ROI/box_roi 帧过滤）
- [x] 运行拆分：运行全部 / 运行到当前节点（增量重跑改动点及下游）
- [x] 参数中文 + 枚举中文 + Chunk Size 联动置灰 + 节点功能按钮区（3D 工具栏）
- [x] 分块/流式执行后源节点输出累积（属性面板可见全部已加载帧）

## 📦 清理规则
- 已完成且不再需要关注的条目，从本文件删除（git 历史可追溯）；只保留交接块、
  近期已完成、进行中、问题 / 失败表、下一步任务。
