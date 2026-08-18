# 离线拼接测试工具

> 位置：`D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\offline_stitch`  
> 目标：不连相机，直接读取本地图像+点云文件对，做标记物检测与点云拼接验证。  
> 范围：仅基础功能，不生成额外 JSON 配置文件。

---

## 文件结构

```
offline_stitch/
├── core/
│   └── offline_stitcher.py      # 离线拼接核心：文件扫描、检测、ChainStitcher 拼接
├── app/
│   └── simple_ui.py             # PySide6 测试 UI
└── README.md
```

---

## 数据格式要求

把数据放在同一个文件夹下，图像和点云文件名一一对应即可：

```
data/
├── 1.png
├── 1.ply
├── 2.png
├── 2.ply
├── 3.png
├── 3.ply
└── ...
```

支持的图像格式：`.png`、`.jpg`、`.jpeg`、`.bmp`  
支持的点云格式：`.ply`

---

## 启动 UI

```bash
cd D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\offline_stitch\app
"D:\Program Files\Anaconda\envs\rvc\python.exe" simple_ui.py
```

---

## 使用步骤

1. 点击 **「选择数据文件夹」**，选中存放图像和点云的目录；
2. 左侧列出所有匹配的文件对（如 `1`、`2`、`3`…）；
3. 点击文件对：
   - 右上显示 2D 图像，并用**红点**标出检测到的编码圆圆心；
   - 右下 3D 预览框显示对应点云；
4. 点击 **「开始拼接」**：
   - 自动对每对文件做 2D/3D 检测；
   - 用 ChainStitcher 做相邻帧配准与合并；
   - 3D 预览框切换为合并结果；
   - 日志区输出节点数、边数、合并点数；
5. 拼接完成后可保存合并 PLY。

---

## 注意事项

- 点云与图像分辨率需要一致（点云总点数 = 图像宽 × 图像高），否则无法把 2D 圆心映射到 3D；
- 当前只做基础功能：相邻帧按顺序拼接，暂不支持闭环优化、手动选择参考帧等高级功能；
- 无额外配置文件，所有结果在内存中计算。
