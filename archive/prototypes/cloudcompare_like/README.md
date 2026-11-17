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

## ROI 选区的口径（K4 / W5a / W5b / W6 / W9，2026-09-24）

**ROI 默认不做遮挡剔除**（`include_occluded=True`）。口径是 **"投影落在矩形
内的全部点"**，不判遮挡 —— CloudCompare 的矩形框选是 2D 屏幕空间选择，与被遮挡
与否无关，本原型按同一语义实现。

- 判据实现拆成两个**纯函数**（`app/cc_gl_viewer.py`）：
  - `roi_project_indices(mvp, points, rect, w, h)` —— 纯投影，不碰 GL；
  - `roi_apply_depth_filter(indices, screen, rect, depth_buf, h)` —— 深度分支，
    **可注入合成 `depth_buf` 直测**。
- 只有显式调用 `set_include_occluded(False)` 才会读深度缓冲做遮挡过滤。
- **`glReadPixels` / `_read_depth_rect()` 不作为 CI 判据**：offscreen 下
  `fbo=0`，深度缓冲读不到（这一点已由测试钉住）。
- **W9：ROI 失败/降级不得静默。** 选区算不出时必须给出原因，经
  `viewer.roi_selection_error()` → 工作区 `_log(warning)` → 属性面板告警色
  三处可见。覆盖 offscreen / 远程桌面 / 软件渲染等无 GL 场景。

边界归属：屏幕坐标用**闭区间** `>= left & <= right`。注意 Qt 的
`QRect.right()` = `x + w − 1`、`bottom()` = `y + h − 1`（闭区间语义），
写测试时不能按 `x + w` 反解边界点。

## 后处理参数的可见性（P0-B，2026-10-10）

`src/core/point_cloud_processor.py` 自 `885063e` 起把 `enable_outlier_removal`
默认设为 `True`（为修主程序拼接输出飞点）。本原型的契约是**"未启用任何算子 =
无操作"**（D1），故 `CloudCompareWorkflow` **显式关闭**该默认值，并在属性面板
「后处理参数」组里把真实生效值暴露出来（面板显示值 = `workflow.processor`
的值，单一真相源）—— 避免"界面上看不见的参数在悄悄改数据"。


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
- **合并口径**：多选合并 = 新增节点；源节点点序/属性不被改写，合并不入撤销历史

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

## 测试

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration
export QT_QPA_PLATFORM=offscreen          # 无显示器 / CI
unset PYTHONPATH
"D:/Program Files/Anaconda/envs/rvc/python.exe" -m unittest discover -s prototypes/cloudcompare_like/tests -t .
```

判据看**进程退出码**（`OK` + exit 0）。当前基线：**118 测试全绿**（2026-10-10 实测，含
Windows 中文控制台、未设 `PYTHONIOENCODING`）。

| 文件 | 覆盖 |
|------|------|
| `tests/test_cc.py` | core：载入/树/处理/历史/ICP/合并/标量场/LOD |
| `tests/test_ui_smoke.py` | K3：导出端到端 + 法线 worker + 门禁 |
| `tests/test_cc_k4.py` | K4 core：裁切（AABB/球/OBB）、ROI 派生新节点、`kind="create"` 历史、W5a/W5b/W9 纯函数 |
| `tests/test_ui_k4.py` | K4 UI：裁切/ROI 接线、参数可见性（P0-B）、工具栏灰显、导出名清洗 |

真机截图验收脚本（S1~S9）：

```bash
"D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/cloudcompare_like/tools/capture_ui.py
```

