# 编码圆标定板生成器 UI（原型）

本目录存放编码圆标定板生成工具的 UI 原型，用于在线调整参数、实时预览并导出可打印的标定板。

## 文件结构

| 文件 | 说明 |
|------|------|
| `generator.py` | 编码圆生成核心逻辑（OpenCV + NumPy，不依赖 PyRVC） |
| `app.py` | PySide6 UI 实现 |
| `main.py` | 入口脚本 |

## 运行方式

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration/prototypes/coded_circle_ui
python main.py
```

## 功能

- **左侧参数面板**：调整扇区数 N、中心圆半径、r1/r2/r3/r4 比例、页面尺寸、DPI、边距、输出格式。
- **右侧实时预览**：参数变化后 200ms 自动刷新预览（渲染少量编码圆，加速显示）。
- **生成标定板**：点击「生成标定板」按钮输出完整页面，同时生成 `coded_circle_meta.json` 元数据。

## 与主项目的关系

- 编码逻辑与 RVC SDK 示例 `Examples/Python/Utils/GenerateCodedCircle.py` 保持一致。
- 参数默认值与 `src/core/marker_detector.py` 中 `MarkerDetector` 的默认编码圆参数兼容（N=8, r1=2.0, r2=3.0）。
- 测试稳定后，可将 `generator.py` 并入 `src/core/` 或 `src/ui_v2/tools/`，并将 `app.py` 集成到主窗口的菜单/工具栏中。
