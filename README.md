# RVC-3D-Metrix

RVC 三维测量软件的 PySide6 工作台。当前版本提供准备、采集、检测和报告四个流程界面，以及可旋转、缩放的法兰座演示模型。

详见 [ScanPort 调研与界面设计](docs/scanport-workbench.md)。

## 启动

在项目根目录使用本机已有的 Conda `rvc` 环境启动。

```powershell
conda run --no-capture-output -n rvc python main.py
```

如果 `rvc` 环境缺少 PySide6，可运行 `conda run -n rvc python -m pip install -r requirements.txt`。

程序启动后先显示工程中心。左侧「会话文件」用于查找和打开工程，左下角「设置」可查看并打开本地工程保存目录。新建测量工程会在 `projects/` 下保存工程名称和格式版本，并打开空白工作台。可以双击本地工程卡片重新进入，也可以通过「打开工程文件」选择其他位置的 `.rvcproj` 文件。首次启动会将内置法兰座演示工程放入 `projects/`，卡片会显示由演示模型生成的三维缩略图。工作台顶部的「工程中心」按钮可返回列表。

## 目录

| 路径 | 用途 |
| --- | --- |
| `src/core/` | 核心功能 |
| `src/ui/` | PySide6 界面 |
| `src/reconstruction/` | 三维重建 |
| `src/pointcloud/` | 点云处理 |
| `src/cad/` | CAD 模型及图纸对比 |
| `src/measurement/` | 尺寸测量 |
| `src/project/` | 项目管理代码 |
| `resources/` | 图标、图片和样式 |
| `configs/` | 配置文件 |
| `plugins/` | 插件模块 |
| `projects/` | 本地测量项目数据，默认由 Git 忽略 |
| `tests/` | 测试代码 |
| `docs/` | 开发文档 |
| `scripts/` | 辅助脚本 |

## UI 约定

新增图标统一定义在 `src/ui/icons.py`，按钮使用 `set_button_icon`。应用启动时，`src/ui/style.py` 统一去除按钮的系统虚线焦点框。新增按钮使用实色背景或实线边框表示选中和键盘焦点。
