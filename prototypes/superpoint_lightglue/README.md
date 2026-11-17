# SuperPoint + LightGlue 无标记拼接原型

从 MCC 仓库根目录用本机 rvc Python 启动。默认进入与主程序相同的启动小窗，可以搜索相机、选择工作模式并连接设备。建议用「单相机移动拼接」做第一轮实机验证。

```powershell
$rvcPython = 'D:/Program Files/Anaconda/envs/rvc/python.exe'
& $rvcPython prototypes/superpoint_lightglue/run.py
```

连接后，在拍摄参数里开启 **点云对应2D**。用 **拍摄机位** 从两个有重叠的视角采集同一个工件，等待原图和点云写入当前 DB，再打开 **点云后处理**。

使用保存的数据复验时，显式传入会话目录或 `session.json`，原型会打开离线工作区和后处理窗口。

```powershell
$earbudSession = (Get-ChildItem sessions -Directory -Filter '*0dc20d90').FullName
& $rvcPython prototypes/superpoint_lightglue/run.py --session $earbudSession
```

1. 在后处理窗口点 **2D 特征拼接**。选择参考帧和移动帧。两帧都需要原图和同尺寸、逐像素对齐的有序点图。
2. 在两幅图上分别拖框选中同一工件，尽量避开标记和静止台面。耳机 I3360 可先选第 1、2 帧，在转台中央框住整只耳机，略留边缘。
3. 点 **匹配像素并计算 3D 变换**。程序在后台加载本地预训练模型、匹配原图像素、从两侧点图插值取 XYZ，并拟合移动帧到参考帧的刚体变换。默认 3D 容差为 2 mm，取点邻域的最大深度差为 5 mm。
4. 看同编号点和报告。绿色通过 3D 筛选，黄色是 3D 外点，红色是深度无效或不连续。满足刚体共识及空间分布要求后，**确认并生成拼接结果** 把两帧选区的有效点及颜色加入工业 DB 和 3D 视口，并记下各来源变换。回到主窗口可保存独立实验会话。

## 预训练文件

本机已有上一轮的 CPU 推理环境，原型从 `outputs/experiments/superpoint_lightglue/` 读取 `deps`、`upstream` 和 `weights`。模型在首次分析时加载。两项权重文件都从本地读取。

其他工作副本可以在 MCC 仓库根目录按以下方式准备同一环境。额外依赖装入原型目录的 `deps`。

```powershell
$modelDir = 'outputs/experiments/superpoint_lightglue'
New-Item -ItemType Directory -Force "$modelDir/weights/hub/checkpoints" | Out-Null
git clone https://github.com/cvg/LightGlue.git "$modelDir/upstream"
git -C "$modelDir/upstream" checkout 5a650c444718caffc2669dc0094cde908f42dd73
& $rvcPython -m pip install --target "$modelDir/deps" --index-url https://download.pytorch.org/whl/cpu --no-deps torch==2.6.0+cpu torchvision==0.21.0+cpu
& $rvcPython -m pip install --target "$modelDir/deps" filelock typing_extensions sympy networkx jinja2 fsspec
& $rvcPython -m pip install --target "$modelDir/deps" --no-deps kornia==0.8.2 kornia-rs==0.2.0
$release = 'https://github.com/cvg/LightGlue/releases/download/v0.1_arxiv'
Invoke-WebRequest "$release/superpoint_v1.pth" -OutFile "$modelDir/weights/hub/checkpoints/superpoint_v1.pth"
Invoke-WebRequest "$release/superpoint_lightglue.pth" -OutFile "$modelDir/weights/hub/checkpoints/superpoint_lightglue_v0-1_arxiv.pth"
```

商业集成前需要核对原版 SuperPoint 推理代码和权重的授权条款。 [LightGlue](https://github.com/cvg/LightGlue) · [SuperPoint 许可](https://github.com/magicleap/SuperPointPretrainedNetwork/blob/master/LICENSE)

## 保存会话验证

| 数据 | 参数与结果 |
|---|---|
| 耳机 I3360，第 1→2 帧 | 手工矩形。2 mm 容差下，44 对匹配、18 对通过深度检查、18 对通过刚体检查。内点 RMS 0.505 mm，合并 140,937 点。相对会话已保存的拼接变换，旋转相差约 0.61°。在这 18 个移动帧采样点上，两种变换后的点位差 RMS 约 0.14 mm。 |
| 蓝色摆件，第 7→8 帧 | 同一组选区在 2 mm 容差下被拒绝。3 mm 下，65 对匹配中有 58 对通过深度检查，42 对通过刚体检查，内点 RMS 1.574 mm，合并 403,228 点。 |
| 深色石块，第 2→3 帧 | 2 mm 容差下，59 对匹配中有 43 对通过深度检查，刚体共识不足，拒绝拼接。 |

工业界面使用鼠标重新框选耳机第 1、2 帧后，得到 47 对匹配、18 对有效深度和 18 对内点，内点 RMS 为 0.528 mm。发布到工业 DB 的 PLY 有 143,683 个有限坐标点并带 RGB，DB 中记录了参考帧和移动帧的变换。

这是双帧选区验证。内点 RMS 是拟合残差，原型还需用更多视角、无标记物实采和多帧闭环来评估稳定性。人工矩形中若混入静止背景，模型仍可能优先匹配背景。

```powershell
& $rvcPython -m unittest prototypes.superpoint_lightglue.test_pipeline
```
