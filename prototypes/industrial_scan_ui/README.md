# 工业扫描 UI 原型

根据用户提供的扫描工作站演示视频，提取顶部功能带、左侧项目树与参数、大面积灰色 3D 视区、底部扫描进度的布局。视频是视觉参考；未复制第三方品牌、程序素材或假定其中不可辨认的参数含义。

本目录独立运行，不修改正式 `src/`，不依赖旧 `ui`，不初始化相机 SDK。

## 运行

Python 3.10+ 开发环境中，在 MCC 根目录执行：

```powershell
python -m pip install -r prototypes/industrial_scan_ui/requirements.txt
python prototypes/industrial_scan_ui/run.py
```

也可在已配置 Python 的开发环境双击 `run.cmd`。客户使用打包后的 EXE，不依赖开发机 Python/Conda 或绝对路径；打包与兼容性说明见 [RENDERING.md](RENDERING.md)。

正常桌面环境使用 Qt＋标准 OpenGL 3.3 GPU 渲染；首次点云文件导入/导出会加载 Open3D。无可用 OpenGL 时明确降级为兼容软件预览。

## 可操作内容

- 演示点云默认显示弯曲板件和背景平面；鼠标左键旋转，右键或 Shift 拖动平移，滚轮缩放，双击适配。
- 模拟扫描可开始、暂停、继续与完成；采样间距改变生成密度，演示时长改变进度速度。所有扫描点云均为合成数据，不执行真实采集、配准或精度检验。
- 项目树控制图层选择与显隐。背景移除对选定图层保留 `Z > 阈值` 的点；删除和裁切支持最多十步撤销。
- 导入 PLY/PCD/XYZ/PTS；必须先选择源单位。m 转为内部 mm，导出始终为 mm。
- 导出完整可见点云到 PLY；GPU 按帧增量缓存，默认静止最多 500 万点、拖动 50 万点，停止约 220 ms 后恢复。细节档为 1000 万/100 万点，流畅档为 100 万/10 万点；均为全场景预算。采样不改变原始帧与导出数据。
- 兼容软件预览静止 18,000 点、拖动 3,000 点；状态栏显示实际后端及原始/显示点数。未实现点拾取，不保证所有客户硬件的固定帧率。
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
python prototypes/industrial_scan_ui/tests/test_prototype.py
python prototypes/industrial_scan_ui/tests/test_render_cache.py
python prototypes/industrial_scan_ui/run.py --screenshot preview.png
```

通过线：unittest 全通过且退出码 0；截图生成且人工查看布局。原生 GPU 测试命令与客户验收范围见 [RENDERING.md](RENDERING.md)，结果见 [VALIDATION.md](VALIDATION.md)。
