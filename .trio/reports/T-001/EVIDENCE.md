# T-001 验收证据索引（A）

> 说明：`roles/CONTRACT.md` 把证据写成 `reports/<任务号>/`（仓根），而框架自带的
> `.trio/tests/test_gitignore.py` 要求 `.trio/reports/` 下有 .py/.png/.md 证据文件。
> 两处**不一致**，这条已在群里报给人。在框架统一之前，两边都放：脚本与原始输出在
> 仓根 `reports/`，本文件加关键结论索引放在这里。

## 结论（2026-09-29，真机，RVC-I2120 / SN I1GM112B652 已插上）

| 判据 | 结论 | 证据 |
|---|---|---|
| 1 工具列表逐项选中不崩 | 通过 | `reports/T-003/repro_crash.py`，6 页全 alive |
| 2 工具页顶部横条不再压标题 | 通过 | `reports/T-003/02_after_欧氏距离.png` |
| 3 浮层无边框/无底色/背景模糊 | **2D 通过；3D 只做到"无边框无底色"，模糊未达成**（见下） | 2D：`reports/T-001/zoom_live_title2.png`（文字底下噪点被抹平，框外仍是椒盐噪点） |
| 4 既有 ctest 不减少 | 通过 | `ctest`：100% tests passed out of 2 |
| 5 工作集不越界 | 通过 | `reports/T-003/workingset_guard.py` exit 0 |
| 6 连相机后预览/拍照不崩 | 通过 | `reports/T-002/repro_camera_crash.log`（预览存活 12s、拍照存活 12s） |

## 本轮修掉的两个崩溃（都是回归，A 二分定位过）

1. 选中「像素→3D」→ `0xC00000FD` 栈溢出：`ToolsPanel::buildPixelTo3DPage()` 把同一个 page
   套了两次 `wrapScrollable()`，第二个把 page 抢走进栈，第一个成了永不进栈的孤儿滚动区
   （它同时就是需求 2 那条"压在标题上的横条"，也是离线冻结判据恒假的根因）。
2. 连相机后点「预览」→ `0xC0000005`：相机出帧后 `render()` →
   `GlassOverlay::paintEvent` → `overlayBlurUnder()` 第一次真正执行就访问违例。
   对照：把 B 的改动 stash 掉重编译同一份探针 → 预览/拍照各存活 12 秒
   （见 `reports/T-002/CAMERA_BISECT.md`）。

## 3D 侧"背景模糊"未达成（A 独立核实，2026-09-29）

3D 浮层按钮/提示是**原生子窗口**（`WA_NativeWindow` + `WA_TranslucentBackground`），
盖在 OSG 的 GL 子窗口上；Qt 侧 `grab()` 抓不到 GL 画面，所以只能用 Windows 合成。
B 走的是 `SetWindowCompositionAttribute` + `ACCENT_ENABLE_BLURBEHIND`，但对这四个
**子窗口**它返回 FALSE。A 独立核实（不是采信 B 的自述）：同机 runtime 日志
`build/src/Release/logs/runtime_20260929.log` 里每次启动都有四条

```
3D: DWM blur-behind not applied to overlay "vis_deviation_toggle"
3D: DWM blur-behind not applied to overlay "vis_pick_hint"
3D: DWM blur-behind not applied to overlay ""        （复位 / 叠加历史）
```

所以 3D 侧现在**只是"无边框、无底色"的透明浮层**，没有模糊。要真做到，得换机制
（把浮层画进 OSG 场景当 HUD，或把浮层做成顶层窗口再手动跟随位置——后者会动到
`VisSceneView` 的原生窗口契约，且在 z 序/焦点上有新风险）。
**这是留给人的取舍，A 不当场替人决定**；判据 3 的 3D 部分因此记为未达成。
