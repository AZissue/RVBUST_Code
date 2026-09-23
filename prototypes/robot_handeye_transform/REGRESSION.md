# 机器人手眼变换原型 — 回归手册（REGRESSION）

> v1 2026-09-23 汇编（@qa 提出、@scribe 落盘）；v2 2026-09-23 批 1.5 / 批 2 后逐条标状态；v3 2026-09-23——收 @qa 第 2 轮复核（锚点表时效性、矩阵侧 NaN 无对称用例）与 @feas 新缺陷 RG-11，新增 RG-11 / RG-12，误拦列改定性表述；**v4 2026-09-23 批 3 后**——@qa 批 3 独立复核结论入库（RG-05 变异台账补 4 条、新增 RG-13）；**v5 2026-09-23 批 4.5 后（@dev 落）**——新增 **RG-14**（`全部叠加` 8→10 条口径、入口改 `host.py`+`RobotWorkspace`、仓库外红灯是设计、定向变异靶点、传递闭包未减），总纲补第 6/7 条，§1 锚点表按 commit 更新（`POST_K2_SRC_DIFF_SHA` 已回填）；**v6 2026-09-23 批 6A 后（@dev 落）**——新增 **RG-15**（矩阵文件 v1 往返判据行、单实现证明手法、导出不卡 A3 门禁的口径待复核），总纲补第 8 条，§0 复跑块加 `test_handeye_file`；**v7 2026-09-23 批 6A 收尾后（@dev 落）**——RG-15 判据行 **4→6 行**（门禁留痕+屏上显形 / 未知值写 null / 安装方式未选必拒），收 @lead v2 §10.4 三项裁定与 @verify 复核备注②③（近似键名、数值不做静默强转）；**v8 2026-09-23 批 6B-1 后（@dev 落）**——新增 **RG-16**（A11-③ 判读规则：内核等价性以 @verify 原始实现为参照、verdict 四值冻结、内核三改待复核、A11-5 覆盖范围如实标注、定向变异靶点实测结果），总纲补第 9 条，§0 复跑块 **6→11 套件**。
> 位置与 `BASELINE.md` 同级，随原型进版本控制。用途：**换机 / 他人 / 未来版本复跑时，判定"真跑了"还是"看起来绿了"**。每条含现象、成因、判读规则、来源。
> 权威口径以方案 `docs\机器人手眼变换原型方案_20260922.md`（当前 v4.3，390 行）为准；本手册只做复跑判读。

## 0. 判读总纲

1. **以退出码判 pass/fail，不用 pytest**：`exit=0` = pass。
2. **退出码 0 不等于判据真跑了**：凡依赖外部资产的节（DLL oracle），必须**在输出里看到该节的实际数值行**才算执行（RG-01、RG-09）。
3. **任何用作比对基线/锚点的 hash、路径、版本号，一律由程序打印后原样粘回**，禁止人工转录（RG-08）。
4. 复跑前固定环境：`unset PYTHONPATH; export QT_QPA_PLATFORM=offscreen`，解释器 `D:/Program Files/Anaconda/envs/rvc/python.exe`（conda `rvc`，py3.10）。
5. 只拷原型目录到别处跑需设 `MCC_REPO_ROOT=<真仓库>`，或把原型放回仓库内（RG-03）；**批 4.5 起"仓库外的红灯"是设计**（RG-14），不是回归。
6. **批 4.5 起绿灯口径含 UI 段判据行与 `全部叠加` 条数**（= **10** 条，RG-14）——末行"失败 0 项"单独不构成批 4.5 证据。
7. **禁自建后台池**（1.0.10）：工作区的后台任务只许走注入 runner；复跑时看 RG-14 的判据行 ④。
8. **批 6A 起绿灯口径含 6A 四行判据**（RG-15）——末行"失败 0 项"单独不构成批 6A 证据。
9. **批 6B-1 起绿灯口径含 11 个测试套件 + A11 判据行**（RG-16）——`test_order_detect` 必须看到内核等价性 `max|Δ|` 行、`12/12 真值唯一通过`、`激励不足时不出排名表`、边界 `通过=2 … 不给唯一答案`、`verdict 取值恰为冻结四值`；只看末行 `[ALL OK]` 不足。

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration
unset PYTHONPATH; export QT_QPA_PLATFORM=offscreen
PY="D:/Program Files/Anaconda/envs/rvc/python.exe"
for t in test_unit_guard test_handeye_result test_handeye_file test_matrix_guard test_pose_source test_transform_chain test_validation_degenerate test_pose_table test_order_detect test_session test_ui_smoke; do
  "$PY" prototypes/robot_handeye_transform/tests/$t.py; echo "$t exit=$?"; done
"$PY" prototypes/robot_handeye_transform/app/main.py --smoke 3; echo "smoke exit=$?"
```

---

## RG-01 DLL oracle 缺失时 `exit=0`，skip 与 pass 无法区分

- **现象（旧版）**：`hand-eye-tools` 不在时，§[5] 打印 `[SKIP] oracle 不可用…`，随后仍 `[ALL OK] test_transform_chain`，**退出码 0**，`nn_max` 行数 = 0。
- **判读规则**：**必须看到 `nn_max=…` 三行才算真跑了厂商 DLL 对拍**；只有 `[ALL OK]` 不足以判定。**降级路径是例外，见 RG-09。**
- **状态**：✅ **默认路径已修复**（批 1.5）。@scribe v2 实测（原型拷到 `C:\Users\jingz\AppData\Local\Temp\scribe_rg09`、oracle 路径置不存在、`MCC_REPO_ROOT` 指向真仓库）：不给 flag → `exit=1` + `[FAILED] 1 项失败: oracle 必需（缺失 → exit≠0；显式降级用 --allow-skip-oracle）`；给 `--allow-skip-oracle` → `exit=0` 且末行仍是裸 `[ALL OK]`（→ RG-09）。
- **来源**：@qa 模拟换机实测；@feas 迁移台架场景 C；@scribe v2 独立复现。

## RG-02 oracle 版本不可追溯（§[5] 必须打印路径 + 版本 + sha256）

- **现象（旧版）**：`handeye-tools/handeye_sdk.py:16-42` 自动取 `E:/jingz/Desktop` 上**版本号最高**的 `RVCHandEyeCalibration_v*_win_release` 目录；输出不打印路径/版本/哈希 → 桌面多装一版即**静默换实现**，`nn_max` 无法跨机比对。
- **状态**：✅ **已落地**（批 1.5 第 ⑦ 项）。@scribe v2 实跑输出：

  ```
  [info] oracle 版本 = v3.9.0  大小 = 64244224 B
  [info] oracle sha256 = 2ab43b6b5ba968f712f2cee840ab2eb5eb781a7b24c2da1b12536511337c29b4
  ```

  测试内自查 `len(sha) == 64` 通过。
- **本机 oracle 基线（程序打印，三方一致：@qa / @arch hashlib / @scribe）**

  | 项 | 值 |
  |---|---|
  | 目录 | `E:\jingz\Desktop\RVCHandEyeCalibration_v3.9.0_20260828_win_release` |
  | DLL | `...\RVCHandEyeCalibration\UI\HandEyeSDK.dll`（与 `...\SDK\C++\External\HandEyeSDK\Win64\bin\HandEyeSDK.dll` 同哈希） |
  | 大小 / sha256 | 64,244,224 B / `2ab43b6b5ba968f712f2cee840ab2eb5eb781a7b24c2da1b12536511337c29b4` |
  | 本机 `nn_max` 基线 | `0.000081 / 0.000070 / 0.000060 mm`（门槛 1e-4） |

- **判读规则**：跨机比对前先对齐"版本 + 大小 + sha256"三项；三项一致而 `nn_max` 不同才说明实现真有差异。该三元组**与运行位置无关**（@feas 迁移台架场景 D 在 clone 副本内跑，与仓库内跑逐位一致）。
- **来源**：@qa 发现；@arch hashlib 复算；@scribe 程序复核（见 RG-08）；@dev 落地打印。

## RG-03 测试套件不可迁移（只拷原型目录必失败）

- **现象（旧版）**：只 `cp -r prototypes/robot_handeye_transform` 到别处运行 → `ModuleNotFoundError: No module named 'core'`，**exit=1 + 堆栈**，死在 §[4]，**§[5] 与"oracle 必需"判据永远执行不到**。
- **成因（旧版）**：`tests/*.py` 用 `dirname(__file__)/../../../src` 硬编码相对位置定位仓库 `src`。
- **状态**：✅ **已修复**（批 1.5 第 ⑥ 项）：改为向上查找含 `src/core/pcd_utils.py` 的仓库根，或读 `MCC_REPO_ROOT`；找不到时打印明确原因，且**不连累 §[5]**。
- **@feas 迁移台架 `feas_r12_reloc.py` 结果**（只 `copytree` 原型目录到 scratch、oracle 置空）：A 无 `MCC_REPO_ROOT` + `--allow-skip-oracle` → `exit=0` 且 §[4]/§[5] **都执行到**；B 加 `MCC_REPO_ROOT` → 仓库根认对（`D:\RVC_SRC\Python\MultiCameraCalibration`）；C 同 B 不给降级 flag → `exit=1 + [FAILED] 1 项失败`；D oracle 恢复 → `nn_max` 三元组与仓库内逐位一致。
- **判读规则**：换机复跑若见 `ModuleNotFoundError: No module named 'core'`，先设 `MCC_REPO_ROOT`。
- **@qa 方法澄清（v3）**：@qa 上轮命令块**漏了第二步**——除 oracle 路径置空外，还把副本里当时那行 `dirname(__file__)/../../../src` 硬编码改成了真仓库绝对路径；没有这一步，就是 @feas 复现到的 `exit=1` 堆栈。**R12 落地后该步已由 `MCC_REPO_ROOT` 取代；引用 @qa 的复现一律按"整仓等价 + `MCC_REPO_ROOT=`"写，不要复制那行硬编码路径。**
- **来源**：@feas 实测（立为 R12）；@arch 入批 1.5；@dev 落地；@qa 方法澄清；@scribe 复现（拷贝目录下 §[4]/§[5] 正常执行）。

## RG-04 正交性检查判别力盲点（种 bug 未必被拦）

- **现象（旧版）**：`ORTH_TOL = 1e9`（等于废掉正交检查）后三测试**全绿未拦**——现有"非正交"用例 `diag([2,1,1])`（`test_handeye_result.py:84`）被 det 检查兜住了。代码本身能拒 `det=+1、‖RᵀR−I‖∞=0.5` 的 shear，仅缺用例覆盖。
- **状态**：✅ **已落地**（批 1.5 第 ⑤ 项）：`test_matrix_guard.py` 增 `det=+1` shear 用例，必须被正交检查单独抓住。
- **可复跑手法（单实现证明）**：把 `unit_guard.ORTH_TOL` 改 `1e9`，`check_rigid_4x4` 与 `handeye_result.validate_matrix` 必须**同时**放行 shear——证明无第二份副本（@dev 已自测）。
- **v3 关闭**：@qa 种 `ORTH_TOL=1e9` → `test_matrix_guard` FAIL×3（含 `det=+1` shear），上轮报的正交盲点已关闭；副本里 `check_rigid_4x4(shear)` 与 `hr.validate_matrix(shear)` 同时放行、`handeye_result` 已无自带三常量 → 单实现委托再次确认。
- **新发现（@qa ②，低）**：**矩阵侧 NaN 的第二道网无直接用例**——把 `unit_guard.py:93` `check_translation_norm` 的 `not (lo <= norm <= hi)` 定向改回 `norm < lo or norm > hi`，三个测试全 `rc=0` 未拦；同手法改**位姿侧** `check_pose_norm` 则立刻 FAIL（`tests/test_matrix_guard.py:99` 有直接调 `check_pose_norm(nan_T,"absolute")` 的用例）。即"双保险"只有位姿侧被测试盯着。已入批 2.1：补 `check_translation_norm(nan_T, True)` 期望 False。
- **来源**：@qa 变异实测（两轮）；@dev 落地。

## RG-05 变异测试结果（测试判别力台账）

由 @qa、@feas 分别独立种入变异，结果互证：

| 变异 | §[1] | §[2] | §[3] | §[5] DLL oracle |
|---|---|---|---|---|
| M1 `transform_points_mm` 丢平移列 | FAIL err 303 / 911 / 830 mm | 未拦 | FAIL「输出坐标正确」 | 未拦（该节走 `transform_pcd`，不经此函数） |
| M2 乘序颠倒（`T_handeye @ T_base2tool`） | FAIL 1272 / 1665 / 2540 mm（@feas 记 1665 / 1272 / 2540） | 未拦 | FAIL | **FAIL `nn_max=79.842688 / 72.966874 mm`** |
| M3 `to_mm` 改 ×100 | — | — | — | `test_unit_guard` + `test_handeye_result` 均 FAIL |

**v2 新增（重要，批 1.5 后口径变了）**：`validate_matrix` 已改为**委托** `unit_guard.check_rigid_4x4`，三个容差常量只存于 `unit_guard`。**今后种变异必须改 `unit_guard`；改 `handeye_result` 的常量已无效果**（该事实已写入 `BASELINE.md` 变更说明，供将来 blame 对照）。

**归档结论（A1 证据分层，分歧关闭）**：§[1] 对**乘序**与**逐点变换函数**都有判别力（真值内联矩阵乘、`got` 走被测函数）；§[2] 是自洽检查；§[5] 厂商 DLL 与 §[1] 互不依赖地同时约束乘序（M2 被 DLL 以 79.8 mm 量级独立抓住）。引用 A1 时按此三层，不得整体升降级。

- **@dev 给 @qa 的待独立验证变异点**：① `unit_guard.ORTH_TOL=1e9` → shear 用例必须 FAIL；② `check_pose_norm` 的 `not (lo<=n<=hi)` 改回 `n<lo or n>hi` → NaN 用例必须 FAIL；③ `to_mm` 改 ×100 → 旧两测试 FAIL。
- **@qa v3 独立种入的 7 类变异**：`ORTH_TOL=1e9` / `to_mm`×100 / 窗口加 `.get()` 兜底 / 跳过刚性校验 / 位姿侧 NaN 写法回退 → **全部被拦住**（`test_matrix_guard` / `test_pose_source` FAIL，`.get()` 由源码级断言拦住）；唯一未拦的是**矩阵侧** NaN 写法回退（见 RG-04 新发现）。
- **@qa v4 批 3 独立种入的 4 类变异**（临时副本，`core/validation.py` / `core/session.py`，全部被拦住）：

| 变异 | 期望 | 实跑 |
|---|---|---|
| M5 禁掉 err_mean 硬门禁（`> gate and False`） | 退化矩阵用例（110 mm）不再 FAIL → 测试 exit≠0 | ✅ `test_validation_degenerate` exit=1 |
| M6 禁掉姿态离面判据（`need=-2.0`） | 纯平移/共轴用例不再 FAIL → exit≠0 | ✅ exit=1 |
| M7 `write_ply` 丢颜色（`has_color=False`） | 颜色一致性用例 FAIL → exit≠0 | ✅ `test_session` exit=1 |
| M8 禁掉位姿 16 数校验（`!=16`→`!=99`） | 坏 poses.json 用例不再 FAIL → exit≠0 | ✅ exit=1 |

- **批 3 复核中修复的一处真实缺陷**：`session.handeye_to_dict` 收到**缺 `T_handeye_mm` 键的字典**时抛未捕获 `KeyError`（不是自家可读报错、也不保证不写盘）——`test_session` 已补负向用例（`{"eye_in_hand": True}` → 拒收，可读报错）。
- **来源**：@qa `qa_mutation_test.py`（两轮）；@feas `feas_probe_mut.py` / `mut_out2.txt`；@qa 批 3 复核（v4，两轮复跑逐位一致 + 4 变异）。

## RG-06 NaN 静默放行（实现写法坑）

- **现象（旧版）**：`pose_source` 接受 NaN 位姿，走完变换链输出 `[nan 40. 520.]` 点云（UI 会空白/崩）。
- **成因**：范数窗口写成 `if n < lo or n > hi: raise` 时，**NaN 两次比较均为 False → 静默放行**。
- **实现约定（强制）**：一律写 `if not (lo <= n <= hi): raise`。
- **状态**：✅ **已落地**（批 1.5 第 ② 项）：NaN 在刚性校验处即被拒，`check_pose_norm` 同时用 `not (lo<=n<=hi)` 双保险；@dev 实测四类必拒（NaN / `det=−1` 镜像 / `det=+1` shear / 末行错）全拒。
- **来源**：@qa 实测透传；@feas 定位机制；@arch 数值复核；@dev 落地。

## RG-07 范数窗口的判别力 assert 与采样口径

- **规则**：窗口必须满足 **`lo > v_max/1000` 且 `hi < 1000·v_min`**（`v` = 该来源合法域极值）；窗口 = 合法域时退化为 `lo > hi/1000`（`unit_guard` 现有 assert 即此形式）。
- **反例**：`[100, 100000]` 用错形式（`lo > v_min/1000`）会被判"通过"，实际**漏拦 81 处**（合法域 `[60,4500]` 0.5 mm 细采样，60→100 mm 段的 ×1000 全落窗内）。
- **误拦列一律定性表述（v3，@feas + @arch 要求）**：`[5,2000]` **裁掉 2000~4500 mm 整段长臂/龙门行程**；`[50,3000]` 裁掉 3000~4500 mm 段；`[30,20000]`、`[10,8000]`、`[50,50000]` 无裁掉。@feas 首轮表里的"误拦 2 / 1"是 **6 个具名场景的计数**，被当比例引用就会错，禁止沿用。
- **采样口径（引用数字时必带）**：`numpy.arange(60, 4500 + 0.25, 0.5)` → **n = 8881**。据此：`[5,2000]` 误拦 5000/8881 = **56.30%**；`[50,3000]` 3000/8881 = **33.78%**；`[100,100000]` 漏拦 **81 处**；`[30,20000]` 0 误拦 0 漏拦。解析核对 `(4500−2000)/(4500−60) = 56.31%` 与采样吻合。**6 点结论不得当定量结论**。
- **位姿侧双窗口**（v4 §4.2）：`absolute → [30, 20000] mm`、`delta → [1, 500] mm`；`pose_type` 与 `unit`/`order` 同级必填。合法域假设集 `[60, 4500] mm` **仍待现场确认**（唯一敞口，@feas 挂账）。
- **硬约束（@arch）**：**禁止 `POSE_NORM_WINDOW_MM.get(pt, 默认值)` 兜底**——一旦有兜底默认值，非法 `pose_type` 会静默落进某一档窗口。@dev 已源码级锁定（`unit_guard.py:193` `lo, hi = POSE_NORM_WINDOW_MM[pt]` 直接索引 + 前置 membership 检查，无 `.get()`，@feas 实读确认），`test_matrix_guard` 增 `inspect.getsource()` 断言 + 歧义值用例（`‖t‖=100 mm` 同时落在两档窗口内，配 `None/""/abs/both/auto` 五个非法 `pose_type` 必须**仍然拒绝**）。
- **来源**：@feas `feas_r10_window.py` / `feas_r10_formula.py`；@arch 复算与细采样；@feas 实读；@dev 落地。

## RG-08 证据纪律：用于比对的值必须程序打印

- **规则**：任何要当键值/复核锚点用的 hash、路径、版本号，由程序打印后原样粘回，禁止人工转述或跨行重排（方案 §10）。
- **状态**：✅ **闭环并已撤回错判**。v4 曾记述"@qa 报的 DLL `sha256` 为 63 位、非法、转录掉一个字符"。@scribe 复核该字符串为 **64 位合法值，且与本机 DLL 实际 sha256 逐字符一致**；@arch 随后的 `hashlib` 复算确认**同值、64 位、64,244,224 B**，并定位分叉点在 **index 22：`cee840` → `ce840`，只丢一个 `e`**，丢失发生在**消息传递环节**，非 @qa 之责——方案已撤回归因并写明复盘。
- **三条教训（@arch 补入方案 §10）**：① 长度异常先查流水线，别先归因于人；② 长 hex 只认程序打印 + 落盘副本；③ 同一值只留一份"程序产生"的落盘副本，后续引用指向它，不再靠聊天窗口传 hash。
- **判读规则**：复核他人给出的 hash 时先**自行计算**再判定；长度不符的判断也要用程序输出，不能肉眼数。
- **来源**：@arch v4 / v4.1；@scribe 复核；@dev 侧 §[5] 已程序打印（v2 复跑可见）。

## RG-09 降级路径把 skip 又变回 pass（新，2026-09-23）

- **现象**：`--allow-skip-oracle`（批 1.5 新增的合法降级入口）下，末行仍是裸 `[ALL OK] test_transform_chain`、**退出码仍是 0**；只有中间一行 `[ORACLE SKIPPED]` 能区分 §[5] 是否执行。
- **@scribe v2 独立复现**（原型拷到 `C:\Users\jingz\AppData\Local\Temp\scribe_rg09`、oracle 路径置不存在、`MCC_REPO_ROOT` 指向真仓库）：

  ```
  降级路径 --allow-skip-oracle : exit=0  末行 = [ALL OK] test_transform_chain   nn_max=0
  默认路径（不给 flag）        : exit=1  末行 = [FAILED] 1 项失败: oracle 必需（缺失 → exit≠0；…）
  ```

  源码位置：`tests/test_transform_chain.py:190-192`（skip 打印 + 默认 FAIL）、`:260`（**无条件**打印 `[ALL OK]`）。
- **判读规则**：降级路径上**只看退出码或只看 `[ALL OK]` 都会把 skip 当 pass**；必须检查是否出现 `nn_max` 三行，或（条款落地后）是否出现"降级"字样。
- **处置**：@arch 已升级为 **A1 第三条硬条款**——降级路径末行禁止裸 `[ALL OK]`，必须写成 `[ALL OK — 已降级：A1 独立判据(§[5]) 未执行]`，且汇总块须出现"降级"字样（@dev 待改，一行）。理由：这个洞出在**方案条款层**（v4 只写"仅 `--allow-skip-oracle` 降级为 0"，未规定降级后如何显示），手册只能事后提醒、拦不住下一次。
- **来源**：@feas 迁移台架场景 A 发现；@scribe 独立复现并定位源码行；@arch 条款级修正。

## RG-10 app 层 smoke 的独立证据面（新，2026-09-23）

- **现象**：`app/main.py --smoke 3` 的真值比对（`app/window.py:374-386`）只覆盖**第 1 帧**，第 2/3 帧仅打印 `‖t_cam2base 平移‖` 范数。多帧闭环只被真值覆盖一次太薄。
- **判读规则**：批 2 收尾后 smoke 必须**三帧逐帧**与解析真值比对（第 1 帧真值走内联矩阵乘，路径独立、非自证）；届时 §[1]（core 层）与 smoke（app 接线层）构成**两级同口径证据**。
- **状态**：@arch 已采纳为 **A4 加严**，@dev 批 2 收尾补。
- **来源**：@feas 实读 + 建议；@arch 采纳。

## RG-11 `pose_type='delta'` 可声明、可过门禁，但链上被当绝对位姿用（新，2026-09-23）

- **源码事实**：`pose_type` 在整个原型里只有三处用途——`normalize_pose_type`、`_check_type_lock`（同源锁定）、`check_pose_norm`（**选窗口**）；`core/` 里**没有任何增量累积/合成分支**；`app/window.py:301` 无条件 `compute_cam2base(True, handeye, T_bt)`；`app/control_panel.py:118` 下拉却给出 `("绝对","absolute") / ("增量","delta")`。@scribe grep：`README.md` 中"增量 / delta"**零命中**，使用者无从知道 delta 未实现。
- **@scribe 独立复现**（探针 `%TEMP%\scribe_rg11_probe.py`，只读 core 函数，未写入原型）：

  ```
  admit_pose(T_delta,"mm","delta")  -> True  | ‖t‖=50.000 mm 在位姿窗口 [1, 500] mm 内（增量位姿）
  窗口 absolute=[30,20000]  delta=[1,500]  重叠区=[30,500] mm
  compute_cam2base 只吃矩阵、不看 pose_type → 逐元素相同
  把 Δ 当绝对位姿用：逐点最大偏差 420.000 mm（全程无报错）
     ‖t_cam2base‖ 错误路径 171.931 mm / 正确路径 717.892 mm
  ```

  重叠区 `[30,500] mm` 说明：落其中的数值**两种声明都 pass** → 窗口对"声明错"判别力为 **0**，元数据声明不可能靠数值自证。
- **裁定（@arch v4.3，选 (a) fail-closed，位置改在 core）**：`admit_pose()` 遇 `pose_type == "delta"` **直接拒绝**（"增量合成未实现，请改绝对位姿"）；UI 下拉「增量」置灰 + tooltip 只是表层提示——洞不能留在 API（否则第三方或迁移后的下游直接构造 delta 源照样静默错）。delta 窗口 `[1,500] mm` **保留为预留值**，批 2~4 不可达。测试要 **core 级负向断言**（delta 位姿不得进入 `compute_cam2base`），不断言数值。选项 (b)（实现累积）的触发条件是**现场只给增量位姿**，届时累积结果必须再过一次 absolute 窗口，并与戳点门禁同口径验收。
- **判读规则**：复跑若见 delta 来源仍能进链 → 该结果不成立；`BASELINE.md` 应记为"**旧行为（真实缺陷）**：delta 可通过门禁但被当绝对位姿用"。
- **来源**：@feas `feas_pose_type_semantics.py`（420 / 450 mm，窗口重叠区证据）；@scribe 独立复现；@arch 裁定与实现位置。

## RG-12 锚点表时效性：禁止"量工作树比历史值"（新，2026-09-23）

- **现象**：`BASELINE.md` 批 1.5 哈希表第 94 行记 `tests/test_matrix_guard.py f275647d688a5570be7ca7d3efe47d593d06eb30`，而磁盘实值 `1a1862ba9bc99fab8ac2a18f4fa1c005687be86f`。取证：`git show 15cedf0:prototypes/robot_handeye_transform/tests/test_matrix_guard.py | sha1sum` = `f275647d…`（记录**当时**正确）、`05fd446` / `384615c` / HEAD = `1a1862ba…` → 批 2 改过这个文件（即 @arch 那条禁兜底窗口的 `inspect.getsource()` 断言 + 歧义值用例），而 `384615c` 只回填了 `app/` 三个文件，批 1.5 那张表没跟更新。@scribe v3 复核 12 个文件哈希：**11 行一致、1 行不符**。
- **后果**：照 BASELINE 复核的人会在这一行判"文件被改过"（**假阳性**）；几次之后就会学会忽略这张表 → 锚点等于没有。
- **规则（@arch 新增 §10.1）**：哈希表一律**按 commit 分节**，取值命令钉死 `git show <commit>:<path> | sha1sum`；**禁止"量工作树比历史值"**（`BASELINE.md` 原文给的 `sha1sum core/*.py tests/*.py` 量的是工作树，与 `15cedf0` 时刻的值比必然假阳性）。批 2.1 第 ⑤ 项按此改，**不是**把 `f275647d` 换成 `1a1862ba` 了事。
- **`.gitignore` 盲区**：原型目录运行会落一个被忽略的 `MultiCameraCalibration.log`（81 B）——**`.gitignore` 不构成"零写入"证据**，A8 污染检查天然漏这类产物（量级无害，但口径要写对）。
- **来源**：@qa 缺陷①与备注；@arch §10.1；@scribe 复核。

## RG-13 批 3 判读规则：smoke 的 A3/A6 段必须看到实际判定行（新，2026-09-23 批 3 后）

- **规则**：`--smoke 3` 末行「失败 0 项」**不构成**批 3 证据——必须同时在输出里看到：
  ① 两行 `[戳点门禁] verdict=`（真值样本 `PASS` + 退化矩阵反例 `FAIL`，各带
  `err_mean` 数值）；② 一行 `A6 会话往返 OK`（含位姿/帧计数）。缺任一则与 RG-01
  同性质的"看起来绿了"，判复跑无效。七测试套件同理：退出码 0 之外，
  `test_validation_degenerate` 必须出现「退化矩阵必须判 FAIL」的 `[OK ]` 行、
  `test_session` 必须出现「四项落盘」行。
- **背景**：批 3（`cde52e8`）把 A3 戳点门禁与 A6 会话接进 UI 状态机
  （UNVERIFIED/VERIFIED/FAILED，VERIFIED 才解锁「保存会话」）。门禁口径钉死：
  n≥3、err_mean ≤ 0.7 mm 硬门禁、err_max > 2.0 mm 仅 warning（R3）、姿态离面
  （≥1 个相对旋转轴与所有其他轴夹角 >20°）为硬条件、特征点每姿态单点
  （姿态内多点拒收——不钉死则 err_max 门限不可复现，@feas §4.2）。
- **复核记录（@qa v4，2026-09-23）**：七测试 + smoke 各 2 轮，除临时目录随机名外
  输出逐位一致；4 类变异全部被拦（见 RG-05 台账 M5~M8）；修复一处真实缺陷
  （`handeye_to_dict` 缺键 `KeyError` → 可读拒收）。
- **来源**：@qa 批 3 独立复核。

## RG-14 批 4.5 判读规则：`全部叠加` 条数与"单一 runner"（新，2026-09-23 批 4.5 后）

- **基线口径变更**：`app/main.py --smoke 3` 日志里的 `全部叠加` 条数 **8 → 10**（批 4 基线 8 条；批 4.5 的 smoke 自检段多做 1 次采集，每帧 2 路 → +2）。复跑按 **10** 比，同时仍须 ≥1（方案 §5 批 4.5 行）；**0 条 = 3D 没上屏**。
- **批 4.5 判据行**（缺任一 = "看起来绿了"，判复跑无效）：

  ```
  [OK] 3D 查看器可用：HAS_VIEWER=True，面板 = ui_v2.widgets.viewer_panel.ViewerPanel
  [OK] 合入形态接口齐备：QWidget 工作区 + set_devices / set_state / set_background_runner / log_message / dirty_changed
  [OK] 无 `from ui.` / `import ui.` 直接依赖（查看器经 ui_v2 面板）
  [OK] 后台任务走注入 runner：调用 1 次 [('capture_job', False, None)]；帧 n→n+1；采集按钮已复位=True
  [OK] dirty_changed 已接线（本次 smoke 共 1 次事件） / [OK] set_state / current_state 生效（matrix_loaded）
  ```

- **入口变更（重命名，不是丢失）**：`app/main.py` → `app/host.py`（QMainWindow 壳 + 日志面板 + 同步 stub runner，与 `BackendBridge._run_background` 同签名）→ `app/window.py::RobotWorkspace(QWidget)`。复跑脚本 grep 旧类名 `RobotHandEyeWindow` 会 **0 命中**。
- **必须在仓库树内运行**（实测，2026-09-23）：仓库外不设 `MCC_REPO_ROOT` 时 `--smoke 3` = **exit=1** + 三行可读报错（`No module named 'ui_v2'` / `src/core 不可用（merge_pointclouds 缺失）` / `仓库根 = 未找到`）；`tests/test_ui_smoke.py` = exit=1 + `ModuleNotFoundError: No module named 'core'` 堆栈（R12 只覆盖了 `MCC_REPO_ROOT` 这条出路）。**这两种红灯都是设计（批 4.5 ⑤），不是回归。**
- **定向变异靶点（换机复跑可自查，均在副本内做，不动仓库）**：

  | 变异 | 期望实测 |
  |---|---|
  | `on_capture` 不走注入 runner（改回自建池 / 直接同步） | exit=1，`[FAIL] 后台任务走注入 runner：调用 0 次` |
  | `from ui_v2.widgets.viewer_panel import ViewerPanel` 掐断 | exit=1，`[FAIL] HAS_VIEWER=False`（`全部叠加`=0 条） |
  | 上一条 **加上** ① 分支去掉 `bad += 1`（= 批 4.5 前的静默降级） | exit=0 且 `全部叠加`=0 条 ← 旧隐患"绿灯 + 3D 消失"可复现，说明那道判据是唯一起作用的一道 |

- **传递闭包未减（已知边界，非缺陷）**：`import ui_v2.widgets.viewer_panel` 连带 **2057 模块**（`ui.main_window` / `ui.viewer_3d` / `ui.worker_thread` / `core.camera_manager` 全进 `sys.modules`；批 4.5 前 `import ui.viewer_3d` 亦为 2033 模块）。"对旧 `ui.*` 直接依赖清零"只成立于**直接 import 层**；按迁移方案 §4 Phase 0.3 的裁决**不改 `src/`**，随 Phase 0 统一收口。
- **仓库外两种失败形态不同，验收口径要分开写（@verify 备注①，2026-09-23 批 4.5 复核）**：
  **app 路径** = 三行**可读报错**（`[ERROR] 3D 查看器引入失败…` / `[ERROR] 合入形态下该降级非法：--smoke 一律判失败（批 4.5 ⑤）` / `仓库根 = 未找到`）；
  **tests 路径** = **原生 traceback**（`ModuleNotFoundError: No module named 'core'`，抛点 `tests/test_ui_smoke.py:71` 的模块级 `from core.pcd_utils import merge_pointclouds`）+ exit≠0。
  后者是设计内（R12 只给出 `MCC_REPO_ROOT` 这条出路，没有包装该 import），**不得判为"报错不友好"缺陷**；若要统一成可读报错，属**批 4.7 候选动作，需 @lead 拍板**后做。
- **批 5 交接硬要求（@verify 备注②）**：`HAS_VIEWER` 显形**目前只活在原型的 `--smoke` 自检段**（`window.py` 那道 `bad += 1`）。批 5 把工作区搬进 `ui_v2` 时，必须把"查看器不可用 ⇒ 判失败（禁止静默降级）"这条判据一并搬过去（工作区自检或 ui_v2 侧测试），**丢了就回到 M2b：绿灯 + 3D 消失**。
- **来源**：@dev 实现 + 副本变异实跑（`%TMPDIR%/mut_b45.py`）；@lead 独立复跑 `--smoke 3`（10 条）+ 闭包实测 + 两处自主扩权裁决；方案 §5 批 4.5 行。

## RG-15 批 6A 判读规则：矩阵文件往返必须看到数值行（新，2026-09-23 批 6A 后）

- **规则**：`--smoke 3` 末行「失败 0 项」**不构成**批 6A（A10 矩阵落文件）证据——必须同时看到 **6 行** `6A` 判据（缺任一 = "看起来绿了"，判复跑无效）：

  ```
  [OK] 6A 矩阵文件写→读：16 元素逐元素 max|Δ|=0.000e+00（门槛 1e-12；roundtrip 0.000e+00）
  [OK] 6A 单位冲突必拒：文件 unit=mm + 界面 m → 已拒绝
  [OK] 6A 门禁留痕+屏上显形：UNVERIFIED 也可导出，文件 validated=False／verification.state=UNVERIFIED，导出按钮可用=True，屏上黄条可见=True
  [OK] 6A 未知值写 null：文件 rms_t_mm=None / rms_r_deg=None / n_samples=None；读回 rms_unknown=True；屏上元数据行含'未知'=True
  [OK] 6A 安装方式未选 → 手动录入已拒：矩阵未被替换=True（旧版会静默当'眼在手外'录进去）
  [OK] 6A 面板导入路径：读回矩阵与导出前逐元素一致=True；导入后状态 validated=False（应 False）
  ```

  七/九测试套件同理：`test_handeye_file` 必须出现 `mm 域写→读 16 元素逐元素一致 | max|Δ|=0.000e+00` 与 `[OK  ] 单实现：改 unit_guard.ORTH_TOL 两侧同时放行` 两行，只看末行 `[ALL OK]` 不足。
- **@dev 复跑基线（2026-09-23，本机，`unset PYTHONPATH` + offscreen）**：9 个测试套件（`test_unit_guard` / `test_handeye_result` / `test_handeye_file` / `test_matrix_guard` / `test_pose_source` / `test_transform_chain` / `test_validation_degenerate` / `test_session` / `test_ui_smoke`）**全部 exit=0**；`app/main.py --smoke 3` **exit=0**、`全部叠加` = **10** 条（RG-14 基线未变）、`失败 0 项`。
- **写→读逐元素 max|Δ|（A10-1）**：**mm 域实测 0.0、m 域实测 0.0**（本机这批数值）；判据按 `< 1e-12` 判，**不把"某批数值恰好 0.0"当恒等式** —— `m` 域是 `÷1000 → ×1000` 的往返，只有 mm 域是恒等变换。
- **`sha256` 不是跨次复跑锚点（新增，务必按此引用）**：`write_matrix_file` 返回的 `sha256` 含 `created_at`，**每次写出都不同**（@dev 三次 smoke：`5fbdaafc…1742` / `d41f5b0b…e182` / `20a1a0e6…53eb`）。它只用于回答"手里这份文件是哪一份"（同文件跨机/跨人流转时逐位可比），**禁止**当"批 6A 复跑是否一致"的锚点；跨次比对用 `max|Δ|` 与判据行。
- **单实现证明手法（换机可自查，副本内做）**：把 `unit_guard.ORTH_TOL` 置 `1e9` → `read_matrix_file(shear)` 与 `HandEyeResult.from_matrix(shear)` 必须**同时放行**（实测：容差正常时 `read_matrix_file(shear)=False`，置 `1e9` 后两者皆 `True`）——证明 `handeye_file` 未自带第二份几何校验，只是委托。测试内已用 `try/finally` 还原容差（不改仓库文件）。
- **导出不卡 A3 门禁但必须显形（@lead v2 §10.4-① 裁定落地）**：`[导出矩阵文件]` 只要**加载了矩阵**就可用（不看 `validated`），理由是用户需求 U1 是"把矩阵带到别处用"；门禁状态**两处显形**——① 文件里 `verification` 块（`state` ∈ VERIFIED/UNVERIFIED/FAILED，含 `tip_verdict`/`err_mean_mm`）+ 布尔冗余 `validated`（两者矛盾则拒）；② UI 门禁黄条 `lbl_export_gate`（未 VERIFIED 黄字、VERIFIED 绿字）。读回一律 UNVERIFIED（A3 不信任文件声明）。
- **`null` = 未知，不是 0（@lead v2 §10.4-②）**：手动/无标定来源的 `rms_t_mm / rms_r_deg / n_samples` 写 **`null`**（旧版写 0.0 会被读成"完美标定"）；读回置 `res.rms_unknown=True`，UI 元数据行 `lbl_he_meta` 显示"未知"。数值字段只接受 JSON number —— `"0.1"` 字符串 / `true` / `n_samples=1.5` 一律拒（**不做静默强转**，@verify 复核备注③ 已收）。
- **近似键名必须拦（@verify 复核备注② 已收）**：`difflib` 相似度 ≥ 0.7 的未知顶层键直接拒并提示正确键名（实测 `order_detect` → 报 `pose_order_detect`）；完全无关的未知键仍容忍。测试内两条用例（拒 / 容忍）都在 `test_handeye_file` §[7]。
- **安装方式未选不再伪装（@lead v2 §10.4-③）**：`control_panel.py` 旧版 `bool(None)→False` 把"没选"变成"选了眼在手外"，对 `eye_in_hand=true` 的 JSON 报成"安装方式不一致"。现在信号原样传 `None`：**手动录入**未选 → 直接拒（无文件可推断，D4/K6）；**文件路径**（JSON / v1 矩阵文件）未选 → 以文件声明为准并在日志明说。
- **来源**：@dev 实现 + 实跑（`core/handeye_file.py` / `tests/test_handeye_file.py` / `app/window.py` / `app/control_panel.py`）；方案 `docs\机器人手眼变换原型_补充方案_矩阵落文件与欧拉顺序自动判定_20260923.md` §1 A10-1~A10-5。

---

## RG-16 批 6B-1（A11-③ 欧拉顺序自动判定）判读规则与已知边界

- **绿灯口径**：`tests/test_pose_table.py` + `tests/test_order_detect.py` 两个新套件 **exit=0**，且必须看到下列**判据行**（只看末行 `[ALL OK]` 不构成证据）：
  - `[OK  ] 残差向量逐元素一致（真值点 / 闭式初值点 / 6 个随机 p）` —— **内核等价性以 @verify 的原始实现为参照**：只 `exec` 源码取其 `resid`，不复制内容；参照文件缺失时该套件**直接 FAIL**（不静默跳过 —— A1 口径）。参照位置按优先级：`tools/golden/full_handeye.py`（@lead v2.3-⑥ 指定）→ @verify scratch 唯一副本。
  - `[OK  ] 12/12 真值唯一通过` + 12 行 `真值 XXX → order=XXX rms≈1e-13 次佳=44.786（4e13×）`
  - `[OK  ] 激励不足时不出排名表`（纯单轴旋转 → `INSUFFICIENT` + 只说"补什么方向"，`ranking=[]`、`order=None`）
  - `[OK  ] 边界（两个约定同时落在阈内）→ 不给唯一答案`（实测 `通过=2 并列=['XYZ/deg', 'xyz/deg']`，`verdict=MULTI`）
  - `[OK  ] verdict 取值恰为冻结四值`、`[OK  ] mm / m 两种声明 → 排名逐位一致`
- **verdict 四值冻结（@lead v2.3-③）**：`OK / MULTI / INSUFFICIENT / INVALID`。后三者**都不出结论**（`order`/`rms`/`T_handeye` 为 `None`）。UI 文案必须分开：`INVALID` = **输入不可用**（记录非法 / 纯位姿表，`dropped_idx` 列出被丢行）；`INSUFFICIENT` = **激励不足**（数据可补，`hints` 给补哪个方向）。
- **定案只走两条一级/二级判据**：一级 = SDK 基线差（`baseline_diff` 与 `poseType=0` 的 `totalMeanError` 比）；二级 = `pass_tol = max(0.05, 3σ)` 下**唯一通过 + 倍数差 ≥ 10**。弱判据（相对旋转角不变性）**只出现在 `_excitation_metrics` 里做激励诊断，不参与任何定案分支**（A11-4；源码扫描断言固定此事实）。
- **`0.05` 的含义**：是**合成无噪口径**的绝对残差门限，现场必须重标（R13）；SDK 引擎里比的是与基线的**差值**不是绝对门限（真实数据真值 `tme=2.05 mm` 远超 0.05）。σ 给了就用 `max(0.05, 3σ)` —— 阈值是噪声底，不是魔数。
- **内核三改（本批实现，@verify 复核单独立项，见提交信息）**：① **残差向量化**（等价性由 `[0]` 节固定）② **AX=ZB 闭式初值**（随机多起点会**假阴性**：真值分支自己停在 rms 8~80 → 报"0 个候选通过"；实测 `n_starts` 1→6 与 `max_nfev` 500→20000 都救不回）③ **零空间解 ±vec(R) 必须先按 `det` 定符号**再做 SO(3) 投影（否则给出错旋转）。
- **覆盖范围如实标注（禁写成"已覆盖"）**：A11-5 的"**留一冠军自然翻转**"本机**未找到合成用例**（@lead v2.3-④ 裁定不为此卡批次）。现测试断言的是：① 边界只出 `MULTI/INSUFFICIENT`；② 排名表并列全部候选；③ **掩码不变量** —— 任何掩码下都不允许"冠军变了而结论仍是 `OK`"。**后续找到自然翻转用例再补**，不得据此条宣称已覆盖翻转。
- **重复位姿按去重计**（@verify 真实数据发现）：激励质量看**去重后的不同旋转条数**，不看总条数（真实数据集前 3 行逐位相同、相对旋转 0.00°）。平移散布判据按**维数**选（R25）：n<4 查共线（第 2 奇异值）、n≥4 查共面（第 3 奇异值）—— 按字面"最小奇异值"读会把**所有 n=3 数据集判死**。
- **性能与超时**：单次判定（24 候选、n=6~8）约 2 s；默认开 LOO 约 41 s；`test_order_detect` 全文件约 **89 s**（12 真值 sweep 用 `n_starts=1, max_nfev=200`）。sweep 不要开 LOO。
- **定向变异靶点（本批实测 5/5 全部检出，副本内做，交付树不动）**：

  | # | 变异（`core/order_detect.py`） | exit | 具名 `[FAIL]` 行 | 命中判据 |
  |---|---|---|---|---|
  | 1 | `MIN_AXIS_SPREAD_DEG = 5.0` → `90.0` | 1 | 2 | 激励门误杀一般位姿数据 → `[0]` 参照/本实现 rms 不一致 |
  | 2 | 关倍数差门（`if not res["gap"]["ok"]:` → `if False and …`） | 1 | 1 | `[5] 自然边界（1 个通过但倍数差 < 10）→ 判边界不给答案`：变异后直接给出 `verdict=OK`（**错误答案**） |
  | 3 | 关 ±vec 符号修正（`if np.linalg.det(RZ) < 0:` → `if False:`） | 1 | 1 | `[3] ±vec 符号坑定点用例（n=3 seed=2）`：变异后 `verdict=MULTI`、`champion=ZXY/deg rms=14.84` |
  | 4 | 唯一通过分支放宽（`if len(passed) != 1:` → `if len(passed) < 1:`） | 1 | 1 | `[5] 边界（两个约定同时落在阈内）`：变异后 `verdict=OK`（**错误答案**） |
  | 5 | `MIN_TRANSLATION_SV_MM = 5.0` → `1e9` | 1 | 2 | 平移门误杀 → `[0]` rms 不一致 |

  **判据是"具名 FAIL 行点到该判据名"，不是"exit=1"** —— 首轮变异 1 只崩在测试自身的格式化（`rms=None` 时 `:.3e` 抛 TypeError）而没给出判据名，已修（`fnum()` 安全格式化）。**靶点 2/3/4 是首轮"未被检出"的两个覆盖洞补出来的**：倍数差门与 ±vec 符号修正原本都没有有效靶点（前者 MULTI 来自"通过数 ≠ 1"分支，后者所有测试数据集都不触发）。
- **来源**：@dev 实现 + 实跑（`core/pose_table.py` / `core/order_detect.py` / `tests/test_pose_table.py` / `tests/test_order_detect.py`）；@verify spike（`full_handeye.py` / `min_poses.py`，收编为 golden 参照）；方案 v2.3 §1 A11-③ 判据细则、§10.5-②（R19 基数）、§10.6（真实数据 sweep）、R24/R25。

---

## 1. 复跑资产与锚点

| 内容 | 路径 / 值 |
|---|---|
| 原型与测试 | `D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\robot_handeye_transform\`（`core/`、`tests/`、`app/`、`README.md`、`BASELINE.md`、`REGRESSION.md`） |
| 基线锚点 | `prototypes\robot_handeye_transform\BASELINE.md`（`PROTO_COMMIT` = `249fdb3d75592572dc946c60b00c7d2b14d7c52e`，`PROTO_COMMIT_BATCH15` = `15cedf0`；`POST_K2_SRC_DIFF_SHA` = `23bfa1ed0dba0b1c88c313429c955ea7f2acc497`，K2 已获 @user 批准并于 `11926c2` 落地、`7b84df6` 回填——**本行 2026-09-23 批 4.5 后更新，原"待回填"已失效**） |
| 批次 commit | `249fdb3` 批 0/1 入库 / `15cedf0` 批 1.5 / `42b6a66` 回填 / `05fd446` 批 2 app / `384615c` 回填 / `ea7aa1e` 批 2.1 / `cde52e8`+`1b065d2` 批 3 / `11926c2` K2 注释 / `7ef769c`+`6750de2` 批 4 / `7b84df6` K2 锚点回填 / **`fb6792a`+`4b41c14` 批 4.5** |
| A8 基线 | K2 前 `git diff -- src/ 2>/dev/null \| sha1sum \| awk '{print $1}'` = `7eceb8c3a8826bc13076a235205fb18d44717c6a`；**K2 后（现行）= `23bfa1ed0dba0b1c88c313429c955ea7f2acc497`**（批 4.5 两提交后复测未变） |
| DLL oracle 依赖 | `D:\RVC_SRC\hand-eye-tools` + 桌面 `RVCHandEyeCalibration_v*_win_release`（见 RG-02） |
| @qa 探针 | `C:\Users\jingz\AppData\Local\hermes\profiles\qa\cache\scratch\`（`qa_probe_handeye.py`、`qa_mutation_test.py`、`sim_out.txt`） |
| @feas 探针 | `C:\Users\jingz\AppData\Local\hermes\profiles\feas\cache\scratch\`（`feas_probe_mut.py`、`feas_r10_window.py`、`feas_r10_formula.py`、`feas_r12_reloc.py`、`mut_out2.txt`、`proto_v2_sim/`） |
| @scribe 复现件 | `C:\Users\jingz\AppData\Local\Temp\scribe_rg09\`（RG-09 最小复现，临时件，不属交付物） |
