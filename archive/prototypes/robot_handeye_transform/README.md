# robot_handeye_transform —— 手眼矩阵 + 机器人位姿 → 点云转基座系

> 落位：`prototypes/robot_handeye_transform/` ｜ 方案：`docs/机器人手眼变换原型方案_20260922.md`（v4.3）
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
app/    main.py            入口 → host.py（无显示器时 QT_QPA_PLATFORM=offscreen；--smoke N 无人值守自检）
        host.py            独立宿主（批 4.5）：QMainWindow 壳 + 日志面板 + 同步 stub runner
                           （与 BackendBridge._run_background 同签名；合入后由 MainWindowShell 替换）
        control_panel.py   左：手眼矩阵 / 机器人位姿 / 采集 / 验证（四组，参数不预选）
        window.py          RobotWorkspace(QWidget)：ui_v2 ViewerPanel + 注入 runner + 合成点云闭环
                           （批 4.5 起本文件**只提供工作区本体**，窗口/日志控件在宿主里）
tests/  test_transform_chain.py / test_handeye_result.py / test_unit_guard.py
        test_matrix_guard.py / test_pose_source.py        （批 1.5 新增）
        test_validation_degenerate.py / test_session.py   （批 3 新增，A3/A6）
        test_ui_smoke.py                                  （批 4 新增，A4/A5，offscreen）
BASELINE.md  A8 版本锚点（BASE_HEAD / src diff hash / PROTO_COMMIT）
REGRESSION.md 回归手册（@scribe，RG-01…RG-13）
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
"$PY" prototypes/robot_handeye_transform/tests/test_validation_degenerate.py  # A3/A9/R2/R3
"$PY" prototypes/robot_handeye_transform/tests/test_session.py          # A6 会话往返
"$PY" prototypes/robot_handeye_transform/tests/test_ui_smoke.py         # A4/A5（offscreen）
```

判 pass/fail 看**进程退出码**（不要用 pytest）。DLL oracle 默认**必需**：缺失时
`[ORACLE SKIPPED]` + **exit≠0**；只在明确接受降级时加 `--allow-skip-oracle`。
oracle 会打印 DLL 路径 / 版本 / sha256（跨机比对基线，禁止人工转录）。
测试套件可迁移：仓库根向上查找 `src/core/pcd_utils.py`，或设 `MCC_REPO_ROOT`（R12）。

```bash
# UI（无相机、无机器人；无显示器加 QT_QPA_PLATFORM=offscreen）
PY="D:/Program Files/Anaconda/envs/rvc/python.exe"
"$PY" prototypes/robot_handeye_transform/app/main.py            # 交互
"$PY" prototypes/robot_handeye_transform/app/main.py --smoke 3  # 无人值守，退出码 0 = 全过
```

**入口结构（批 4.5 起）**：`app/main.py` → `app/host.py`（独立宿主：QMainWindow 壳 + 日志面板
+ 同步 stub runner）→ `app/window.py` 的 `RobotWorkspace(QWidget)`（工作区本体，接口 =
`set_devices` / `set_state` / `set_background_runner` + `log_message` / `dirty_changed`）。
**独立运行时的界面就是合入后的形态**：工具栏 / 状态栏 / 日志面板由壳提供，合入时壳换成
`MainWindowShell` + `BackendBridge._run_background`，工作区零改动。

**⚠️ 必须在仓库树内运行**（app 与 tests 都靠"向上找含 `src/core/pcd_utils.py` 的仓库根"定位 `src/`）：

| 场景 | 实测结果（2026-09-23） |
|---|---|
| 原型拷到仓库外、不设 `MCC_REPO_ROOT` | `--smoke 3` → **exit=1** + 三行可读报错（`No module named 'ui_v2'` / `src/core 不可用（merge_pointclouds 缺失）` / `仓库根 = 未找到`），无静默绿灯；`test_ui_smoke` → exit=1 + `ModuleNotFoundError: No module named 'core'` 堆栈 |
| 原型在仓库外、设 `MCC_REPO_ROOT=<真仓库>` | **可跑**：`--smoke 3` exit=0（`全部叠加`=10）、`test_ui_smoke` exit=0（2026-09-23 实测；批 4.5 变异台架即在此模式下运行） |

**另一条已知边界（@lead 实测闭包）**：`import ui_v2.widgets.viewer_panel` 会连带加载 **2057 个模块**
（`ui.main_window` / `ui.viewer_3d` / `ui.worker_thread` / `core.camera_manager` 全进
`sys.modules`）——"原型对旧 `ui.*` 直接依赖清零"只在**直接 import 层**成立（`grep` 0 命中），
**传递闭包没减**。这是迁移方案 §2.2 的 `ui/__init__` 放大器所致，按 §4 Phase 0.3 的裁决
**不改 `src/`**，随 Phase 0 统一收口；原型的代价就是"必须在仓库树内运行"。

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

**批 3 实测（2026-09-23，offscreen 实跑）**

| 项 | 结果 |
|---|---|
| 七测试退出码 | 全 0（五旧测试无退化 + test_validation_degenerate / test_session 全绿） |
| A3 退化矩阵回归 | 平移错 110 mm 的矩阵（`success=True/rms_t=0` 型退化）→ 戳点 err_mean=35.874 mm → **判 FAIL**；正确矩阵 → err_mean=0.000000 → PASS |
| A3 姿态离面（可测性） | 纯平移验证 / 全共轴旋转 → 离面不满足 → FAIL（沿公共轴平移误差不可辨，fail-closed） |
| A9 判别下限 | 3.0 mm 偏差必判 FAIL；0.2 mm 判 PASS（非亚毫米保证）；1.0 mm 在本合成几何/姿态集 err_mean=0.326 不保证检出——检出率依赖几何与姿态集 |
| R3 err_max 诊断 | 8 姿态含 1 个 2.4 mm 粗差 → err_max=2.100 warning 在、verdict 仍 PASS（不进硬门禁） |
| R2 重合度快检 | 同一云复制 → median=0.000000；整体平移 1 mm → median=1.000000（度量正确）；旋转差 <30° → PRECONDITION_FAILED；轴向盲区提示恒在 |
| A6 会话往返 | handeye（含 validated=True）/ 4 位姿 / 4 帧（含颜色）/ error_report 落盘后逐位还原；缺文件/坏 JSON → 拒绝恢复（fail-closed，无半截会话） |
| smoke 批 3 段 | 戳点 PASS → VERIFIED 解锁导出 → 会话往返 OK → 退化矩阵判 FAIL 回锁 → 重载矩阵回 UNVERIFIED，全过 |

**批 4 实测（2026-09-23，offscreen 实跑）**

| 项 | 结果 |
|---|---|
| 八测试退出码 | 全 0（七旧测试无退化 + test_ui_smoke 两轮复跑 exit=0/0） |
| A4 三帧逐帧真值 | 合并前三帧比对：`0.000e+00 / 2.274e-13 / 2.274e-13 mm`（均 < 1e-9） |
| A4 合并规模 | 3 × 20000 = **60000** 点（`merge_pointclouds` 两参折叠式：copy 首帧后逐帧 fold，非列表入参） |
| A4 PLY 往返 | 落盘 → 重载点数 60000/60000 一致；NN 距离 median=0.000000 < 0.5 |
| A5 实时性 | 30 万点**单帧** 复制+变换+合并 median=28.6 ms < 50 ms（5 次 runs 23.0/28.1/28.6/31.7/30.3；计时只含被测两段，累加器重建在计时外） |
| 门禁接线 | 保存合并 PLY 按钮状态机全过：未 VERIFIED / 0 帧置灰 → VERIFIED 且 ≥1 帧解锁；清空后回锁但会话保存键保持解锁（两者语义不同，已写注释钉死） |

**批 4.5 实测（2026-09-23，合入预适配；offscreen 实跑 + 副本变异）**

| 项 | 结果 |
|---|---|
| 八测试退出码 | 全 0（七旧测试无退化 + `test_ui_smoke` 含新增 §[5] 合入形态段） |
| `--smoke 3` | exit=0，失败 0 项；日志 `全部叠加` = **10 条** = 批 4 基线 **8** 条 + 批 4.5 自检段额外 1 次采集（×2 路）——**上轮"8 条"口径作废** |
| 合入形态接口 | `QWidget` 工作区 + 5 接口齐备、不再是 QMainWindow（smoke 内自检 `[OK]`） |
| 旧 `ui.*` 直接依赖 | 源码级自检 + `grep "^\s*\(from\|import\)\s\+ui\."` = **0 命中**；查看器经 `ui_v2.widgets.viewer_panel.ViewerPanel` |
| 后台 runner 单一来源 | 记录型 runner：调用 **1** 次 `capture_job`、帧 0→1、回调后按钮复位、`dirty_changed` 触发 `True`（1.0.10 禁自建池） |
| 定向变异 M1（`on_capture` 不走注入 runner） | **exit=1**（`[FAIL] 后台任务走注入 runner：调用 0 次`）——自建池路径已被守住 |
| 定向变异 M2a（查看器 import 掐断，守卫在） | **exit=1** + `[FAIL] HAS_VIEWER=False`；`全部叠加`=0 条 |
| 定向变异 M2b（掐断 **且** 打回静默降级 = 批 4.5 前旧行为） | **exit=0** 且 `全部叠加`=0 条 —— 旧隐患（"绿灯 + 3D 消失"）可复现，证明 smoke 里那道 `HAS_VIEWER` 判据是唯一起作用的一道 |
| A8 锚点 | `git diff -- src/ \| sha1sum` = `23bfa1ed…`（`fb6792a` / `4b41c14` 两提交后未变）；`grep -rni "handeye\|robot" src/ui_v2/` = 0 命中 |

## 进度

- [x] 批 0：prototypes/README 表更新 + A8 基线复核（HEAD=8221b82，
      src/ diff sha1=7eceb8c3a8826bc1 与 @arch/@feas 记录一致，见 `BASELINE.md`）。
      `src/core/robot_stitch_workflow.py` 3 行注释修正（K2）**已落地**：commit `11926c2`
      （3+/3- 纯注释，§8-③ 已获 @user 批准），A8 **全闭环**。
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
- [x] 批 2：app UI（复用主功能组件）—— `05fd446` 交付，实测见上表
- [x] 批 2.1：收尾 5 项全落 —— `ea7aa1e`（delta fail-closed / 降级可见 / 三帧真值 /
      矩阵侧 NaN 对称用例 / 锚点按 commit 分节）
- [x] 批 3：validation.py（TipTouchValidator 戳点门禁 + TwoFrameOverlapChecker
      warning 级快检）+ session.py（A6 会话落盘/恢复）+ UI 门禁接线
      （UNVERIFIED/VERIFIED/FAILED 状态机，VERIFIED 才允许保存会话）
- [x] 批 4（offscreen 部分）：test_ui_smoke（A4 端到端 + A5 计时 + 门禁接线）+
      UI「保存合并 PLY」（走 `merge_pointclouds`，VERIFIED 门禁）。
      **真机联调与 CameraPreviewCard 待 §8 现场信息（机器人品牌/位姿格式、
      手眼矩阵是否落成文件、K2 注释批准），不在本批范围。**
- [x] 批 4.5（合入预适配，@lead 拍板插入；与批 4 真机联调互不阻塞）—— `fb6792a`：
      ① `RobotHandEyeWindow(QMainWindow)` → `RobotWorkspace(QWidget)`，接口对齐
      `workspaces/turntable_workspace.py`（`set_devices` / `set_state` /
      `set_background_runner` + `log_message` / `dirty_changed`），窗口/日志控件移出
      ② viewer 换 `ui_v2.widgets.viewer_panel.ViewerPanel`（`viewer_message` 转发
      `status_changed`），原型对旧 `ui.*` **直接依赖清零**
      ③ 删 `_workers` 池与 `ui.worker_thread` 依赖，后台任务走注入 runner（1.0.10）
      ④ 新增 `app/host.py` 独立宿主（QMainWindow 壳 + 同步 stub runner，同签名）
      ⑤ `HAS_VIEWER=False` 不再静默降级：`--smoke` 判失败
      ⑥ 独立提交 `4b41c14`：`session.py` 加载侧过滤原子写残留 `*.tmp.ply`（+ `test_session` §[6]）

> **批 4.5 状态（2026-09-23）**：八测试 + `--smoke 3` 全 exit=0，`全部叠加`=10 条，
> A8 锚点 `23bfa1ed…` 未变。三条定向变异（runner 换回自建 / 查看器掐断 / 掐断+静默降级）
> 实测分别为 exit=1 / exit=1 / exit=0 且 3D 消失，见上表。**合入形态 = 原型形态**：
> 批 5 迁移时只有"壳换成 MainWindowShell + 注入真实 runner"这一处动作，工作区零改动。
> 残留已知边界两条：① 传递闭包未减（2057 模块，`ui/__init__` 放大器，随 Phase 0 收口）；
> ② 必须在仓库树内运行（或设 `MCC_REPO_ROOT`），仓库外的失败是红灯不是绿灯。

> **批 4 状态（2026-09-23，offscreen 部分完成）**：新增 `tests/test_ui_smoke.py`
> （8 节），app 加「保存合并 PLY」按钮 + `merged_pcd()` + `on_save_merged_ply()`
> （QFileDialog，VERIFIED 门禁），`_refresh_state` 按"VERIFIED 且 ≥1 帧"控钮态。
> 八测试 + `--smoke 3` 全 exit=0，A8 守住（`git diff -- src/ | sha1sum` 仍
> `7eceb8c3a8826bc1…`）。关键实现事实：`src/core/pcd_utils.merge_pointclouds`
> 是**两参折叠式** `merge_pointclouds(merged, pcd)`（copy 首帧后逐帧 fold），
> 不是列表入参；A5 计时口径为"单帧"——累加器重建在计时外，被测段只有
> `transform_pcd`（内含 copy）+ `merge_pointclouds(acc, c1)` 两段，与 @qa 基线同项。
> 真机联调与 CameraPreviewCard 依赖方案 §8 现场信息，明确归入后续批次。

> **批 3 状态（2026-09-23）**：core 新增 `validation.py` / `session.py`，新增
> `tests/test_validation_degenerate.py` / `tests/test_session.py`，`app/` 两文件接
> 验证区（戳点记录/门禁/重合度快检/保存会话）。七测试 + `--smoke 3` 全 exit=0，
> A8 守住（`git diff -- src/ | sha1sum` 仍 `7eceb8c3a8826bc1…`），oracle nn_max 三元组
> 与基线逐位一致。戳点门禁口径：n≥3、err_mean≤0.7 mm 硬门禁、err_max>2.0 仅
> warning、姿态离面（≥1 轴与所有其他相对旋转轴夹角 >20°）为硬条件；特征点每姿态
> **单点**（姿态内多点拒收，err_max 门限才可复现）。

> **批 2 状态（2026-09-23）**：`app/main.py` / `control_panel.py` / `window.py` 三文件已落，
> 闭环"合成点云 → 变基座系 → 3D 显示"跑通（`--smoke 3` exit=0，实测见上表）。
> **两点与方案 v4.1 的差异已获 @arch 裁决**：① `CameraPreviewCard` **批 2 不接**（A4 无 2D 项，
> 无相机时是死控件），留到批 4 接真机/离线 2D 帧；② `WorkerThread` 只用在"拍一帧"的变换上，不扩。

> **批 2.1 状态（2026-09-23，收尾 5 项全落）**：RG-11 delta fail-closed（core 级收口 + 三入口
> 负向用例）、RG-09 降级末行可见、smoke 三帧逐帧真值、矩阵侧 NaN 对称用例、锚点表按 commit 分节。
> **delta 不支持**：原型未实现增量累积，`admit_pose()` 一律拒绝 delta；UI 下拉「增量（未支持）」
> 置灰 + tooltip；delta 窗口 `[1, 500] mm` 为预留值（批 2~4 入口不可达）。
