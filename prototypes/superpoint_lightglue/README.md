# SuperPoint + LightGlue 无标记拼接原型

从 MCC 仓库根目录用本机 rvc Python 启动。默认进入与主程序相同的启动小窗，可以搜索相机、选择工作模式并连接设备。建议用「单相机移动拼接」做第一轮实机验证。

```powershell
$rvcPython = 'D:/Program Files/Anaconda/envs/rvc/python.exe'
& $rvcPython prototypes/superpoint_lightglue/run.py
```

1. 在启动小窗选择 **单相机移动拼接**，搜索并连接相机。
2. 在 **识别参数 → 识别类型** 选择 **SuperPoint + LightGlue（2D 特征）**，在 **拍摄参数** 将 **点云对应2D** 设为「是」。
3. 固定工件，点击 **拍摄机位** 保存第一帧作为参考。移动相机，保持相邻视角有足够重叠和纹理，再拍下一帧。
4. 原始帧写入 DB 后可继续拍摄。后台按入库顺序处理每一帧，尝试与最近三个已入链机位匹配，用通过检查的 3D 对应点共同拟合位姿。拼接结果在首帧坐标系中累积，DB 保存原始帧、结果和来源位姿。
5. 打开 **2D 图像** 或点击 DB 帧下的 **2D 图像**。页面显示内点最多的一组匹配及配对帧号。绿色是 3D 内点，红色是外点，黄色是至少一侧无有效深度的 2D 匹配。叠加点在本次运行中可查看，重开会话后可点 **执行拼接** 重新生成。
6. 配准失败时可查看 2D 页面和运行日志。失败帧仍保留在 DB，后续配准使用已入链机位。首次配对尚未成功时继续以首帧为参考。

如果背景容易抢占匹配，在采集一帧后打开 **识别参数 → 匹配区域（ROI）→ 绘制 ROI**。在选中的原始帧上框住需要匹配的区域，未选中原始帧时使用最新一帧。框选以图像比例保存在会话中，后续参考帧和当前帧使用同一个区域。请留出足够余量覆盖工件在各帧中的位置。需要让已有帧按新 ROI 重算时，点击 **执行拼接**。点击 **恢复整图** 可清除 ROI。

ROI 只限制提取和匹配特征的范围，匹配点仍显示在原始像素位置，成功配准后仍合并整帧点云。在 **识别参数 → 2D 检测与 3D 配准** 可调整检测长边、特征点上限、匹配分数下限、深度跳变上限、3D 内点容差和最低内点比例。默认值分别为 1024 px、2048 点、0.10、5 mm、2 mm 和 60%。至少需要 6 对内点。参数随会话保存，修改后点击 **执行拼接** 可用相同原始帧复验。移动拼接时保持工件固定。若工件随转台转动，ROI 应排除静止背景，并保留足够多随工件一起运动、可取深度的特征。

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

离线复验「耳机 I3360」移动拼接会话的前两帧：916 对像素匹配，661 对有有效深度，446 对通过刚体检查。3D 内点拟合 RMS 为 0.622 mm，DB 保存 4,817,546 个有效点及两帧位姿。同一会话的前四帧中，第 4 帧使用三个参考机位，得到 1,372 对 3D 内点，拟合 RMS 0.634 mm，拼接结果共 9,635,329 点。RMS 表示对应点拟合残差。

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
