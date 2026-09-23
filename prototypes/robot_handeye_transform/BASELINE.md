# A8 版本锚点基线（BASELINE）

> 目的：让「本原型是否污染了主项目 src/」能被任何人在任何时候复核，而不靠方案文档里
> 写死的 hash（方案改版 / 他人在 src/ 的改动都会让写死的值漂移）。
> 生成命令口径（§10 证据纪律：一律程序打印，禁止人工转录）：
>
> ```bash
> cd D:/RVC_SRC/Python/MultiCameraCalibration
> git rev-parse --short HEAD
> git diff -- src/ 2>/dev/null | sha1sum | awk '{print $1}'   # 注意 awk 去掉尾巴 " -"
> ```

## 主项目基线

| 项 | 值 |
|---|---|
| `BASE_HEAD` | `8221b82`（2026-09-09，分支 `MultiCameraCalibration`） |
| `BASE_SRC_DIFF_SHA`（K2 改**前**，2026-09-23 @dev 复核） | `7eceb8c3a8826bc13076a235205fb18d44717c6a` |
| `POST_K2_SRC_DIFF_SHA`（K2 改**后**） | **待回填** —— K2 三行注释修正尚未获 @user 批准（方案 §8-③），未落地 |
| 工作树原有未提交改动 | 15 文件 +363/−236（**非本原型引入**，不清理也不背锅，R9） |

一致性记录：该值与 @arch 方案 v4 的 A8 记述、@feas 独立复跑值逐字符一致。

## K2：`src/core/robot_stitch_workflow.py:11-13` 三行注释

**改前原文（当前工作树实读，2026-09-23）**

```
11  Eye-in-Hand: T_base2cam = T_base2tool @ T_tool2cam
12               其中 T_tool2cam = inv(T_cam2tool)（手眼标定结果）
13  Eye-to-Hand: T_base2cam = T_cam2base^{-1} = T_base2cam（手眼标定结果）
```

问题：11-12 行写 `T_tool2cam = inv(T_cam2tool)`，而实现（`compute_cam2base`）
用的是 `T_cam2tool`（实现对，注释错）；13 行 `T_cam2base⁻¹ = T_base2cam` 自相矛盾。
14 行正确，不动。

**拟改后原文（待批）**

```
11  Eye-in-Hand: T_cam2base = T_base2tool @ T_cam2tool
12               其中 T_cam2tool 即手眼标定结果（相机→法兰）
13  Eye-to-Hand: T_cam2base = T_cam2base（手眼标定结果，与机器人位姿无关）
```

批准后需：① 落地这 3 行；② 把新的 `git diff -- src/ | sha1sum` 写进上表
`POST_K2_SRC_DIFF_SHA`。**不批的代价**：A8 只算半闭环（@feas 实读：现有两个 hunk
全是功能性改动 `write_point_cloud_atomic`，没有任何注释 hunk）。

## 变更说明（供将来 blame 对照）

**批 1.5（`15cedf0`）——注意其中两条是「旧代码真实缺陷」，不是新增特性**

1. `pose_source.euler_to_matrix` 删除 `order="ZYX"` 默认（静默默认=静默错姿态）。
2. `pose_source._parse` **修掉旧解析器崩溃**：原实现先 `float()` 整行再判列数，
   任何 **7 列**（含 order）位姿文件都会在 `order` 列抛 `ValueError`。此前无用例覆盖，
   所以从未暴露；批 1.5 改为**先按列数分流再转数值**，并同时支持逗号/空格/制表符分隔。
3. `handeye_result.validate_matrix` 由私有实现改为**委托** `unit_guard.check_rigid_4x4`；
   `ORTH_TOL / DET_TOL / LAST_ROW_TOL` 三个常量随之从 handeye_result 删除 ——
   变异测试（改容差）今后必须改 `unit_guard`，改 handeye_result 不再有任何效果。
4. `pose_source` 三入口签名变更（新增必填 `unit` / `pose_type` / `order`），
   CSV 需带 `# pose_type: absolute|delta` 声明行。

**批 2（本批）**：新增 `app/main.py` / `app/control_panel.py` / `app/window.py`，
不修改 core/ 与 src/。

## 原型自身锚点

| 项 | 值 |
|---|---|
| `PROTO_COMMIT`（首次入库，批 0/批 1 基线） | `249fdb3d75592572dc946c60b00c7d2b14d7c52e`（短 `249fdb3`） |
| `PROTO_COMMIT_BATCH15`（批 1.5 交付） | `15cedf0`（共用校验层 + 位姿守卫 + R12/oracle 证据） |

**批 1 基线（入库版本，@qa 给出的 untracked 代码锚点，@dev 复核一致）**

```
core/handeye_result.py    fd971471f28f4fafae284a0ae7cbe2440f2295aa
core/pose_source.py       3bab3cf09a0c9ee23fefce022f24c6bd50742d97
core/transform_chain.py   3fbec4c574a169818d5210d5280aac4ec043f2fc
core/unit_guard.py        3f3fc533accc03831ce5a068452f1d4139ade216
tests/test_handeye_result.py   96598d6ec4f6f5d99ab50ec143989d85e7ba3134
tests/test_transform_chain.py  5c1b6c2b77d0171a59f845c5e39bfbcfa9cc459c
tests/test_unit_guard.py       e42ae64e0010633d8a87d43b83dfec38081e583b
```

**批 1.5 后（本次改动，待 commit）**

```
core/handeye_result.py    e12e1627ef8fce26f784bd025054b237b1dfa3f1  （validate_matrix 改为委托）
core/pose_source.py       20c94ad6fba68345a3868bdd27243a07b5a9a42  （三入口补 unit/pose_type/order + 守卫）
core/transform_chain.py   3fbec4c574a169818d5210d5280aac4ec043f2fc  （未动）
core/unit_guard.py        8b9b3add0c4c334fc6677964b9823bc8ebcb097c  （共用校验层 + 位姿窗口）
tests/test_handeye_result.py   96598d6ec4f6f5d99ab50ec143989d85e7ba3134  （未动）
tests/test_matrix_guard.py     f275647d688a5570be7ca7d3efe47d593d06eb30  （新增）
tests/test_pose_source.py      1968615a5068f4157a1ba5f11f1bce4df4a0ec95  （新增）
tests/test_transform_chain.py  4b13671b682a0d00ee2295e3361b93703e9084cb  （R12 + oracle 证据/必需判据）
tests/test_unit_guard.py       e42ae64e0010633d8a87d43b83dfec38081e583b  （未动）
```

复核命令：

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration/prototypes/robot_handeye_transform
sha1sum core/*.py tests/*.py
```

**批 2（commit `05fd446`）**

```
app/control_panel.py   4137344b5493aae7c565b692983c461de6c5591f
app/main.py            786576a4668fc05590ba8d5615fde0c11a87a77f
app/window.py          2d6ed2bef30fc7584e0d270aa44764726eaba13c
```
