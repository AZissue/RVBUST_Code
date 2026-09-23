# robot_handeye_transform —— 手眼矩阵 + 机器人位姿 → 点云转基座系

> 落位：`prototypes/robot_handeye_transform/` ｜ 方案：`docs/机器人手眼变换原型方案_20260922.md`（v2）
> 范围（D1）：**只做变换不做标定求解**。手眼矩阵来自独立工具（RVHandEyeCalibration v3.9.0）
> 或 `src/core/handeye.py`；本原型吃它的输出。

## 核心闭环

加载/录入手眼矩阵（显式选单位）+ 取机器人位姿 → 实时把相机系点云转到
机器人基座系 → 3D 显示/保存。无机器人、无相机可跑完整闭环（MockPoseSource /
手动位姿 + 合成点云）。

## ⚠️ 判别下限声明（A9，三处明示之一）

戳点验证门禁的**可判别平移偏差下限 ≈ 1.0 mm**（1.0 mm 检出 100%，0.5 mm
检出 0~30%，0.2 mm 不可判；旋转 0.5°→1.24 mm、1.0°→2.38 mm）。
**禁止把验证通过当作亚毫米保证。**

## 状态机与门禁（A2/A3/K8）

`IDLE → 相机就绪 → 矩阵已加载(UNVERIFIED) → 戳点验证通过(VERIFIED) → 允许导出`

- 矩阵加载后一律 **UNVERIFIED**；`rms_t_mm/rms_r_deg` 是内符合指标，**不是**
  可用性判据——单轴退化标定数据下它们恒为 0，但矩阵平移可错 110 mm（已双人复现）。
- **唯一门禁 = 戳点绝对位置度量**（mean ≤ 0.7 mm 硬门禁；≥3 姿态，建议 ≥6）。
  两帧重合度**不是**门禁：平移误差平行于两位姿旋转轴时重合度恒为 0（数学恒等），
  只配当 warning。
- 单位**显式必选**（mm/m，无 auto、无默认，D4）：手眼矩阵单位由产出者决定
  （SDK 内存点云=米；MCC 检测毫米点云=毫米），JSON 无 unit 字段，不可推断。
  平移范数物理窗口兜底：眼在手上 [5, 2000] mm / 眼在手外 [50, 20000] mm。

## 目录与运行

```
core/   handeye_result.py  加载 JSON/手动 4×4 → A7 校验 + K6/K7 守卫 + A2 单位
        unit_guard.py      单位换算 + 平移范数物理窗口（纯函数）
        pose_source.py     PoseSource：Mock / 手动六自由度 / CSV 回放 / TcpRobot(空)
        transform_chain.py compute_cam2base + transform_pcd（先 copy，K3）
        validation.py      批 3：戳点门禁 + 重合度 warning
        session.py         批 3：会话落盘/恢复
app/    批 2：复用主功能 UI 组件（EmbeddedPointCloudViewer/CameraPreviewCard/WorkerThread）
tests/  test_transform_chain.py / test_handeye_result.py / test_unit_guard.py
```

```bash
cd D:\RVC_SRC\Python\MultiCameraCalibration
unset PYTHONPATH && export QT_QPA_PLATFORM=offscreen
PY="D:/Program Files/Anaconda/envs/rvc/python.exe"
"$PY" prototypes/robot_handeye_transform/tests/test_unit_guard.py        # A2
"$PY" prototypes/robot_handeye_transform/tests/test_handeye_result.py    # A7
"$PY" prototypes/robot_handeye_transform/tests/test_transform_chain.py   # A1（含可选 DLL oracle）
```

判 pass/fail 看**进程退出码**（不要用 pytest）。DLL oracle 仅在机器上存在
`D:\RVC_SRC\hand-eye-tools`（handeye_sdk + HandEyeSDK.dll）时启用。

## 实测基线（2026-09-22，conda rvc py3.10 实跑）

| 项 | 结果 |
|---|---|
| A1 变换链真值（两分支×3 trial） | 逐点最大偏差 0.000e+00 mm（<1e-9 门槛） |
| A1 厂商 DLL oracle（3 帧） | nn_max 0.000081 / 0.000070 / 0.000060 mm（<1e-4 门槛，与 @feas 实测一致） |
| A2 单位往返 | 同一矩阵 mm↔m 往返 diff = 0.000e+00 mm（<1e-6 门槛） |
| A2 范数窗口 | 眼在手上/外各 6 档合法全过、÷1000/×1000 误读全拦（含 @scribe 眼在手外回归） |
| A7 加载守卫 | NaN/非正交/det=-1/末行错/success=False/缺键/单位非法 → 全部拒绝且可读 |
| 三个测试退出码 | 全 0 |

## 进度

- [x] 批 0（部分）：prototypes/README 表更新 + A8 基线复核（HEAD=8221b82，
      src/ diff sha1=7eceb8c3a8826bc1 与 @arch 记录一致）。
      `src/core/robot_stitch_workflow.py` 3 行注释修正**待 @user 批准（§8-③）**。
- [x] 批 1：core 四件套 + A1/A2/A7 测试全绿
- [ ] 批 2：app UI（复用主功能组件）
- [ ] 批 3：validation.py（戳点门禁 + 重合度 warning）+ session.py
- [ ] 批 4：offscreen 端到端 + README 收尾 + 真机联调（待 §8 现场信息）
