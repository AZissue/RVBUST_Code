# T-008 r2 验收证据（A）— 标定结果正文的单一出处

日期：2026-09-30　　结论：**通过**（含两条流程观察，见 §4）

## 1. 判据（`python .trio/verify.py T-008 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | 正文只在 `CalibrationService` 里拼一次 | ✓ | `reports/T-008/dedupe_probe.py` → `PASS`（两个字面量各 1 处，两个调用点都出现 `formatResult(`） |
| 2 | 正文不因重构变形 | ✓ | `qt_class_probe calibration_service 7` → `PASS`（7 passed / 0 failed） |
| 3 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2` |
| 4 | 工作集守门 | ✓ | `reports/tools/workingset_guard.py`（四个文件） |

## 2. 改前的红（`--pre`）

```
✗ [判据 1] 标定正文只在 CalibrationService 里拼一次（两个字面量各 1 处）
✗ [判据 2] 正文内容不因重构变形（formatResult 的用例）
✓ [判据 3] 既有测试不退化
✓ [判据 4] 工作集守门
```

## 3. A 独立复核的要点

- `git diff` 显示两个调用点各删掉 **22 行**、`CalibrationService.cpp` 多出 `formatResult()`；
  被搬走的那段正文与原来**逐字节相同**（diff 里是删除 + 原样新增）。
- 失败分支也归并了：`formatResult(!ok)` → `标定失败：<error>`（原来两处各写各的）。
- 调用点的副作用没动：`MainWindow` 仍写侧栏 / tip / toast / 日志，`ToolsPanel` 仍写
  `m_calibResult`。
- 新增用例 `formatResultCarriesMatrixAndPerFrameErrors` 钉住组数、总平均误差、
  `4×4 矩阵`、矩阵首末元素（6 位小数）、`逐组误差`、`第 1 组`、误差数值、`识别失败`
  标注，以及失败分支的 `标定失败` + `r.error`。

## 4. 两条流程观察（都记下来，不藏）

1. **B 说自己跑过探针，但本轮它没有重建。** A 第一次跑验收时
   `calibration_service` 只有 6 项（r1 的 4 条用例 + init/cleanup），
   而 exe 的时间戳还是 r1 那一版 —— 也就是"代码改完了、二进制没跟上"。
   A 自己 `cmake --build` 之后才是 7 项全过。**这正是"不采信实现方自述"的价值**：
   如果只看 B 的交付说明，这一轮会被判成通过，而磁盘上的 exe 其实还是旧的。
   本轮不判失败（代码本身对、判据全绿），但记在这里。
2. **A 的 `checks.py` 两次把用例数下限算错**（T-006 写成 19 实际 18；
   T-008-r2 写成 9 实际 7）。规律：`QTest` 的 `Totals` = **用例数 + initTestCase + cleanupTestCase**。
   两次都是"判据没红、但数字不对"的形式暴露的 —— 说明探针里那条
   "用例数下限"确实在起作用（它防的是"用例被悄悄删掉"）。

## 5. T-008 还剩什么

r3（可选、低优先）：品牌色收敛（`rgba(22,119,255,…)` 散落 5-6 处 +
`VisSceneView.cpp:586` 的 `rgb(26,31,46)`）、`URRealtimeReader.{h,cpp}` 的 Tab 缩进。
两项都是纯外观/格式，没人抱怨过；排在 T-009~T-013 之后再做。
