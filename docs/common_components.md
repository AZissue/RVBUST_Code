# 公共组件维护说明

本说明对应正式程序的工业工作区。整理代码时保持现有工业风格、操作门禁及会话格式；公共能力按职责复用，不把整个业务工作区搬入通用控件层。

## 组件索引

| 能力 | 入口 | 职责与边界 |
|---|---|---|
| 加载动画 | `src/ui_common/loading.py` | 动画、提示卡、随父窗口定位的遮罩；只负责展示与计时器生命周期 |
| 运行日志 | `src/ui_common/activity_log.py` | 有界日志、等级筛选、搜索和自动滚动 |
| 参数滑块 | `src/ui_common/parameter_slider.py` | 数值输入、范围、未知值占位及滑块同步；不读写相机 |
| 防误滚轮 | `src/ui_common/setting_wheel_guard.py` | 保护设置控件，滚轮交给外层滚动区 |
| 2D 预览 | `src/ui_common/image_preview.py` | 图像呈现与交互 |
| 3D 视窗 | `src/ui_common/industrial_viewer.py`、`industrial_scene/` | 渲染、导航、标记检查；不负责标定和拼接求解 |
| 标记显示语义 | `src/ui_common/industrial_scene/marker_display.py` | 标记有效性、配对颜色、相机坐标点和历史世界坐标点的转换 |
| 标定结果窗口 | `src/ui_common/calibration_result.py` | 独立结果快照、3D 对齐、误差图表与矩阵；不读取文件或调用设备，接入见 `calibration_result_component.md` |
| 点云后处理 | `src/ui_v2/postprocess/`、`src/core/postprocess/` | 复用当前项目 DB、独立编辑图层、后台处理及结果分支写回；操作和边界见 `pointcloud_postprocess.md` |
| 后台 Qt 任务 | `src/ui_common/worker_thread.py` | 工作线程及结果信号；业务回填由调用层处理 |
| DB 树与选择 | `src/ui_v2/frame_database.py` | 数据树、右键操作、选中对象与预览的业务接线 |
| DB 多帧显示 | `src/ui_v2/db_cloud_overlay.py` | 勾选帧的异步读取、显示缓存和叠加；不修改几何或应用标定变换 |
| 对象属性 | `src/ui_v2/widgets/db_properties.py` | 按选中数据展示属性，连接公共 3D 控制和拍摄参数页 |
| 拍摄参数页 | `src/ui_v2/widgets/capture_parameters.py` | 参数分组、相机切换、读写请求与失效回调保护 |
| 识别参数页 | `src/ui_v2/widgets/recognition_parameters.py` | 当前识别类型、标定板规格及 Gamma；离线可用，应用后更新后台识别配置 |
| 相机参数服务 | `src/core/capture_parameters.py` | SDK 能力与范围查询、参数读写、锁及失败处理 |
| 后台识别 | `src/ui_v2/background_recognition.py`、`src/core/frame_recognition.py` | UI 调度与结果回填、独立检测配置和缓存；生命周期见 `background_recognition.md` |

表中 `ui_v2` 模块是三种工作模式共用的业务组件；`ui_common` 是可独立复用的展示组件。二者不要互相循环引用。

## 本次统一的接口

- 数值控件通过 `ParameterSlider.set_range()`、`set_value()`、`value()` 和 `set_unloaded()` 使用。未知值不显示虚构的相机参数；启用状态由业务页决定。内部 `spin`、`slider` 保留供 Qt 信号和焦点接线兼容。
- 拍摄参数页将字段构建、结果展示、待应用值收集分开。界面没有修改的字段继续使用 SDK 原始精度，调整后自动合并更新目标相机（约 250 ms 间隔），在飞更新完成后只补发最新编辑；失败保留原缓存，禁止无编辑时反复重试。
- 单帧 DB、勾选叠加和后台识别刷新统一调用 `classify_markers(...).cloud_points()`。排除无编码或无有效深度的行，保留相机实测坐标、颜色、顺序及跨帧重复编码。历史世界坐标显示继续使用 `cumulative_world_markers()`，不能混用。

## 后续维护约束

1. UI 公共控件不持有设备句柄，不初始化 SDK，不执行磁盘点云读取或识别计算。
2. 模式差异通过业务接线处理；通用显示规则只保留一份实现。
3. 异步结果回填校验相机或项目身份与数据版本，关闭时停止定时器并等待必要任务；不让旧回调覆盖新对象。
4. 复用现有颜色、图标和控件样式；不因内部整理调整按钮布局、视角或用户设置。
5. 使用现有针对性回归验证参数精度、离线占位、切换失效、防误滚轮、DB 预览及后台回填。离屏结果不等同实机与 GPU 验收。

## 拍摄参数范围依据

本机 SDK：`D:/Program Files/RVBUST/RVC/RVCSDK`。`include/RVC/RVC.h` 为 X1/X2 提供 `GetExposureTimeRange`、`GetGainRange`、`GetGammaRange`，页面及写入校验使用当前相机查询结果，不硬编码曝光/增益/Gamma 通用范围。查询失败时不开放相应无可靠范围的设置。浮点控件向范围内部取整，避免显示精度将端点扩到 SDK 范围外。

`examples/Python/AdjustCaptureParameter.py` 标注投影亮度 1～240；按本项目要求编辑范围设为 0～240，0 保留为关闭亮度设置，上限 240。数值在 SDK 参数保存前再次校验；具体型号是否接受 0 仍以实机 SDK 返回为准，失败保留原有效参数。

自动调参沿用 SDK `SaveCaptureOptionParameters` 和采集锁更新流程；实时取景开启时，后续帧使用更新后的参数。只修改 3D 曝光/增益的效果需要下一次 3D 拍摄查看，2D 取景不反映 3D 点云质量变化。

## 线扫与面阵曝光区分

- SDK 依据：`include/RVC/RVC.h:2230`、`examples/Python/X2SwingLineScanMode.py` 及 `X2FixedLineScanMode.py`。面阵使用 `exposure_time_3d`（ms）；摆动/固定线扫使用 `line_scanner_exposure_time_us`（µs），例如 SDK 示例值 300。修改线扫曝光时保留面阵曝光、扫描时间、HDR 等其他设置。
- 当前 SDK 没有独立的单行曝光范围查询。该字段未取得设备上下限前使用整数输入，暂不显示会误导用户的全范围滑块；整数类型范围不宣称为设备允许范围。SDK 拒绝时保留原有效缓存并显示原始错误，若错误包含明确上下限，重新读取后使用设备返回范围及滑块；断开设备时清除已知范围。
- 切换拍摄模式后重新生成适用字段，面阵与线扫曝光互斥显示；不同字段集合的旧页面编辑不会续发到新模式。
- 相机下拉框的显示名称和 SN 与内部 camera ID 分离，改名和换机不把显示文本作为采集或写入目标。
- 四个属性页签采用紧凑字号与间距，覆盖 290 px 侧栏；相机刷新使用图标按钮，完整名称与 SN 同时提供悬浮提示。
