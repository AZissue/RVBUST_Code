# 临时固定多相机外参标定与拼接

复用 MCC `MarkerDetector`、`CalibBoardDetector`、`CalibrationEngine`、`StitchEngine` 和 `CameraManager`。独立运行，不修改主程序。原型不升级正式版本（当前主程序 1.12.62）。

## 启动

在 PowerShell 执行：

```powershell
& 'D:/RVC_SRC/Python/MultiCameraCalibration/prototypes/quick_extrinsic/run.ps1'
```

也可以直接运行，支持指定输出位置：

```powershell
& 'D:/Program Files/Anaconda/envs/rvc/python.exe' 'D:/RVC_SRC/Python/MultiCameraCalibration/prototypes/quick_extrinsic/app/quick_extrinsic.py' --output 'D:/MCC_QuickOutput'
```

依赖使用现有 rvc 环境：PySide6、NumPy、OpenCV、Open3D、SciPy、PyRVC。不自动安装依赖，不修改全局环境。编码圆检测需要 PyRVC，即使使用离线文件也需要其检测库；SDK 设备系统只在点击枚举/连接时初始化。

## 操作

1. 点击「枚举设备」，核对设备索引与 SN。填写 `0,1` 或 `0,1,2`，点击「连接」。默认读取相机内保存的采集参数；需要调整曝光、采集模式时先在 RVCManager 中保存参数并退出 RVCManager，释放设备。
2. 保持相机固定，放置同一块标定板或同一组编码圆，点击「① 采集标定帧」。采用串行软触发：一台完成采集、原始帧保存及 SDK 资源释放后才触发下一台，场景须保持静止。
3. 选择「编码圆」或「非对称圆标定板」。编码圆可修改 N、r1/r0、r2/r0。非对称圆板默认尝试 4×11、7×11、4×5，可编辑规格 JSON 添加尺寸。`cols`/`rows` 沿用 MCC 定义，非对称圆心满足 `x=j*d, y=(i+0.5*(j%2))*d`；不支持棋盘格或对称圆网格。圆心间距会按 MCC 核心从有效深度自动估计，填写值是回退值。圆板识别自动尝试核心内置 gamma 阶梯。
4. 点击「② 检测并显示」。图像标签页展示各路叠图和圆心编号，绿圈为有效三维点，红圈表示有二维检测但无有效深度；右侧表格显示像素和 XYZ。圆板检测失败时核心可能不返回二维候选点，因而不会显示红圈。
5. 核对所有视角的编号对应同一物理圆心，再勾选确认框。圆板没有独立编码，某些朝向存在 180°/对称排列歧义，必须核对编号朝向；低拟合 RMS 不能证明物理对应正确。整个标定组中不能移动板，也不能在不同相机前换成另一块同规格板。
6. 选择参考相机，点击「③ 计算外参」。两两尝试同码点配准，至少 4 对不共线有效点；不同圆板规格不互配。通过 RMS 和内点率门禁的边组成变换图；所有参与相机必须能连通参考相机，否则保留上一次外参并报告失败。MCC RANSAC 计算结果用于两种标记物，不把单路圆板位姿误差当成跨相机残差。右侧外参页展示配对误差、内点率及每路 cam→ref 矩阵。可点击「保存外参」，以后用「载入外参」恢复。
7. 相机位置保持不变，移走标定板、放入待扫描工件，点击「④ 采集扫描帧」。标定帧和扫描帧分别存储。
8. 点击「⑤ 拼接并导出」。按照外参变换，过滤非有限点及零点，可设置体素降采样（0 表示关闭）。输出彩色 PLY（如果输入有颜色）、配套外参 JSON。点击「查看拼接3D」在独立 Open3D 进程查看；显示最多约 50 万点，导出点云不受显示抽样影响。

这是固定外参拼接，不包含 ICP 微调、自动曝光、硬同步或多帧全局优化。相机移动或连接序列号改变须重新标定。在线扫描会同时核对采集帧与外参的设备 SN；无设备 SN 的离线外参不能直接用于在线扫描。编号仅在当前枚举序列有效，应通过 SN 检查。

## 离线入口与输出

「离线标定帧」/「离线扫描帧」分别选择相机 ID、图像、PLY。每台相机重复一次，使用同一 ID（例如 cam0、cam1）；同一 ID 再次导入替换该帧。切换数据组可用「清空帧列表」清除运行期帧引用，保留外参与所有磁盘文件。请勿混用不同场景的数据组。

标定 PLY 必须以 **毫米**为单位，与图像逐像素对应，保留无效点且点数等于宽×高；不能用过滤、裁剪、压缩后的无序点云。工具检查点数，无法仅凭文件自动证明逐像素顺序或单位正确。扫描 PLY 可无序，仍必须为毫米。离线数据的设备身份由操作者核对。

默认输出为本目录 `outputs/`：

- `calib/时间/`、`scan/时间/`：在线采集的原始图像、mm 有序点云、帧元数据；每组新目录，不覆盖历史采集。
- `detection_cam*.png`、`detection.json`：最近一次识别叠图和圆心记录，再次检测会替换同名诊断文件。
- `stitch_inputs/时间/`：拼接用的有效点副本，原始有序点云不改动。
- `merged_时间.ply`、`merged_时间.extrinsics.json`：拼接结果与外参快照。
- 手动保存的外参兼容 MCC `pairs` 格式，另附单位、方向和设备 SN。工具只读取自身保存的带 mm / cam_to_ref 元数据的外参。

坐标定义：`p_ref = T_cam_to_ref @ p_cam`，矩阵平移和 PLY 坐标均为 mm。多帧扫描只处理最近一次每台相机的一帧，不累计重复帧。

## 验证（2026-10-22）

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& 'D:/Program Files/Anaconda/envs/rvc/python.exe' -m unittest discover -s 'D:/RVC_SRC/Python/MultiCameraCalibration/prototypes/quick_extrinsic/tests' -v
$env:QT_QPA_PLATFORM = 'offscreen'
& 'D:/Program Files/Anaconda/envs/rvc/python.exe' 'D:/RVC_SRC/Python/MultiCameraCalibration/prototypes/quick_extrinsic/app/quick_extrinsic.py' --smoke --output 'D:/RVC_SRC/Python/MultiCameraCalibration/tmp_skill_logs/quick_extrinsic'
```

已验证：18 项离线及界面测试（含三种默认规格及自定义 5×9 圆板真实检测、真实 PyRVC 编码圆离线检测、外参方向/保存载入/拼接闭环、链式共视、不同规格/共线点/不连通/不完整扫描/设备SN变化拦截、采集保存失败资源释放、逐台保存释放后再触发、检测半组失败恢复、无效外参载入恢复，以及界面数据回填/后台成功失败恢复）。界面离屏构造与截图检查通过。没有执行设备 SystemInit、连接或实体采集；实体相机、真实标定精度与原生 Open3D GPU 交互尚未验证。
