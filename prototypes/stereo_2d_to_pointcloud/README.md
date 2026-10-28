# stereo_2d_to_pointcloud —— 双目左右 2D 图 + 内外参离线重建点云

**功能一句话**：用 M 系列（X2）双目相机单次采集的左右 2D 图，仅凭内外参 +
SGBM 离线算出左相机系点云，并实测"10fps 2D 采集"下各阶段耗时与端到端帧率。

## 目录结构

```
stereo_2d_to_pointcloud/
├── core/
│   └── stereo_reconstruct.py    # 纯算法（无 SDK 依赖）：畸变重排 + StereoReconstructor
├── app/
│   ├── reconstruct_bench.py     # 实机基准脚本（需相机；退出码 0/2）
│   ├── reconstruct_from_files.py # 纯离线：已保存左右图+参数目录 → 点云（无需相机）
│   ├── calib_rig_from_board.py  # 出厂外参组合法：同帧标定板双拍 → rig.json（需相机+板）
│   └── calib_rig_from_coded_circle.py  # 编码圆自检测法：生成板→检测→stereoCalibrate（无硬件依赖最少）
├── tests/
│   ├── test_stereo_reconstruct.py  # 无硬件 unittest（退出码 0/1）
│   └── test_coded_circle_rig.py    # 编码圆 rig 全链路合成验证（退出码 0/1）
└── README.md
```

## 运行命令

解释器统一用 `D:/Program Files/Anaconda/envs/rvc/python.exe`。

```bash
# 单元测试（无硬件，判据 exit 0）
"D:/Program Files/Anaconda/envs/rvc/python.exe" \
    prototypes/stereo_2d_to_pointcloud/tests/test_stereo_reconstruct.py

# 实机基准（已有标定 JSON 时）
"D:/Program Files/Anaconda/envs/rvc/python.exe" \
    prototypes/stereo_2d_to_pointcloud/app/reconstruct_bench.py \
    --frames 30 --out tmp_stereo_bench --calib tmp_stereo_bench/calib.json

# 实机基准（无标定 → 交互式棋盘格标定，9x6 内角点 / 20mm 方格 / 目标 10 对）
"D:/Program Files/Anaconda/envs/rvc/python.exe" \
    prototypes/stereo_2d_to_pointcloud/app/reconstruct_bench.py \
    --frames 10 --out tmp_stereo_bench

# 无标定且拒绝交互标定 → 退出码 2
... reconstruct_bench.py --frames 10 --out tmp_stereo_bench --skip-calib

# 纯离线重建（无需相机）：已保存数据目录（camera_parameters.json + 左右 PNG）
#   --rig composed  ：由两份"标定板→相机"外参组合（⚠️ 仅当两外参同源才有效）
#   --rig features  ：SIFT+本质矩阵从图像对在线估计 R,T（尺度任意，基线=1 单位）
#   --rig <rig.json>：{"R": 3x3, "T": [3]}，如实机 stereoCalibrate 结果
"D:/Program Files/Anaconda/envs/rvc/python.exe" \
    prototypes/stereo_2d_to_pointcloud/app/reconstruct_from_files.py \
    --data <数据目录> --rig features --clahe
```

## 关键实现点

- **畸变顺序坑**：RVC SDK `X2.GetIntrinsicParameters()` 返回 `(k1, k2, k3, p1, p2)`，
  OpenCV 期望 `(k1, k2, p1, p2, k3)`；`core/stereo_reconstruct.py:rvc_dist_to_opencv`
  负责重排，bench 会把取到的原始成员顺序打一行日志备查。
- **外参来源**：`GetExtrinsicMatrix` 是"标定板→相机"变换，**不能**当左右外参用；
  R/T 必须来自 `cv2.stereoCalibrate(..., flags=CALIB_FIX_INTRINSIC)`（交互标定流程
  或 `--calib` JSON）。
- **取图策略**：探测三种模式并如实记入报告——`single`（一次 Capture 左右都有）、
  `switch`（右图需第二次采集，优先 `Capture2D()`，否则连续两次 `Capture()` 近似，
  左右帧不同步）、`unavailable`（拿不到右图，退出码 2）。**右图能走通哪种模式以实机
  实测为准**。
- **单位**：内部点云一律米（左相机系，Z 沿光轴）；`sample.ply` 保存时 ×1000 转毫米，
  PLY 头部注释注明。
- numpy 2.x：全程 `np.asarray(x, copy=True)` 取 SDK 图像数据，不用 `copy=False`。

## 验收判据

1. 单元测试：上述测试命令 **exit 0**，四个用例各打印一行 `[PASS]`：
   - `test_distortion_reorder` —— 畸变系数重排
   - `test_planar_reconstruction_accuracy` —— 合成 Z=1.0m 平面，Z 中位数 ±5%
   - `test_two_depth_layers` —— 1.0m / 0.7m 两层各 ±5%
   - `test_invalid_region_mask` —— 无匹配区 valid_mask=False 且 points 置 0
2. 实机基准：bench 在实机上输出 4 阶段（采集 / 拷贝 / remap+SGBM / reproject3D）
   均值与中位耗时、端到端"点云对/秒"、取图模式判定，并落盘 `report.json`、
   左右图 png、视差 colormap png、`sample.ply`（毫米）。取不到右图时退出码 2 也算
   正常结果（如实记录模式判定）。

## 实测记录（2026-10-19，数据：M51000C / SN M3GM150W005 左右 2D 图）

- **交付的外参不能组合出左右相对位姿**：两份"标定板→相机"外参旋转组合出
  **14.2°** 相对旋转、**423mm** 以 Y 为主的基线 —— 刚性双目机构不可能如此，
  结论是两路外参来自不同标定时刻、非同源。`--rig composed` 重建出 Z 中位 −21m
  的垃圾点云，脚本已加合理性检查（相对旋转 >3° 或基线超出 10~300mm 即告警）。
- **`--rig features` 可行但只能定相对尺度**：弱纹理场景下 SIFT 默认阈值几乎提
  不出点（ct=0.04 → 49/27 个），降到 0.01 得 1.7k；再用「出厂行对准、真匹配
  |dy|≤15px」做几何先验过滤误配（26/124 幸存），RANSAC 内点极线误差中位
  **0.63px**，场景深度中位 **56.9 基线单位**。若基线 ~100mm → 墙面约 5.7m，
  与办公室场景吻合。
- **cv2.recoverPose 两个坑**：本环境（4.13）的 `distanceThresh` 是第 5 个位置
  参数且不能用关键字；输出 mask 的内点值是 **255 不是 1**，`sum()` 计数会放大
  255 倍（765=3×255）。T 符号不要用 recoverPose 的 cheirality（弱纹理下只剩
  3 个幸存点，不可靠），改对自己三角化内点判 Z 符号。
- **弱纹理离线重建的天花板**：CLAHE+SGBM（numDisparities=384）在该数据上
  有效率 ~32%，按三角化深度 [0.2, 2.5]× 过滤飞点后剩 102 万点；主平面结构正确
  （深度序：柜 < 墙），但平板区大量空洞、仍有条纹噪声 —— 被动双目无投射纹理时
  的固有限制。
- **位姿自动估计在该数据上被证伪（4 种独立方法互斥）**，这是本数据集的结论：
  1. E-RANSAC（dy≤15px 过滤，26 对）→ t≈−X 貌似物理，但 23 个内点矫正视差
     全部坍缩在 59.0±0.2px —— 重复纹理板面造成的"幻影平面共识"，不可信；
  2. E-RANSAC（dx 负窄带严格集，23 对）→ t 沿光轴（physically 不可能），
     矫正行差 39px —— 单应退化下的另一个自洽假解；
  3. 工厂先验 t=−X + R 网格投票（197 对匹配）→ 最多 2 对行对齐；
  4. t 方向 ±19° × R ±4° 分阶段投票 → 最多 10/197。
  根因：重复无纹理板面使 SIFT 误配率 ~90%+，近平面场景对位姿约束病态，
  极线/手性一致都无法区分真假解。**该数据离线可交付的最好结果就是流程验证，
  不可作为测量依据**；出路只有三选一（均需相机）：棋盘格 stereoCalibrate 出
  真 rig（管线已支持 --rig rig.json 直接复用于本数据）、采集时开投射散斑、
  或用 SDK GetPointMap 作基准。
- **OpenCV on Windows 中文路径**：`cv2.imread/imwrite` 按 ANSI 解析路径，
  中文目录静默失败；统一走 `np.fromfile + cv2.imdecode` / `cv2.imencode +
  tofile`（脚本内 `_imread_unicode/_imwrite_unicode`）。

## 出路 A：出厂外参组合法（待实机验证）

`app/calib_rig_from_board.py`：同一块 RVC 标定板置于左右共视视野，同帧分别调
`GetExtrinsicMatrix(Left/Right)`，两个"板→相机"矩阵共享同一板系，
`rig = TR @ inv(TL)` 即真 rig（板尺寸 SDK 已知 → 自带米制尺度）。多板位采样取
平均可消检测噪声。脚本自动判定可行性：

1. **新鲜度**——各样本矩阵随板位变化（不变 = API 返回固化历史值 → 此路不通）；
2. **合理性**——每样本相对旋转 <1.5°、基线 10~300mm；
3. **离散度**——基线 std <1mm、旋转 std <0.2°；
4. 可选 `--scene-dir` 立即用新 rig 重建历史数据，Z 应为合理米制值，用卷尺核对。

运行：`python app/calib_rig_from_board.py --sn <SN> --samples 8 --out rig.json
--scene-dir <历史数据目录> --clahe`

⚠️ 已在 v1.15 SDK 文档（本机 D:/Kimi_WorkSpace/SDK开发文档/）全量确认：**没有**
直接暴露左右相机出厂相对位姿的 API，Extrinsic 相关只有 GetExtrinsicMatrix /
GetCaliBoardPoseX2 / 外接彩色相机标定三个。出路 B（问原厂要内部 rig）仍然有效。

## 编码圆自检测标定（推荐路线，全链路已合成验证）

`app/calib_rig_from_coded_circle.py` 三步：

```bash
# ① 生成标定板（board.png + layout.json 配套，改动任一生成参数都重跑这步）
python app/calib_rig_from_coded_circle.py --gen-board board_out
# ② 打印 board.png（100% 实际尺寸）贴到刚性板面
# ③ 实机标定（或离线 --pairs 已拍图对；离线需 --intrinsics camera_parameters.json）
python app/calib_rig_from_coded_circle.py --sn M3GM150W005 \
    --layout board_out/layout.json --samples 8 --out rig.json \
    --scene-dir <历史数据目录> --clahe
```

原理：复用 `src/core/marker_detector.py` 的 `RVC.DetectCodedCircleMarker` 检测，
编码圆 ID 唯一 → 左右图按 ID 配对零歧义；layout.json 给出每个圆心的物理坐标
（生成公式与绘制像素级一致）；`stereoCalibrate(CALIB_FIX_INTRINSIC)` 解 R/T，
圆间距是生成时设定的物理量 → **rig 自带米制尺度**，不依赖 SDK 板检测行为。

**合成验证**（`tests/test_coded_circle_rig.py`，无硬件，exit 0）：生成板按已知
内参/rig 渲染 4 个板位的左右虚拟视图，走完整链路——检出 12/12，重投影
rms ≤0.11px，基线恢复 49.66mm（真值 50mm，误差 0.68%），相对旋转 0.088°。
2026-10-19 实测通过。

实机注意：检测器对圆像素半径敏感（r0 > ~15px 时全分辨率可能漏检，
MarkerDetector 自带 0.75x/0.5x 回退）；板太远检出少时加大 `--radius-mm`
（或换 A3），`--gen-board` 打印的"圆心距 mm"供估算板位。

## 已知限制

- **左右不同步**：`switch` 模式下左右图来自两次采集，运动场景会产生匹配误差；
  只有 `single` 模式才是严格同帧。
- **匹配质量依赖纹理**：M 系列为结构光投射纹理时，离线 SGBM 的匹配质量取决于
  投射散斑的可区分度；纹理弱/重复区域 valid_mask 会明显收缩。
- **右图获取模式以实测为准**：本原型不预设 X2 必然支持单次采集同时出左右 2D 图，
  以 bench 打印的 `grab_mode` 为定论。
- 标定质量直接决定重建精度；`stereo_calib_rms_px` 记在 calib JSON 里供复查。
