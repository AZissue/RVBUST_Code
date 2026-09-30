# T-001 r2：§2 / §2b 两条 0xC0000005 的根因（B，2026-09-29）

## 结论

两条崩溃**同一处代码**：`src/ui/Image2DView.cpp::overlayBlurUnder()`（r1 新增）里的

```cpp
const QRect want(w->mapTo(m_imageLabel, QPoint(0, 0)), w->size());
```

`m_imageLabel` 不是那几个浮层控件的祖先（标题/缩放标签是 `this` 的子控件，
工具条按钮在 `bar` 里），它只是它们的**兄弟**。而 Qt 5.14 的
`QWidget::mapTo()` 在 parent 不在祖先链上时会解引用空指针。

## 依据一：Qt 5.14 源码（本机 `D:/Program Files/Qt/5.14.2/Src/qtbase/src/widgets/kernel/qwidget.cpp`）

```cpp
QPoint QWidget::mapTo(const QWidget * parent, const QPoint & pos) const
{
    QPoint p = pos;
    if (parent) {
        const QWidget * w = this;
        while (w != parent) {                    // ← 循环条件里没有 w
            Q_ASSERT_X(w, "QWidget::mapTo(const QWidget *parent, const QPoint &pos)",
                       "parent must be in parent hierarchy");
            p = w->mapToParent(p);
            w = w->parentWidget();
        }
    }
    return p;
}
```

父不在祖先链上 → 循环越过顶层控件 → `w == nullptr` → 下一轮仍满足
`w != parent` → 在空指针上调用 `mapToParent()` → `pos + data->crect.topLeft()`
解引用 `data`。Release（NDEBUG）下 `Q_ASSERT_X` 被编掉，所以不是断言失败、
而是访问违例：**0xC0000005，故障指令在 Qt5Widgets.dll**——与 A 的日志
`[CRASH] SEH 0xC0000005 ... module=Qt5Widgets.dll` 对上。

## 依据二：为什么只在"第一次真正取模糊源"时炸

`overlayBlurUnder()` 第一行就是 `if (... || m_cachedVisible.isNull()) return {};`。
开机、连相机之前 2D 视窗没有画面（`m_cachedVisible` 为空），这段代码一次都没跑过。
两条崩溃都发生在它第一次跑起来时：

- §2 `probe_glass.py`：填「数据文件夹」→ 离线冻结第一次生效 → `render()` 首次有图 →
  浮层首次绘制 → 炸（`reports/T-001/probe_glass.log`）。
- §2b `repro_camera_crash.py`：点「预览」→ 首帧到达 →
  `updateFrame()` → `render()` → `updateOverlayBackdrops()` → `GlassOverlay::paintEvent()`
  → `overlayBlurUnder()` → 炸。

`updateOverlayBackdrops()` 本身不是元凶：它在开机时（`resizeEvent()` → `render()`
的空图分支）就已经跑过一遍，`isVisible()`/`update()` 都正常。

## 依据三：同机的运行时日志（build/src/Release/logs/runtime_20260929.log）

```
[17:36:07.643] connect OK: I1GM112B652 (X1, 1542 ms)
[17:36:12.783] [CRASH] SEH 0xC0000005 at 0x00007FFA61771420 module=Qt5Widgets.dll
```
（17:36:12 即「预览已开启」，首帧到达后立刻崩。）

另外这次日志里还有四条：

```
3D: DWM blur-behind not applied to overlay ""
3D: DWM blur-behind not applied to overlay "vis_deviation_toggle"
3D: DWM blur-behind not applied to overlay "vis_pick_hint"
```

即 `SetWindowCompositionAttribute(ACCENT_ENABLE_BLURBEHIND)` 对本机这四个**子窗口**
全部返回 FALSE —— 3D 侧的 DWM 模糊这条路在这台机器上不通（见交回说明的"不确定点"）。
它不是崩溃原因（调用返回 FALSE，什么都没改）。

## 修法（本轮）

不用 `mapTo(m_imageLabel, ...)`：先映射到**合法祖先** `this`，再用 `m_imageLabel`
在 `this` 里的位置换算，并在调用前用 `isAncestor()` 自查祖先链（对不上就返回空图、
不调 Qt 的映射函数）。

## 复现/验证

- §2：`python reports/T-001/probe_glass.py`（A 跑）
- §2b：`python reports/T-002/repro_camera_crash.py`（A 跑）
