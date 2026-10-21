# industrial_pointcloud_postprocess — 工业风点云后处理原型

工业风格 UI 的轻量点云后处理工具，定位是 `prototypes/cloudcompare_like/` 的
"工业风 UI + 基础功能"轻量对照版：仅包含 **加载 / 多边形分割 / 多选合并 / 下采样 / 撤销 / 导出**，
算法与 UI 独立自包含（不 import cloudcompare_like 或其他原型的代码），渲染直接复用
`src/ui_common/industrial_scene/` 的 `CloudCanvas` / `GpuCloudCanvas`，界面视觉语言对齐
主程序新版 `src/ui_v2`（theme 设计 token + studioHeader/ribbon/侧栏卡片布局）。

## 功能

- **加载点云**：ply / pcd / xyz / pts（open3d 读取，后台线程），源单位可选 mm / m，内部统一 mm。
- **多图层管理**：图层树面板（对齐主程序 FrameBrowser 结构：顶部条 + 计数 + 删除按钮、
  项目根节点、两列、多选、右键菜单、底部摘要），勾选显隐；**删除移入会话级回收区，
  右键"恢复上次删除"按原索引还原（不进撤销栈）**。
- **多边形分割（CloudCompare segment 语义）**：左键加顶点、**Alt+左键撤销上一个顶点**、
  右键（或双击）封闭（≥3 点）、Esc 取消；封闭后先**暂存**（轮廓保留、横幅与 02 卡片显示
  框内/框外点数），在 02 卡片执行「保留框内 / 保留框外」或「放弃框选」。沿当前视线方向
  正交投影。**保留部分替换当前图层；舍去部分不删除，作为 `<原名> · 分割(框外/框内)` 分支
  图层追加到树**（source 注明"由 <原名> 多边形分割生成"），可照常显隐/导出/删除/合并；
  分割进撤销栈。保留部分为空则拒绝且不改动数据；舍去部分为空则不建分支。
- **多选合并**：DB 树 ExtendedSelection 选中 ≥2 层（选中根节点=全部）后 ribbon「合并图层」
  按树顺序 vstack 合并为 `合并点云 (N 层)`（置于原第一选中层位置，source 列来源层名），
  原图层移除；合并进撤销栈。
- **下采样**：体素下采样（体素尺寸 mm，体素内坐标与颜色取均值）与随机抽样（保留百分比，
  无放回），作用于选中图层，可撤销。
- **导出**：可见图层合并写出 PLY（open3d，mm，后台线程）。
- **撤销**：编辑前快照图层列表，上限 8 步，覆盖分割 / 合并 / 下采样 / 替换。
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
QT_QPA_PLATFORM=offscreen python prototypes/industrial_pointcloud_postprocess/tools/shot_selection_mode.py tmp_proto_shot_segment.png --segment
```

通过线：六条命令退出码均为 0；第 2、4 条打印 `[OK]` 标记（第 2 条覆盖分割暂存 /
segment in / segment out / 撤销回滚 / 分支回收 / 多选合并 / Alt 撤点 / 空保留拒绝断言）；
第 3 条生成非空截图（offscreen 下自动使用软件渲染，截图逻辑等待图层加载与画面稳定后再 grab）；
第 5 条截取框选绘制态（横幅不与画布 HUD 重叠）；第 6 条截取已封闭暂存态
（轮廓 + 横幅提示 + 02 卡片两个分割按钮可用、卡片不被摘要文字遮挡）。

## 已知边界

- 正交框选沿当前视线方向裁剪，**不做深度区分**（视线方向上的所有点一视同仁）。
- 显示抽稀（显示质量档位 / 软件预览 18,000 点上限）只影响预览，**不影响原始数据与导出**。
- GPU 不可用（offscreen、无 OpenGL 3.3 上下文）时自动降级为 18,000 点兼容软件预览，
  并在日志中明确提示，不冒称 GPU 渲染。
- 撤销以整层快照实现，上限 8 步，覆盖分割 / 合并 / 下采样 / 替换；加载与显隐切换不进撤销栈；
  **删除走回收区恢复机制，与撤销栈并存且互不污染**。回收图层常驻内存（原型级回收，不释放）。
- 框选暂存绑定"封闭时刻的当前图层与相机视角"：切换当前图层或任何改变图层数据/列表的
  操作都会使暂存失效并提示。
- 合成演示点云仅用于界面演示，不代表任何测量精度。
