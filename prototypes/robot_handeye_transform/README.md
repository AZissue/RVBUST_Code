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
        unit_guard.py      单位换算 + 范数窗口 + **共用校验层**（check_rigid_4x4 /
                           check_pose_norm，矩阵侧与位姿侧唯一实现）
        pose_source.py     PoseSource：Mock / 手动六自由度 / CSV 回放 / TcpRobot(空)
                           unit / pose_type / order **三项必填无默认**（批 1.5）
        transform_chain.py compute_cam2base + transform_pcd（先 copy，K3）
        validation.py      批 3：戳点门禁 + 重合度 warning
        session.py         批 3：会话落盘/恢复
app/    main.py            入口（无显示器时 QT_QPA_PLATFORM=offscreen；--smoke N 无人值守自检）
        control_panel.py   左：手眼矩阵 / 机器人位姿 / 采集 / 验证（四组，参数不预选）
        window.py          主窗口：EmbeddedPointCloudViewer + WorkerThread + 合成点云闭环
tests/  test_transform_chain.py / test_handeye_result.py / test_unit_guard.py
        test_matrix_guard.py / test_pose_source.py        （批 1.5 新增）
BASELINE.md  A8 版本锚点（BASE_HEAD / src diff hash / PROTO_COMMIT）
REGRESSION.md 回归手册（@scribe，RG-01…RG-08）
```

```bash
cd D:\RVC_SRC\Python\MultiCameraCalibration
unset PYTHONPATH && export QT_QPA_PLATFORM=offscreen
PY="D:/Program Files/Anaconda/envs/rvc/python.exe"
"$PY" prototypes/robot_handeye_transform/tests/test_unit_guard.py       # A2
"$PY" prototypes/robot_handeye_transform/tests/test_handeye_result.py   # A7
"$PY" prototypes/robot_handeye_transform/tests/test_matrix_guard.py     # 共用校验层
"$PY" prototypes/robot_handeye_transform/tests/test_pose_source.py      # A2 位姿侧
"$PY" prototypes/robot_handeye_transform/tests/test_transform_chain.py  # A1（含 DLL oracle）
```

判 pass/fail 看**进程退出码**（不要用 pytest）。DLL oracle 默认**必需**：缺失时
`[ORACLE SKIPPED]` + **exit≠0**；只在明确接受降级时加 `--allow-skip-oracle`。
oracle 会打印 DLL 路径 / 版本 / sha256（跨机比对基线，禁止人工转录）。
测试套件可迁移：仓库根向上查找 `src/core/pcd_utils.py`，或设 `MCC_REPO_ROOT`（R12）。

```bash
# 批 2 UI（无相机、无机器人；无显示器加 QT_QPA_PLATFORM=offscreen）
PY="D:/Program Files/Anaconda/envs/rvc/python.exe"
"$PY" prototypes/robot_handeye_transform/app/main.py            # 交互
"$PY" prototypes/robot_handeye_transform/app/main.py --smoke 3  # 无人值守，退出码 0 = 全过
```

## 实测基线（2026-09-22，conda rvc py3.10 实跑）

| 项 | 结果 |
|---|---|
| A1 变换链真值（两分支×3 trial） | 逐点最大偏差 0.000e+00 mm（<1e-9 门槛） |
| A1 厂商 DLL oracle（3 帧） | nn_max 0.000081 / 0.000070 / 0.000060 mm（<1e-4 门槛，与 @feas 实测一致） |
| A2 单位往返 | 同一矩阵 mm↔m 往返 diff = 0.000e+00 mm（<1e-6 门槛） |
| A2 范数窗口 | 眼在手上/外各 6 档合法全过、÷1000/×1000 误读全拦（含 @scribe 眼在手外回归） |
| A7 加载守卫 | NaN/非正交/det=-1/末行错/success=False/缺键/单位非法 → 全部拒绝且可读 |
| 三个测试退出码 | 全 0 |

**批 1.5 实测（2026-09-23，@dev 本机实跑，conda rvc py3.10）**

| 项 | 结果 |
|---|---|
| 五个测试退出码 | 全 0（三旧测试未退化 + 两新测试全绿） |
| 位姿米制误读（@qa 缺陷①） | `set_pose_xyz_rpy([0.4,0.1,0.2],…,unit="mm")` → 被范数窗口拦（旧版静默错 457.799 mm）；`unit="m"` → 与毫米真值 maxdiff=0.000e+00 |
| 位姿四类必拒 | NaN / det=−1 镜像 / det=+1 shear / 末行错 → 全拒 |
| CSV | 16 列、7 列（空格与逗号分隔）放行；6 列 / 缺 pose_type 声明 / 声明不一致 → 拒 |
| det=+1 shear（@qa 盲点） | `test_matrix_guard` 判 FAIL 必须通过 —— 正交性检查单独有效 |
| 单实现证明 | 把 `unit_guard.ORTH_TOL` 改 1e9 后，矩阵侧 `validate_matrix` 同步放行（确认委托、无第二份副本） |
| oracle 证据 | `v3.9.0 / 64,244,224 B / sha256=2ab43b6b…37c29b4`（程序打印，len=64 自查通过） |
| skip≠pass | 换机模拟（只拷原型目录 + oracle 路径置空）→ `[ORACLE SKIPPED]` + **exit=1**；加 `--allow-skip-oracle` 才 exit=0 |
| R12 可迁移 | 换机模拟下 §[4] 报可读失败但 §[5] **仍执行**（旧版死在 §[4] 堆栈，看不到 oracle）；设 `MCC_REPO_ROOT` 后 exit=0 |

**批 2 实测（2026-09-23，offscreen 实跑）**

| 项 | 结果 |
|---|---|
| `--smoke 3` | 三帧全部 OK，退出码 0；帧间位姿不同（#1/3 → #3/3，‖t_cam2base‖=690.000 / 703.623 / 708.868 mm） |
| 3D 上屏 | 查看器日志 `全部叠加 (2 台相机)` / `点数: 40,000` = 相机系 20000 + 基座系 20000（白色=相机系参考） |
| 基座系点云 vs 解析真值 | 逐点最大偏差 **0.000e+00 mm**（门槛 1e-9；真值为内联矩阵乘，与 A1 同口径） |
| 交互模式起窗口 | `QT_QPA_PLATFORM=offscreen` 常驻 6 秒无 traceback（正常被 kill，124） |
| UI 槽位（信号接线） | 缺 order → 拒绝且位姿仍为空；米制当毫米 → 拒绝；正确米制录入 → 采集成功 |
| 位姿序列推进 | Mock 按「先取当前帧再步进」，首帧不跳过（R6） |

**批 2.1 实测（2026-09-23）**

| 项 | 结果 |
|---|---|
| 五测试 | 全 exit=0（新增 delta 负向用例、矩阵侧 NaN 对称用例均绿） |
| RG-11 delta fail-closed | 三入口（Mock / Manual / CSV）+ UI 槽位全拒，报文含"增量位姿（pose_type='delta'）暂不支持"；`check_pose_norm(delta)` 仍工作（预留值） |
| RG-11 不可判别性证据 | 重叠区 `‖t‖=300 mm` 在 absolute 与 delta 两窗内都放行 → 声明对错数值不可判别，只能 fail-closed |
| RG-09 降级末行 | `--allow-skip-oracle`：exit=0 且末行 `[ALL OK — 已降级：A1 独立判据(§[5]) 未执行]` + 降级汇总；不降级：exit=1 |
| A4 三帧真值 | 第 1/2/3 帧逐帧比对：`0.000e+00 / 2.274e-13 / 1.137e-13 mm`（均 < 1e-9） |

## 进度

- [x] 批 0（部分）：prototypes/README 表更新 + A8 基线复核（HEAD=8221b82，
      src/ diff sha1=7eceb8c3a8826bc1 与 @arch/@feas 记录一致，见 `BASELINE.md`）。
      `src/core/robot_stitch_workflow.py` 3 行注释修正**待 @user 批准（§8-③）**。
- [x] 批 1：core 四件套 + A1/A2/A7 测试全绿
- [x] 批 1.5（批 2 前置，9 项全落）：
      ① `check_rigid_4x4` / `check_pose_norm` 抽进 `unit_guard` 共用层，
      `handeye_result.validate_matrix` 改为委托（单实现有测试证明）
      ② `pose_source` 三入口补 `unit` + `pose_type` + `order`（全必填无默认）
      + 刚性校验 + 范数窗口；CSV 6 列拒收、须带 pose_type 声明行
      ③ 新增 `test_matrix_guard.py` / `test_pose_source.py`
      ④ 原型首次 commit `249fdb3` + `BASELINE.md`
      ⑤ det=+1 的 shear 用例（正交性检查单独有效，补 @qa 盲点）
      ⑥ R12 src 定位：向上找仓库根 / `MCC_REPO_ROOT`（换机可跑）
      ⑦ §[5] 打印 oracle 路径 + 版本 + sha256（程序打印，非人工转录）
      ⑧ 清掉 `SKIPPED = []` 死代码；oracle 缺失默认 **exit≠0**
      ⑨ 三入口尺寸/类型错误统一为自家可读报错
- [ ] 批 2：app UI（复用主功能组件）—— 起点已满足（PoseSource 签名冻结于批 1.5）
- [ ] 批 3：validation.py（戳点门禁 + 重合度 warning）+ session.py
- [ ] 批 4：offscreen 端到端 + README 收尾 + 真机联调（待 §8 现场信息）

> **批 2 状态（2026-09-23）**：`app/main.py` / `control_panel.py` / `window.py` 三文件已落，
> 闭环"合成点云 → 变基座系 → 3D 显示"跑通（`--smoke 3` exit=0，实测见上表）。
> **两点与方案 v4.1 的差异已获 @arch 裁决**：① `CameraPreviewCard` **批 2 不接**（A4 无 2D 项，
> 无相机时是死控件），留到批 4 接真机/离线 2D 帧；② `WorkerThread` 只用在"拍一帧"的变换上，不扩。

> **批 2.1 状态（2026-09-23，收尾 5 项全落）**：RG-11 delta fail-closed（core 级收口 + 三入口
> 负向用例）、RG-09 降级末行可见、smoke 三帧逐帧真值、矩阵侧 NaN 对称用例、锚点表按 commit 分节。
> **delta 不支持**：原型未实现增量累积，`admit_pose()` 一律拒绝 delta；UI 下拉「增量（未支持）」
> 置灰 + tooltip；delta 窗口 `[1, 500] mm` 为预留值（批 2~4 入口不可达）。
