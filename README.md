# MultiCameraCalibration

N 相机固定外参标定与点云融合系统。从成熟的双相机项目
[DualCameraFusion](../DualCameraFusion)（4258 行单文件）抽取核心算法，
按 N 相机架构重组，并持续扩展为 **RVC 拼接工作站**：
多相机外参标定（A）、单相机移动链式拼接（B）、转台 360° 拼接（C）、
离线拼接重放（D，原型 UI 并入主程序）、机器人手眼配合拼接（E，core 已落地）。
DualCameraFusion 保持不动，本项目为全新工程。

当前版本：`v1.1.2+g<hash>`（运行时自动附加 Git commit 短 hash）。
版本变更详见 [`CHANGELOG.md`](CHANGELOG.md)。

## 功能特性

- **N 相机支持**：任意数量相机统一管理（`camera_id` 字符串键），
  软触发同步/异步拍摄，卡片式 2D 预览网格自适应布局
- **UI v2 重构**：`src/ui_v2/` 提供 LauncherDialog 模式选择 + 工作区 +
  浮动日志/3D 查看器/评估卡片等现代化组件，逐步替代旧版 `src/ui/`
- **星型拓扑标定**：单块编码圆标定板全共视，所有非参考相机分别对标参考相机
- **链式拓扑（BFS）**：相邻相机两两共视时，`pose_graph` 自动 BFS 复合变换链
- **编码圆 2D+3D 检测**：RVC `DetectCodedCircleMarker` + PLY 像素级 3D 提取
- **编码圆标定板生成器**：支持扇区数、半径比、整体缩放、页面尺寸、打印 DPI 调节，
  导出 PDF/PNG，预览与导出严格一致
- **非对称圆标定板检测**：OpenCV `findCirclesGrid` + 位姿估计，自动估计板间距、
  兼容 180° 旋转等排列歧义
- **RANSAC 鲁棒标定**：SVD Kabsch 求解 + 内点 refine，逐点误差详情
- **多帧平均标定**：四元数半球统一平均（已修复 q/-q 符号歧义 bug）+ 平移平均
- **标定质量评分**：RMS / 内点率 → 优 / 良 / 合格 / 差 四级评分
- **点云拼接**：N 路点云合并到参考坐标系，支持按站位/高度着色；
  后处理（裁切 AABB/球/OBB、体素下采样、统计离群点去除）core 已具备，
  将在后续版本中通过独立页面提供 UI 入口
- **离线会话**：拍摄帧落盘 → 重新加载 → 批量检测 → 批量标定 → 批量拼接，
  全流程可脱离相机重放
- **单相机移动链式拼接**：只有 1 台相机时，移动到不同站位各拍一帧，
  每个站位注册为虚拟相机（`station_N`）参与自动配准与拼接；拍摄后立即存盘
  （防止 RVC 句柄被后续拍摄覆盖），支持离线加载会话目录重放拼接
- **转台 360° 拼接**：作为独立模式并入主程序，支持转台场景多视角扫描拼接
- **离线拼接重放（模式 D，原型 UI 并入主程序）**：
  `prototypes/offline_stitch/` 提供完整测试 UI，可选择本地图像/点云文件夹，
  自动检测编码圆并拼接导出
- **机器人手眼标定配合拼接（模式 E，core 已落地）**：
  `src/core/handeye.py` + `robot_interface.py` + `robot_stitch_workflow.py`，
  用机器人位姿 + 手眼标定结果直接变换点云，无需标记物；UI 尚未接线
- **标定结果导入导出**：JSON 保存/加载全部 pair 外参
- **版本号自动跟踪**：`src/version.py` 运行时自动附加 Git commit 短 hash
- **无 SDK 优雅降级**：PyRVC 全部延迟导入，无相机/无 SDK 环境可离线开发与测试

## 快速开始

```bash
# conda rvc 环境（Python 3.10），依赖见 requirements.txt
pip install -r requirements.txt
# PyRVC 需从 RVC SDK 安装：D:\Program Files\RVBUST\RVC\RVCSDK\Python

python main.py                     # 启动 UI（默认进入 LauncherDialog 模式选择）
python test_core.py                # core 模块测试（无需相机/GUI）
python test_ui.py                  # UI 测试（offscreen）
python test_integration.py         # 端到端集成测试（offscreen + 合成数据）
python test_station.py             # 单相机多站位模式测试（offscreen + 合成数据）
python test_chain_stitcher.py      # 链式拓扑与 N 路拼接测试
python test_handeye.py             # 手眼标定求解测试（合成数据）
python test_robot_stitch.py        # 机器人拼接工作流测试（mock 机器人）
python test_generate_coded_circle.py  # 编码圆标定板生成器测试
python prototypes/offline_stitch/tests/test_offline_stitch.py  # 离线拼接测试
```

## 使用指南

### 模式 A：多相机外参标定拼接

1. **相机连接**：LauncherDialog 选择「多相机外参标定拼接」→「查找设备」→
   多选 →「添加选中相机」，中央网格生成预览卡片
2. **拍摄**：编码圆标定板放入所有相机共视区 →「拍摄所有相机（同步软触发）」
3. **检测**：标定步骤「检测标记」，提取编码圆 2D+3D 坐标并叠加显示
4. **标定**：选择参考相机 →「标定所有 pair」；可多次拍摄「累积当前帧」后
   「多帧标定」提高精度
5. **拼接**：拼接步骤「拼接当前帧」，3D 查看器查看合并结果；
   「拼接并保存 PLY」导出（后处理配置页面后续独立提供）
6. **保存标定**：标定步骤「保存标定」导出 JSON，下次可直接「加载标定」

### 模式 B：单相机移动链式拼接

只有 1 台相机时，把相机移动到不同站位各拍一帧，每个站位视为一台
虚拟相机（`station_1`、`station_2` ...）参与自动配准与拼接：

1. **连接相机**：LauncherDialog 选择「单相机移动链式拼接」→「查找设备」→
   选中 →「连接相机」
2. **开始取景**：点击「开始取景」查看实时画面
3. **拍摄机位**：标定板放入视野 → 移动相机到站位 1 →「拍摄机位」，
   自动检测标记物、评估重合度，通过后方加入拼接链；失败则提示重拍
4. **继续移动**：重复拍摄机位，系统实时增量拼接并在 3D 区显示合并结果
5. **闭环优化**：当新帧与早期机位产生足够共视时，可执行全局优化消除累积漂移
6. **保存**：点击「保存拼接数据」导出合并点云 `merged.ply` 与误差报告 `error_report.json`

**离线加载会话**：点击「离线加载会话」，选择一个已保存的 `session_*` 文件夹，
系统会自动读取 `station_N/station_N.png + station_N.ply` 并按顺序拼接。

站位帧目录结构：

```
offline_data/stations/session_YYYYMMDD_HHMMSS/
    meta.json                      # 会话级：created / stations / updated
    station_1/
        station_1.png  station_1.ply  meta.json
    station_2/ ...
```

### 模式 C：转台 360° 拼接

相机固定，物体放在转台上旋转拍摄，适用于小型物体 360° 扫描：

1. **连接相机**：LauncherDialog 选择「转台 360° 拼接」→ 连接相机
2. **设置转台参数**：输入旋转步数、起始角度等
3. **开始扫描**：系统自动按设定步数旋转并拍摄
4. **拼接**：所有角度帧按转台角度或标记物配准，合并为完整 360° 点云
5. **保存**：导出合并点云与转台元数据

### 模式 D：离线拼接（原型 UI 并入主程序）

不连相机，直接加载本地图像/点云文件夹做检测→标定→拼接→导出。

- 主程序入口：LauncherDialog 或顶部工具栏「打开会话」可加载离线数据
- 独立测试 UI：`prototypes/offline_stitch/app/simple_ui.py`，支持：
  - 选择本地图像/点云文件夹（递归/模糊匹配文件对）
  - 输入编码圆参数以确保正确识别
  - 自动检测、配准、合并
  - 缓存合并结果，切换单个文件对后仍可恢复显示
  - 显示级下采样，大数据量渲染不卡

适合产线离线复盘、现场数据带回办公室处理、演示。

### 模式 E：机器人手眼配合拼接（core 已落地，UI 未接线）

相机配合工业机器人做多视角扫描拼接：
用机器人位姿 + 手眼标定结果直接给出每帧变换，**不依赖标记物**。
核心模块 `src/core/handeye.py`、`robot_interface.py`、`robot_stitch_workflow.py`
已提供求解、抽象接口与 mock 端到端测试，UI 卡片与 bridge 接线待补充。

## 目录结构

```
MultiCameraCalibration/
├── main.py                         # 启动入口（LauncherDialog → 模式工作区）
├── CHANGELOG.md                    # 版本更新日志
├── requirements.txt                # 核心依赖（PyPI 可装）
├── src/
│   ├── core/                       # 与 UI 完全解耦的业务核心
│   │   ├── camera_manager.py       # N 相机管理（软触发）
│   │   ├── frame_data.py           # 帧数据（在线/离线双模式）
│   │   ├── marker_detector.py      # 编码圆 / 非对称圆标定板 2D+3D 检测
│   │   ├── calib_board_detector.py # 非对称圆标定板检测 + 位姿估计
│   │   ├── calibration_engine.py   # N 相机外参标定（星型）
│   │   ├── pose_graph.py           # 链式拓扑 BFS + 全局优化预留
│   │   ├── chain_stitcher.py       # 链式/增量点云拼接
│   │   ├── stitch_engine.py        # N 相机点云拼接引擎
│   │   ├── point_cloud_processor.py# 点云裁切/下采样/滤波
│   │   ├── offline_session.py      # 离线会话（批量检测/标定/拼接）
│   │   ├── station_manager.py      # 单相机多站位（拍后立即存盘）
│   │   ├── handeye.py              # 手眼标定求解 + JSON（模式 E）
│   │   ├── robot_interface.py      # 机器人抽象接口 + MockRobot（模式 E）
│   │   ├── robot_stitch_workflow.py# 机器人扫描站位队列 + 拼接（模式 E）
│   │   ├── mobile_chain_workflow.py# 单相机移动链式拼接工作流
│   │   ├── fixed_multi_cam_workflow.py # 多相机外参标定工作流
│   │   └── utils.py                # 日志 + 安全资源释放
│   ├── ui/                         # 旧版 PySide6 UI（逐步迁移中）
│   │   ├── main_window.py
│   │   ├── camera_card.py
│   │   ├── viewer_3d.py
│   │   └── panels/
│   ├── ui_v2/                      # 新版 UI（LauncherDialog + 工作区）
│   │   ├── launcher_dialog.py
│   │   ├── main_window.py
│   │   ├── backend_bridge.py
│   │   ├── theme.py
│   │   ├── icons.py
│   │   ├── widgets/                # camera_grid、viewer_panel、log_panel 等
│   │   └── workspaces/             # multi_cam / mobile_chain / turntable
│   └── version.py                  # 版本号管理（自动附加 Git commit hash）
├── prototypes/                     # 独立原型，不污染主代码
│   ├── coded_circle_ui/            # 编码圆标定板生成器原型
│   ├── offline_stitch/             # 离线拼接原型（已并入主程序，保留验证）
│   └── turntable_360_stitch/       # 转台 360° 拼接实验
├── docs/                           # 设计/审查/规划文档
└── test_*.py                       # 回归测试
```

## 架构

```
┌─────────────────────────────────────────────────────┐
│ ui_v2/  (PySide6)                                       │
│   launcher_dialog    模式选择卡片（A/B/C/D/E）          │
│   main_window        工作区容器 + 模式分发              │
│   backend_bridge     UI 信号 ↔ core 业务线程桥接        │
│   widgets/           camera_grid、viewer_panel 等        │
│   workspaces/        multi_cam / mobile_chain / turntable│
├─────────────────────────────────────────────────────┤
│ ui/  (PySide6，旧版，逐步迁移)                       │
├─────────────────────────────────────────────────────┤
│ core/  (与 UI 完全解耦，不 import PySide6)           │
│   camera_manager        N 相机管理（软触发）          │
│   frame_data            帧数据（在线/离线双模式）     │
│   marker_detector       编码圆 / 标定板 2D+3D 检测    │
│   calibration_engine    N 相机外参标定（星型）        │
│   pose_graph            链式拓扑 BFS + 全局优化预留   │
│   chain_stitcher        链式/增量拼接                 │
│   stitch_engine         N 相机点云拼接引擎            │
│   point_cloud_processor 点云裁切/下采样/滤波          │
│   offline_session       离线会话（批量检测/标定/拼接）│
│   station_manager       单相机多站位（拍后立即存盘）  │
│   handeye.py            手眼标定求解（模式 E）        │
│   robot_interface.py    机器人抽象接口（模式 E）      │
│   robot_stitch_workflow 机器人扫描拼接（模式 E）      │
│   utils                 日志 + 安全资源释放           │
├─────────────────────────────────────────────────────┤
│ PyRVC SDK / Open3D / NumPy / SciPy / OpenCV         │
└─────────────────────────────────────────────────────┘
```

### N 相机数据模型

- `CameraManager._cameras: Dict[str, SingleCameraController]` —— 以
  camera_id（任意字符串）为键管理任意数量相机。
- `CalibrationEngine.pair_results: Dict[(ref_id, cam_id), result]` ——
  每条标定结果存一对相机的外参，`result['T']` 为 **cam→ref** 的 4x4
  变换（`p_ref = T @ p_cam`，即 `pts_ref ≈ pts_cam @ R.T + t`）。
- `OfflineSession.frames: Dict[str, List[FrameData]]` —— 会话帧按
  camera_id 分组、frame_id 对齐（同一次拍摄的所有相机共享 frame_XXXX/ 目录）。

### 标定拓扑

**星型拓扑**：单块标定板全共视，每台非参考相机分别对标参考相机；
`get_transform(from, to)` 直达 pair 直接返回，反向 pair 求逆。

```
        ref
       / | \
      A  B  C ...
```

**链式拓扑**：相邻相机两两共视（如环绕式布局）。`get_transform`
找不到直达 pair 时自动委托 `pose_graph.find_path_transform`（BFS
变换链复合，经 ref 中转或相邻链逐级复合）。

## 开发计划

| Phase | 内容 | 状态 |
|---|---|---|
| 1 | core 模块抽取与 N 相机重组、星型标定、test_core | ✅ 完成 |
| 2 | 链式拓扑 pose_graph BFS、StitchEngine N 路拼接 | ✅ 完成 |
| 3 | PySide6 UI（连接/拍摄/标定/拼接预览）、test_ui | ✅ 完成 |
| 4 | 离线会话、UI 离线集成、test_integration、文档 | ✅ 完成 |
| 5 | 单相机多站位模式（StationManager + 站位面板）、test_station | ✅ 完成 |
| 6 | UI v2 重构（LauncherDialog + 工作区 + 浮动面板） | ✅ 完成 |
| 7 | 转台 360° 拼接（模式 C）并入主程序 | ✅ 完成 |
| 8 | 离线拼接：不连相机重放会话数据（prototypes/offline_stitch 保留验证） | ✅ 完成 |
| 9 | 编码圆标定板生成器 | ✅ 完成 |
| 10 | 机器人手眼配合拼接（模式 E）：手眼标定 + 机器人扫描 | 🚧 core 已落地，UI 未接线 |

后续扩展方向：

- 全局位姿图优化（`pose_graph.optimize_global` 目前为 BFS 生成树，
  可换 g2o/Ceres 式 BA）
- 硬触发同步（多相机硬件级同步拍摄）
- 标定报告导出（PDF/HTML，含逐点误差图表）
- 模式 E 的 UI 接线与真机联调

## 已知限制

- **硬触发未实现**：目前为软触发同步，多相机拍摄存在毫秒级时间差
- **全局 BA 已提供接口**：`pose_graph.optimize_global_ba` 已实现，移动链式模式
  已提供闭环全局优化入口；默认仍使用 BFS 生成树以兼顾速度
- **模式 E UI 未接线**：手眼标定与机器人扫描的 core 已落地，但 LauncherDialog
  无入口、backend_bridge 无信号接线
- **检测依赖 SDK**：编码圆检测需 PyRVC；无 SDK 环境仅可走合成数据测试
- **单标定板假设**：星型标定假设所有相机同时看到同一块编码圆板

## 版本与变更日志

- 版本号规则：`v1.0.x` 小修复、`v1.x.0` 中等规模、`v2.0.0` 大型重构/功能
- 运行时版本号自动附加 Git commit 短 hash：`v1.1.2+g<hash>`
- 完整版本变更记录见 [`CHANGELOG.md`](CHANGELOG.md)

## 环境

- conda 环境 `rvc`（Python 3.10.20）：`D:\Program Files\Anaconda\envs\rvc\python.exe`
- RVC SDK：`D:\Program Files\RVBUST\RVC\RVCSDK\Python`（PyRVC）
- 依赖见 `requirements.txt`
