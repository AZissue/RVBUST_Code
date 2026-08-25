---
name: pointcloud-search-workflow
description: PointCloudSearch 项目工作流与约束（阶段 2 节点完善）
type: prompt
whenToUse: 在 D:/RVC_SRC/PointCloudSearch 项目下询问、开发、调试、新增节点或修改代码时调用
---

在 `D:/RVC_SRC/PointCloudSearch` 项目下工作时，优先遵守以下约定：

## 项目定位
模块化点云查找 / 分析桌面程序（节点式图形化流程编排）+ C++ SDK，面向 RVC 3D 相机客户。

## 技术栈
- C++20 + CMake + MSVC（VS2026）
- PCL 1.13.0（`D:/Program Files/PCL 1.13.0`）
- Qt 6.8.3 + VTK 9.4（GUI 与 3D 渲染）
- 当前阶段：**阶段 2「节点逐个完善」**，主线是 ROI BOX + 下采样 / 滤波 / 聚类 / 分割节点 E2E

## 常用命令
```bash
cd D:/RVC_SRC/PointCloudSearch
cmake -S . -B build && cmake --build build --config Release -j 8
cd build && ctest -C Release --output-on-failure
start.bat --smoke <ply>
start.bat --demo <ply> --autoquit N
```

## 不可破坏的红线
- 语言 C++20，不能降级
- 内部坐标单位恒为 **mm**，换算只在 IO 层
- 所有结果保留原始点索引（`Region.indices` / `source_indices`）
- 节点输入输出统一为 `ObjectList`
- 端口类型 `cloud` / `region` / `any`，类型不符禁止连线
- 界面默认中文 + Dark 主题（蓝白磨砂玻璃），布局不变
- 异步执行引擎不可破坏（千万级点云不卡 UI）
- 提交前 `ctest` 全绿 + 应用冒烟通过

## 新增节点流程
1. 在 `modules/pipeline/src/nodes/core_nodes.cpp` 的 `registerCoreNodes()` 中注册
2. 节点实现优先复用 `modules/filters/`、`modules/segmentation/`、`modules/clustering/` 已有算法
3. 输入输出统一 `ObjectList`；输出 region 时务必填充 `source_indices`
4. 为该节点补 E2E 单测（走 Graph 全链路）
5. 手动验证：点云加载 → 该节点 → 保存 / 3D 显示

## 下采样 / 后处理节点清单（阶段 2 当前重点）
- 体素下采样（voxel_downsample）
- 随机下采样（random_downsample）
- Z 范围过滤（z_filter）
- 移除无效点（remove_invalid）
- ROI Crop（消费 region 端口）

## 提交与推送
- 提交信息遵循 Conventional Commits（`feat:` / `fix:` / `docs:` / `test:`）
- **本地提交照常**（便于回溯）
- `git push` 只在用户明确说“推送”时执行

## 参考资源
- 项目级 AGENTS.md：`D:/RVC_SRC/PointCloudSearch/AGENTS.md`
- 项目级 PROJECT.md / PLAN.md / STATUS.md：项目根目录
- 参考仓库（搬运成熟实现）：`third_party/ref/RVBUST_Code-rvc-vision-studio/`
- 记忆库：先检索 `~/.codex/knowledge/pointcloudsearch-*`

如果文档与代码矛盾，停下向用户说明，以代码为准并同步修正文档。
