# RvcVisionStudio

对标海康 VisionMaster 的拖拽式零代码流程编排软件，围绕 RVC 3D 结构光相机做点云采集与测量。

> 手动编译/启动/测试的分步操作指南见 **[docs/构建与测试指南.md](docs/构建与测试指南.md)**；
> 逐文件的代码地图（分层、调用链、改动定位）见 **[docs/源码结构说明.md](docs/源码结构说明.md)**。

**当前里程碑：M3 + UI 主题批次 — Foundation 设计系统主题（`src/ui/Theme.h/.cpp` 集中 token，
暗色优先 + 琥珀橙点缀，Geist/JetBrains Mono 内嵌字体，可扩展换肤）**

- 工具箱拖拽模块到画布、连线订阅数据（类型不符禁止连线）、点运行按拓扑序执行流程
- `core` 层不依赖 QWidget，可无头运行；画布（QtNodes）只是 `core::Process` 的 UI 投影
- 通用参数机制：模块构造时声明 `ParamDesc`，右侧「属性」Dock 选中节点自动生成编辑控件
- 交互式 3D 视窗：旋转/缩放/平移、重置视角、点大小、框选 ROI（写回选中模块的 ROI 参数）
- 多视窗：「窗口」菜单可增删/折叠 3D 视窗；Display3D 模块按 `viewport` 参数路由，视窗不存在自动创建
- ROI 是一等数据类型（RoiBox）：BoxRoi 模块导出 roi 端口，拟合/测量模块可选订阅；优先级：连线 roi > 模块自有 roiXxx 参数 > 不裁
- 运行异步化：worker 线程执行，运行中禁用运行按钮，日志/结果/视口均经 Qt 队列回 GUI 线程
- **单位约定：全工程内部与参数/结果显示一律为米（角度为度）**
- 待做：真机采集（M1）、撤销重做、运行中断（停止按钮）

## 自编译 VTK 9.2.2（带 Qt 支持）

PCL 1.13.0 捆绑的 VTK 9.2.2 **未编译 GUISupportQt**（无 `QVTKOpenGLNativeWidget`）。
为获得交互式 3D 视口，自编译**同版本** VTK 并开启 Qt 模块 —— DLL 同名 ABI 兼容，
PCL 预编译 DLL（pcl_visualization 等）运行时直接解析到我们部署的 VTK DLL：

```bat
:: 源码（GitHub 直连不稳时用镜像）
git clone --depth 1 --branch v9.2.2 https://ghfast.top/https://github.com/Kitware/VTK.git third_party/VTK-src

cmake -S third_party/VTK-src -B third_party/VTK-build -G "Visual Studio 18 2026" -A x64 ^
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON ^
  -DVTK_GROUP_ENABLE_Qt=YES -DVTK_QT_VERSION=6 ^
  -DCMAKE_PREFIX_PATH="D:/Qt/6.8.3/msvc2022_64" ^
  -DVTK_BUILD_TESTING=OFF -DVTK_BUILD_EXAMPLES=OFF ^
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 ^
  -DCMAKE_INSTALL_PREFIX=D:/RVC_SRC/RvcVisionStudio/third_party/VTK-install

cmake --build third_party/VTK-build --config Release --parallel 12
cmake --install third_party/VTK-build --config Release
```

> VS2026 兼容补丁：VTK 9.2.2 捆绑的 diy2/fmt（`ThirdParty/diy2/vtkdiy2/include/vtkdiy2/fmt/format.h`）
> 在 `_SECURE_SCL` 分支使用已被 VS2026 STL 移除的 `stdext::checked_array_iterator`，
> 已将该分支守卫改为 `defined(_SECURE_SCL) && _SECURE_SCL && (!defined(_MSC_VER) || _MSC_VER < 1940)`
> （本仓库 third_party/VTK-src 内已打补丁，重编只需直接 clone + build）。
> 另外 CMake 4.x 配置需 `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`（vtksys 的最低版本声明过旧）。
> 构建产出 147 个 Release DLL；已用 dumpbin 核对 pcl_visualization 等 PCL DLL 的
> 31 个直接 VTK 依赖在本安装中全部齐备。

主工程 CMake 在 `find_package(PCL)` 前将 `VTK_DIR` 指向 `third_party/VTK-install`，
PCLConfig 复用该 VTK；部署时拷贝我们的 VTK Release DLL（不再拷 PCL 3rdParty 的）。

## 模块清单（分类 / 名称 / 端口 / 参数）

| 分类 | 模块 | 输入 | 输出 | 参数 |
|---|---|---|---|---|
| 采集 | 加载PLY点云 | — | cloud | filePath（文件） |
| 预处理 | ROI裁剪 | cloud | cloud, **roi** | xmin/xmax/ymin/ymax/zmin/zmax（默认 ±1e9 不裁） |
| 预处理 | 体素降采样 | cloud | cloud | leafSize（默认 0.002） |
| 预处理 | 统计去噪 | cloud | cloud | meanK(50)、stddevMul(1.0) |
| 拟合 | 平面拟合 | cloud, **roi(可选)** | plane, inliers | distanceThreshold(0.005)、maxIterations(1000)、roiEnabled+roiXxx |
| 拟合 | 直线拟合 | cloud, **roi(可选)** | line, inliers | distanceThreshold、maxIterations、roiEnabled+roiXxx |
| 拟合 | 圆拟合 | cloud, **roi(可选)** | circle, inliers | distanceThreshold、maxIterations(10000)、radiusMin/Max、roiEnabled+roiXxx |
| 测量 | 点面距离 | cloud, plane, **roi(可选)** | mean, max | roiEnabled+roiXxx |
| 测量 | 面面夹角/间距 | planeA, planeB | angle, distance（夹角<阈值才输出） | parallelAngleDeg(5) |
| 测量 | 包围盒尺寸 | cloud, **roi(可选)** | sizeX, sizeY, sizeZ | roiEnabled+roiXxx |
| 测量 | 圆直径 | circle | diameter | — |
| 显示 | 3D显示 | cloud + plane/line/circle（可选） | — | **viewport（目标视窗名，默认"主视窗"）** |
| IO | 保存PLY点云 | cloud | — | filePath（中文路径自动走 ASCII 临时文件规避） |

数据类型：PointCloud / **Roi** / Plane / Line / Circle / Pose / Scalar / String（Image 占位）。
ROI 生效优先级：**连线 roi 端口 > 模块自有 roiXxx 参数（roiEnabled=true）> 不裁剪**。
拟合失败条件：内点 < 50 或 < 输入点数 3%。3D显示叠加：平面=黄色网格、直线=青色延长线、圆=品红圆环+圆心球；框选 ROI 显示为绿色线框。

## 目录结构

```
RvcVisionStudio/
├── CMakeLists.txt          # AUTOMOC/RCC/UIC；Qt6/PCL/RVC；VTK_DIR 指向自编译 VTK；x64 检查
├── cmake/FindRVC.cmake     # 定位 RVC SDK，导出 RVC::RVC + rvc_copy_runtime_dlls()
├── third_party/
│   ├── nodeeditor/         # QtNodes v3.0.9（commit 0a3a9318，BSD-3）
│   ├── Catch2/             # Catch2 v3.9.1
│   ├── VTK-src/            # VTK v9.2.2 源码（浅克隆，.gitignore 排除）
│   ├── VTK-build/          # VTK 构建目录（.gitignore 排除）
│   └── VTK-install/        # VTK 安装目录（.gitignore 排除，主工程 VTK_DIR 指向这里）
├── src/
│   ├── core/               # ★ 核心层：无 QWidget/VTK-GUI 依赖，可无头运行
│   │   ├── DataTypes.h         # 端口类型：PointCloud/RoiBox/Plane3D/Line3D/Circle3D/Pose/Scalar/String
│   │   ├── ModuleBase.h        # 模块基类 + ModuleContext + ParamDesc 参数机制
│   │   ├── ModuleRegistry.h    # 模块注册表（工厂 + 按类别枚举 → 工具箱数据源）
│   │   ├── Process.h/.cpp      # 模块有向图：连线校验（类型/单订阅/成环）、拓扑排序、输出缓存
│   │   ├── Solution.h/.cpp     # 方案：持有 Process，QJsonObject 保存/加载
│   │   └── Engine.h/.cpp       # runOnce：同步拓扑执行（Qt-free，支持进度回调）
│   ├── camera/RvcCamera.*      # RVC SDK 封装骨架（SystemInit RAII、设备枚举、PointMap→PCL）
│   ├── modules/                # acquisition/preprocess/fit/measure/io/display（CloudUtils 共享 ROI 逻辑）
│   └── ui/
│       ├── MainWindow.*        # 全 Dock 布局 + 窗口菜单（Dock 折叠/添加3D视窗）+ 异步运行
│       ├── FlowModel.*         # QtNodes v3 AbstractGraphModel ↔ core::Process 双向同步
│       ├── FlowView.*          # 画布视图（接收工具箱拖放）
│       ├── Toolbox.*           # 分类列表 + 拖拽
│       ├── PropertyPanel.*     # 按 ParamDesc 自动生成参数编辑控件
│       ├── Viewport3D.*        # QVTKOpenGLNativeWidget 交互视口 + 框选ROI（RubberBandPick）
│       ├── ViewportManager.*   # 多视窗 Dock 管理 + 按名路由显示回调
│       └── EngineRunner.*      # Engine 异步封装（QThread worker + QueuedConnection）
│   └── app/main.cpp            # --selftest / --smoke / --demo / --autoquit
└── tests/test_core.cpp     # Catch2：core + 合成点云数值断言 + ROI 联动裁剪
```

## 环境依赖（本机已核实路径）

| 依赖 | 版本 | 路径 |
|---|---|---|
| Qt | 6.8.3 (msvc2022_64) | `D:\Qt\6.8.3\msvc2022_64` |
| PCL | 1.13.0 | `D:\Program Files\PCL 1.13.0` |
| VTK（自编译） | 9.2.2 + GUISupportQt | `third_party\VTK-install` |
| RVC SDK | v1.15 | `D:\Program Files\RVBUST\RVC\RVCSDK` |
| 编译器 | VS Community 2026 | `D:\Program Files\Microsoft Visual Studio\18\Community` |
| CMake | 4.2.3 | PATH |

## 构建

```bat
cd /d D:\RVC_SRC\RvcVisionStudio
cmake -B build -G "Visual Studio 18 2026" -A x64 -DCMAKE_PREFIX_PATH="D:/Qt/6.8.3/msvc2022_64"
cmake --build build --config Release
```

- 需先完成上方 VTK 自编译（找不到 `third_party/VTK-install` 会配置失败）
- 可选覆盖：`-DRVC_SDK_ROOT=<RVC SDK 路径>`、`-DRVC_TEST_PLY=<测试用 PLY 路径>`
- 构建后自动部署运行时 DLL：RVC runtime、自编译 VTK Release DLL、PCL/OpenNI2 DLL、
  QtNodes.dll、Qt DLL（windeployqt --release）

## 测试

```bat
cd build
ctest -C Release --output-on-failure
```

22 个用例：拓扑排序、环/类型拒绝、JSON 往返、真实 PLY 加载、合成点云拟合数值断言
（平面/直线/圆）、ROI 精确点数、点面距、面面夹角与平行间距、包围盒、可选端口、
参数机制、RoiBox 导出端口、ROI 连线/自有参数/优先级/干扰面剔除。

## 运行

```bat
:: GUI（N 秒后自动退出可用于自动化冒烟）
build\Release\RvcVisionStudio.exe [--autoquit N]

:: GUI 演示链路：加载PLY→ROI裁剪→降采样→平面拟合(订阅ROI)→3D显示(叠加平面)+点面距
build\Release\RvcVisionStudio.exe --demo "D:\Kimi_WorkSpace\Test\captured_data\offline_visualize.ply" [--autoquit N]

:: 无头自测（M0 链路回归）：LoadPLY → Display3D 回调计数断言，退出码 0/1
build\Release\RvcVisionStudio.exe --selftest "<ply路径>"

:: 无头冒烟（测量流水线）：LoadPLY → ROI → 降采样 → 平面拟合 → 点面距，退出码 0/1
build\Release\RvcVisionStudio.exe --smoke "<ply路径>"
```

GUI 用法要点：
- 「窗口」菜单：勾选控制各 Dock 显示/折叠；「添加3D视窗」新建视窗（Display3D 模块的
  viewport 参数填视窗名即路由到对应视窗，名字不存在会自动创建）
- 视窗工具条：重置视角 / 框选ROI（拖矩形后，框内点包围盒写回画布当前选中模块的
  ROI 参数：选中「ROI裁剪」写 xmin..zmax；选中拟合/测量写 roiXxx 并置 roiEnabled）
  / 点大小
- 运行期间「运行」按钮禁用，日志逐模块推送（含耗时），Scalar 结果在「结果」tab

## RVC SDK 已知陷阱（已写入 `src/camera/RvcCamera.h` 注释）

1. 修改 CaptureOptions 前必须先 `LoadCaptureOptions`，否则设置不生效
2. SDK 不阻止同一相机多次 Open —— 应用层按 SN 查重（`RvcCamera` 已预留登记表）
3. PointMap 内存数据单位是**米**（double 行主序 x,y,z 连续），Save 存盘才选米/毫米
4. SaveImage / PointMap::Save 不支持中文路径（SavePlyModule 已做同款规避）
