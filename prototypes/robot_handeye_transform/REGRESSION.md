# 机器人手眼变换原型 — 回归手册（REGRESSION）

> 起始版本：2026-09-23（@qa 提出，@scribe 汇编落盘）。位置与 `BASELINE.md` 同级，随原型进版本控制。
> 用途：**换机 / 他人 / 未来版本复跑时，判定"真跑了"还是"看起来绿了"**。每条含现象、成因、判读规则、来源。
> 权威口径以方案 `docs\机器人手眼变换原型方案_20260922.md`（当前 v4）为准；本手册只做复跑判读。

## 0. 判读总纲

1. **以退出码判 pass/fail，不用 pytest**：`exit=0` = pass。
2. **但退出码 0 不等于判据真跑了**：凡依赖外部资产的节（DLL oracle），必须**在输出里看到该节的实际数值行**才算执行（见 RG-01）。
3. **任何用作比对基线/锚点的 hash、路径、版本号，一律由程序打印后原样粘回**，禁止人工转录（见 RG-08）。
4. 复跑前固定环境：`unset PYTHONPATH; export QT_QPA_PLATFORM=offscreen`，解释器 `D:/Program Files/Anaconda/envs/rvc/python.exe`（conda `rvc`，py3.10）。

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration
unset PYTHONPATH; export QT_QPA_PLATFORM=offscreen
PY="D:/Program Files/Anaconda/envs/rvc/python.exe"
"$PY" prototypes/robot_handeye_transform/tests/test_unit_guard.py     ; echo exit=$?
"$PY" prototypes/robot_handeye_transform/tests/test_handeye_result.py ; echo exit=$?
"$PY" prototypes/robot_handeye_transform/tests/test_transform_chain.py; echo exit=$?
```

---

## RG-01 DLL oracle 缺失时 `exit=0`，skip 与 pass 无法区分

- **现象**：`hand-eye-tools` 不在时，§[5] 打印 `[SKIP] oracle 不可用…`，随后仍 `[ALL OK] test_transform_chain`，**退出码 0**，`nn_max` 行数 = 0。
- **成因**：`test_transform_chain.py:134-137` 的 oracle 分支缺失即跳过，不改变退出码。
- **判读规则**：**必须看到 `nn_max=…` 三行才算真跑了厂商 DLL 对拍**；只有 `[ALL OK]` 不足以判定。
- **现状与目标**：v4 已把 oracle 升为 A1 必需判据——缺失须打印 `[ORACLE SKIPPED]` 且 `exit≠0`，仅 `--allow-skip-oracle` 可显式降级（批 1.5 交付）。
- **来源**：@qa 模拟换机实测（改副本 oracle 路径至不存在目录）；@scribe 本机复跑确认 `hand-eye-tools` 存在时 `rc=0 files=3` 且 `nn_max` 非零。

## RG-02 oracle 版本不可追溯（§[5] 必须打印路径 + 版本 + sha256）

- **现象**：`handeye-tools/handeye_sdk.py:16-42` 自动取 `E:/jingz/Desktop` 上**版本号最高**的 `RVCHandEyeCalibration_v*_win_release` 目录；测试输出不打印路径/版本/哈希。桌面上多装一个更高版本 → oracle **静默换实现**，`nn_max` 无法跨机比对。
- **本次实测基线**（@scribe 程序打印，2026-09-23）：

  | 项 | 值 |
  |---|---|
  | 目录 | `E:\jingz\Desktop\RVCHandEyeCalibration_v3.9.0_20260828_win_release` |
  | DLL | `...\RVCHandEyeCalibration\UI\HandEyeSDK.dll`（与 `SDK\C++\External\HandEyeSDK\Win64\bin\HandEyeSDK.dll` 为同一副本，哈希一致） |
  | 大小 | 64,244,224 B |
  | sha256 | `2ab43b6b5ba968f712f2cee840ab2eb5eb781a7b24c2da1b12536511337c29b4` |

- **判读规则**：§[5] 未打印 DLL 路径/版本/sha256 时，本机 `nn_max` 只能与"同版本"结果比；跨机比对前先对齐该三项。
- **来源**：@qa 发现；@scribe 复核（见 RG-08 的更正说明）。

## RG-03 测试套件不可迁移（只拷原型目录必失败）

- **现象**：只 `cp -r prototypes/robot_handeye_transform` 到别处运行 → `ModuleNotFoundError: No module named 'core'`，**exit=1 + 堆栈**，死在 §[4]，**§[5] 与"oracle 必需"判据永远执行不到**。
- **成因**：`tests/test_transform_chain.py:115-116` 用 `dirname(__file__)/../../../src` 硬编码相对位置定位仓库 `src`。
- **判读规则**：换机复跑必须**整仓克隆**（或等批 1.5 修好 R12）；若在只拷原型目录的场景下看到"绿"，该结果不成立。
- **注**：@feas 用 @qa 描述的方法（仅 `cp -r` + sed oracle 路径）复现出的是 `exit=1`，与 @qa 报告的 `[SKIP]`+`exit=0` 输出不一致；按整仓克隆等价层级后才逐字复现。**报告复现步骤时必须写明是否整仓拷贝**。
- **来源**：@feas 实测（立为 R12）；@arch 已入批 1.5 第 ⑥ 项。

## RG-04 正交性检查判别力盲点（种 bug 未必被拦）

- **现象**：把 `ORTH_TOL` 改成 `1e9`（等于废掉正交检查）后，三个测试**全绿未拦**——因为 `test_handeye_result.py:84` 的"非正交"用例是 `diag([2,1,1])`，被 det 检查兜住了。
- **补充事实**：代码本身能拒 `det=+1 但 ‖RᵀR−I‖∞=0.5` 的 shear 矩阵，只是无可判别用例覆盖（@qa 实测 `validate_matrix` 返回非正交）。
- **判读规则**：新增 `check_rigid_4x4` / `check_pose_*` 时必须补 **`det=+1` 的 shear 用例**，否则新守卫继承同一盲点（批 1.5 第 ⑤ 项）。
- **来源**：@qa 变异实测。

## RG-05 变异测试结果（测试判别力台账）

由 @qa、@feas 分别独立种入变异，结果互证：

| 变异 | §[1] | §[2] | §[3] | §[5] DLL oracle |
|---|---|---|---|---|
| M1 `transform_points_mm` 丢平移列 | FAIL err 303 / 911 / 830 mm | 未拦 | FAIL「输出坐标正确」 | 未拦（该节走 `transform_pcd`，不经此函数） |
| M2 乘序颠倒（`T_handeye @ T_base2tool`） | FAIL 1272 / 1665 / 2540 mm（@feas 记 1665 / 1272 / 2540） | 未拦 | FAIL | **FAIL `nn_max=79.842688 / 72.966874 mm`** |
| M3 `to_mm` 改 ×100 | — | — | — | `test_unit_guard` + `test_handeye_result` 均 FAIL |

**归档结论（A1 证据分层，分歧关闭）**：§[1] 对**乘序**与**逐点变换函数**都有判别力（真值内联矩阵乘、`got` 走被测函数）；§[2] 是自洽检查；§[5] 厂商 DLL 与 §[1] 互不依赖地同时约束乘序（M2 被 DLL 以 79.8 mm 量级独立抓住）。引用 A1 时按此三层，不得整体升降级。

- **来源**：@qa `qa_mutation_test.py`；@feas `feas_probe_mut.py` / `mut_out2.txt`（脚本位置见 §1）。

## RG-06 NaN 静默放行（实现写法坑）

- **现象**：`pose_source` 接受 NaN 位姿，走完变换链输出 `[nan 40. 520.]` 点云（UI 会空白/崩）。
- **成因**：范数窗口写成 `if n < lo or n > hi: raise` 时，**NaN 两次比较均为 False → 静默放行**。
- **判读规则 / 实现约定**：一律写 `if not (lo <= n <= hi): raise`（@arch 数值复核确认）。
- **来源**：@qa 实测透传；@feas 定位机制；@arch 复核。

## RG-07 范数窗口的判别力 assert

- **规则**：窗口必须满足 **`lo > v_max/1000` 且 `hi < 1000·v_min`**（`v` = 该来源合法域极值）；窗口 = 合法域时退化为 `lo > hi/1000`（`unit_guard` 现有 assert 即此形式，无需改）。
- **反例（务必记牢）**：`[100, 100000]` 用错形式（`lo > v_min/1000`）会被判"通过"，实际漏拦 `60×1000=60000` 的 ×1000 误读。
- **位姿侧双窗口**（v4 §4.2）：`absolute → [30, 20000] mm`、`delta → [1, 500] mm`；`pose_type` 与 `unit`/`order` 同级必填。合法域假设集 `[60, 4500] mm` **仍待现场确认**。
- **来源**：@feas `feas_r10_window.py`；@arch 复算更正公式形式。

## RG-08 证据纪律：用于比对的值必须程序打印

- **规则**：任何要当键值/复核锚点用的 hash、路径、版本号，由程序打印后原样粘回，禁止人工转述或跨行重排（方案 §10）。
- **起因更正（@scribe 复核，2026-09-23）**：v4 §1-A1 与 §10 记述"@qa 报的 DLL `sha256` 为 63 位十六进制、不是合法 sha256、转录掉了一个字符"。**@scribe 实测该字符串为 64 位十六进制，长度合法，且与本机 DLL 实际 sha256 逐字符一致**（命令见 RG-02 表）。故"长度不合法/发生转录事故"这一记述**不成立**，需 @arch 更正；规则本身（程序打印优先）保留。
- **判读规则**：复核他人给出的 hash 时，先**自行计算**再判定；长度不符的判断也要用程序输出而不是肉眼数。
- **来源**：@arch v4 §10；@scribe 复核。

---

## 1. 复跑资产位置

| 内容 | 路径 |
|---|---|
| 原型与测试 | `D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\robot_handeye_transform\` |
| 基线锚点（待建，批 1.5） | `prototypes\robot_handeye_transform\BASELINE.md` |
| 本手册 | `prototypes\robot_handeye_transform\REGRESSION.md` |
| DLL oracle 依赖 | `D:\RVC_SRC\hand-eye-tools` + 桌面 `RVCHandEyeCalibration_v*_win_release`（见 RG-02） |
| @qa 探针 | `C:\Users\jingz\AppData\Local\hermes\profiles\qa\cache\scratch\`（`qa_probe_handeye.py`、`qa_mutation_test.py`、`sim_out.txt`） |
| @feas 探针 | `C:\Users\jingz\AppData\Local\hermes\profiles\feas\cache\scratch\`（`feas_probe_mut.py`、`feas_r10_window.py`、`mut_out2.txt`） |
