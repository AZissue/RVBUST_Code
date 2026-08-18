# ui_v2 重构对照文档

> 日期：2026-08-06
> 目的：下午按 `src/ui_v2` 空壳重构主 UI 时的快速参考
> 关键：**ui_v2 是纯 UI 空壳，所有业务逻辑通过 Qt 信号接入现有 core 模块**

---

## 一、ui_v2 整体结构（一句话总览）

```
[LauncherDialog 启动小窗] ──连接成功──▶ [MainWindowShell 主窗口]
  · 模式卡片 A/B 分流                    · 顶部功能栏（设备管理/模式/会话/后处理/日志/帮助）
  · 设备搜索/自动IP/多选表格             · QStackedWidget 双工作区（互不干扰）
  · 数量规则门控（A≥2台 / B=1台）        · 底部状态栏 + 右侧日志 dock（默认隐藏）
```

**运行空壳预览**：
```bash
python src/ui_v2/run_shell.py   # mock 数据演示完整交互，可离线跑
```

### 目录结构

```
src/ui_v2/
├── theme.py                    # 设计 token（深色工业风 + RVC 红 #E53935）+ 全局 QSS
├── launcher_dialog.py          # 启动小窗（模式卡片 + 设备管理 + 数量门控）
├── main_window.py              # MainWindowShell：功能栏 + 双工作区 + 状态栏 + 日志 dock
├── run_shell.py                # 离线演示入口（mock 后端）
├── widgets/                    # 通用控件
│   ├── step_bar.py             # 步骤条（pending/current/done/disabled 四态）
│   ├── loading_overlay.py      # 加载遮罩
│   ├── mode_card.py            # 模式选择卡片
│   ├── device_table.py         # 设备多选表格（DeviceInfo 数据结构）
│   ├── camera_grid.py          # 相机取景网格（标记数/共视/帧分区角标）
│   ├── viewer_panel.py         # 3D 查看器占位（接口对齐 EmbeddedPointCloudViewer）
│   ├── station_timeline.py     # 机位时间线（模式 B 核心）
│   ├── evaluation_card.py      # 评估卡片（🟢/🟡/🔴 三色）
│   ├── live_view_panel.py      # 实时取景（检测叠加接口）
│   └── log_panel.py            # 日志面板
└── workspaces/                 # 两个工作区（核心）
    ├── multi_cam_workspace.py    # 模式 A：步骤条 + 三栏 + 状态机门控
    └── mobile_chain_workspace.py # 模式 B：时间线 + 取景/3D + 评估 + 状态机门控
```

---

## 二、核心设计点（与当前 UI 的本质差异）

### 模式 A（多相机外参标定）`MultiCamWorkspace`

- **状态机驱动 UI 门控**：`idle → connected → captured → detected → calibrated → locked`
  - 每个状态决定哪些按钮可用（`set_state()` 一处集中控制）
  - 质量门禁：标定不达标时扫描按钮置灰
- **步骤条**：连接相机→拍摄标定→检测标记→计算外参→扫描拼接→保存
- **左面板**只读设备列表 + 拍摄控制（同步/异步单选 + 拍摄 + 参考相机下拉）
- **中央**相机网格（卡片带标记数角标 + 共视状态 + 帧分区标签「标定帧/扫描帧」）+ 3D 预览
- **右面板**两个 Tab：标定（检测/结果表/质量评分/外参存取）+ 扫描（撤板横幅/扫描控制/批量拍摄）

### 模式 B（单相机移动链式）`MobileChainWorkspace`

- **无手动「检测」按钮**：拍摄 → 自动检测→匹配→评估→入链，全流程工作流驱动
- **左：机位时间线**（每节点显示重合度/误差/三色状态，失败节点内嵌重拍按钮）
- **中央**：上实时取景（检测叠加：绿框编码圆 + 共有标记蓝圈引导）/ 下 3D 实时拼接
- **底部**：评估卡片（🟢继续/🟡谨慎/🔴重拍）+ 操作按钮 + 常驻统计行
  - `已接 N 机位 | 累计误差 | 平均单步误差`（超阈值变红建议全局优化）
- **术语隔离**：UI 只有「机位/重合度/链/误差」，无标定术语

### 主窗口 `MainWindowShell`

- 顶部功能栏：⚙设备管理（回小窗改模式/换设备）/ 模式▾ / 💾保存会话 / 📂打开会话 / 🧹后处理 / 📋日志 / ❓帮助
- 日志改为**右侧 dock**（默认隐藏，按钮 toggle），不再是底部固定面板
- 底部状态栏：`模式 | 设备在线 n/m | 当前状态 | 建议`
- `set_dirty(bool)` 脏标记：未保存时切模式/关窗口先弹确认

---

## 三、信号→后端接口对照表（重构时的接线清单）

### 3.1 LauncherDialog（启动小窗）

| ui_v2 信号 | 参数 | 现有后端接入点 |
|---|---|---|
| `refresh_requested` | — | `SingleCameraController.find_devices()` / `CameraManager.find_devices()` |
| `auto_ip_requested` | `List[DeviceInfo]` | `CameraManager.auto_configure_network(indices)`（DeviceInfo.backend_ref 携带句柄） |
| `network_config_requested` | — | 新增网卡选择对话框（可选，先做自动 IP） |
| `connect_requested` | `(mode, List[DeviceInfo])` | `CameraManager.add_camera()` + `connect()` 逐台连接（QThread 后台，见 main_window._on_add_cameras） |

**注意**：`DeviceInfo` 是 ui_v2 的数据结构（model/serial/ip/online/backend_ref），
枚举时由后端构造，`backend_ref` 放设备索引或 SDK 设备对象，UI 原样回传。

### 3.2 MultiCamWorkspace（模式 A）

| ui_v2 信号 | 现有后端 | 回填接口 |
|---|---|---|
| `capture_requested(sync)` | `CameraManager.capture_all(sync=sync)` | `on_capture_done(thumbnails)` → `set_state("captured")` |
| `detect_requested(method)` | `MarkerDetector.detect_3d()`（coded_circle）/ `CalibBoardDetector`（calib_board） | `on_detect_done(marker_counts)` → `set_state("detected")` |
| `calibrate_requested` | `CalibrationEngine.calibrate_pair()` 遍历非参考相机 | `on_calibrate_done(pairs, score, quality_passed)` → `set_state("calibrated")` |
| `save_extrinsics_requested` | `CalibrationEngine.save_calibration(path)` | — |
| `load_extrinsics_requested` | `CalibrationEngine.load_calibration(path)` | 回填结果表 + `set_state("locked")` |
| `capture_scan_requested` | `CameraManager.capture_all()`（外参锁定后） | 卡片 `set_frame_kind("扫描帧")` |
| `stitch_save_requested` | `StitchEngine.stitch()` + `o3d.io.write_point_cloud` | `viewer().set_pointcloud_merged(pcd)` |
| `batch_scan_requested(n)` | 循环 N 次 拍摄+拼接+保存 | — |
| `reference_changed(id)` | `CalibrationEngine.reference_id = id` | — |
| `step_back_requested(i)` | 工作流状态回退确认 | `set_state(...)` |

**质量门禁**：`on_calibrate_done(..., quality_passed=False)` 扫描保持置灰；
通过 → `set_state("locked")` 显示撤板横幅 + 解锁扫描 Tab。
对应现有 `FixedMultiCamWorkflow._check_calibration_quality()`。

### 3.3 MobileChainWorkspace（模式 B）

| ui_v2 信号 | 现有后端 | 回填接口 |
|---|---|---|
| `capture_station_requested` | `MobileChainWorkflow.capture_station()`（内部：拍摄→ChainStitcher.add_frame 自动配准） | `on_capture_done(frame_pixmap)` → `on_detection_done(markers)` → `on_evaluation_done(...)` |
| `undo_requested` | `MobileChainWorkflow.undo_last_station()` | `on_undo_done()` |
| `recapture_requested(i)` | 删除机位 i 后重拍（`StationManager.remove_station`） | 时间线节点刷新 |
| `delete_station_requested(i)` | 删除机位 + 位姿图去边 | 时间线节点刷新 |
| `optimize_requested` | `MobileChainWorkflow.optimize_global()`（PoseGraph.optimize_global_ba） | `on_optimize_done(before, after)` |
| `save_requested` | `SessionManager` + `error_report.json` + PLY | — |
| `auto_mode_changed(auto)` | 手动模式兜底（可选） | — |

**评估阈值**：共视≥6 / 内点率≥0.7 / RMS≤2mm —— 已在 `ChainStitcher` 实现
（`min_common_markers / min_inlier_ratio / max_rms_mm`），工作流判定后经
`on_evaluation_done(shared, inlier, rms, level, suggestion)` 传入，UI 只呈现。

### 3.4 MainWindowShell（主窗口）

| ui_v2 信号 | 现有后端 |
|---|---|
| `device_manager_reopened(mode, devices)` | 断开旧设备 → `CameraManager.disconnect_all()` → 连接新设备 |
| `save_session_requested` | `OfflineSession` / `SessionManager.save_*` |
| `open_session_requested` | `OfflineSession.load_session()` |
| `postprocess_applied(params)` | `PointCloudProcessor`（裁切/下采样/离群点） |
| `log(msg, level)` | `core.utils.logger` + 状态栏 |
| `show_loading(text)` / `hide_loading()` | `LoadingOverlay`（现有 src/ui/loading_overlay.py） |

---

## 四、现有组件替换映射（不用重写，直接换）

| ui_v2 空壳 | 换回现有组件 | 备注 |
|---|---|---|
| `widgets/step_bar.py` | `ui/widgets/wizard_step_bar.py` | 接口已对齐（set_current / step_clicked） |
| `widgets/loading_overlay.py` | `ui/loading_overlay.py` | 接口一致 |
| `widgets/viewer_panel.py` | `ui/viewer_3d.py` EmbeddedPointCloudViewer | 方法签名已对齐（set_pointcloud / set_pointcloud_merged / clear_all / reset_view） |
| `widgets/camera_grid.py` 缩略图 | `ui/camera_card.py` AspectRatioLabel + numpy_to_qpixmap | 标记叠加（绿圈+code）已有 |
| `widgets/live_view_panel.py` 叠加层 | 同上 camera_card | 共有标记蓝圈为新增样式 |
| `main_window.log()` | `core.utils.logger` | 双通道：日志面板 + 状态栏 |
| `LauncherDialog` | 现有 `ui/launcher_window.py` 可参考 | ui_v2 版有数量门控更完善 |

---

## 五、重构建议步骤（下午开工顺序）

1. **先跑空壳**：`python src/ui_v2/run_shell.py`，确认交互符合预期再动手
2. **LauncherDialog 接线**：`refresh_requested` / `connect_requested` ← CameraManager
   （DeviceInfo.backend_ref 携带设备索引）
3. **模式 A 接线**：capture/detect/calibrate 三个 `on_*_done` 回填 ← FixedMultiCamWorkflow
4. **模式 B 接线**：capture_station → on_capture/detection/evaluation_done ← MobileChainWorkflow
5. **ViewerPanel 整体替换**为 EmbeddedPointCloudViewer
6. **会话存取 + set_dirty 脏标记**接线
7. **入口切换**：`main.py` 启动流程改为 LauncherDialog → MainWindowShell

## 六、注意事项

- ui_v2 的 `theme.py` 提供全局 QSS（`GLOBAL_QSS`），与现有 `STYLESHEET` 二选一，不要混用
- ui_v2 不导入 core/PyRVC/OpenGL，run_shell.py 可离线跑；正式接入后需加回依赖
- 模式 B 的时间线 `StationTimeline`、评估卡片 `EvaluationCard` 是新组件，
  比我之前实现的 `mobile_chain_view.py` 更完善，建议直接用 ui_v2 的版本
- 现有 `mobile_chain_view.py`（我之前 P3 写的）可以废弃，以 ui_v2 的 workspace 为准
- 现有测试脚本（test_ui.py 等）针对旧 UI，重构后需要重写 UI 测试

---

## 七、一句话总结

**ui_v2 已经把「双窗口模型 + 双工作区 + 状态机门控 + 术语隔离」全部 UI 做好了，
下午的工作就是：把 ui_v2 的 Qt 信号逐个接到 P1/P2 已完成的 core 模块
（CameraManager / FixedMultiCamWorkflow / MobileChainWorkflow / SessionManager），
并把控件替换为现有的 viewer_3d / camera_card 等成熟组件。**
