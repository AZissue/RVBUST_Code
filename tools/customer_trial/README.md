# MCC Python 拼接开发示例

使用 Windows x64 Python 3.10。进入 PythonSDK 目录后在 PowerShell 执行：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe stitch.py fixed demo/input.json result-fixed
.\.venv\Scripts\python.exe stitch.py markers demo/input.json result-markers
.\.venv\Scripts\python.exe stitch.py fpfh demo/input.json result-fpfh
```

每个命令使用一个新的输出目录，写出 merged.ply 和 report.json。自带三帧合成数据，每帧1000点，三种方式预期各输出3000点。也可以用 `python make_demo.py 新目录` 重新生成数据。

| 模式 | 输入要求 | 报告 |
|---|---|---|
| fixed | PLY 和带 reference_id、pairs 的 MCC 标定 JSON 数据 | 各相机到参考相机的矩阵 |
| markers | 每帧 PLY 及已识别的同编号 3D 标记。也可在条目指定 image，输入与图像逐像素对应的有序 PLY，由 MCC 识别 | 逐步共视标记、内点率、RMSE 及累计矩阵 |
| fpfh | 有重叠的 PLY，按输入清单顺序排列 | 相邻帧指标、首帧坐标系累计矩阵及参数 |

用 demo/input.json 作模板。路径相对于清单所在目录。所有坐标与矩阵平移均为毫米，矩阵方向为局部帧到参考帧，列向量公式为 p_ref = T @ p_local。FPFH 的 fpfh 字段覆盖默认参数，完整参数定义位于 core/postprocess/fpfh_registration.py 的 DEFAULTS。需要调用代码时可导入 stitch.run(mode, manifest, output)，或使用 stitch_fixed、stitch_markers、stitch_fpfh。输入不满足条件时会报告错误。

## 点云转换和标记物识别

桌面软件的“SDK 源码”菜单可直接打开这些脚本。以下命令使用随包的合成输入：

```powershell
.\.venv\Scripts\python.exe transform_cloud.py demo/cam1.ply demo/cam1_to_cam0.json aligned.ply
.\.venv\Scripts\python.exe recognize_markers.py demo/board.png demo/board.ply board-markers.json
```

点云转换把 cam1 的 1000 点转换到 cam0 坐标系，并保留颜色。识别示例用 OpenCV 识别非对称圆标定板，通过有序 PLY 获取三维坐标，预期输出 77 个有效标记。客户自己的编码圆可传入 `--type coded_circle --bits 8 --r1 2 --r2 3`，需要安装与 Python 对应的 PyRVC。不同标记物使用各自的识别参数。

## 连接实体相机

先从 RVC 官方渠道安装与相机匹配的 RVC SDK，再按其说明在同一个 Python 环境安装匹配 Python 3.10 x64 的 PyRVC。下列命令会按序列号连接设备并拍摄一帧，确认设备可使用后再执行：

```powershell
.\.venv\Scripts\python.exe capture_rvc.py --serial 实际序列号 --output captures/frame-001
```

用 cam0.png 和 cam0.ply 填写输入清单。标记物匹配需要开启相机的点云对应 2D 选项。采集示例使用显式连接、保存和释放，离线拼接示例可在无相机环境运行。

本版示例覆盖固定外参、标记物和 FPFH 拼接。转台和机器人工作流可在桌面软件中测试。FPFH 按相邻帧求解，长链可能累积误差。
