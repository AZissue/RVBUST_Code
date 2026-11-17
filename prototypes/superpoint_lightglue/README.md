# SuperPoint + LightGlue 无标记拼接原型

从 MCC 仓库根目录用本机 rvc Python 启动。默认进入与主程序相同的启动小窗，可以搜索相机、选择工作模式并连接设备。建议用「单相机移动拼接」做第一轮实机验证。

```powershell
$rvcPython = 'D:/Program Files/Anaconda/envs/rvc/python.exe'
& $rvcPython prototypes/superpoint_lightglue/run.py
```

1. 在启动小窗选择 **单相机移动拼接**，搜索并连接相机。
2. 在 **识别参数 → 识别类型** 选择 **SuperPoint + LightGlue（2D 特征）**，在 **拍摄参数** 将 **点云对应2D** 设为「是」。
3. 固定工件，点击 **拍摄机位** 保存第一帧作为参考。移动相机，保持相邻视角有足够重叠和纹理，再拍下一帧。
4. 采集完成后自动匹配两幅图的像素，从有序点图取对应 XYZ，拟合刚体变换，并把点云变换到首帧坐标系。通过检查后，主工作区会显示新的拼接结果，DB 保存原始帧和来源位姿。
5. 配准失败时查看运行日志。原始帧仍会入库，已拼接的结果保留，下一次拍摄继续和最近一次成功入链的帧匹配。首次配对尚未成功时，继续以首帧为参考。

原型无需训练，也无需框选或手动匹配。当前在整幅图上寻找特征，默认 3D 内点容差为 2 mm，取点邻域最大深度差为 5 mm。相机移动时保持工件和背景相对静止；如果工件在转台上转动、背景固定，不能用这一流程验证工件位姿。

使用已保存的会话复验时，显式传入单相机移动拼接的会话目录或 `session.json`。进入离线工作区后选择同一识别类型，按拍摄顺序选中或勾选原始帧，再点 **执行拼接**。离线验证使用会话副本。

```powershell
$earbudSession = (Get-ChildItem sessions -Directory -Filter '*0dc20d90').FullName
& $rvcPython prototypes/superpoint_lightglue/run.py --session $earbudSession
```

## 预训练文件

本机已有上一轮的 CPU 推理环境，原型从 `outputs/experiments/superpoint_lightglue/` 读取 `deps`、`upstream` 和 `weights`。模型在首次配准时加载。两项权重文件都从本地读取。

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

## 自动模式验证

离线复验「耳机 I3360」移动拼接会话的前两帧：916 对像素匹配，661 对有有效深度，446 对通过刚体检查。3D 内点拟合 RMS 为 0.622 mm，DB 保存 4,817,546 个有效点及两帧位姿。该残差用于判断这对帧的拟合效果，不能代表外部测量精度。

## 历史验证：手工选区

| 数据 | 参数与结果 |
|---|---|
| 耳机 I3360，第 1→2 帧 | 手工矩形。2 mm 容差下，44 对匹配、18 对通过深度检查、18 对通过刚体检查。内点 RMS 0.505 mm，合并 140,937 点。相对会话已保存的拼接变换，旋转相差约 0.61°。在这 18 个移动帧采样点上，两种变换后的点位差 RMS 约 0.14 mm。 |
| 蓝色摆件，第 7→8 帧 | 同一组选区在 2 mm 容差下被拒绝。3 mm 下，65 对匹配中有 58 对通过深度检查，42 对通过刚体检查，内点 RMS 1.574 mm，合并 403,228 点。 |
| 深色石块，第 2→3 帧 | 2 mm 容差下，59 对匹配中有 43 对通过深度检查，刚体共识不足，拒绝拼接。 |

工业界面使用鼠标重新框选耳机第 1、2 帧后，得到 47 对匹配、18 对有效深度和 18 对内点，内点 RMS 为 0.528 mm。发布到工业 DB 的 PLY 有 143,683 个有限坐标点并带 RGB，DB 中记录了参考帧和移动帧的变换。

这些数据来自旧版双帧手工选区流程，不能作为当前自动识别的成功率。内点 RMS 是拟合残差，原型还需用更多视角、无标记物实采和多帧闭环来评估稳定性。人工矩形中若混入静止背景，模型仍可能优先匹配背景。

```powershell
$env:PYTHONPATH = 'src'
& $rvcPython -m unittest prototypes.superpoint_lightglue.test_pipeline prototypes.superpoint_lightglue.test_automatic prototypes.superpoint_lightglue.test_launch
```
