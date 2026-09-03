# CloudCompare-Like 后处理原型 v2

> 位置：`prototypes/cloudcompare_like/`  
> 目标：不基于 `postprocess_test`，全新设计高性能点云后处理原型，深度参考 CloudCompare 功能，方便后期合入主 `src/`。

---

## 架构设计

```
cloudcompare_like/
├── core/                          # 纯算法层（无 PySide6 依赖）
│   ├── cc_workflow.py             # 工作流：DB树状态 + 处理管线
│   ├── cc_processor.py            # 后处理算法（继承并扩展 PointCloudProcessor）
│   ├── cc_geometry.py             # RANSAC 几何拟合（平面/球/圆柱）
│   ├── cc_scalar_field.py         # 标量场计算（高度/密度/曲率/强度）
│   └── cc_octree_lod.py           # LOD 八叉树（高性能渲染核心）
├── app/                           # UI 层（PySide6）
│   ├── cc_gl_viewer.py            # 高性能 OpenGL 查看器（LOD + Frustum Culling）
│   ├── cc_db_tree.py              # CloudCompare 式 DB 树
│   ├── cc_properties.py           # 属性面板（标量场/颜色/法线/测量）
│   ├── cc_toolbar.py              # 工具栏（选择工具/着色/视角）
│   ├── cc_workspace.py            # 主工作区（CloudCompare 三栏布局）
│   └── main.py                    # 独立运行入口
└── tests/
    └── test_cc.py                 # 单元测试（无 UI）
```

## 与主 src 的对齐

| 主 src | 本原型 | 合并路径 |
|--------|--------|---------|
| `core/workflow_base.py` | `core/cc_workflow.py` | 提取 `CloudCompareWorkflow` 作为新工作流 |
| `core/point_cloud_processor.py` | `core/cc_processor.py` | 扩展 `PointCloudProcessor` |
| `ui_v2/widgets/viewer_panel.py` | `app/cc_gl_viewer.py` | 替换或并行提供 `ViewerPanelLOD` |
| `ui_v2/theme.py` | 直接复用 | 不变 |

## 核心特性

### 1. 高性能渲染（LOD Octree）
- 每朵点云构建 8 层八叉树 LOD
- 视距自适应：近处高密度、远处低密度
- Frustum Culling：只渲染视锥内体素
- 目标：单路 5000 万点流畅交互

### 2. CloudCompare 式功能
- **DB 树**：文件 → 点云 → 标量场/法线/网格 多级节点
- **标量场**：高度/Z/密度/曲率/强度 + Colorbar
- **选择工具**：矩形/多边形套索/Brush/分段
- **几何工具**：RANSAC 平面/球/圆柱拟合 + 距离测量
- **后处理**：法线估计、网格化（Poisson/Ball Pivoting）、欧式聚类

### 3. 快捷键

| 快捷键 | 功能 |
|--------|------|
| Ctrl+O | 打开点云 |
| Ctrl+S | 导出 |
| Ctrl+Z/Y | 撤销/重做 |
| Delete | 删除选中 |
| Space | 切换显隐 |
| 1/2/3/4 | 顶/前/侧/等轴视角 |
| F | 适配视角到选中 |
| Esc | 取消选择/ROI |

## 运行

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration
"D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/cloudcompare_like/app/main.py
```
