# MultiCameraCalibration UI 重构设计方案

> 版本：v1.0  
> 日期：2026-08-06  
> 目标：基于现有功能和信号接口，全面重构 UI 布局与视觉系统，**零业务逻辑改动**，仅迁移/重组 UI 组件的呈现方式。

---

## 一、现状诊断

### 1.1 现有布局架构

```
┌─────────────────────────────────────────────────────────────┐
│  顶部工具栏（返回/设备管理/模式切换）                          │  36px
├──────────┬────────────────────────────┬─────────────────────┤
│          │                            │                     │
│ 左侧     │      中央区域               │     右侧            │
│ 350px    │                            │     380px           │
│ QTabWidget│   上：相机卡片网格(QGrid)   │   QTabWidget        │
│          │   下：3D查看器(QSplitter)   │   (采集/标定/拼接)   │
│ 0: 设备  │        ↕ 可折叠             │                     │
│ 1: 站位  │                            │                     │
│ 2: 链式  │                            │                     │
│          │                            │                     │
├──────────┴────────────────────────────┴─────────────────────┤
│  底部可折叠日志面板 (CollapsibleLogPanel)                     │  200px
└─────────────────────────────────────────────────────────────┘
```

### 1.2 核心痛点

| 序号 | 痛点 | 影响 |
|------|------|------|
| 1 | **左侧 350px 固定宽度利用率低** | 设备列表空白多，站位模式只有少量按钮 |
| 2 | **中央卡片+3D 垂直分割，两者都局促** | 相机多时卡片被压缩，3D 视口也受限 |
| 3 | **右侧 Tab 面板内容拥挤** | 采集/标定/拼接三组控件挤在 380px 内 |
| 4 | **日志面板常驻占用 200px** | 大部分时间只需要看状态行 |
| 5 | **模式切换与左侧 Tab 耦合混乱** | 顶部按钮切换 left_tabs，left_tabs 又切换 page_stack |
| 6 | **启动窗口过于简陋** | 只有列表+按钮，无视觉层次 |
| 7 | **样式表混合内联+全局+objectName** | 维护困难，优先级混乱 |
| 8 | **无键盘快捷键系统** | 工业场景效率低 |

### 1.3 现有代码质量评估

- ✅ **业务逻辑层**：完整且健壮，后台线程分离良好
- ✅ **3D 渲染核心**：OpenGL 3.0 + ArcBall 相机，性能优秀
- ✅ **信号接口设计**：各面板通过信号与 MainWindow 解耦
- ⚠️ **UI 装配层**：布局嵌套过深，Splitter 层级多
- ⚠️ **样式管理**：全局 QSS + 局部 setStyleSheet 混用
- ❌ **无设计系统 token**：颜色/圆角/间距硬编码

---

## 二、设计目标

### 2.1 核心原则

1. **视口优先（Viewport-First）**：3D 点云查看器是核心产出，应占据最大空间
2. **上下文感知（Context-Aware）**：右侧面板根据当前操作步骤动态变化，而非固定 Tab
3. **渐进披露（Progressive Disclosure）**：次要功能收起，需要时展开
4. **键盘友好**：常用操作支持快捷键，工业场景效率优先
5. **信号零改动**：所有现有信号接口原样保留，只改组件内部呈现

### 2.2 参考风格

- **布局参考**：Blender（窄侧边栏 + 可展开区域）、CloudCompare（中央视口最大化）
- **配色参考**：现代 IDE 深色主题（VS Code / JetBrains Darcula 的饱和度降低版）
- **交互参考**：工业软件的专业感 + Web 应用的即时反馈

---

## 三、新布局架构

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  标题栏（最小化）│  全局操作区              │  模式指示器    │ 帮助   │  32px
├────┬──────────────────────────────────────────┬─────────────────────┤
│    │                                          │                     │
│ 侧 │                                          │   右侧面板          │
│ 边 │         中央视口（3D查看器最大化）        │   (可折叠抽屉)      │
│ 导 │                                          │   根据上下文动态内容  │
│ 航 │    ┌──────────────────────────────┐     │                     │
│ 栏 │    │    浮动预览栏（可收纳）       │     │   - 设备管理        │
│ 48 │    │    相机缩略图水平排列        │     │   - 采集参数        │
│ px │    │    悬停展开 / 点击最大化      │     │   - 标定工具        │
│    │    └──────────────────────────────┘     │   - 拼接参数        │
│    │                                          │   - 站位列表        │
│    │    ┌──────────────────────────────┐     │                     │
│    │    │    步骤条（WizardStepBar）    │     │                     │
│    │    │    仅在多相机模式显示         │     │                     │
│    │    └──────────────────────────────┘     │                     │
│    │                                          │                     │
├────┴──────────────────────────────────────────┴─────────────────────┤
│  ▼ 状态栏 │ [状态信息]                    │  日志 │ 点数 │ 相机数  │  24px
├─────────────────────────────────────────────────────────────────────┤
│  底层面板（终端式日志，可完全收起 = 只剩状态栏）                      │  0~200px
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 布局层次（代码实现）

```python
# 根布局：QMainWindow + 自定义中央部件
QMainWindow
└── centralWidget: QWidget (QVBoxLayout, margin=0, spacing=0)
    ├── TitleBar: QWidget (32px, 可拖拽移动窗口)
    ├── MainSplitter: QSplitter(Horizontal)
    │   ├── LeftSidebar: QWidget (48px 固定宽度)
    │   │   ├── IconButton[]: 模式切换 + 功能按钮（垂直排列）
    │   │   └── Spacer
    │   ├── CenterViewport: QWidget (QVBoxLayout)
    │   │   ├── 3DViewer: EmbeddedPointCloudViewer (占据绝大部分空间)
    │   │   ├── FloatingPreviewBar: CollapsibleBar (水平缩略图栏)
    │   │   └── WizardBar: WizardStepBar (底部，模式相关显隐)
    │   └── RightDrawer: QDockWidget / 自定义抽屉 (可折叠到 0px)
    │       └── ContextPanel: QStackedWidget
    │           ├── PageDevice: DevicePanel 重构版
    │           ├── PageCapture: CapturePanel 重构版
    │           ├── PageCalibrate: CalibrationPanel 重构版
    │           ├── PageStitch: StitchPanel 重构版
    │           ├── PageStation: StationPanel 重构版
    │           └── PageChain: MobileChainView 重构版
    ├── StatusBar: QWidget (24px, 信息密度行)
    └── BottomPanel: CollapsibleLogPanel (终端式，可收起至只剩标题栏)
```

### 3.3 空间分配策略

| 区域 | 默认宽度/高度 | 最小尺寸 | 可折叠 |
|------|-------------|---------|--------|
| 标题栏 | 32px | 32px | 否（可隐藏） |
| 侧边导航 | 48px | 48px | 否 |
| 中央视口 | 自适应 | 600×400 | 否 |
| 右侧面板 | 320px | 0px（完全收起） | ✅ |
| 状态栏 | 24px | 24px | 否 |
| 底层面板 | 150px | 24px（仅标题栏） | ✅ |

---

## 四、设计系统（Design System）

### 4.1 色彩体系

```
Base Layers:
  --bg-window:      #0D0D12    # 窗口背景（比现有 #0F0F13 更冷）
  --bg-surface:     #141419    # 卡片/面板背景
  --bg-elevated:    #1C1C23    # 悬停/ elevated 表面
  --bg-input:       #1A1A22    # 输入框背景

Borders:
  --border-default: #2A2A35    # 默认边框
  --border-hover:   #3A3A4A    # 悬停边框
  --border-focus:   #2979FF    # 焦点边框（主色）

Text:
  --text-primary:   #E8E8F0    # 主文本（比现有更亮，提升对比）
  --text-secondary: #8B8D9A    # 次要文本
  --text-muted:     #5C5E6A    # 禁用/占位文本

Accent:
  --accent-primary: #2979FF    # 主色（保留现有蓝色）
  --accent-hover:   #1565C0    # 主色悬停
  --accent-glow:    rgba(41,121,255,0.15)  # 发光效果

Status:
  --status-success: #00C853    # 更鲜艳的绿色
  --status-warning: #FFB300    # 琥珀色
  --status-error:   #FF5252    # 更柔和的红色
  --status-info:    #448AFF    # 信息蓝

Camera Palette (保留现有，微调饱和度):
  --cam-ref:        #F0F0F0    # 参考相机白色
  --cam-1:          #29B6F6    # 青（更饱和）
  --cam-2:          #FFA726    # 橙
  --cam-3:          #66BB6A    # 绿
  --cam-4:          #EC407A    # 品红
  --cam-5:          #FFEE58    # 黄
  --cam-6:          #AB47BC    # 紫
  --cam-7:          #26C6DA    # 蓝绿
  --cam-8:          #EF5350    # 红
```

### 4.2 字体体系

```
--font-sans:  "Inter", "Segoe UI", "Microsoft YaHei", system-ui, sans-serif
--font-mono:  "JetBrains Mono", "Fira Code", "Consolas", monospace

字号阶梯:
  --text-xs:   10px / 14px   # 标签、状态提示
  --text-sm:   11px / 16px   # 按钮、输入框
  --text-base: 12px / 18px   # 正文
  --text-lg:   14px / 20px   # 面板标题
  --text-xl:   16px / 24px   # 窗口标题

字重:
  --weight-normal: 400
  --weight-medium: 500
  --weight-semibold: 600
  --weight-bold: 700
```

### 4.3 圆角与间距

```
圆角:
  --radius-sm:  4px    # 按钮、输入框
  --radius-md:  6px    # 卡片、面板
  --radius-lg:  8px    # 大面板、弹窗
  --radius-full: 999px  # 标签、胶囊

间距:
  --space-1: 2px
  --space-2: 4px
  --space-3: 6px
  --space-4: 8px
  --space-5: 12px
  --space-6: 16px
```

### 4.4 阴影与发光

```
# 卡片悬停微提升
--shadow-sm: 0 1px 2px rgba(0,0,0,0.3)
--shadow-md: 0 4px 12px rgba(0,0,0,0.4)

# 主按钮发光
--glow-primary: 0 0 12px rgba(41,121,255,0.25)

# 选中态发光
--glow-selected: 0 0 0 2px rgba(41,121,255,0.3)
```

---

## 五、新组件设计

### 5.1 侧边导航栏（SidebarNav）

**新组件**，替代现有 `left_tabs` 的 Tab 切换功能。

```python
class SidebarNav(QWidget):
    """48px 窄图标导航栏，点击展开对应右侧面板。"""

    mode_changed = Signal(str)   # "multi" | "station" | "chain"
    device_manager_clicked = Signal()  # 打开设备管理抽屉

    def __init__(self, parent=None):
        # 垂直排列的图标按钮组
        # 每个按钮：40×40px，圆角 6px，图标 20px
        # 选中态：左侧 3px 蓝色指示条 + 背景 elevated
        # 悬停态：背景略亮
        pass

    def set_mode(self, mode: str): ...
    def set_badge(self, icon_name: str, count: int): ...  # 红点徽标
```

**按钮列表（从上到下）**：
1. 🎥 多相机模式（默认选中）
2. 📍 站位模式
3. 🔗 移动链式
4. ─── 分隔线 ───
5. 🔧 设备管理（打开右侧抽屉，显示 DevicePanel）
6. ⚙️ 设置（预留）

### 5.2 浮动预览栏（FloatingPreviewBar）

**新组件**，替代现有 `grid_scroll` 中的相机卡片网格。

```python
class FloatingPreviewBar(QWidget):
    """可收纳的水平相机缩略图栏，悬浮在 3D 视口底部。"""

    capture_requested = Signal(str)      # 保留，同 CameraPreviewCard
    disconnect_requested = Signal(str)   # 保留
    preview_toggled = Signal(str, bool)  # 保留
    card_clicked = Signal(str)           # 新：点击缩略图放大到中央
    card_double_clicked = Signal(str)    # 新：双击全屏该卡片

    def __init__(self, parent=None):
        # 默认高度：80px（缩略图 72px + 边距）
        # 收起状态：高度 24px（只显示标题栏 + 相机数量）
        # 缩略图：固定 128×72px，16:9 比例
        # 选中态：蓝色边框 2px + 发光
        # 状态指示器：右上角小圆点（绿=已连接，灰=断开）
        pass

    def add_card(self, camera_id: str, desc: str = ""): ...
    def remove_card(self, camera_id: str): ...
    def update_frame(self, camera_id: str, frame: FrameData, markers=None): ...
    def set_selected(self, camera_id: str): ...
    def set_collapsed(self, collapsed: bool): ...
```

**关键交互**：
- 鼠标悬停预览栏边缘 → 自动展开（可关闭）
- 点击缩略图 → 该相机卡片放大到中央区域（覆盖 3D 视口，30% 透明度背景）
- 再次点击 / 按 Esc → 恢复 3D 视口
- 右键菜单 → 断开 / 重命名 / 参数设置

### 5.3 右侧面板抽屉（RightDrawer）

**新容器**，替代现有 `right_tabs`。

```python
class RightDrawer(QWidget):
    """可折叠的右侧面板抽屉，内容根据当前上下文切换。"""

    collapsed_changed = Signal(bool)

    def __init__(self, parent=None):
        # 默认宽度 320px
        # 折叠按钮在左边缘（40px 宽的手柄区域）
        # 展开时宽度动画 0→320px
        # 折叠时只显示手柄（手柄上有当前页面图标）
        pass

    def set_page(self, page_name: str): ...  # "device" | "capture" | "calibrate" | "stitch" | "station" | "chain"
    def set_collapsed(self, collapsed: bool): ...
```

**页面映射**：

| 当前上下文 | 右侧面板显示 |
|-----------|------------|
| 侧边栏点击"设备管理" | DevicePanel（设备搜索/添加/网络配置） |
| 多相机模式 + 无相机 | DevicePanel |
| 多相机模式 + 有相机 | CapturePanel（采集参数/拍摄控制） |
| 多相机模式 + 有帧数据 | CapturePanel + CalibrationPanel（标定工具） |
| 多相机模式 + 有标定结果 | StitchPanel（拼接参数/执行） |
| 站位模式 | StationPanel（设备连接/站位列表/拍摄） |
| 移动链式 | MobileChainView（时间线/评估/控制） |

### 5.4 状态栏（StatusBar）

**新组件**，替代现有日志面板的"状态显示"功能。

```python
class CompactStatusBar(QWidget):
    """24px 高密度信息行，常驻显示最关键状态。"""

    log_toggle_requested = Signal()  # 点击展开日志

    def __init__(self, parent=None):
        # 左：状态图标 + 一句话状态（如"就绪 | 3台相机已连接"）
        # 中：操作提示（如"下一步：点击拍摄获取标定帧"）
        # 右：快速指标（相机数 | 总点数 | 站位数）
        pass

    def set_status(self, text: str, level: str = "info"): ...  # level: info/warn/error/success
    def set_hint(self, text: str): ...  # 操作提示
    def set_metrics(self, cameras: int = 0, points: int = 0, stations: int = 0): ...
```

### 5.5 终端式日志面板（TerminalPanel）

**重构**现有 `CollapsibleLogPanel`。

改进点：
- 完全收起时只留 24px 标题栏（与状态栏融合）
- 展开时高度动画滑出
- 增加命令输入框（可扩展为 REPL）
- 增加日志级别过滤按钮（ERROR/WARN/INFO/DEBUG）
- 增加时间戳开关
- 增加"自动滚动"开关

```python
class TerminalPanel(QWidget):
    toggled = Signal(bool)

    def set_expanded(self, expanded: bool): ...
    def append(self, text: str, level: str = "info"): ...
    def clear(self): ...
    def set_filter(self, levels: list): ...
```

### 5.6 中央视口切换器（ViewportSwitcher）

**新组件**，管理中央区域的内容切换（3D 视口 / 相机大图 / 移动链式视图）。

```python
class ViewportSwitcher(QStackedWidget):
    """中央内容切换器，支持平滑过渡动画。"""

    view_changed = Signal(str)  # "3d" | "camera" | "chain"

    def show_3d(self): ...
    def show_camera(self, camera_id: str, frame: FrameData): ...
    def show_chain(self): ...
```

---

## 六、现有组件 → 新组件映射

### 6.1 信号接口迁移计划

**原则：所有信号原样保留，只改变发射信号的组件。**

| 原信号源 | 信号名 | 新信号源 | 备注 |
|---------|--------|---------|------|
| `DevicePanel` | `refresh_devices_requested` | `RightDrawer > DevicePanel` | 原样保留 |
| `DevicePanel` | `cameras_added(list)` | `RightDrawer > DevicePanel` | 原样保留 |
| `DevicePanel` | `camera_remove_requested(str)` | `FloatingPreviewBar` | 从缩略图右键菜单 |
| `DevicePanel` | `auto_configure_network_requested(list)` | `RightDrawer > DevicePanel` | 原样保留 |
| `CapturePanel` | `capture_all_requested` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `capture_sequential_requested` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `continuous_capture_toggled(bool,int)` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `capture_params_changed(dict)` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `save_frame_to_session_requested` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `save_session_requested` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `load_session_requested` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `batch_detect_requested` | `RightDrawer > CapturePanel` | 原样保留 |
| `CapturePanel` | `batch_calibrate_requested` | `RightDrawer > CapturePanel` | 原样保留 |
| `CalibrationPanel` | `detect_requested` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `calibrate_pair_requested(ref,cam)` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `add_frame_requested` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `calibrate_multi_requested` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `clear_frames_requested` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `save_calibration_requested` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `load_calibration_requested` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `reference_changed(str)` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `pair_selected(ref,cam)` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `marker_type_changed(str)` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `StitchPanel` | `stitch_requested` | `RightDrawer > StitchPanel` | 原样保留 |
| `StitchPanel` | `stitch_save_requested` | `RightDrawer > StitchPanel` | 原样保留 |
| `StitchPanel` | `stitch_session_requested` | `RightDrawer > StitchPanel` | 原样保留 |
| `StitchPanel` | `process_params_changed(dict)` | `RightDrawer > StitchPanel` | 原样保留 |
| `StitchPanel` | `auto_params_requested` | `RightDrawer > StitchPanel` | 原样保留 |
| `StationPanel` | `refresh_devices_requested` | `RightDrawer > StationPanel` | 原样保留 |
| `StationPanel` | `connect_requested(int)` | `RightDrawer > StationPanel` | 原样保留 |
| `StationPanel` | `disconnect_requested` | `RightDrawer > StationPanel` | 原样保留 |
| `StationPanel` | `capture_station_requested` | `RightDrawer > StationPanel` | 原样保留 |
| `StationPanel` | `station_removed(str)` | `RightDrawer > StationPanel` | 原样保留 |
| `StationPanel` | `stations_cleared` | `RightDrawer > StationPanel` | 原样保留 |
| `StationPanel` | `new_session_requested` | `RightDrawer > StationPanel` | 原样保留 |
| `MobileChainView` | `capture_station_requested` | `RightDrawer > MobileChainView` | 原样保留 |
| `MobileChainView` | `undo_station_requested` | `RightDrawer > MobileChainView` | 原样保留 |
| `MobileChainView` | `optimize_global_requested` | `RightDrawer > MobileChainView` | 原样保留 |
| `MobileChainView` | `save_session_requested` | `RightDrawer > MobileChainView` | 原样保留 |
| `CameraPreviewCard` | `capture_requested(str)` | `FloatingPreviewBar` | 原样保留 |
| `CameraPreviewCard` | `disconnect_requested(str)` | `FloatingPreviewBar` | 原样保留 |
| `CameraPreviewCard` | `preview_toggled(str,bool)` | `FloatingPreviewBar` | 原样保留 |
| `EmbeddedPointCloudViewer` | `status_changed(str)` | `EmbeddedPointCloudViewer` | 原样保留 |
| `EmbeddedPointCloudViewer` | `maximize_toggled(bool)` | `EmbeddedPointCloudViewer` | 原样保留 |
| `EmbeddedPointCloudViewer` | `collapse_toggled(bool)` | `EmbeddedPointCloudViewer` | 原样保留 |

### 6.2 方法接口迁移计划

| 原组件 | 方法 | 新组件 | 变化说明 |
|--------|------|--------|---------|
| `CameraPreviewCard` | `update_frame(FrameData, markers)` | `FloatingPreviewBar` | 方法名保留 |
| `CameraPreviewCard` | `update_captured()` | `FloatingPreviewBar` | 方法名保留 |
| `CameraPreviewCard` | `set_connected(bool)` | `FloatingPreviewBar` | 方法名保留 |
| `CameraPreviewCard` | `set_title()` | `FloatingPreviewBar` | 改为 `set_card_title()` |
| `DevicePanel` | `set_devices(list)` | `RightDrawer > DevicePanel` | 原样保留 |
| `DevicePanel` | `add_camera_entry(str,desc)` | `FloatingPreviewBar` + `RightDrawer > DevicePanel` | 拆分到两处 |
| `DevicePanel` | `remove_camera_entry(str)` | `FloatingPreviewBar` + `RightDrawer > DevicePanel` | 拆分到两处 |
| `CalibrationPanel` | `set_camera_ids(list)` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `CalibrationPanel` | `update_results(dict)` | `RightDrawer > CalibrationPanel` | 原样保留 |
| `StitchPanel` | `set_result(points,elapsed_ms,path)` | `RightDrawer > StitchPanel` | 原样保留 |
| `StationPanel` | `add_station(str,time_str)` | `RightDrawer > StationPanel` | 原样保留 |
| `MobileChainView` | `add_station_to_timeline(...)` | `RightDrawer > MobileChainView` | 原样保留 |

### 6.3 不需要改动的组件

以下组件功能完整、接口清晰，**原样保留**，只调整在新布局中的位置：

- ✅ `EmbeddedPointCloudViewer`（3D 查看器核心）
- ✅ `PointCloudViewer`（OpenGL 渲染）
- ✅ `_ArcBallCamera`（相机控制器）
- ✅ `AxesIndicatorWidget`（坐标轴指示器）
- ✅ `WorkerThread`（后台线程）
- ✅ `LoadingOverlay`（加载遮罩）
- ✅ `WizardStepBar`（步骤条，调整位置到底部）
- ✅ `icons.py`（图标工具）

---

## 七、各工作模式的新布局差异

### 7.1 多相机标定模式（默认）

```
┌─────────────────────────────────────────────────────────────┐
│ [≡] 多相机标定          [拍摄 ▼] [检测] [标定] [拼接]  [?]  │
├────┬───────────────────────────────────────┬────────────────┤
│ 🎥 │                                       │  📐 标定工具   │
│ 📍 │          3D 点云视口                   │  ────────────  │
│ 🔗 │         (最大化显示)                   │  参考相机:     │
│ ─  │                                       │  [cam0 ▼]      │
│ 🔧 │  ┌─────────────────────────────┐      │  标记物类型:   │
│    │  │   浮动预览栏 (可收起)        │      │  [编码圆 ▼]   │
│    │  │  [cam0] [cam1] [cam2] ...   │      │  ────────────  │
│    │  └─────────────────────────────┘      │  [检测标记]    │
│    │  ┌─────────────────────────────┐      │  [标定选中pair]│
│    │  │   步骤条：设备→拍摄→检测→标定→拼接 │  [累积多帧]    │
│    │  └─────────────────────────────┘      │  [多帧平均标定]│
│    │                                       │                │
├────┴───────────────────────────────────────┴────────────────┤
│ ▼ 就绪 | 3台相机已连接 | 下一步：点击"拍摄"获取标定帧         │
├─────────────────────────────────────────────────────────────┤
│ [终端日志面板 ─ 可收起]                                       │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板上下文切换逻辑**：
1. 刚添加相机 → 显示 **CapturePanel**（拍摄参数）
2. 点击"拍摄"后 → 自动切换或提示切换到 **CalibrationPanel**
3. 完成标定后 → 自动提示切换到 **StitchPanel**
4. 用户可手动点击抽屉手柄保持当前面板

### 7.2 单相机站位模式

```
┌─────────────────────────────────────────────────────────────┐
│ [≡] 单相机站位          [拍摄站位] [清空] [新会话]      [?]  │
├────┬───────────────────────────────────────┬────────────────┤
│ 🎥 │                                       │  📍 站位管理   │
│ 📍◄│          3D 点云视口                   │  ────────────  │
│ 🔗 │         (最大化显示)                   │  设备: [连接 ▼]│
│ ─  │                                       │  [断开]        │
│ 🔧 │  ┌─────────────────────────────┐      │  ────────────  │
│    │  │   浮动预览栏                │      │  站位列表:     │
│    │  │  [当前相机] [站位1] [站位2]...│    │  ☑ station_1   │
│    │  └─────────────────────────────┘      │  ☑ station_2   │
│    │                                       │  ☐ station_3   │
│    │                                       │  ────────────  │
│    │                                       │  [拍摄站位]    │
│    │                                       │  [清空站位]    │
│    │                                       │  [新会话]      │
├────┴───────────────────────────────────────┴────────────────┤
│ ▼ 就绪 | 已拍 3 个站位 | 可继续移动拍摄或到标定 Tab 检测      │
├─────────────────────────────────────────────────────────────┤
│ [终端日志面板 ─ 可收起]                                       │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 移动链式模式

```
┌─────────────────────────────────────────────────────────────┐
│ [≡] 移动链式拼接    [拍摄机位] [撤销] [全局优化] [保存]  [?]│
├────┬───────────────────────────────────────┬────────────────┤
│ 🎥 │                                       │  🔗 链式控制   │
│ 📍 │          3D 点云视口                   │  ────────────  │
│ 🔗◄│         (显示拼接结果)                 │  时间线:       │
│ ─  │                                       │  ●━●━●━○      │
│ 🔧 │                                       │  (3站/质量良)  │
│    │                                       │  ────────────  │
│    │                                       │  [拍摄机位]    │
│    │                                       │  [撤销上一机位]│
│    │                                       │  [全局BA优化]  │
│    │                                       │  [保存会话]    │
│    │                                       │  ────────────  │
│    │                                       │  RMS: 0.23mm   │
│    │                                       │  点数: 128万   │
├────┴───────────────────────────────────────┴────────────────┤
│ ▼ 就绪 | 3 个机位已配准 | RMS 0.23mm                          │
├─────────────────────────────────────────────────────────────┤
│ [终端日志面板 ─ 可收起]                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 八、样式系统实现

### 8.1 全局样式表（精简版）

```css
/* ================================================================
   MultiCameraCalibration — 全局样式表 v2.0
   基于 CSS 变量 + QSS 降级实现
   ================================================================ */

/* ---- 基础 ---- */
QMainWindow { background-color: #0D0D12; }

QWidget {
    color: #E8E8F0;
    font-family: "Inter", "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
    font-size: 11px;
    outline: none;
}

/* ---- 按钮系统 ---- */
QPushButton {
    background-color: #1C1C23;
    border: 1px solid #2A2A35;
    border-radius: 4px;
    padding: 4px 10px;
    color: #E8E8F0;
    font-weight: 500;
    min-height: 24px;
}
QPushButton:hover { background-color: #25252E; border-color: #3A3A4A; }
QPushButton:pressed { background-color: #2E2E3A; }
QPushButton:disabled { background-color: #141419; color: #5C5E6A; border-color: #1E1E26; }

/* 主按钮 */
QPushButton#primary {
    background-color: #2979FF;
    border-color: #2979FF;
    color: #FFFFFF;
}
QPushButton#primary:hover { background-color: #448AFF; border-color: #448AFF; }
QPushButton#primary:pressed { background-color: #1565C0; }

/* 危险按钮 */
QPushButton#danger {
    background-color: transparent;
    border-color: #FF5252;
    color: #FF5252;
}
QPushButton#danger:hover { background-color: rgba(255,82,82,0.1); }

/* ---- 工具按钮（无边框图标按钮）---- */
QToolButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px;
    color: #8B8D9A;
}
QToolButton:hover { background-color: #25252E; color: #E8E8F0; }
QToolButton:checked { background-color: rgba(41,121,255,0.15); color: #2979FF; }

/* ---- 输入框 ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #1A1A22;
    border: 1px solid #2A2A35;
    border-radius: 4px;
    padding: 3px 6px;
    color: #E8E8F0;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #2979FF;
}

/* ---- 分组框 ---- */
QGroupBox {
    background-color: transparent;
    border: 1px solid #2A2A35;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 8px;
    font-weight: 600;
    font-size: 11px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #8B8D9A;
}

/* ---- 表格 ---- */
QTableWidget {
    background-color: #141419;
    border: 1px solid #2A2A35;
    border-radius: 4px;
    gridline-color: #1E1E26;
    font-size: 10px;
}
QHeaderView::section {
    background-color: #1C1C23;
    padding: 4px 6px;
    border: none;
    border-right: 1px solid #2A2A35;
    font-weight: 600;
    font-size: 10px;
    color: #8B8D9A;
}

/* ---- Splitter ---- */
QSplitter::handle {
    background-color: #1E1E26;
}
QSplitter::handle:horizontal { width: 2px; }
QSplitter::handle:vertical { height: 2px; }
QSplitter::handle:hover { background-color: #2979FF; }

/* ---- 滚动条 ---- */
QScrollBar:vertical {
    background-color: transparent;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #3A3A4A;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background-color: #5C5E6A; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ---- 侧边导航栏选中态 ---- */
SidebarNavButton:checked {
    background-color: #1C1C23;
    border-left: 3px solid #2979FF;
}
```

### 8.2 组件级样式规则

- **新组件优先使用类名样式**：`SidebarNav`, `FloatingPreviewBar`, `RightDrawer` 等通过 `setObjectName()` + 全局 QSS 选择器设置样式
- **不再使用内联 `setStyleSheet()`**：除动态计算的颜色外，所有样式集中到全局样式表
- **动态状态使用 QPalette 或属性选择器**：`[state="active"]`, `[state="error"]`

---

## 九、交互规范

### 9.1 快捷键表

| 快捷键 | 功能 | 适用模式 |
|--------|------|---------|
| `Space` | 拍摄（所有已连接相机） | 多相机/站位 |
| `Ctrl+S` | 保存当前帧到会话 | 多相机 |
| `Ctrl+D` | 检测标记 | 多相机 |
| `Ctrl+Shift+D` | 批量检测 | 多相机（离线） |
| `Tab` | 切换右侧面板页面 | 全局 |
| `Esc` | 退出相机大图预览 / 取消操作 | 全局 |
| `F11` | 3D 查看器全屏 | 全局 |
| `Ctrl+L` | 展开/收起日志面板 | 全局 |
| `Ctrl+B` | 展开/收起右侧面板 | 全局 |
| `1/2/3` | 切换多相机/站位/链式模式 | 全局 |

### 9.2 过渡动画规范

| 动画 | 时长 | 缓动 |
|------|------|------|
| 右侧面板展开/收起 | 200ms | ease-out |
| 日志面板展开/收起 | 150ms | ease-in-out |
| 预览栏悬停展开 | 100ms | ease-out |
| 3D 查看器最大化 | 250ms | ease-in-out |
| 按钮点击反馈 | 50ms | linear |
| 状态栏信息切换 | 200ms | ease-out |

### 9.3 状态反馈规范

- **加载中**：全局遮罩 + 居中 spinner + 操作描述文字
- **成功**：状态栏绿色闪烁 1 秒 + 日志记录
- **警告**：状态栏琥珀色 + 右侧提示徽标
- **错误**：状态栏红色 + 日志红色高亮 + 可选弹窗
- **进行中**：进度条（确定性）/ 脉冲动画（不确定性）

---

## 十、实施计划

### Phase 1：基础设施（不改动业务逻辑）

1. **创建新组件（空壳）**：
   - `sidebar_nav.py` — `SidebarNav`
   - `floating_preview_bar.py` — `FloatingPreviewBar`
   - `right_drawer.py` — `RightDrawer`
   - `compact_status_bar.py` — `CompactStatusBar`
   - `terminal_panel.py` — `TerminalPanel`（重构 CollapsibleLogPanel）
   - `viewport_switcher.py` — `ViewportSwitcher`

2. **新建全局样式文件**：
   - `styles/theme_v2.py` — 设计系统常量 + 全局样式表字符串

3. **保留所有现有组件**：不删除任何文件，通过新 MainWindow 选择性引用

### Phase 2：新 MainWindow 装配

1. **创建 `main_window_v2.py`**：
   - 复制现有 MainWindow 所有业务槽函数（`_on_*` 系列）
   - 重写 `_setup_ui()` 为新的布局架构
   - 重写 `_connect_signals()` 连接到新组件

2. **信号桥接**：
   - 新组件信号 → 复用现有槽函数
   - 确保零业务逻辑改动

### Phase 3：面板适配

1. 将现有 `CapturePanel` / `CalibrationPanel` / `StitchPanel` / `StationPanel` / `DevicePanel` 放入 `RightDrawer` 的 `QStackedWidget` 中
2. 微调各面板的内部布局，适应 320px 宽度（现有 380px → 320px 略窄，需要紧凑化）
3. `CameraPreviewCard` 的功能迁移到 `FloatingPreviewBar`

### Phase 4：测试与切换

1. 保留 `main_window.py` 作为回退
2. 通过入口参数或配置切换新旧 UI
3. 全面测试三种工作模式的所有功能路径

---

## 十一、文件结构

```
src/ui/
├── __init__.py
├── app.py                    # 入口（选择加载 v1/v2）
├── main_window.py            # 现有主窗口（保留）
├── main_window_v2.py         # 新主窗口（重构目标）
│
├── styles/
│   ├── __init__.py
│   ├── theme_v2.py           # 设计系统常量 + 全局 QSS
│   └── animations.py         # 过渡动画工具（QPropertyAnimation 封装）
│
├── components/               # 新布局组件
│   ├── __init__.py
│   ├── sidebar_nav.py        # 侧边导航栏
│   ├── floating_preview_bar.py  # 浮动预览栏
│   ├── right_drawer.py       # 右侧面板抽屉
│   ├── compact_status_bar.py # 紧凑状态栏
│   ├── terminal_panel.py     # 终端式日志面板
│   └── viewport_switcher.py  # 中央视口切换器
│
├── panels/                   # 现有功能面板（保留，微调）
│   ├── device_panel.py
│   ├── capture_panel.py
│   ├── calibration_panel.py
│   ├── stitch_panel.py
│   └── station_panel.py
│
├── workflows/                # 工作流视图
│   └── mobile_chain_view.py  # 保留
│
├── widgets/                  # 通用小部件
│   ├── wizard_step_bar.py    # 保留
│   ├── camera_card.py        # 保留（供预览栏内部使用）
│   ├── loading_overlay.py    # 保留
│   └── worker_thread.py      # 保留
│
├── viewer_3d.py              # 保留（3D 核心）
├── icons.py                  # 保留
└── launcher_window.py        # 保留（Phase 2 再重构）
```

---

## 十二、风险与回退

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 新布局导致信号连接遗漏 | 中 | 高 | 建立完整的信号映射表，逐项核对 |
| 320px 右侧面板太窄，控件溢出 | 中 | 中 | 预留 360px 备选方案，面板内部使用折叠组 |
| 浮动预览栏与 3D 视口冲突 | 低 | 中 | 预览栏使用 QWidget::raise() 始终置顶 |
| 动画卡顿（低配置机器） | 低 | 低 | 动画可配置关闭，使用瞬时切换 |
| 用户习惯现有布局不愿切换 | 中 | 低 | 保留 v1 入口，v2 作为可选 |

---

## 附录 A：现有完整接口清单

### A.1 信号总表

| # | 信号名 | 发射组件 | 参数 | 接收槽函数 | 用途 |
|---|--------|---------|------|-----------|------|
| 1 | `search_requested` | LauncherWindow | 无 | `_on_refresh_devices` | 查找设备 |
| 2 | `connect_requested(list)` | LauncherWindow | `List[int]` | `_on_add_cameras` | 添加相机 |
| 3 | `auto_ip_requested` | LauncherWindow | 无 | `_on_auto_configure_network` | 自动配IP |
| 4 | `capture_requested(str)` | CameraPreviewCard | `str` | `_on_capture_single` | 单拍 |
| 5 | `disconnect_requested(str)` | CameraPreviewCard | `str` | `_on_remove_camera` | 移除相机 |
| 6 | `preview_toggled(str,bool)` | CameraPreviewCard | `str,bool` | `_on_preview_toggled` | 2D预览开关 |
| 7 | `refresh_devices_requested` | DevicePanel | 无 | `_on_refresh_devices` | 刷新设备 |
| 8 | `cameras_added(list)` | DevicePanel | `List[int]` | `_on_add_cameras` | 添加相机 |
| 9 | `camera_remove_requested(str)` | DevicePanel | `str` | `_on_remove_camera` | 移除相机 |
| 10 | `auto_configure_network_requested(list)` | DevicePanel | `List[int]` | `_on_auto_configure_network` | 自动配IP |
| 11 | `capture_all_requested` | CapturePanel | 无 | `_on_capture_all` | 拍摄全部 |
| 12 | `capture_sequential_requested` | CapturePanel | 无 | `_on_capture_sequential` | 串行拍摄 |
| 13 | `continuous_capture_toggled(bool,int)` | CapturePanel | `bool,int` | `_on_continuous_toggled` | 连续拍摄 |
| 14 | `capture_params_changed(dict)` | CapturePanel | `dict` | `_on_capture_params` | 参数变更 |
| 15 | `save_frame_to_session_requested` | CapturePanel | 无 | `_on_save_frame_to_session` | 保存帧 |
| 16 | `save_session_requested` | CapturePanel | 无 | `_on_save_session` | 保存会话 |
| 17 | `load_session_requested` | CapturePanel | 无 | `_on_load_session` | 加载会话 |
| 18 | `batch_detect_requested` | CapturePanel | 无 | `_on_batch_detect` | 批量检测 |
| 19 | `batch_calibrate_requested` | CapturePanel | 无 | `_on_batch_calibrate` | 批量标定 |
| 20 | `detect_requested` | CalibrationPanel | 无 | `_on_detect_markers` | 检测标记 |
| 21 | `calibrate_pair_requested(ref,cam)` | CalibrationPanel | `str,str` | `_on_calibrate_pair` | 标定pair |
| 22 | `add_frame_requested` | CalibrationPanel | 无 | `_on_add_frame` | 累积帧 |
| 23 | `calibrate_multi_requested` | CalibrationPanel | 无 | `_on_calibrate_multi` | 多帧标定 |
| 24 | `clear_frames_requested` | CalibrationPanel | 无 | `_on_clear_frames` | 清空缓存 |
| 25 | `save_calibration_requested` | CalibrationPanel | 无 | `_on_save_calibration` | 保存标定 |
| 26 | `load_calibration_requested` | CalibrationPanel | 无 | `_on_load_calibration` | 加载标定 |
| 27 | `reference_changed(str)` | CalibrationPanel | `str` | `_on_reference_changed` | 参考相机变更 |
| 28 | `pair_selected(ref,cam)` | CalibrationPanel | `str,str` | `_on_pair_selected` | 选中pair |
| 29 | `marker_type_changed(str)` | CalibrationPanel | `str` | `_on_marker_type_changed` | 标记类型 |
| 30 | `stitch_requested` | StitchPanel | 无 | `_on_stitch` | 拼接 |
| 31 | `stitch_save_requested` | StitchPanel | 无 | `_on_stitch_save` | 拼接并保存 |
| 32 | `stitch_session_requested` | StitchPanel | 无 | `_on_stitch_session` | 批量拼接 |
| 33 | `process_params_changed(dict)` | StitchPanel | `dict` | `_on_process_params` | 后处理参数 |
| 34 | `auto_params_requested` | StitchPanel | 无 | `_on_auto_params` | 自动参数 |
| 35 | `refresh_devices_requested` | StationPanel | 无 | `_on_station_refresh_devices` | 站位刷新 |
| 36 | `connect_requested(int)` | StationPanel | `int` | `_on_station_connect` | 站位连接 |
| 37 | `disconnect_requested` | StationPanel | 无 | `_on_station_disconnect` | 站位断开 |
| 38 | `capture_station_requested` | StationPanel | 无 | `_on_capture_station` | 拍摄站位 |
| 39 | `station_removed(str)` | StationPanel | `str` | `_on_remove_station` | 删除站位 |
| 40 | `stations_cleared` | StationPanel | 无 | `_on_clear_stations` | 清空站位 |
| 41 | `new_session_requested` | StationPanel | 无 | `_on_new_station_session` | 新会话 |
| 42 | `capture_station_requested` | MobileChainView | 无 | `_on_mobile_capture_station` | 链式拍摄 |
| 43 | `undo_station_requested` | MobileChainView | 无 | `_on_mobile_undo_station` | 撤销机位 |
| 44 | `optimize_global_requested` | MobileChainView | 无 | `_on_mobile_optimize_global` | 全局优化 |
| 45 | `save_session_requested` | MobileChainView | 无 | `_on_mobile_save_session` | 保存链式 |
| 46 | `status_changed(str)` | EmbeddedPointCloudViewer | `str` | `_log` | 3D状态 |
| 47 | `maximize_toggled(bool)` | EmbeddedPointCloudViewer | `bool` | `_on_viewer_maximized` | 最大化 |
| 48 | `collapse_toggled(bool)` | EmbeddedPointCloudViewer | `bool` | `_on_viewer_collapse_toggled` | 折叠 |
| 49 | `step_clicked(int)` | WizardStepBar | `int` | （暂无连接） | 步骤点击 |
| 50 | `toggled(bool)` | CollapsibleLogPanel | `bool` | `_on_log_toggled` | 日志折叠 |
| 51 | `finished(result,error)` | WorkerThread | `any,str` | 各 `_on_done` | 后台完成 |

### A.2 公共方法总表

| 组件 | 方法 | 参数 | 返回值 | 用途 |
|------|------|------|--------|------|
| LauncherWindow | `selected_mode()` | 无 | `str` | 获取选择模式 |
| LauncherWindow | `selected_devices()` | 无 | `list` | 获取选中设备 |
| LauncherWindow | `set_devices(list)` | `List[str]` | 无 | 设置设备列表 |
| CameraPreviewCard | `update_frame(FrameData, markers)` | `FrameData, list` | 无 | 更新预览 |
| CameraPreviewCard | `update_captured()` | `FrameData` | 无 | 更新拍摄后 |
| CameraPreviewCard | `set_connected(bool)` | `bool` | 无 | 设置连接状态 |
| CameraPreviewCard | `set_title(str, str)` | `str, str` | 无 | 设置标题 |
| CameraPreviewCard | `set_capture_button_text(str, str)` | `str, str` | 无 | 设置按钮文字 |
| CameraPreviewCard | `set_preview_mode(bool, str)` | `bool, str` | 无 | 设置预览模式 |
| CameraPreviewCard | `stop_preview()` | 无 | 无 | 停止预览 |
| CameraPreviewCard | `is_preview_active()` | 无 | `bool` | 是否预览中 |
| EmbeddedPointCloudViewer | `set_pointcloud(str, pcd)` | `str, o3d.geometry.PointCloud` | 无 | 设置点云 |
| EmbeddedPointCloudViewer | `set_pointcloud_merged(pcd)` | `o3d.geometry.PointCloud` | 无 | 设置合并点云 |
| EmbeddedPointCloudViewer | `set_reference(str)` | `str` | 无 | 设置参考相机 |
| EmbeddedPointCloudViewer | `set_highlight(str, list)` | `str, list` | 无 | 高亮索引 |
| EmbeddedPointCloudViewer | `clear_highlight()` | 无 | 无 | 清除高亮 |
| EmbeddedPointCloudViewer | `remove_camera(str)` | `str` | 无 | 移除相机 |
| EmbeddedPointCloudViewer | `clear_all()` | 无 | 无 | 清除所有 |
| EmbeddedPointCloudViewer | `reset_view()` | 无 | 无 | 重置视角 |
| EmbeddedPointCloudViewer | `set_view_preset(str)` | `str` | 无 | 视角预设 |
| EmbeddedPointCloudViewer | `set_point_size(int)` | `int` | 无 | 点大小 |
| EmbeddedPointCloudViewer | `set_maximized(bool)` | `bool` | 无 | 最大化 |
| DevicePanel | `set_devices(list)` | `List[str]` | 无 | 设置设备 |
| DevicePanel | `add_camera_entry(str, str)` | `str, str` | 无 | 添加相机项 |
| DevicePanel | `remove_camera_entry(str)` | `str` | 无 | 移除相机项 |
| DevicePanel | `update_camera_entry(str, str)` | `str, str` | 无 | 更新相机项 |
| DevicePanel | `set_auto_configure_enabled(bool)` | `bool` | 无 | 启用自动配置 |
| CapturePanel | `get_capture_params()` | 无 | `dict` | 获取参数 |
| CapturePanel | `set_capture_enabled(bool)` | `bool` | 无 | 启用拍摄 |
| CapturePanel | `stop_continuous()` | 无 | 无 | 停止连续 |
| CapturePanel | `set_save_frame_enabled(bool)` | `bool` | 无 | 启用保存 |
| CapturePanel | `set_batch_enabled(bool)` | `bool` | 无 | 启用批量 |
| CapturePanel | `set_session_path(str)` | `str` | 无 | 设置会话路径 |
| CalibrationPanel | `set_camera_ids(list)` | `List[str]` | 无 | 设置相机ID |
| CalibrationPanel | `get_reference()` | 无 | `str` | 获取参考相机 |
| CalibrationPanel | `set_reference(str)` | `str` | 无 | 设置参考相机 |
| CalibrationPanel | `get_marker_type()` | 无 | `str` | 获取标记类型 |
| CalibrationPanel | `set_marker_type(str)` | `str` | 无 | 设置标记类型 |
| CalibrationPanel | `set_accumulated_frames(int)` | `int` | 无 | 设置累积帧数 |
| CalibrationPanel | `update_results(dict)` | `dict` | 无 | 更新结果 |
| CalibrationPanel | `show_matrix(np.ndarray)` | `np.ndarray` | 无 | 显示矩阵 |
| CalibrationPanel | `clear_results()` | 无 | 无 | 清除结果 |
| StitchPanel | `get_process_params()` | 无 | `dict` | 获取处理参数 |
| StitchPanel | `set_process_params(dict)` | `dict` | 无 | 设置处理参数 |
| StitchPanel | `set_result(int, float, str)` | `int, float, str` | 无 | 设置结果 |
| StitchPanel | `clear_result()` | 无 | 无 | 清除结果 |
| StitchPanel | `set_auto_notes(list)` | `List[str]` | 无 | 设置自动参数说明 |
| StitchPanel | `set_points_alert(bool)` | `bool` | 无 | 点数警告 |
| StationPanel | `set_devices(list)` | `List[str]` | 无 | 设置设备 |
| StationPanel | `set_connected(bool, str)` | `bool, str` | 无 | 设置连接状态 |
| StationPanel | `set_capture_enabled(bool)` | `bool` | 无 | 启用拍摄 |
| StationPanel | `add_station(str, str)` | `str, str` | 无 | 添加站位 |
| StationPanel | `remove_station(str)` | `str` | 无 | 移除站位 |
| StationPanel | `clear_stations()` | 无 | 无 | 清空站位 |
| StationPanel | `set_session_path(str)` | `str` | 无 | 设置会话路径 |
| MobileChainView | `add_station_to_timeline(str, int, float, str)` | `...` | 无 | 添加时间线 |
| MobileChainView | `update_evaluation(dict)` | `dict` | 无 | 更新评估 |
| MobileChainView | `set_preview_text(str)` | `str` | 无 | 设置预览文字 |
| MobileChainView | `set_3d_text(str)` | `str` | 无 | 设置3D文字 |
| WizardStepBar | `set_current(int)` | `int` | 无 | 设置当前步骤 |
| WizardStepBar | `set_step_done(int, bool)` | `int, bool` | 无 | 设置步骤完成 |
| WizardStepBar | `get_current()` | 无 | `int` | 获取当前步骤 |
| LoadingOverlay | `show_message(str)` | `str` | 无 | 显示加载 |
| LoadingOverlay | `hide_overlay()` | 无 | 无 | 隐藏加载 |
| CollapsibleLogPanel | `set_expanded(bool)` | `bool` | 无 | 设置展开 |
| CollapsibleLogPanel | `append(str)` | `str` | 无 | 追加日志 |
| CollapsibleLogPanel | `clear()` | 无 | 无 | 清空日志 |
| CollapsibleLogPanel | `set_status(str)` | `str` | 无 | 设置状态 |

---

*本文档为设计阶段输出，不修改任何现有代码。下一步：按 Phase 1 开始实现新组件空壳。*
