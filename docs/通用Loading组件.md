# 通用 Loading 组件

2026-10-22，随 1.12.38 接入。正式实现位于 `src/ui_common/loading.py`，只依赖 Qt 和 `ui_common.appearance`，无需设备、工作流或 `ui_v2`。

| 组件 | 用途 |
|---|---|
| `LoadingSpinner` | 可单独嵌入布局的旋转圆环 |
| `LoadingCard` | 圆环、操作标题和补充说明，适合嵌入面板 |
| `LoadingOverlay` | 覆盖父控件并居中显示卡片，自动跟随父控件缩放 |
| `LoadingAppearance` | 颜色、背景、边框、文字和卡片最大宽度配置，位于 `src/ui_common/appearance.py` |

## 窗口内提示

在 GUI 线程创建并持有组件，耗时任务继续使用现有后台工作线程：

```python
from ui_common.loading import LoadingOverlay

self.loading = LoadingOverlay(self)
self.loading.show_message('正在执行拼接', detail='原始帧保持独立')
# 也兼容原有中文分号分层文案：
self.loading.update_message('正在保存；请稍候...')
# 完成或失败的 GUI 回调都需关闭提示：
self.loading.hide_overlay()
```

默认鼠标穿透，保持主窗口已有业务门禁。需要拦截鼠标的窗口使用 `LoadingOverlay(self, block_input=True)`：同时显示暗色背景；连接窗口仍自行维护原有忙状态和键盘/按钮门禁。组件不自行创建任务、决定操作权限或提供取消操作。

`show_message()` 开始新动画周期，`update_message()` 保留当前动画相位。更新文本用纯文本显示；隐藏、关闭或父窗口隐藏时停止定时器，父控件销毁时由 Qt 释放。仅使用内部实际经过时间计算旋转相位，不显示“已用时”或虚构百分比。

## 单独嵌入与外观

```python
from ui_common.loading import LoadingCard, LoadingSpinner
from ui_common.appearance import LoadingAppearance

card = LoadingCard(appearance=LoadingAppearance(accent='#D32F2F', card_width=380))
card.set_message('正在加载点云', detail='请稍候')
layout.addWidget(card)

spinner = LoadingSpinner()  # 可放到其他面板；随可见性自动启停
layout.addWidget(spinner)
```

`LoadingCard.set_message()` 只更新文字，不负责启动业务或显示遮罩。颜色通过 `LoadingAppearance` 传入，公共层不反向导入业务主题。

## 正式接入与兼容

- A/B/C 三模式共用 `MainWindowShell.show_loading()` / `hide_loading()`，保留底部进度条及原先的业务门禁。
- `LauncherDialog.show_connection_overlay()` / `hide_connection_overlay()` 改为同一通用遮罩的阻止鼠标版本，保留连接状态和淡出流程。
- `src/ui_v2/widgets/loading_overlay.py` 仅保留 `LoadingOverlay` 的兼容导入，既有代码无需修改方法调用。不要在该文件重新实现动画。

## 验证

`test_loading_component.py` 覆盖独立导入、真实帧图变化、隐藏/关闭/销毁、更新文案不重启动画、中文分号与显式说明、无计时文字、卡片背景、窄窗口和鼠标策略，以及启动器与三模式正式入口。

离屏运行上述5项，加架构17项、启动器7项、离线预览7项、显式拼接15项和工业呈现8项，共59项通过。检查独立卡片、主窗口与启动连接截图。证据位于 `D:/RVC_SRC/.verify_reports/mcc-loading-20261022/`。

未初始化相机SDK，未做实际拼接高负载、客户GPU或安装包验证。该组件不解决主线程被耗时同步调用阻塞的问题，业务仍须使用后台线程。
