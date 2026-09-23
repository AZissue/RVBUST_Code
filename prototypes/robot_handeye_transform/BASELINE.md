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

**批 2（`05fd446`）**：新增 `app/main.py` / `app/control_panel.py` / `app/window.py`，
不修改 core/ 与 src/。

**批 2.1（本批，收尾 5 项）**

1. **RG-11 fail-closed**：`pose_source.admit_pose()` 对 `pose_type == "delta"` **直接拒绝**。
   *旧行为（旧代码真实缺陷）*：delta 位姿能通过入口与范数窗口，下游 `compute_cam2base`
   把它当绝对位姿用 → **静默错 420~620 mm**（@feas/@qa 实测），且两窗重叠区
   `[30, 500] mm` 内"声明对错"纯数值不可判别。delta 窗口 `[1, 500] mm` 保留为**预留值**，
   批 2~4 入口不可达。收口在 core（不是 UI 置灰），否则第三方/批 5 下游直接构造 delta 源照样踩洞。
2. **RG-09 降级可见**：`test_transform_chain` 在 `--allow-skip-oracle` 降级时，末行改为
   `[ALL OK — 已降级：A1 独立判据(§[5]) 未执行]` 并附降级汇总，**禁止裸 `[ALL OK]`**。
   *旧行为*：降级路径与真跑同样打印 `[ALL OK]` + exit 0，只看末行/只看退出码的脚本无法区分。
3. **A4 加严**：`app` 的 `--smoke` 改为**每帧**跑解析真值比对（原只覆盖第 1 帧）。
4. `unit_guard.check_translation_norm` 补**矩阵侧 NaN/Inf 对称用例**（此前只有位姿侧被测试盯）。
5. 本文件锚点表改**按 commit 分节** + 钉死 `git show` 取值命令（RG-12）。

## 原型自身锚点

| 项 | 值 |
|---|---|
| `PROTO_COMMIT`（首次入库，批 0/批 1 基线） | `249fdb3d75592572dc946c60b00c7d2b14d7c52e`（短 `249fdb3`） |
| `PROTO_COMMIT_BATCH15`（批 1.5 交付） | `15cedf0`（共用校验层 + 位姿守卫 + R12/oracle 证据） |
| `PROTO_COMMIT_BATCH2`（批 2 交付） | `05fd446`（app 三文件闭环 UI） |
| `PROTO_COMMIT_BATCH21`（批 2.1 收尾） | `ea7aa1e`（delta fail-closed + 降级可见 + 三帧真值 + 锚点分节） |

**锚点取值命令（§10.1，钉死；禁止「量工作树比历史值」——那必然假阳性，RG-12）**

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration
git show <commit>:prototypes/robot_handeye_transform/core/<file> | sha1sum
```

按 commit 分节（每条都是 `git show` 取出的**当时**内容）：

### `249fdb3` —— 批 0/批 1 基线（首次入库）

| 文件 | sha1 |
|---|---|
| core/handeye_result.py | `fd971471f28f4fafae284a0ae7cbe2440f2295aa` |
| core/pose_source.py | `3bab3cf09a0c9ee23fefce022f24c6bd50742d97` |
| core/transform_chain.py | `3fbec4c574a169818d5210d5280aac4ec043f2fc` |
| core/unit_guard.py | `3f3fc533accc03831ce5a068452f1d4139ade216` |
| tests/test_handeye_result.py | `96598d6ec4f6f5d99ab50ec143989d85e7ba3134` |
| tests/test_transform_chain.py | `5c1b6c2b77d0171a59f845c5e39bfbcfa9cc459c` |
| tests/test_unit_guard.py | `e42ae64e0010633d8a87d43b83dfec38081e583b` |

### `15cedf0` —— 批 1.5

| 文件 | sha1 |
|---|---|
| core/handeye_result.py | `e12e1627ef8fce26f784bd025054b237b1dfa3f1` |
| core/pose_source.py | `20c94ad6fba68345a3868bdd27243a07b5a9a42d` |
| core/transform_chain.py | `3fbec4c574a169818d5210d5280aac4ec043f2fc` |
| core/unit_guard.py | `8b9b3add0c4c334fc6677964b9823bc8ebcb097c` |
| tests/test_handeye_result.py | `96598d6ec4f6f5d99ab50ec143989d85e7ba3134` |
| tests/test_matrix_guard.py | `f275647d688a5570be7ca7d3efe47d593d06eb30` |
| tests/test_pose_source.py | `1968615a5068f4157a1ba5f11f1bce4df4a0ec95` |
| tests/test_transform_chain.py | `4b13671b682a0d00ee2295e3361b93703e9084cb` |
| tests/test_unit_guard.py | `e42ae64e0010633d8a87d43b83dfec38081e583b` |

> @qa 上一轮报的「`test_matrix_guard.py` 不一致」由此表可解释：`249fdb3` 时该文件不存在、
> `15cedf0` 时是 `f275647d…`、`05fd446` 起是 `1a1862ba…`（批 2 加了 @arch 硬约束用例）。
> 旧表把 `15cedf0` 的值留在「批 1.5 后」标题下让人去量工作树 → 结构性假阳性（RG-12）。

### `05fd446` —— 批 2（也是 `384615c` / `1fee333` 时点的 .py 状态）

| 文件 | sha1 |
|---|---|
| app/control_panel.py | `4137344b5493aae7c565b692983c461de6c5591f` |
| app/main.py | `786576a4668fc05590ba8d5615fde0c11a87a77f` |
| app/window.py | `2d6ed2bef30fc7584e0d270aa44764726eaba13c` |
| core/handeye_result.py | `e12e1627ef8fce26f784bd025054b237b1dfa3f1` |
| core/pose_source.py | `20c94ad6fba68345a3868bdd27243a07b5a9a42d` |
| core/transform_chain.py | `3fbec4c574a169818d5210d5280aac4ec043f2fc` |
| core/unit_guard.py | `8b9b3add0c4c334fc6677964b9823bc8ebcb097c` |
| tests/test_handeye_result.py | `96598d6ec4f6f5d99ab50ec143989d85e7ba3134` |
| tests/test_matrix_guard.py | `1a1862ba9bc99fab8ac2a18f4fa1c005687be86f` |
| tests/test_pose_source.py | `1968615a5068f4157a1ba5f11f1bce4df4a0ec95` |
| tests/test_transform_chain.py | `4b13671b682a0d00ee2295e3361b93703e9084cb` |
| tests/test_unit_guard.py | `e42ae64e0010633d8a87d43b83dfec38081e583b` |

**想复核"文件有没有被改过"**：改前后都比 `git show` 出的值；只有在**你刚改过工作树**时，
才用 `sha1sum core/*.py tests/*.py app/*.py` 量工作树，并明确那是"未提交状态"，不是锚点。

### `ea7aa1e` —— 批 2.1（当前 HEAD 的 .py 状态）

| 文件 | sha1 |
|---|---|
| app/control_panel.py | `404601088f7e01a7bcfbfd13fa27b077d476fe27` |
| app/main.py | `786576a4668fc05590ba8d5615fde0c11a87a77f` |
| app/window.py | `c07bf4f99484caa4bb834b7e3ea4d290596f67fd` |
| core/handeye_result.py | `e12e1627ef8fce26f784bd025054b237b1dfa3f1` |
| core/pose_source.py | `a58d874ed1661901574289ed69872d4afa9e0690` |
| core/transform_chain.py | `4f15aa421422d0696fd74958cbd6af597c6b87e3` |
| core/unit_guard.py | `8b9b3add0c4c334fc6677964b9823bc8ebcb097c` |
| tests/test_handeye_result.py | `96598d6ec4f6f5d99ab50ec143989d85e7ba3134` |
| tests/test_matrix_guard.py | `a72a19a6cb3941f1f6edbee6ec179820ee591116` |
| tests/test_pose_source.py | `94e080308d05aa3d5899f4f59315b25c71b0d37e` |
| tests/test_transform_chain.py | `383e1f2e30a7cc2f6e9fe89a8985f4e37013f793` |
| tests/test_unit_guard.py | `e42ae64e0010633d8a87d43b83dfec38081e583b` |
