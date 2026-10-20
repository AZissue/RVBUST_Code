# industrial_pointcloud_postprocess — 工业风点云后处理原型

工业风格 UI 的轻量点云后处理工具，定位是 `prototypes/cloudcompare_like/` 的
"工业风 UI + 基础功能"轻量对照版：仅包含 **加载 / 多边形框选裁剪 / 下采样 / 撤销 / 导出**，
算法与 UI 独立自包含（不 import cloudcompare_like 或其他原型的代码），渲染直接复用
`src/ui_common/industrial_scene/` 的 `CloudCanvas` / `GpuCloudCanvas`，界面视觉语言对齐
主程序新版 `src/ui_v2`（theme 设计 token + studioHeader/ribbon/侧栏卡片布局）。

## 功能

- **加载点云**：ply / pcd / xyz / pts（open3d 读取，后台线程），源单位可选 mm / m，内部统一 mm。
- **多图层管理**：图层树（名称 + 点数），勾选显隐，删除图层（可撤销）。
- **多边形框选裁剪**：框选模式下左键加顶点、双击或右键闭合（≥3 点）、Esc 取消；
  按"保留框内 / 移除框内"沿当前视线方向正交投影裁剪选中图层（CloudCompare segment 语义），可撤销。
- **下采样**：体素下采样（体素尺寸 mm，体素内坐标与颜色取均值）与随机抽样（保留百分比，
  无放回），作用于选中图层，可撤销。
- **导出**：可见图层合并写出 PLY（open3d，mm，后台线程）。
- **撤销**：编辑前快照图层列表，上限 8 步。
- **视图**：等轴测 / 顶视 / 正视 / 右视、适配全部、视区截图、显示质量档位、点大小、
  颜色模式（原始 / 高度 / 统一）、网格与坐标轴开关（画布内置能力，仅接参数）。

## 运行

```bash
# 交互界面（可带点云文件直接打开，假定 mm）
python prototypes/industrial_pointcloud_postprocess/run.py [cloud.ply ...]
python prototypes/industrial_pointcloud_postprocess/run.py --renderer software
```

## 验收判据（在仓库根目录执行，全部退出码 0 为通过）

```bash
python prototypes/industrial_pointcloud_postprocess/tests/test_processing.py
QT_QPA_PLATFORM=offscreen python prototypes/industrial_pointcloud_postprocess/tests/test_ui_smoke.py
QT_QPA_PLATFORM=offscreen python prototypes/industrial_pointcloud_postprocess/run.py --screenshot tmp_proto_shot.png
python prototypes/industrial_pointcloud_postprocess/run.py --self-test-io
QT_QPA_PLATFORM=offscreen python prototypes/industrial_pointcloud_postprocess/tools/shot_selection_mode.py tmp_proto_shot_selection.png
```

通过线：五条命令退出码均为 0；第 2、4 条打印 `[OK]` 标记；第 3 条生成非空截图
（offscreen 下自动使用软件渲染，截图逻辑等待图层加载与画面稳定后再 grab）；
第 5 条进入框选模式并截取激活态画面，用于回归验证框选提示横幅与画布 HUD 不重叠。

## 已知边界

- 正交框选沿当前视线方向裁剪，**不做深度区分**（视线方向上的所有点一视同仁）。
- 显示抽稀（显示质量档位 / 软件预览 18,000 点上限）只影响预览，**不影响原始数据与导出**。
- GPU 不可用（offscreen、无 OpenGL 3.3 上下文）时自动降级为 18,000 点兼容软件预览，
  并在日志中明确提示，不冒称 GPU 渲染。
- 撤销以整层快照实现，上限 8 步；加载 / 显隐切换不进撤销栈。
- 合成演示点云仅用于界面演示，不代表任何测量精度。
