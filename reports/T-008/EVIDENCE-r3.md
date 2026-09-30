# T-008 r3 验收证据（A）— 品牌色收敛 + Tab 缩进

日期：2026-09-30　　结论：**通过**（T-008 到此三段全绿）

## 1. 判据（`python .trio/verify.py T-008 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | 颜色收敛到 `Theme::withAlpha()`、Tab 清零 | ✓ | `reports/T-008/cleanup_probe.py` → `PASS` |
| 2 | 颜色值没变（alpha 逐点与 HEAD 字面量一致） | ✓ | 同上（三个调用文件的 alpha 集合逐一相等） |
| 3 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2` |
| 4 | 工作集守门 | ✓ | `reports/tools/workingset_guard.py` |

## 2. 改前的红（`--pre`）

```
✗ [判据 1] 颜色收敛到 Theme::withAlpha()、Tab 缩进清零
✓ [判据 2] 界面配色没变（当时还是像素比对）
✓ [判据 3] 既有测试不退化
✓ [判据 4] 工作集守门
```

## 3. A 独立复核的要点

- `Theme.h` 新增 `QString Theme::withAlpha(const char* color, double alpha)`；
  三个曾经手写品牌蓝的文件全改成 `Theme::withAlpha(Theme::PRIMARY, …)`；
  `VisSceneView.cpp` 不再写死 `rgb(26,31,46)`；`URRealtimeReader.{h,cpp}` 的 84 行 Tab 全部转空格
  （158 行改动 = 纯缩进重排）。
- **颜色没变**：探针把 HEAD 里每个 `rgba(22,119,255,A)` 的 alpha，和现在同一个文件里
  `Theme::withAlpha(<色>, A)` 的 alpha 逐一对照 —— 集合完全相等，也就是说
  "同一个颜色换了个写法"，不是重新配色。

## 4. 判据 2 中途换过仪器（记下来）

原本判据 2 是**屏幕像素比对**（`reports/T-008/visual_smoke.py`：采"工具列表当前选中项"的
平均 RGB，与改前基线比）。第一次验收时它报了 diff≈180/通道 —— 但那是**仪器在抖**：
基线那次采到的是暗区（36/51/46），改后那次采到的是浅色区（215/228/246），
说明那个矩形在某些窗口层级/重绘时机下采到的根本不是列表项。

**一个自己会抖的判据比没有判据更糟**（它会把好改动判成坏改动），所以换成
上面那条"alpha 逐点比"——纯粹比数值，不含像素、不含窗口状态。
`visual_smoke.py` 留在仓库里当诊断脚本，但**不再是判据**。

## 5. 遗留

- T-008 三段（r1 SDK 异常码/PLY list 属性、r2 标定正文去重、r3 颜色/Tab）全部验收通过。
- 工作树里仍有 **T-012 的暂停 WIP**（`MeasureTools.*` / `MeasurePage*` / `MeasurePages.cpp` /
  `MainWindow.cpp` / `ToolsPanel.h`），**故意没有提交**：它没通过验收，
  而 T-012 在等人从三个选项里挑（见 bus #88 的升级）。
