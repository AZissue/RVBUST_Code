# PointCloudSearch UI 小优化建议文档

> 目标：在不改动整体布局、不切换主题风格（保持蓝白磨砂玻璃 Dark 主题）的前提下，做最小改动，让界面更现代、更一致。
> 当前版本基线：`dc5e522`（`pointcloud-search` 分支）。

---

## 1. 顶部标题栏去白框（Windows 深色标题栏）

**问题**：窗口仍使用原生 Windows 标题栏，Dark 主题下顶部仍是白色，和深色主体割裂；之前也反馈过关窗按钮异常。

**方案**：调用 Windows DWM 沉浸式深色标题栏，保持原生按钮和拖拽，改动最小。

**修改文件**：
- `app/CMakeLists.txt`
- `app/src/main_window.cpp`
- `app/src/main_window.h`（可选，如放在 `showEvent`）

**建议代码**：

在 `app/CMakeLists.txt` 的 `if(WIN32)` 块里加一行：

```cmake
if(WIN32)
    target_link_libraries(pcsearch_app PRIVATE dwmapi)   # <-- 新增
    ...
endif()
```

在 `main_window.cpp` 顶部新增平台相关头：

```cpp
#ifdef Q_OS_WIN
#include <windows.h>
#include <dwmapi.h>
#ifndef DWMWA_USE_IMMERSIVE_DARK_MODE
#define DWMWA_USE_IMMERSIVE_DARK_MODE 20
#endif
#endif
```

在 `MainWindow` 构造函数末尾（`rebuildPalette()` 之后）调用：

```cpp
#ifdef Q_OS_WIN
    // 强制标题栏进入深色模式，和深色主题一致
    if (HWND hwnd = reinterpret_cast<HWND>(winId())) {
        BOOL dark = TRUE;
        DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                              &dark, sizeof(dark));
    }
#endif
```

> 注：`winId()` 会强制创建窗口句柄，此处调用安全。若希望只在首次显示时执行，可重载 `showEvent()` 并加一次性标志位。

---

## 2. 节点颜色跟随主题（画布节点夜间不再发白）

**问题**：`NodeItem::paint` 里节点背景、边框、文字都是硬编码色值，深色主题下节点仍是白底黑字，和整体 Dark 风格冲突。

**修改文件**：`app/src/node_flow_widget.cpp`

**建议代码**：把 `NodeItem::paint` 中硬编码颜色改为从调色板读取：

```cpp
void paint(QPainter* painter, const QStyleOptionGraphicsItem*, QWidget*) override {
    const QRectF body = bodyRect();
    const bool selected = isSelected();
    const QPalette& pal = widget_->palette();

    const QColor fill = selected ? pal.color(QPalette::Highlight)
                                 : pal.color(QPalette::Base);
    const QColor stroke = selected ? pal.color(QPalette::Highlight).darker(120)
                                   : pal.color(QPalette::Mid);
    painter->setBrush(fill);
    painter->setPen(QPen(stroke, 1.5));
    painter->drawRoundedRect(body, 6, 6);

    painter->setPen(selected ? pal.color(QPalette::HighlightedText)
                             : pal.color(QPalette::Text));
    painter->drawText(body.adjusted(2, 0, -2, 0), Qt::AlignCenter,
                      widget_->displayTitle(node_));
    // ... 端口绘制保持不变
}
```

**验证**：切换 Light/Dark 主题后，节点背景、文字应自动反转。

---

## 3. 画布网格/边线颜色跟随主题

**问题**：`drawBackground` 中网格线用固定色值；边线 `rebuildEdges` 也是固定蓝色，主题切换后可能不协调。

**修改文件**：`app/src/node_flow_widget.cpp`

**建议代码**：

`drawBackground`：

```cpp
const QPalette& pal = palette();
const bool dark = pal.color(QPalette::Window).lightness() < 128;
const QColor text = pal.color(QPalette::Text);
const int alpha = dark ? 30 : 25;
const QColor line(text.red(), text.green(), text.blue(), alpha);
```

`rebuildEdges`：

```cpp
const QColor hl = palette().color(QPalette::Highlight);
const QColor edge(hl.red(), hl.green(), hl.blue(), 190);
e.item->setPen(QPen(edge, 2));
```

---

## 4. 左侧工具栏增加「全部展开 / 折叠」按钮

**问题**：分类已经支持手动折叠，但当分类很多时没有一键收起/展开，找节点效率低。

**修改文件**：`app/src/toolbox_widget.cpp`、`app/src/toolbox_widget.h`

**建议代码**：

在 `toolbox_widget.h` 增加两个槽：

```cpp
private slots:
    void expandAll();
    void collapseAll();
```

在构造函数里，搜索框下方加一行工具按钮：

```cpp
auto* btn_bar = new QHBoxLayout();
btn_bar->setSpacing(4);
auto* expand_btn = new QToolButton(this);
expand_btn->setText(tr("+"));
expand_btn->setToolTip(tr("Expand All"));
auto* collapse_btn = new QToolButton(this);
collapse_btn->setText(tr("−"));
collapse_btn->setToolTip(tr("Collapse All"));
btn_bar->addWidget(expand_btn);
btn_bar->addWidget(collapse_btn);
btn_bar->addStretch();
layout->addLayout(btn_bar);
layout->addWidget(tree_, 1);

connect(expand_btn, &QToolButton::clicked, this, &ToolboxWidget::expandAll);
connect(collapse_btn, &QToolButton::clicked, this, &ToolboxWidget::collapseAll);
```

实现：

```cpp
void ToolboxWidget::expandAll() { tree_->expandAll(); }
void ToolboxWidget::collapseAll() { tree_->collapseAll(); }
```

> 图标可后续换 `QIcon`，先用文字 + 提示，改动最小。

---

## 5. 文件浏览按钮样式统一

**问题**：`ParamsPanel` 里文件/目录参数使用 `QToolButton` + 文字 "..." + `setAutoRaise(true)`，在不同风格下可能不明显。

**修改文件**：`app/src/params_panel.cpp`、`app/src/themes.cpp`

**建议代码**：

在 `File` / `Directory` 分支里给按钮命名：

```cpp
browse->setObjectName(QStringLiteral("browseButton"));
```

在 `themes.cpp` 的 `kDarkStyle` / `kLightStyle` 里都加上：

```qss
QToolButton#browseButton {
    background: #2563EB;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 2px 8px;
    font-weight: 600;
}
QToolButton#browseButton:hover { background: #1D4ED8; }
QToolButton#browseButton:pressed { background: #1E40AF; }
```

---

## 6. 运行按钮 accent 样式 + 3D 工具栏留白

**问题**：3D 视窗顶部工具栏按钮和主题按钮样式一致，`Run` 不够突出；工具栏紧贴边缘显得拥挤。

**修改文件**：`app/src/main_window.cpp`、`app/src/themes.cpp`

**建议代码**：

`main_window.cpp` 构造里给运行按钮命名：

```cpp
run_button_->setObjectName(QStringLiteral("runButton"));
```

加一点点工具栏边距：

```cpp
toolbar->setSpacing(8);
toolbar->setContentsMargins(4, 2, 4, 2);
```

`themes.cpp` 增加：

```qss
QPushButton#runButton {
    background: #2563EB;
    color: white;
    border-color: #2563EB;
    font-weight: 600;
}
QPushButton#runButton:hover { background: #1D4ED8; }
QPushButton#runButton:pressed { background: #1E40AF; }
```

---

## 7. 面板阴影降级/主题化（减少视觉脏边）

**问题**：`applyPanelShadow` 使用硬编码蓝色阴影（`#1E3A5F` alpha 46），在某些背景下会形成明显蓝边；且 `QGraphicsDropShadowEffect` 对大量面板有轻微性能开销。

**修改文件**：`app/src/main_window.cpp`

**建议代码**：使用 palette 的 Shadow 色并降低模糊半径：

```cpp
void applyPanelShadow(QWidget* w) {
    auto* effect = new QGraphicsDropShadowEffect(w);
    effect->setBlurRadius(10);
    effect->setOffset(0, 2);
    const QColor c = w->palette().color(QPalette::Shadow);
    effect->setColor(QColor(c.red(), c.green(), c.blue(), 45));
    w->setGraphicsEffect(effect);
}
```

> 如果仍嫌阴影重，可直接移除 `applyPanelShadow` 调用，用 `QGroupBox` 边框和背景色区分层级，更干净。

---

## 8. 参数面板表单的行距与标签对齐

**问题**：`ParamsPanel` 默认 `QFormLayout` 行距较紧，长参数名和输入框贴得太近。

**修改文件**：`app/src/params_panel.cpp`

**建议代码**：在 `ParamsPanel` 构造函数里设置：

```cpp
form_->setVerticalSpacing(8);
form_->setHorizontalSpacing(10);
form_->setLabelAlignment(Qt::AlignRight | Qt::AlignVCenter);
form_->setFieldGrowthPolicy(QFormLayout::ExpandingFieldsGrow);
```

---

## 9. 主题切换后刷新所有自定义绘制区域

**问题**：`setThemeDark` 只更新了 `flow_->viewport()->update()`，节点、参数面板、工具栏等若缓存了颜色可能不立刻刷新。

**修改文件**：`app/src/main_window.cpp`

**建议代码**：

```cpp
void MainWindow::setThemeDark(bool dark) {
    auto* app = static_cast<QApplication*>(QApplication::instance());
    applyTheme(*app, dark);
    flow_->viewport()->update();
    params_panel_->update();
    toolbox_->update();
    update();
}
```

---

## 最小改动实施顺序建议

1. **先做 1（深色标题栏）+ 9（刷新）**：立竿见影解决顶部白框。
2. **再做 2 + 3（画布主题化）**：Dark 主题下画布不再突兀。
3. **最后做 4 / 5 / 6 / 7 / 8**：细节打磨，互不依赖。

每步完成后用 `start.bat` 或 `start.bat --demo <ply> --autoquit 5` 做冒烟；回归 `ctest -C Release`。

---

## 红线核对

- 不改动布局：左组件 / 画布 / 3D / 右参数 + 属性 / 底日志保持不变。
- 不切换主题：保持蓝白磨砂玻璃 Dark 主基调。
- 不引入新依赖：仅 `dwmapi` 为 Windows 系统库。
