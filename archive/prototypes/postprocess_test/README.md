# 点云后处理测试工具（ui_v2 工作区重构版）

> 位置：`D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\postprocess_test`  
> 目标：验证点云后处理子功能，UI 与接口对齐 `src/ui_v2/workspaces/`，后期可直接并入主程序。

---

## 功能

- **CloudCompare 式布局**：左侧 DB 树（文件节点 + 点云子节点）/ 中间 3D 预览 / 右侧后处理面板。
- **DB 树管理**：加载多路点云，支持分支、勾选显隐、删除、属性编辑。
- **显示预算**：全局 GPU 点数上限，自动均匀降采样显示（原始点云保留）。
- **3D 交互**：左键旋转 / 右键平移 / 滚轮缩放 / 中键点击设旋转中心（高亮圆点标识）。
- **视觉元素**：选中点云包围盒、比例尺、深色背景（坐标轴/网格已精简）。
- **属性面板**：名称、点数、可见性、点大小、颜色、包围盒尺寸、中心点。
- **后处理**：体素下采样、统计离群点去除、AABB/球/OBB 裁切、自动参数估计。
- **ICP 点云配准**：点到点 / 点到面，源点云自动对齐到目标点云。
- **ROI 框选**：矩形框选保留/剔除，精确索引映射（显示下采样不丢精度）。
- **点云合并**：安全属性对齐（颜色/法线），避免 open3d `+=` 属性丢失。
- **撤销 / 重做**：处理历史回退。
- **导出**：PLY / PCD 格式。

---

## 目录结构

```
postprocess_test/
├── core/
│   ├── __init__.py
│   └── postprocess_workflow.py   # 后处理工作流（无 UI 依赖）
├── app/
│   ├── __init__.py
│   ├── postprocess_workspace.py  # 基于 ui_v2 的工作区（可迁往 src/ui_v2/workspaces/）
│   └── simple_ui.py              # 独立运行入口
├── tests/
│   ├── __init__.py
│   └── test_postprocess_workflow.py
└── README.md
```

---

## 运行

### 单元测试（无 UI）

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration
"D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/postprocess_test/tests/test_postprocess_workflow.py
```

### 独立 UI（需 PySide6 + open3d）

```bash
cd D:/RVC_SRC/Python/MultiCameraCalibration
"D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/postprocess_test/app/simple_ui.py
```

---

## 与主项目的关系

- **core 算法**：`core/postprocess_workflow.py` 继承自 `src/core/workflow_base.py` 的设计模式，
  复用 `src/core/point_cloud_processor.py` 与 `src/core/pcd_utils.py`。
- **UI 工作区**：`app/postprocess_workspace.py` 完全按 `src/ui_v2/workspaces/mobile_chain_workspace.py`
  的信号/状态机/布局风格设计。
- **并入路径**：
  1. `core/postprocess_workflow.py` → `src/core/postprocess_workflow.py`
  2. `app/postprocess_workspace.py` → `src/ui_v2/workspaces/postprocess_workspace.py`
  3. `MainWindowShell` 增加后处理工作区注册
  4. `BackendBridge` 增加 `_wire_postprocess_workspace()`

---

## 验证清单

- [x] 单元测试：加载/删除/下采样/裁切/撤销重做/ICP/合并/导出/自动参数
- [x] ROI 索引映射测试：恒等映射/下采样精确映射/mask 生成/多朵点云预算分配
- [x] UI 实例化：offscreen 模式可创建 PostprocessWorkspace
- [ ] 实机验证：加载真实 PLY 数据 > 1000 万点，验证显示预算与 ROI 性能
- [ ] 并入主程序：迁移到 `src/ui_v2/workspaces/` 并接入 `BackendBridge`
