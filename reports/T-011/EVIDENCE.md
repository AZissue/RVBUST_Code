# T-011 验收证据（A）— 预览 worker 与 CameraManager 的生命周期

日期：2026-09-30　　结论：**通过**

## 1. 判据（`python .trio/verify.py T-011 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | worker 与 CameraManager 的生命周期被绑住 | ✓ | `reports/T-011/preview_lifetime.py` → `PASS` |
| 2 | 真机：连相机→预览→关窗口 ×5 不崩 | ✓ | `reports/T-011/exit_cycles.py 5` → `PASS`（5/5 退出码 0，无新 `[CRASH]`） |
| 3 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2` |
| 4 | 工作集守门 | ✓ | `reports/tools/workingset_guard.py` |

## 2. 改前的红（`--pre`）

```
✗ [判据 1] 预览 worker 的生命周期被绑住
✓ [判据 2] 真机 ×5 不崩
✓ [判据 3] 既有测试不退化
✓ [判据 4] 工作集守门
```

## 3. B 选的修法与 A 的复核

B 选的是**方案 B**（析构显式等待），只动 `CameraManager.{h,cpp}`（+28 / −2 行）：

- `onPreviewTick()` 把线程池返回的 future 存进成员 `m_previewFuture`
  （原来 `QtConcurrent::run(...)` 的返回值被丢掉，析构根本无从等）；
- `~CameraManager()` 在 `m_impl.reset()` **之前** `m_previewFuture.waitForFinished()`，
  并留了注释说明"已经越过 token 检查、正在用 `this`/`m_impl` 的那一轮"就是它要等的东西；
- 队列里还没开跑的 worker 仍由 token 兜住（原来那条路没变）。

A 复核：预览仍在 `QtConcurrent::run` 里跑（判据 1 顺带确认了这条），
没有为了好过判据把它挪回 UI 线程；`shutdown()` 的幂等语义没动（`camera_manager_release` 用例仍过）。

## 4. 这条判据的诚实说明

**UAF 的窗口太窄，跑不出稳定复现**（A 先用"连相机→预览→关窗口"跑了多轮，一次都没崩）。
所以判据 1 是**结构性**的：它钉的是"机制"——worker 不许捕获裸 `this`，**或**析构必须显式等待。
判据 2 是它的真机配对证据：证明这一改动没有把退出路径弄坏（5/5 干净退出）。

换句话说：这条验收证明的是"那个窗口按机制被关掉了 + 退出路径是好的"，
而不是"我亲眼看见它崩过、现在不崩了"。这一点写在这里，免得以后有人把结论读得过强。
