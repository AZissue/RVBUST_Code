# 功能入口与模式工作区

当前变更先在工业扫描原型中实现。正式程序 main.py 的 LauncherDialog、设备连接和 A/B/C 工作流继续保留；本次没有用离线按钮替换生产采集流程。

## 启动

```powershell
python prototypes/industrial_scan_ui/run.py
```

默认打开功能小窗，选定方案后进入对应主界面。顶部“选择功能”可返回小窗；取消保持当前界面，相同功能及相同槽位数量不重建。切换会确认未导出数据，正在扫描或运行任务时禁止切换。新工作区创建成功才清理旧工作区，创建失败保留当前数据。

可直接进入指定功能：

```powershell
python prototypes/industrial_scan_ui/run.py --mode multi_cam --camera-count 4
python prototypes/industrial_scan_ui/run.py --mode mobile_chain
python prototypes/industrial_scan_ui/run.py --mode turntable
```

--screenshot <png> 自动进入工作区截图，未指定模式时使用移动链式布局。--launcher-screenshot <png> 单独输出入口小窗截图。原有 --renderer 和 --self-test-io 保留。

## 三种布局

| 功能 | 2D与3D | 专属操作 |
|---|---|---|
| 多相机外参标定 | 2～16路独立2D图像网格，旁边保留3D预览；4路默认两行完整显示 | 选择参考相机；各路载入图像/检测JSON；调用现有 CalibrationEngine 计算离线外参；保存 JSON |
| 单相机移动链式拼接 | 大型3D视区，右上角当前帧2D | 复用帧列表、配准质量卡、编码圆信息和底部日志 |
| 转台拼接 | 沿用扫描布局，左侧增加转台标定 | 载入 frame0/frame1 检测JSON；调用现有 TurntableCalibrator 计算轴、中心、角度和步数；标定失效时禁用模拟扫描 |

画面槽位不是已连接设备。没有硬件控制器时，实时拍摄按钮禁用。转台采集间隔通过 acquisition_settings_changed 信号提供给后续控制器；当前原型的模拟扫描仍只生成合成点云，不控制转台，也不将合成点云描述为实测拼接成果。

## 离线输入

```json
{
  "units": "mm",
  "image": "cam1.png",
  "markers": [
    {"code": 31, "x_2d": 120, "y_2d": 240,
     "x_3d": 10, "y_3d": 20, "z_3d": 500, "valid_3d": true}
  ]
}
```

image 相对 JSON，允许仅提供标记坐标。坐标使用相机坐标系毫米值，像素位置不归一化；units 缺省为项目内部 mm，不接受直接传入米。重复 ID、无效深度和非有限 XYZ 不参与求解。转台 frame0/frame1 需至少3个共有非共线有效标记，转台标定不自行发明 RANSAC 内点率。

多相机外参输出明确记录 units=mm、direction=camera_to_reference 和参考相机。图像或参考相机更新后清除旧外参。各相机有效标记均载入后才能计算；相机对存在失败时禁止导出整套成功外参。

多路2D叠加沿用绿色有效、红色共有、黄色仅2D规则；有求解结果时排除离群圆，失败对不显示共有红圈。主程序旧默认预览的颜色策略未在本次全局替换，共用预览组件仅新增可选 display_color 输入。

## 扩展

core/functions.py 的 FunctionRegistry 是原型的统一目录。每项 FunctionSpec 声明标识、名称、说明、图标、相机数量范围和工作区工厂。入口自动列出注册项，不需要继续增加启动小窗的 if/elif。新增原型工作区继承 ModeWorkbench（或实现相同生命周期、日志与任务接口）并注册自己的工厂即可。创建工作区时进行数量校验。

纯文件处理功能可将相机数量范围和默认值均设为0；入口会显示“无需相机”，不强制所有未来功能都连接设备。

本注册表负责界面组合，不等于正式程序已支持任意新算法。新增真实功能还需要实现对应控制器、工作流和设备契约，并完成实机验证。现有生产 UiComposition/WorkspaceFactories 的三模式接线不受本原型影响。

## 验证

- tests/test_studio.py：入口数量规则、第四项注册、切换取消/忙碌/工厂失败保护、离线外参方向、转台标定与失效门控。
- tests/gpu_studio.py：原生三模式切换、多相机嵌套GPU视区、兼容模式替换及不导入相机模块；--report-dir 可指定输出目录。
- 原有原型测试、生产UI架构与图像叠加回归继续适用。
