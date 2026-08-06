# ui_v2 —— 拼接软件新 UI 空壳

> 日期：2026-08-06
> 依据：《拼接软件UI重设计-AI提示词.md》+《docs/ui_redesign_v2.md》
> 定位：**纯 UI 层空壳**，接口全部留出，可完全离线运行（无相机 / 无 PyRVC / 无 OpenGL）。

---

## 一、这是什么

按提示词「双窗口模型」重新搭建的整套 UI 骨架：

```
[启动小窗 LauncherDialog] ──连接成功──▶ [主窗口 MainWindowShell]
  · 模式卡片（A/B 分流）                 · 顶部功能栏（设备管理/模式/会话/后处理/日志/帮助）
  · 设备管理（搜索/自动IP/多选）          · QStackedWidget 双工作区（互不干扰）
  · 模式-数量规则门控连接按钮             · 状态栏：模式 | 设备在线 | 当前状态 | 建议
```

**空壳的含义**：
- 所有布局、控件、配色、状态门控均已实现并可操作；
- 所有与 `src/core`、Workflow、SDK、PyRVC 的交互点均以 **Qt 信号 + `# TODO(BACKEND):` 注释** 留出，壳内不含任何业务逻辑；
- `run_shell.py` 用 mock 数据演示完整交互流程，正式接入时删除 mock、把信号接到后端即可。

## 二、运行

```bash
# 项目根目录
python src/ui_v2/run_shell.py
```

启动后出现启动小窗（已注入 4 台 mock 设备）：
- 默认选中「多相机外参标定」→ 勾选 ≥2 台 →「连接设备 →」进入模式 A 工作区；
- 切到「单相机移动拼接」→ 勾选恰好 1 台 → 进入模式 B 工作区；
- 主窗口「⚙ 设备管理」可随时回小窗改模式/换设备。

## 三、目录结构

```
src/ui_v2/
├── __init__.py
├── theme.py                      # 设计 token（深色工业风 + RVC 红）+ 全局 QSS
├── launcher_dialog.py            # 启动小窗：模式卡片 + 设备管理 + 数量规则门控
├── main_window.py                # 主窗口框架：功能栏 + QStackedWidget + 状态栏 + 日志 dock
├── run_shell.py                  # 离线演示入口（mock 设备 + mock 流程回调）
├── widgets/
│   ├── step_bar.py               # 步骤条（pending/current/done/disabled 四态）
│   ├── loading_overlay.py        # 加载遮罩（接口同 src/ui/loading_overlay.py）
│   ├── mode_card.py              # 模式选择卡片
│   ├── device_table.py           # 设备多选表格（DeviceInfo 数据结构）
│   ├── camera_grid.py            # 相机取景卡片网格（标记数/共视/帧分区角标）
│   ├── viewer_panel.py           # 3D 查看器占位（接口对齐 EmbeddedPointCloudViewer）
│   ├── station_timeline.py       # 机位时间线（模式 B 核心控件）
│   ├── evaluation_card.py        # 评估卡片（🟢/🟡/🔴 三色语义）
│   ├── live_view_panel.py        # 实时取景占位（自动检测叠加接口）
│   └── log_panel.py              # 日志面板
└── workspaces/
    ├── multi_cam_workspace.py    # 模式 A：步骤条 + 三栏 + 状态机门控
    └── mobile_chain_workspace.py # 模式 B：时间线 + 取景/3D + 评估 + 状态机门控
```

## 四、接口清单（接后端的位置）

### 4.1 LauncherDialog（启动小窗 → 后端）

| 信号 | 参数 | 后端接入点 |
|------|------|-----------|
| `refresh_requested` | — | SDK `SystemListDevices` 枚举，回 `set_devices()` |
| `auto_ip_requested` | `List[DeviceInfo]` | 自动网络配置（参考 `AutoConfigureNetwork.py`） |
| `network_config_requested` | — | 网卡选择对话框（GigE 静态 IP） |
| `connect_requested` | `(mode, List[DeviceInfo])` | `CameraManager` 逐台连接；全部成功 `accept()`，部分失败弹窗可重试 |

`DeviceInfo.backend_ref` 字段用于携带后端设备句柄，UI 不解释、原样回传。

### 4.2 MultiCamWorkspace（模式 A → 后端）

| 信号 | 后端接入点 | 回填接口 |
|------|-----------|---------|
| `capture_requested(sync)` | 全部相机拍摄（同步/异步） | `on_capture_done(thumbnails)` → `set_state("captured")` |
| `detect_requested(method)` | MarkerDetector / CalibBoardDetector | `on_detect_done(marker_counts)` → `set_state("detected")` |
| `calibrate_requested` | CalibrationEngine | `on_calibrate_done(pairs, score, quality_passed)` → `set_state("calibrated")` |
| `save/load_extrinsics_requested` | 外参 JSON 存取 | — |
| `capture_scan_requested` | 外参锁定后扫描拍摄 | 卡片 `set_frame_kind("扫描帧")` |
| `stitch_save_requested` | StitchEngine 拼接 + 存 PLY | `viewer().set_pointcloud_merged()` |
| `batch_scan_requested(n)` | 连续 N 次批量拼接 | — |
| `reference_changed(id)` | 参考相机变更 | — |
| `step_back_requested(i)` | 步骤回退确认 | `set_state(...)` |

质量门禁：`on_calibrate_done(..., quality_passed=False)` 时扫描按钮保持置灰；
通过后 `set_state("locked")` 显示撤板横幅并解锁扫描 Tab。

### 4.3 MobileChainWorkspace（模式 B → 后端）

| 信号 | 后端接入点 | 回填接口 |
|------|-----------|---------|
| `capture_station_requested` | 拍摄 → **自动**检测→匹配→评估（无手动检测入口） | `on_capture_done()` → `on_detection_done(markers)` → `on_evaluation_done(...)` |
| `undo_requested` / `recapture_requested(i)` / `delete_station_requested(i)` | StationManager | `on_undo_done()` / 时间线节点刷新 |
| `optimize_requested` | 位姿图闭环全局优化 | `on_optimize_done(before, after)` |
| `save_requested` | 会话 + PLY + error_report.json | — |
| `auto_mode_changed(auto)` | 手动模式兜底面板显隐 | — |

评估阈值（共视≥6 / 内点率≥0.7 / RMS 达标）由工作流判定，经
`on_evaluation_done(shared, inlier, rms, level, suggestion)` 传入，
UI 只呈现不编造文案。

### 4.4 MainWindowShell（主窗口 → 后端）

| 信号 | 后端接入点 |
|------|-----------|
| `device_manager_reopened(mode, devices)` | 断开旧设备 → 连接新设备 → 工作区已自动切换 |
| `save_session_requested` / `open_session_requested` | OfflineSession（`scans/<mode>_session_时间戳/`） |
| `postprocess_applied(params)` | PointCloudProcessor（裁切/下采样/离群点滤波） |

公共方法：`log(msg, level)`、`show_loading(text)` / `hide_loading()`、
`set_dirty(bool)`（未保存数据脏标记，关闭/切模式前弹确认）。

## 五、与现有组件的替换映射

空壳为自包含实现，正式接入时以下占位件可整体换回现有组件：

| 空壳 | 换回的现有组件 | 说明 |
|------|--------------|------|
| `widgets/step_bar.py` | `ui/widgets/wizard_step_bar.py` | 接口已对齐（set_current / step_clicked） |
| `widgets/loading_overlay.py` | `ui/loading_overlay.py` | 接口一致，仅换色 |
| `widgets/viewer_panel.py` | `ui/viewer_3d.py` EmbeddedPointCloudViewer | 方法签名已对齐（set_pointcloud / set_pointcloud_merged / clear_all / reset_view） |
| `widgets/camera_grid.py` 缩略图 | `ui/camera_card.py` AspectRatioLabel + `numpy_to_qpixmap` | 标记叠加（绿圈+code）已有实现 |
| `widgets/live_view_panel.py` 叠加层 | 同上 | 共有标记蓝圈为新增样式 |
| `main_window.log()` | `core.utils.logger` | 双通道：日志面板 + 状态栏 |

## 六、已落实的提示词硬性要求

- [x] 入口即分流：模式卡片 + 数量规则门控（A≥2 台 / B=1 台），切模式清空多选
- [x] 随时可回头：主窗口「设备管理/模式」回小窗，回填当前状态，脏数据先确认
- [x] 模式 A：步骤条驱动门控、质量门禁禁扫描、撤板横幅、断线重连重标提示
- [x] 模式 B：**无手动「检测」按钮**，拍摄后自动检测/匹配/评估/入链；
      时间线节点三色 + 失败节点内嵌重拍 + 闭环优化入口；
      底部常驻「已接 N 机位 | 累计误差 | 平均单步误差」
- [x] 术语隔离：B 区文案只有「机位/重合度/链/误差」，无标定术语
- [x] 视觉规范：深色工业风 + RVC 红 #E53935，统一 theme.py QSS，8px 间距 / 6px 圆角
- [x] 离线可启动：不导入 core / PyRVC / OpenGL

## 七、下一步（接入顺序建议）

1. `LauncherDialog.connect_requested` ← CameraManager 连接流程（含部分失败弹窗）
2. 模式 A：拍摄 → 检测 → 标定三回填接口（`on_*_done`）接 Workflow 事件
3. 模式 B：移动链式工作流事件 → `on_capture/detection/evaluation_done`
4. `ViewerPanel` 整体替换为 `EmbeddedPointCloudViewer`
5. 会话存取（OfflineSession）与 `set_dirty` 脏标记接线
