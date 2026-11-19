# SuperPoint + LightGlue 无标记拼接原型

从 MCC 仓库根目录用本机 rvc Python 启动。默认进入与主程序相同的启动小窗，可以搜索相机、选择工作模式并连接设备。建议用「单相机移动拼接」做第一轮实机验证。

```powershell
$rvcPython = 'D:/Program Files/Anaconda/envs/rvc/python.exe'
& $rvcPython prototypes/superpoint_lightglue/run.py
```

1. 在启动小窗选择 **单相机移动拼接**，搜索并连接相机。
2. 在 **识别参数 → 识别类型** 选择 **SuperPoint + LightGlue（2D 特征）**，在 **拍摄参数** 将 **点云对应2D** 设为「是」。
3. 固定工件，点击 **拍摄机位** 保存第一帧作为参考。移动相机，保持相邻视角有足够重叠和纹理，再拍下一帧。
4. 拍摄只保存原始帧，后台读取图像，与之前最近的三个原始机位进行像素匹配并缓存。底部滚动进度条表示正在计算，期间可以继续拍摄、查看图像或调整参数。
5. 打开 **2D 图像** 查看缓存匹配。蓝点表示已匹配的像素，等待 3D 验证。只有点击 **执行拼接** 才读取对应点云、估计位姿并发布合并结果。
6. 执行时复用同一帧版本、ROI、掩膜和图像参数的匹配缓存。只改深度或 3D 配准参数时可以直接复用像素匹配。缺少的匹配及旋转重试按需补算。匹配尚未结束时点击执行，会先衔接当前匹配任务。
7. 手动配准后的绿点、红点、黄点分别表示 3D 内点、外点和无有效深度的匹配。日志列出实际接入关系，如 003→002。较大的视角变化仍需要具有共同可见区域的中间帧。

像素匹配缓存在当前运行中有效。重拍、删除、变更 ROI 或匹配参数后，过期结果不会叠加到当前图像。关闭重开后会按需重新计算匹配。

如果背景容易抢占匹配，在采集一帧后打开 **识别参数 → 匹配区域（ROI）→ 绘制 ROI**。在选中的原始帧上框住需要匹配的区域，未选中原始帧时使用最新一帧。框选以图像比例保存在会话中，后续参考帧和当前帧使用同一个区域。请留出足够余量覆盖工件在各帧中的位置。需要让已有帧按新 ROI 重算时，点击 **执行拼接**。点击 **恢复整图** 可清除 ROI。

ROI 只限制提取和匹配特征的范围，匹配点仍显示在原始像素位置，成功配准后仍合并整帧点云。在 **识别参数 → 2D 检测与 3D 配准** 可调整检测细节、每帧最多找点、图像匹配严格度、允许的深度落差、允许的对齐误差和至少多少点对齐。默认值分别为 1024 px、2048 点、0.10、5 mm、2 mm 和 60%。至少需要 6 对内点。参数随会话保存，修改后点击 **执行拼接** 可用相同原始帧复验。移动拼接时保持工件固定。若工件随转台转动，ROI 应排除静止背景，并保留足够多随工件一起运动、可取深度的特征。

在 **识别参数 → 工件区域与二值化掩膜** 可绘制第二个工件 ROI。青框是匹配范围，橙框是工件范围，实际找点范围取两者交集。两个框都按图像比例应用于后续帧，绘制时应留出工件运动的余量。

勾选 **用掩膜辅助增强工件纹理**，选择亮工件或暗工件。阈值设为 **自动 Otsu** 时逐帧计算，也可输入 0～255 的手动阈值。程序先保留原始灰度图的匹配，再在掩膜引导下对工件局部做 CLAHE 对比度增强、平滑过渡，补充匹配。两组对应点合并时保留原图对应关系，去掉重复点及与原有点冲突的对应。掩膜为空时直接使用原图匹配。开启辅助会增加一轮增强图的计算，最终仍需通过 3D 配准检查。

勾选 **在原始 2D 图像上显示掩膜** 可在 DB 原始帧图像上查看结果。两个框的交集内，绿色标出增强重点，红色标出其余区域，框外保持透明。原始灰度匹配始终保留。显示开关可以独立开关，未启用增强时也可预览二值化效果。修改 ROI 或掩膜参数后，点击 **执行拼接** 可重新分析已有帧。

在 **识别参数 → ICP 点云精配准** 可开关拼接时的 ICP（默认开启）。特征对应先给出初始位姿，再用两个 ROI 交集内的有效工件点对最近三帧精修。默认最大对应距离 2 mm、计算采样间距 0.5 mm、迭代上限 50 次、最低重叠率 30%。采样只用于计算，整帧有效点及颜色仍按最终位姿输出。

运行日志分别列出特征初始拟合误差和 ICP 的几何误差/重叠率变化。ICP 未通过质量检查时保留特征初始位姿。工件转动时应框紧工件，避免静止台面或背景参与 ICP；整帧输出中的背景会随工件位姿变换，仍可能重影。这一流程逐帧精配准至最近几帧，不包含全局闭环优化。

使用已保存的会话复验时，显式传入单相机移动拼接的会话目录或 `session.json`。进入离线工作区后选择同一识别类型，按拍摄顺序选中或勾选原始帧，再点 **执行拼接**。离线验证使用会话副本。

```powershell
$earbudSession = (Get-ChildItem sessions -Directory -Filter '*0dc20d90').FullName
& $rvcPython prototypes/superpoint_lightglue/run.py --session $earbudSession
```

## 预训练文件

本机已有上一轮的 CPU 推理环境，原型从 `outputs/experiments/superpoint_lightglue/` 读取 `deps`、`upstream` 和 `weights`。模型在首次后台匹配时加载。两项权重文件都从本地读取。

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
