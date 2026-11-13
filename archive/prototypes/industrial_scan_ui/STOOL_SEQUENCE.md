# 凳子逐帧拼接临时演示

此入口复用工业扫描原型与 GPU 点云视区。右上角图像与编码圆面板已成为 ScanWorkbench 的可复用功能；正式业务 UI 不受影响。

数据准备：

```powershell
python prototypes/industrial_scan_ui/prepare_stool_sequence.py 'E:/jingz/Desktop/凳子拼接' 'D:/RVC_SRC/outputs/stool-sequence/cache'
```

运行：

```powershell
python prototypes/industrial_scan_ui/run_stool_sequence.py --cache D:/RVC_SRC/outputs/stool-sequence/cache
```

参数 `--video <mp4>` 逐帧导出实际 Qt/OpenGL UI，完成后保留可交互窗口；`--verify` 检查八阶段 GPU 累积、颜色分类、网格关闭与重播复位。

8 组原始 PNG/PLY 分别检测编码圆，用共有有效编码计算 cam→reference 刚性变换，按有效共有数量最多且 RMS≤2 mm、内点率≥0.4 的已注册参考帧进行配准。地面编码圆平面用于摆正场景。该数据集 2–8 帧均选中首帧为参考，最大内点拟合 RMS 约 0.8293 mm；这仅是标记配准拟合残差，不是设备绝对精度。

显示每帧稳定随机采样 600,000 点，共 4,800,000 点。采样仅用于预览，配准使用实测标记坐标，原始 PLY/PNG 不修改。缓存不应作为全分辨率拼接成果导出。

每 3.4 秒叠加一帧，先停留再平滑转动约 9°，八帧后停留，总视频约 29.2 秒。参考网格关闭。右上角显示当前帧图像、检测数量与 ID，点击“编码圆数据”查看像素坐标和相机 XYZ（mm）。

- 绿色：2D 检出且有有效实测 XYZ，未被当前拼接对选为红色。
- 红色：当前帧与明确指定参考帧共有、两边均有有效 XYZ 且 ID 唯一的同码圆。若提供求解器 used_codes，则只标内点；被剔除或配准失败的圆不标红。
- 黄色：仅 2D 检出，没有有效 XYZ，不参与拼接。

3D 视区累积保留历史有效圆，按 ID 去重，当前红色覆盖绿色。GPU 使用独立的小标记缓冲和深度测试，不在每次鼠标移动时扫描点云；软件兼容预览的二维投影标记不提供遮挡保证。2D 面板只统计当前帧，另外列出累积 3D 红绿数量。

本组数据首帧有 34 个可用圆，后续帧的有效圆全部存在于首帧，因此当前帧可能全红，累积场景仍有其余绿色圆。不人为改变红绿数量。旧缓存未记录求解器内点时，明确显示“共有可配对”；新准备脚本额外保存 used_codes / rejected_codes / registration_accepted，不把旧 shared 字段冒充内点。

通用原型可在选中点云图层后点击“载入2D结果”，载入 JSON：

```json
{
  "frame_id": 2,
  "image": "2.png",
  "reference_id": 1,
  "used_codes": [31],
  "markers": [
    {"code": 31, "x_2d": 120, "y_2d": 240, "valid_3d": true,
     "x_3d": 10, "y_3d": 20, "z_3d": 500, "world": [15, 25, 500]}
  ]
}
```

图像路径相对 JSON；像素坐标不归一化，相机 XYZ 与世界坐标均为 mm。参考图层也需先关联检测结果，或通过 reference_markers 直接提供参考帧检测列表。world 必须是经过拼接变换后的坐标，缺失时只显示 2D 标记；不把相机坐标直接当成世界坐标。也可由控制器调用 set_frame_observation。未关联图像或检测结果的普通 PLY 不伪造编码圆。

“重新播放逐帧拼接”从首帧重播；播放后保留普通旋转、平移、缩放与图层显隐操作。该入口是离线回放，不连接相机、不执行真实扫描。
