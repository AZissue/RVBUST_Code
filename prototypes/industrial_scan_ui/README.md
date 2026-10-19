# 工业扫描 UI 原型

根据用户提供的扫描工作站演示视频，提取顶部功能带、左侧项目树与参数、大面积灰色 3D 视区、底部扫描进度的布局。视频是视觉参考；未复制第三方品牌、程序素材或假定其中不可辨认的参数含义。

本目录独立运行，不修改正式 `src/`，不依赖旧 `ui`，不初始化相机 SDK。

## 运行

在 MCC 根目录执行：

也可直接双击本目录 `run.cmd` 启动。

```powershell
& 'D:/Program Files/Anaconda/envs/rvc/python.exe' prototypes/industrial_scan_ui/run.py
```

依赖使用现有 rvc 环境：PySide6、NumPy、Open3D。预览采用 Qt 软件绘制，不要求 OpenGL；首次文件导入/导出会加载 Open3D。

## 可操作内容

- 演示点云默认显示弯曲板件和背景平面；鼠标左键旋转，右键或 Shift 拖动平移，滚轮缩放，双击适配。
- 模拟扫描可开始、暂停、继续与完成；采样间距改变生成密度，演示时长改变进度速度。所有扫描点云均为合成数据，不执行真实采集、配准或精度检验。
- 项目树控制图层选择与显隐。背景移除对选定图层保留 `Z > 阈值` 的点；删除和裁切支持最多十步撤销。
- 导入 PLY/PCD/XYZ/PTS；必须先选择源单位。m 转为内部 mm，导出始终为 mm。
- 导出完整可见点云到 PLY，视区最多采样显示 18,000 点。预览采样不会改变导出数据；软件预览不提供严格的深度缓冲、点拾取或大点云性能承诺。
- 点大小、原始/高度/统一颜色、网格、坐标轴、等轴测/顶/正/右视图和视区截图可用。
- 顶部 A/B/C 场景下拉仅切换演示标签，共用模拟流程，不是正式业务模式接入。
- 新建/关闭时提示未导出修改；当前不实现项目会话保存与恢复。点云导出不等于完整项目保存。

## 并入边界

`ScanWorkbench` 是可嵌入 QWidget，暴露 `set_devices`、`set_state`、`current_state`、`set_background_runner` 和日志/脏状态信号。设备描述只显示，不连接硬件。文件 I/O 默认由后台 WorkerThread 执行，亦可注入统一 runner。

它目前是独立交互设计验证，不完整实现正式 A/B/C 工作区协议；`save_session_requested` 预留给后续会话集成，尚未绑定项目保存按钮。正式并入前需要将布局接到既有业务命令、结果接口、会话保存及关闭门禁。

## 验证

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONIOENCODING='utf-8'
& 'D:/Program Files/Anaconda/envs/rvc/python.exe' prototypes/industrial_scan_ui/tests/test_prototype.py
& 'D:/Program Files/Anaconda/envs/rvc/python.exe' prototypes/industrial_scan_ui/run.py --screenshot 'D:/RVC_SRC/.verify_reports/industrial_scan_ui.png'
```

通过线：unittest 全通过且退出码 0；截图生成且人工查看布局。测试覆盖模拟状态机、按钮接线、暂停门禁、显隐/裁切/撤销/删除、单位转换和真实文件往返、预览采样预算、鼠标操作、后台线程回收与注入 runner。
