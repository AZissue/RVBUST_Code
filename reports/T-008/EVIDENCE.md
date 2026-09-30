# T-008 r1 验收证据（A）— 两处"会说错话"的地方

日期：2026-09-30　　结论：**通过**（T-008 还有 r2：标定结果格式化去重 / 品牌色 / Tab 缩进）

## 1. 判据（`python .trio/verify.py T-008 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | PLY 顶点元素上的 list 属性不再静默错值 | ✓ | `qt_class_probe pixel_to_3d 19` → `PASS` |
| 2 | SDK 内部异常不再被说成「参数无效」 | ✓ | `qt_class_probe calibration_service 6` → `PASS` |
| 3 | 桥接层真的用了独立的 `kSdkInternalError` | ✓ | `reports/T-008/bridge_sentinel.py` → `PASS` |
| 4 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2` |
| 5 | 工作集守门 | ✓ | `reports/tools/workingset_guard.py`（四个文件） |

## 2. 改前的红（`--pre`）

```
✗ [判据 1] PLY 顶点元素上的 list 属性不再静默错值
✗ [判据 2] SDK 内部异常不再被说成「参数无效」（文案层）
✗ [判据 3] 桥接层真的用了独立的 kSdkInternalError
✓ [判据 4] 既有测试不退化
✓ [判据 5] 工作集守门
```

判据 1/2 的红是**编译级**的：A 的验收测试引用还不存在的
`HandEyeSDKBridge::kSdkInternalError`（与 T-005 同一手法：验收测试定义接口）。

## 3. A 独立复核的要点

- `kSdkInternalError = -1000`（`HandEyeSDKBridge.h`）。SDK 自己的码是 0 与 -1…-7
  （见 `CalibrationService::errorText`），-1000 落在外面，不会撞车。
- `errorText(-1000)` 给出「SDK 内部异常（标定接口调用崩溃，输入参数未必有问题），
  请附带日志联系技术支持」——**不含**「参数无效」，且把排查方向指向 SDK 而不是用户的输入。
  既有各码（0、-1…-7、默认分支）文案逐字未变（判据 2 的测试同时钉住了 `-1` 仍是「参数无效」）。
- `bridge_sentinel.py` 按花括号配平切出 `handEyeCalibrationMarker` 与
  `handEyeCalibrationTcpTouch` 的函数体，要求各自出现该常量 —— 即
  "抓到了异常就返回它"，而不是原来的"保持预置的 -1"。
- PLY：`p.size == 0` 的顶点属性不再被静默丢弃（list 属性现在会被拒）；
  既有 16 条 PLY 用例（含 ascii / binary / face-first / 好文件）全过 → 没有把好文件误杀。

## 4. 残留 / 去向

- T-008 r2（下一轮）：标定结果格式化去重（`MainWindow.cpp:1077` / `ToolsPanel.cpp:860`）、
  品牌色收敛（`rgba(22,119,255,…)` 散落 5-6 处 + `VisSceneView.cpp:586` 的 `rgb(26,31,46)`）、
  `URRealtimeReader.{h,cpp}` 的 Tab 缩进。
- 框架侧（不属本仓代码）：`.trio/verify.py` 的"既有测试基线"通道写死
  `python -m unittest discover`，本仓是 ctest，所以每个任务都带 `--no-baseline`，
  真正管"测试别退化"的是各任务判据里的 `ctest`。修法要给骨架仓加一个
  config 驱动的 `test_cmd`，见 `reports/T-008/FRAMEWORK-NOTE.md`。
