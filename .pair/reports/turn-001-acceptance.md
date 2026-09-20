# turn 001 独立验收（Codex 侧，不经 Claude 之手）

- 日期：2026-09-20
- 任务书：`.pair/inbox/001.md`（抽出「像素→3D」共享服务）
- 交付说明：`.pair/outbox/001.md`（只作参考，不作证据）
- 被验对象：`src/logic/PixelTo3DService.{h,cpp}`、`src/ui/ToolsPanel.cpp`、`src/CMakeLists.txt`
- 结论：**通过**

## 1. 机械证据

### 1.1 构建（命令原文）

```text
cmake --build build --config Release        → 退出码 0
ctest --test-dir build -C Release --output-on-failure
    1/2 Test #1: unit_tests .......... Passed 1.16 sec
    2/2 Test #2: measurement_truth ... Passed 0.41 sec
    100% tests passed out of 2
```

### 1.2 单测总数（Codex 自己数出来的，不看实现方自述）

```text
Get-ChildItem .pair\reports\unit-tests-turn001.*.txt → 统计 "Totals:"
classes=24  passed=270  failed=0
```

基线是 23 类 / 255 passed（见 ledger 000 行）→ 本轮 **+1 类 / +15 条**，
新增的正是 Codex 自己写的验收类 `TestPixelTo3DService`（`tests/test_pixel_to_3d_service.*`）。
既有用例一条没少、一条没红。

### 1.3 源码级契约

```text
rg -n "alignedIndex|pointAt|buildProjectedIndex|buildCorrespondIndex|queryIndex" src\ui\
→ 无匹配（退出码 1）
```

即 UI 层不再自己取点，5 个纯函数调用只存在于服务实现里，符合任务书判据 4。

## 2. 真机证据（真实进程 + 真实界面 + 真实文件，不是假对象）

### 2.1 已知真值的探针数据

`python .pair/tools/make_pixel_probe.py` 生成
`.pair/reports/ui-probe-001/{probe.png, probe.ply}`（64×48 对齐点云，
点 i = (i+0.125, 2i+0.25, 3i+0.375)），所以界面上读到什么数，就能反推它取了哪个索引。

### 2.2 驱动真实 GUI 取数

```text
python .pair/tools/ui_pixel3d_check.py 25352 .pair\reports\ui-probe-001 "5, 7" "0, 0" "63, 47" "1000, 1000"
```

进程：`HandEyeCalibrationTool.exe`（PID 25352，Release 构建实际产物），
路径：工具面板 → 像素→3D（离线反投影）→ 数据文件夹 = 探针目录、2D 图像 = probe.png。

| 界面输入像素 | 界面结果行（原文） | 期望（真值，索引 py*64+px） | 判定 |
|---|---|---|---|
| `5, 7` | `453.125, 906.250, 1359.375` | 索引 453 → `453.125, 906.250, 1359.375` | 一致 |
| `0, 0` | `0.125, 0.250, 0.375` | 索引 0 → `0.125, 0.250, 0.375` | 一致 |
| `63, 47` | `3071.125, 6142.250, 9213.375` | 索引 3071 → 同上 | 一致 |
| `1000, 1000` | 结果行保持上一次值 + 提示 `像素坐标超出图像范围` | 越界应报错、不应给数 | 行为正确（文案变化见 3.1） |

截图：`.pair/reports/ui-app-turn001.png`（面板实际样子：数据文件夹、2D 图像、像素坐标、结果行）。

## 3. 与改前的差异（判据 6 要求的"行为不变"逐条核对）

### 3.1 唯一文案差异：越界像素

改前：对齐/投影路径遇到越界像素都报 `该像素无有效 3D 点（背景或无效深度）`。
改后：`OutOfRange` 是**任务书判据 3 要求新增**的状态，UI 直接沿用 `statusText()`，
所以越界时提示变成 `像素坐标超出图像范围`。

判定：**接受**。语义更准确（越界 ≠ 无有效点），且失败仍然明确报错、不静默给数。
已在批次队列里记为后续可选项（如需逐字一致，可在 002 里加一条映射）。

### 3.2 极端组合（Claude 主动申报，我复核后确认存在）

非对齐点云 + 外参文本非空但解析失败 + 该像素**恰好**命中不带外参投影出来的点 →
改后会返回结果，不再报外参错。触发需要"垃圾外参 + 巧合命中"，属边角输入，
本轮不改；已排进下一轮（002 会重写这一页，正好一并收口）。

## 4. 本轮发现但**不属于**本任务的问题（留给后续任务）

- 手动在「数据文件夹」里打字**不会**刷新「2D 图像」下拉框，必须点「浏览」走一次对话框
  （`refreshPixelTo3DImages()` 只挂在浏览按钮上）。这是**既有行为**，不是本轮引入；
  但在 003「离线：工具打开期间主 2D 显示加载文件图像」里必须一起修好，否则用户会以为功能坏了。

## 5. 判据逐条结论

| 判据 | 结论 |
|---|---|
| 1 构建 0 / ctest 2/2 / 用例数不降 | 通过（24 类 270 passed，基线 23 类 255） |
| 2 新增 API 与签名一致 | 通过（逐字核对 `PixelTo3DService.h`） |
| 3 分派顺序与旧实现一致 | 通过（读实现 + 单测覆盖对应图/对齐/投影三条路径） |
| 4 `src/ui/` 无直接取点调用 | 通过（grep 无匹配） |
| 5 `formatPoint`/`statusText` 文案 | 通过（单测钉死 `1.235, -2.500, 0.000` 与「该像素无有效 3D 点」） |
| 6 离线行为不变 | 通过（真机 3 个像素逐位一致；差异仅越界提示文案，见 3.1） |

## 6. 花费

真实花费 ≈ **¥0.02**（DeepSeek 余额差值，runner 记录）；Claude 自报 costUSD 0.69 是价目表估算，
与实际相差约 30 倍，符合历次经验。
