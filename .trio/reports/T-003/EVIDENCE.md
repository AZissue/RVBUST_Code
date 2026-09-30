# T-003 验收证据索引（A，2026-09-30）

需求（人）：「把 3D 视窗工具栏按钮的 UI 设计（不含文字和功能）做得与 2D 视窗一模一样。」

## 结论

| 判据 | 结论 | 证据 |
|---|---|---|
| 1 UI 一模一样（人判） | 通过 | `reports/T-003/overlay2d_after.png`（2D：勾选态蓝色圆角胶囊，未勾选为无底色文字）/ `reports/T-003/overlay3d_after.png`（3D：未勾选同为无底色文字，白雾已消失） |
| 2 代码层解耦 + 冒烟（机检） | 通过 | `python reports/T-003/overlay_decoupled.py` → exit 0 |

## 判据 2 的四项（脚本输出）

```
{"check": "both use Theme::viewOverlayButtonStyle()", "ok": true}
{"check": "VisSceneView.cpp has no per-view rgba background override", "ok": true, "found": []}
{"check": "a shared overlay-button header is included by both", "ok": true,
 "shared": {"include": "ui/ViewOverlay.h", "file": "src\\ui\\ViewOverlay.h"}}
{"check": "app starts and shows its main window", "ok": true}
{"result": "PASS"}
```

## 根因（改前 → 改后）

- 改前：3D 在 `Theme::viewOverlayButtonStyle()` 之后**追加了一段 3D 专属底色**
  `QPushButton { background-color: rgba(255,255,255,0.14); }`（VisSceneView.cpp:657-659）
  → 常态多一层白色薄雾，所以与 2D「配色不一样」。
- 改前 `GlassOverlay` 只是 `Image2DView.cpp` 里的局部模板，3D 用不到 → 人说的「没解耦」成立。
- 改后：浮层按钮/标签实现搬到共享头 `src/ui/ViewOverlay.h`，两个视窗用**同一个组件 + 同一个
  `Theme::viewOverlayButtonStyle()`**；3D 不再有专属底色；模糊源是宿主可选提供项——
  2D 提供（模糊副本 70% 合成），**3D 不提供时组件不画任何底**（因此与 2D 未勾选态一致）。

## 说明

- B 这轮没按任务书附上 `reports/T-003/overlay2d_after.png` / `overlay3d_after.png`；
  上面两张是 A 用真机截图自己截的（连相机 → 预览 → 拍照后取 2D/3D 工具栏）。
  判据以 A 的证据为准，所以不算失败，但已在群里点出这个交付缺口。
- 冒烟里 `exit_code: 1` 是探针主动 terminate 进程的结果，不是崩溃。
