# MultiCameraCalibration

N 相机固定外参标定与点云融合系统。从成熟的双相机项目
[DualCameraFusion](../DualCameraFusion)（4258 行单文件）抽取核心算法，
按 N 相机架构重组。DualCameraFusion 保持不动，本项目为全新工程。

## 功能特性

- **N 相机支持**：任意数量相机统一管理（`camera_id` 字符串键），
  软触发同步/异步拍摄，卡片式 2D 预览网格自适应布局
- **星型拓扑标定**：单块编码圆标定板全共视，所有非参考相机分别对标参考相机
- **链式拓扑（BFS）**：相邻相机两两共视时，`pose_graph` 自动 BFS 复合变换链
- **编码圆 2D+3D 检测**：RVC `DetectCodedCircleMarker` + PLY 像素级 3D 提取
- **RANSAC 鲁棒标定**：SVD Kabsch 求解 + 内点 refine，逐点误差详情
- **多帧平均标定**：四元数半球统一平均（已修复 q/-q 符号歧义 bug）+ 平移平均
- **标定质量评分**：RMS / 内点率 → 优 / 良 / 合格 / 差 四级评分
- **点云拼接与后处理**：N 路点云合并到参考坐标系，支持裁切（AABB/球/OBB）、
  体素下采样、统计离群点去除
- **离线会话**：拍摄帧落盘 → 重新加载 → 批量检测 → 批量标定 → 批量拼接，
  全流程可脱离相机重放
- **单相机多站位模式**：只有 1 台相机时，移动到不同站位各拍一帧，
  每个站位注册为虚拟相机（`station_N`）参与标定拼接；拍摄后立即存盘
  （防止 RVC 句柄被后续拍摄覆盖），物理相机取景卡片固定网格第一位
- **标定结果导入导出**：JSON 保存/加载全部 pair 外参
- **无 SDK 优雅降级**：PyRVC 全部延迟导入，无相机/无 SDK 环境可离线开发与测试

## 快速开始

```bash
# conda rvc 环境（Python 3.10），依赖见 requirements.txt
pip install PySide6 numpy opencv-python open3d scipy PyOpenGL
# PyRVC 需从 RVC SDK 安装：D:\Program Files\RVBUST\RVC\RVCSDK\Python

python main.py              # 启动 UI
python test_core.py         # core 模块测试（9 组，无需相机/GUI）
python test_ui.py           # UI 测试（6 组，offscreen）
python test_integration.py  # 端到端集成测试（10 步，offscreen + 合成数据）
python test_station.py      # 单相机多站位模式测试（6 组，offscreen + 合成数据）
```

## 使用指南

### 在线流程

1. **相机连接**：左面板「查找设备」→ 多选 →「添加选中相机」，中央网格生成预览卡片
2. **拍摄**：编码圆标定板放入所有相机共视区 →「拍摄所有相机（同步软触发）」
3. **检测**：标定 Tab「检测标记」，提取编码圆 2D+3D 坐标并叠加显示
4. **标定**：选择参考相机 →「标定所有 pair」；可多次拍摄「累积当前帧」后
   「多帧标定」提高精度
5. **拼接**：拼接 Tab「拼接当前帧」，3D 查看器查看合并结果；
   可配置裁切/下采样/滤波后处理，「拼接并保存 PLY」导出
6. **保存标定**：标定 Tab「保存标定」导出 JSON，下次可直接「加载标定」

### 单相机多站位流程（左面板「📍 单相机站位」Tab）

只有 1 台相机时，把相机移动到不同站位各拍一帧，每个站位视为一台
虚拟相机（`station_1`、`station_2` ...）参与标定与拼接：

1. **连接相机**：站位 Tab「查找设备」→ 选中 →「连接」，
   中央网格第一位出现「当前相机（取景）」卡片（实时取景辅助移动站位）
2. **逐站位拍摄**：标定板放入视野 → 移动相机到站位 1 →「拍摄站位」，
   帧立即存盘并在网格新增「站位 1」卡片；移动到下一站位重复
3. **检测**：标定 Tab「检测标记」，各站位卡片叠加编码圆
4. **标定**：参考相机默认站位 1 →「标定所有 pair」（星型拓扑）；
   站位管理（删除/清空/新会话）在站位 Tab 的站位列表操作
5. **拼接**：拼接 Tab「拼接当前帧」，各站位点云合并到站位 1 坐标系
6. **保存标定**：与多相机模式相同，JSON 导出/加载

站位帧目录结构（拍摄后立即存盘，物理相机继续拍摄不会覆盖已拍站位）：

```
offline_data/stations/session_YYYYMMDD_HHMMSS/
    meta.json                      # 会话级：created / stations / updated
    station_1/
        station_1.png  station_1.ply  meta.json
    station_2/ ...
```

**两种标定/扫描流程的注意事项**：

- **标记常驻**：编码圆标定板（或固定在场景中的编码圆标记）在标定和
  后续扫描拼接时都保持在各站位共视区内。标定与扫描可用同一批站位帧，
  流程最简单；适合标记可长期固定的场合。
- **标定板可撤**：标定阶段各站位拍标定板完成外参求解后，撤掉标定板，
  重新逐站位拍摄被测物体，用已保存的标定结果（「保存标定」JSON）
  直接拼接。注意：撤板后到扫描前**不可再移动任何站位**，否则外参失效；
  站位移动后需重新标定。

无论哪种流程，站位之间移动相机时**场景与标定板必须保持静止**；
站位模式同样遵循星型标定的单标定板全共视假设（或链式拓扑下相邻
站位两两共视，`pose_graph` 自动 BFS 复合）。

### 离线会话流程

1. 拍摄后点左面板「📥 保存当前帧到会话」（首次自动创建
   `offline_data/session_时间戳/`）；重复拍摄-保存可累积多拍
2. 「📂 加载会话」选择会话目录，各相机最新帧自动加载到预览
3. 「🔎 批量检测标记」→「📐 批量标定会话」（多帧平均）
4. 拼接 Tab「🗂 批量拼接会话」，全部帧对合并到参考坐标系

会话目录结构：

```
offline_data/session_YYYYMMDD_HHMMSS/
    meta.json                  # 会话级：created / camera_ids / frame_count
    frame_0001/
        cam0.png  cam0.ply     # 各相机图像 + 点云（mm）
        cam1.png  cam1.ply
        meta.json              # 帧级：{"frame_id", "cameras": {cam: {markers, ...}}}
    frame_0002/ ...
```

## 架构

```
┌─────────────────────────────────────────────────────┐
│ ui/  (PySide6)                                      │
│   main_window        三栏装配 + 信号转发 + 业务逻辑   │
│   camera_card        相机预览卡片                    │
│   viewer_3d          嵌入式 3D 点云查看器             │
│   panels/            相机 / 站位 / 标定 / 拼接 面板   │
├─────────────────────────────────────────────────────┤
│ core/  (与 UI 完全解耦，不 import PySide6)           │
│   camera_manager        N 相机管理（软触发）          │
│   frame_data            帧数据（在线/离线双模式）     │
│   marker_detector       编码圆 2D 检测 + 3D 提取      │
│   calibration_engine    N 相机外参标定（星型）        │
│   pose_graph            链式拓扑 BFS + 全局优化预留   │
│   stitch_engine         N 相机点云拼接引擎            │
│   point_cloud_processor 点云裁切/下采样/滤波          │
│   offline_session       离线会话（批量检测/标定/拼接）│
│   station_manager       单相机多站位（拍后立即存盘）  │
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
| 1 | core 模块抽取与 N 相机重组、星型标定、test_core（9 组） | ✅ 完成 |
| 2 | 链式拓扑 pose_graph BFS、StitchEngine N 路拼接 | ✅ 完成 |
| 3 | PySide6 UI（连接/拍摄/标定/拼接预览）、test_ui（6 组） | ✅ 完成 |
| 4 | 离线会话、UI 离线集成、test_integration（10 步）、文档 | ✅ 完成 |
| 5 | 单相机多站位模式（StationManager + 站位面板）、test_station（6 组） | ✅ 完成 |

后续扩展方向：

- 全局位姿图优化（`pose_graph.optimize_global` 目前为 BFS 生成树，
  可换 g2o/Ceres 式 BA）
- 硬触发同步（多相机硬件级同步拍摄）
- 标定报告导出（PDF/HTML，含逐点误差图表）
- 手眼标定（相机-机械臂）

## 已知限制

- **硬触发未实现**：目前为软触发同步，多相机拍摄存在毫秒级时间差
- **全局 BA 未实现**：链式拓扑仅 BFS 最短路径复合，无全局误差均衡，
  长链累积误差随链长增长
- **链式拓扑无优化**：`optimize_global` 为 BFS 生成树占位实现
- **检测依赖 SDK**：编码圆检测需 PyRVC；无 SDK 环境仅可走合成数据测试
- **单标定板假设**：星型标定假设所有相机同时看到同一块编码圆板

## 环境

- conda 环境 `rvc`（Python 3.10.20）：`D:\Program Files\Anaconda\envs\rvc\python.exe`
- RVC SDK：`D:\Program Files\RVBUST\RVC\RVCSDK\Python`（PyRVC）
- 依赖见 `requirements.txt`
