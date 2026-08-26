# STATUS.md — 进度状态（每次会话结束必须更新）

> 最后更新：2026-08-26
> 只保留“当前快照”，不积累历史；旧条目删除即可，git 历史里仍可追溯。

## ⏭ 交接块（新会话先读这里）
- 当前状态：阶段 2「节点逐个完善」进行中。本会话（2026-08-26）完成
  2026-08-26 用户测试反馈的 **8 项整改**（git 提交 00121aa ~ 15741a3）：
  ① load_cloud 文件路径/批量文件夹二选一互斥（ParamDef 空值依赖 + File/Directory
  编辑器 objectName 遮蔽修复）；
  ② 属性面板「全选」清空 3D 修复（源节点占位输入组/无选中兜底布局回退输出组 +
  输入行端口角色拆分，新增 MainWindow 级 QtTest）；
  ③ 「平移/旋转」工具（选中帧左拖平移/右拖旋转，按 (provenance, frame) 存变换、
  刷新后保持，Reset 清除；ROI 框选按钮移入 Box ROI 节点功能区）；
  ④ Box ROI 重构：移除 frame_filter（必然每帧处理）；box_count>1 无 JSON 时复制
  当前盒 N 份；新增 Box 选择器支持每盒独立交互编辑并写回 boxes_json；
  ⑤ 「显示输出」下拉 →「显示数据类型」多选筛选（点云/包围盒/直线，默认全勾；
  包围盒按 RoiBox OBB 画线框）；运行到当前后属性面板默认选输出组（视窗即时刷新）；
  ⑥ 运行交互：未选中禁用「运行到当前」+ tooltip；运行中按钮 Running... 忙碌提示 +
  日志；运行中 3D 可操作、画布/参数禁用并有违规日志；
  ⑦ 连线命中区域 10px → 20px；⑧ 画布缩小切大纲后按钮/Ctrl+滚轮放大切回，大纲只读。
- 待办（下会话）：§9 第 8 项输入端口 optional 标志（Node API）；其余节点按 §8.8
  补批量 E2E（平面/聚类/Z 过滤/下采样/ROI Crop）；Box ROI「盒列表改点云对象属性
  （每帧独立列表）」方案待评估后定（本会话保持节点级 boxes_json 共享模型）；
  display3d 直播流式刷新 + LOD 密度自适应（硬件档位 API 已就绪）。
- 手动验证清单（VTK/UI 交互无法 QtTest 断言）：平移/旋转拖拽手感与旋转轴方向；
  多盒选择器切盒后交互框位置；包围盒线框叠加显示；ROI 编辑写回 boxes_json。
- 远程协作：项目在 `github.com/AZissue/RVBUST_Code` 的 `pointcloud-search` 分支；
  本地 master 跟踪 `origin/pointcloud-search`；本机 GitHub 直连超时需走代理：
  http `127.0.0.1:10809` / socks5 `127.0.0.1:10808`。
- 上次会话结束已提交：是（本会话 10 个功能/修复提交，未推送）

## ✅ 已完成（近期；更早历史见 git）
- [x] 2026-08-26 用户测试反馈 8 项整改全部落地（互斥、全选修复、平移/旋转工具、
  Box ROI 重构[去 frame_filter + 盒选择器]、显示类型筛选、运行交互、连线命中、
  画布缩放回切）——10 个提交 00121aa ~ 15741a3，ctest 7/7 + smoke 通过
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
- 阶段 2（节点逐个完善）：§9 用户反馈 8 项已全部落地。下一步：§9 第 8 项
  输入端口 optional 标志（Node API）+ 其余节点按 §8.8 补批量 E2E；
  Box ROI「盒列表改点云对象属性」待方案评估。

## 🐛 已知 BUG / 问题
| 问题 | 状态 | 备注 |
|---|---|---|
| 本机 ctest 直启 QtTest 卡死（PCL DLL ALPC 等待） | 已绕开 | `cmake -P` 包装 + 显式 PATH；换机器需复查 |
| 端口圆心贴节点边缘，精确点击可能不命中 | 已缓解 | boundingRect +4px；点圆内部即可 |
| 右键断开菜单 `menu.exec` 阻塞，QtTest 未覆盖 | 搁置 | 仅直接调用 removeEdge 的用例 |
| 切换语言后部分控件不即时重刷 | 搁置 | 低优先级 |
| 参数枚举值保持英文 | 已中文化 | 2026-08-26 修复（逐帧/分批/全部等） |
| 属性面板「全选」后 3D 视窗清空 | 已修复 | 00121aa + test_main_window 回归 |
| 运行到当前后视窗不刷新选中节点输出 | 已修复 | ca81880（默认选输出组） |
| 节点连线不易选中 | 已修复 | ce7347f（命中带 20px） |
| 画布缩小切大纲后无法放大切回 | 已修复 | 237eaf1（按钮 + Ctrl+滚轮回切，大纲只读） |
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
- [x] load_cloud 文件路径 / 批量文件夹二选一互斥
- [x] 属性面板全选 → 3D 显示全部选中帧（修复清空 bug）
- [x] 「平移/旋转」工具：点选单帧独立变换、刷新后保持；ROI 框选移入 Box ROI 节点按钮区
- [x] Box ROI 重构：去 frame_filter；盒数量 +/−；单帧多盒可操控可设 ID（节点级 boxes_json 模型）
- [ ] Box ROI 盒列表改点云对象属性（每帧独立列表，方案待评估）
- [x] 运行到当前后视窗即时刷新选中节点输出
- [x] 「显示输出」改为「显示数据类型」多选筛选（点云/包围盒/几何…默认全勾）
- [x] 运行交互：未选中节点禁用「运行到当前」+ 提示；运行按钮忙碌提示；运行中禁画布/参数操作并日志提示
- [x] 节点连线命中区域加大
- [x] 画布缩放布局回切修复（缩小切大纲、放大切回画布；大纲布局只读）

## 📦 清理规则
- 已完成且不再需要关注的条目，从本文件删除（git 历史可追溯）；只保留交接块、
  近期已完成、进行中、问题 / 失败表、下一步任务。
