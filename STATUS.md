# STATUS.md — PointCloudSearch 项目状态

最后更新：2026-08-24

## 更新记录

- 2026-08-24：修复 ROI 框选无法操作的根因（`RemoveAllViewProps` 会把
  vtkBoxWidget2 的表示层演员一并清掉，导致看不到也点不到盒子）；改为只移除
  点云演员。包围盒升级为可旋转 OBB（中心 + 半长 + 欧拉角），Box ROI 参数面板
  新增「重置包围盒（按输入点云）」按钮，按整个输入点云合并包围盒并同步参数 /
  交互框。交互位姿读取改用表示层 8 个角点直接计算（`GetTransform` 的 position
  在原点居中放置时不是盒子中心，且 vtkTransform PostMultiply 命名与常规相反；
  已用 VTK 探针程序验证平移 / 缩放 / 旋转后角点读取全部正确）。新增旋转 ROI
  单测与重置按钮 UI 测试，ctest 6/6 全绿。
- 2026-08-24（二）：重置包围盒后自动进入 ROI 框选模式并让相机对准包围盒，
  解决“点完重置看不到包围盒”的问题；进入框选时同样自动对准相机。
- 2026-08-24（三）：修复重置得到 ±1e9 的错误包围盒。根因：`nodeInputBounds`
  用 `std::min/max` 直接扫全点，RVC 点云的 NaN/Inf 空洞（1.ply 有 148,247 个
  无效点）会污染结果。新增 `filters::computeBounds`（跳过非有限点，语义同
  PCL getMinMax3D / Open3D AABB），`Params::set` 拒绝 NaN/Inf 作为第二道防线；
  顺带修复 `Params::define` 未应用声明默认值（此前所有参数默认都是 0，导致
  新 Box ROI 初始包围盒是 0 尺寸退化盒）——现在 box_roi 默认 ±100000。
  已用真实文件验证：有效点 1,406,953/1,555,200，包围盒
  x[-310.42, 308.94] y[-196.62, 248.31] z[549.23, 744.42]。
- 2026-08-24（四）：修复“运行点云加载节点闪退（还没加载点云）”。两个根因：
  (a) `fileParam` 未设置 default_value，Params::define 后 File 参数默认变成
  double 0.0，渲染点云加载参数面板时 std::get<std::string> 抛
  bad_variant_access → 界面线程未捕获 → 立即闪退（添加/选中节点即崩）；
  修复：fileParam 补默认空串 + Params::define 按类型规整默认值 +
  ParamsPanel 全部改用类型安全访问。
  (b) 关闭/退出时 QThread 仍在执行长流程（5M 加载/裁剪/保存）→ QThread
  运行中被销毁 → Qt6Core fail-fast 0xC0000409；修复：Graph::execute 支持
  节点间取消、GraphRunner.requestCancel、MainWindow 析构时取消并等待线程。
- 2026-08-24（五）：5M 点云显示压垮 Intel HD630 核显/远程桌面（先卡顿后
  vtkRenderingCore 访问违例）。修复：显示降采样（单精度顶点 + 均匀步长，
  显示上限 150 万点，管线数据不变），异常兜底 + displayInfo 日志提示。
  5M 文件 demo + 中途 autoquit 复测 3 次干净退出。
- 2026-08-24（六）：ROI 框选操控卡顿 + 日志刷屏。根因：拖动手柄时每次鼠标
  移动都触发 onRoiEdited，且每次重建整个参数面板 + 重建线框演员重渲染 +
  写日志。修复：拖动中只写参数（轻量），vtkBoxWidget2 EndInteractionEvent
  （松手）时一次性刷新面板/线框/日志（新增 roiEditFinished 信号）。
- 2026-08-24（七）：保存点云报 cannot determine format from extension
  （路径无扩展名，format=auto）。修复：auto + 无扩展名时回退 PLY 并自动
  补 .ply 后缀（保存多对象时 expandPath 正确派生 *_0.ply 等）。
- 2026-08-24（八）：保存点云“运行成功但路径下没有文件”——旧设计只有单个
  “输出路径”，用户填了文件夹路径，代码按文件路径处理（补 .ply 后写到
  文件夹旁边/内部奇怪名字）。改为两个参数：输出文件夹（Directory 类型，
  浏览器选目录）+ 文件名（默认 cloud，自动补扩展名）；format=auto 回退
  PLY；运行前自动 create_directories 创建文件夹（含嵌套）。
- 2026-08-20：完成画布交互（连线拖动跟随 / 右键断开 / 背景风格）、路径文件浏览、
  默认中文 + Dark、ROI 独立模块化（RoiSelector）与上游点云联动显示、Box ROI
  交互调优（左键拖动 / 手柄缩放 / 滚轮缩放视窗）。`ctest` 6/6 全绿，demo E2E
  通过；进入阶段 2 节点逐个验证。
- 2026-08-20（二）：新增一键启动脚本 `start.bat`（根目录）——无参数双击直接
  启动程序；带参数时透传 `--smoke / --demo / --autoquit` 并在前台运行保留退出码；
  Release 缺失时自动 cmake 配置 + 构建。已实测三种调用方式。

## 一、已完成 ✅

### 环境与工程
- 依赖：VS2026 + CMake 4.4、PCL 1.13.0、Qt 6.8.3、VTK 9.4（编译安装到
  `D:\Program Files\VTK`）、RVC SDK（待真机联调）。
- 部署：`cmake/deploy_runtime.cmake` 统一部署 Qt（windeployqt）+ PCL + VTK 到
  exe 目录，并剔除旧版 MSVC 运行库；VS 调试环境自动注入 Qt/VTK/PCL 路径。
- 全局 `/utf-8` 编译；中文路径 UTF-8→宽字符读写。

### 核心模块
- `core_data`：PointCloudData / Region / RoiBox / ObjectList（含原始索引映射）。
- `io`：PCD / PLY / XYZ / CSV 读写 + 单位换算 + 中文路径。
- `filters`：移除无效点、体素 / 随机下采样、Z 范围过滤。
- `segmentation`：多平面检测（RANSAC）。
- `clustering`：DBSCAN、欧几里得聚类。
- `pipeline`：Params / Node / Graph（DAG 增量执行、逐节点耗时、端口类型校验、
  run stats）、多输出端口（executeAll）、零依赖 mini JSON、方案 save/load、
  `box_roi` / `roi_crop` / `display3d` 节点、`ParamType::File`。

### 桌面程序（app）
- 异步执行引擎（GraphRunner 线程，运行中锁定编辑）。
- 工具箱分类树 + 搜索（Ctrl+F）、双击 / 拖拽实例化。
- 画布：拖拽 / 点击连线、连线随节点拖动实时跟随、右键删除节点、右键断开连线、
  画布背景（网格 / 点阵 / 纯色 / 自定义图片）、全视口刷新无残留。
- 端口类型着色（cloud 蓝 / region 绿 / any 灰）+ 禁连提示。
- 节点选中联动：3D 视窗显示上游输入点云；双击聚焦参数。
- ROI：独立 RoiSelector 模块（vtkBoxWidget2，左键拖盒子 / 手柄缩放 / 滚轮缩放
  视窗 / 边手柄旋转），Box ROI 参数实时线框预览（支持旋转），框选写回参数；
  参数面板提供「重置包围盒（按输入点云）」按钮（合并全部输入对象 AABB 写回
  参数并同步交互框）。
- `RoiBox` 升级为有向包围盒（OBB）：世界中心 + 局部半长 + 旋转矩阵；`contains`
  先把点变换到盒子局部系再判断，带微米级相对容差（避免 90° 旋转时浮点误差
  把恰好贴在面上的点剔除）。`box_roi` 新增 `rot_x/rot_y/rot_z` 参数（度）。
- 多视窗 ViewportManager + display3d 节点路由。
- 方案 File → Save/Open Solution（`*.pcsearch.json`，含节点位置）。
- 默认中文 + Dark 主题（View → Language/Theme 切换）；节点 / 分类 / 参数标签
  中英文统一在 `node_titles.cpp`。
- 路径参数带「…」浏览按钮（加载用打开对话框、保存用保存对话框）。
- CLI：`--smoke <ply>` / `--demo <ply> [--autoquit N]` / `--autoquit N`。

### 测试与演示
- `ctest` 6/6 全绿：io / filters / clustering / pipeline / plane_detector /
  node_flow（拖拽连线、拖动跟随、Delete 删除、背景、中文标题、断开连线、
  Box ROI 重置按钮）。pipeline 测试新增旋转 ROI 用例（Rz90 裁剪区域校验）。
- demo 链路：点云加载 → Box ROI → 保存点云 → 3D 显示，E2E 验证通过。
- 一键启动：`start.bat`（无参启动 / `--smoke <ply>` / `--demo <ply> --autoquit N`）。

## 二、当前进行中 🔄

- 阶段 2：节点逐个验证与完善。基准流程「点云加载 → Box ROI → 保存点云」已跑通；
  下一步用平面检测 / 聚类 / Z 过滤 / 体素等节点替换 Box ROI 逐个测试。

## 三、已知 BUG 与问题 ⚠️

1. 本机 ctest 直接 CreateProcess 启动 QtTest 会卡死（加载 PCL DLL 时所有线程
   阻塞在 ALPC 等待）。已用 `cmake -P` 包装脚本 + 显式 PATH 绕过；属环境问题，
   换机器需复查。
2. 端口圆心位于节点矩形边缘，精确点击圆心可能不命中场景命中测试；
   已通过 boundingRect 加 4px 边距缓解，正常点击圆内部即可。
3. 右键「断开连接」已实现，但 `menu.exec` 阻塞，QtTest 未覆盖该路径
   （仅直接调用 removeEdge 的用例）。
4. 切换语言后，已打开的多视窗标题、日志面板等部分控件不即时重刷
   （低优先级）。
5. 中英文切换为运行时切换；参数枚举值（millimeter / meter 等）保持英文
   （属设计取舍，非 BUG）。
6. ROI 交互框的旋转欧拉角在 `rot_y = ±90°` 附近存在万向锁（欧拉角取值跳变，
   裁剪结果仍正确；后续可换四元数表示消除）。
7. `vtkBoxWidget2` 的交互无法用 QtTest 模拟（需要真实鼠标事件 + GL 渲染），
   交互回归目前靠手动测试清单（见本轮回复）验证。
8. 命令行工具 / 探针接收中文路径参数时会按 ANSI 代码页解析而打不开文件
   （GUI 内走宽字符路径无此问题）；排查时先复制到 ASCII 路径。
9. 关闭窗口时若当前节点执行超过 30 秒（如超大文件保存），会阻塞等待其完成
   而非崩溃（节点间取消已生效，单节点内部不可中断）。

## 四、已尝试但失败 / 放弃的方案

- ctest 直接运行 QtTest exe → 进程卡死（ALPC 等待）→ 改 `cmake -P` 包装。
- `cmd /c` 作为 ctest 命令 → “命令语法不正确”（CreateProcess 引号拼接问题）。
- `windeployqt --no-compiler-runtime` 仍会带旧 MSVC 运行库 → POST_BUILD 最后
  统一删除 concrt/msvcp/vcruntime DLL。
- Qt6_DIR 到 bin 的两级路径计算 → 指向不存在的 `lib/bin` → 修正为三级
  （`Qt6_DIR/../../../bin`）。
- 拖拽连线释放点用 `scene->items()` 命中 → 边界不稳定 → 改为端口距离吸附。
- 假设 ctest 卡死与 `w.show()` 有关 → 排除（去掉 show 仍卡，根因是加载期）。
- 用 `vtkBoxRepresentation::GetTransform` 读取盒子中心 → 原点居中放置时
  GetPosition = R·c（带旋转会偏）；改用角点直接计算，全部交互后验证正确。

## 五、重要技术决策

- 自研 QGraphicsView 画布，不迁移 QtNodes（渐进增强，布局已获认可）。
- `Node::executeAll` 支持多输出端口（box_roi 输出 cloud + region）。
- ROI 为一等类型 `RoiBox`（OBB：center + local min/max + orientation），挂在
  `PointCloudObject.roi`；`RoiSelector` 独立模块供各视窗复用。
- 视窗渲染分层：点云演员由 `PointCloudView` 自己持有并只清自己，绝不调用
  `renderer_->RemoveAllViewProps()`，保证交互控件（widget 演员）与线框叠加层
  不受点云刷新影响。
- `box_roi` 参数语义：xmin..zmax 表示盒子中心 ± 半长（未旋转时即世界 AABB），
  rot_x/y/z 为 XYZ 内旋欧拉角（度），与 RoiSelector 的提取公式一致。
- ROI 交互位姿读取：从 `vtkBoxRepresentation::GetPolyData` 的 8 个角点计算
  （中心=角点均值、半长=边方向范数/2、旋转=归一化边方向矩阵），不依赖
  `GetTransform` 的分解；放置用默认 PreMultiply 构造 T(c)·R。
- 边界判定带相对容差 `max(1e-3 mm, 1e-4 * 盒边长)`，保证旋转后边界点仍包含。
- AABB 计算（`filters::computeBounds`）只统计有限点，NaN/Inf 一律跳过
  （PCL getMinMax3D / Open3D get_axis_aligned_bounding_box 语义）；
  `Params::set` 拒绝非有限数值，参数层不允许出现 NaN/Inf。
- `ParamDef.default_value` 为参数唯一默认来源（helpers 填充），`Params::define`
  首次定义时应用；此前默认值只写在 description 里、实际存储为 0。
- 关闭/退出安全性：QThread 运行中禁止销毁；`Graph::execute(cancel)` 在节点间
  检查取消标志，MainWindow 析构时 requestCancel + quit + wait。
- 大点云显示：一律均匀步长降采样到 ≤150 万点 + float 顶点，避免核显/远程
  桌面下整帧上传 5M 点导致卡顿与 GL 驱动崩溃；降采样仅影响视图不影响数据。
- ROI 交互性能：拖动中只 setParam 更新参数，松手（EndInteractionEvent）
  才重建面板/线框/写日志，避免每帧重活导致的卡顿与日志刷屏。
- 保存格式兜底：format=auto 且路径无扩展名 → 自动回退 PLY 并补 .ply。
- 保存节点参数：folder（ParamType::Directory，目录选择器）+ file_name
  （默认 cloud）+ format + target_unit；扩展名由 format 决定，文件夹自动创建。
- 零依赖 mini JSON（pipeline 层保持 Qt-free）。
- `ParamType::File` 照搬旧项目，路径浏览交互。
- 默认中文 + Dark；中英文名统一放 `app/src/node_titles.cpp`。
- 连线跟随 BUG 根因：缺 `ItemSendsGeometryChanges` 标志（QtTest 复现 + 回归）。
- 内部 mm；单位换算只在 IO 层；结果保留原始索引。

## 六、下一步任务

1. 阶段 2：替换 Box ROI 逐个测试节点：平面检测 → DBSCAN / 欧几里得 → Z 过滤 →
   体素 / 随机下采样 → ROI Crop；先把本轮 ROI 交互按手动测试清单验证通过。
2. 阶段 3：形状（圆 / 矩形 / 球 / 圆柱 / 长方体）与空洞检测节点。
3. 阶段 4：RVC 相机接入（需真机 / 离线数据）。
4. 阶段 5：2D 视窗与深度学习。
5. 阶段 6：SDK 化与发布。
