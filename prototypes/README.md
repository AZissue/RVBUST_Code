# prototypes — 功能原型与单元测试

> 位置：`D:\RVC_SRC\Python\MultiCameraCalibration\prototypes`
> 更新：2026-10-10（补全 7 个原型索引 + 并入状态；此前只有 3 条且状态停留在批 1）

本目录用于存放各子功能的**独立原型**和**单元测试**。每个子功能一个子文件夹，内部自包含 `core/`（核心算法）、`app/`（可运行 UI/脚本）、`tests/`（单元测试），验证稳定后再合并到主项目 `src/` 中。

---

## 当前原型

| 子文件夹 | 功能 | 阶段 | 已并入主程序？ | 测试 |
|---|---|---|---|---|
| `cloudcompare_like/` | 点云后处理 v2（CloudCompare 式：DB 树 / 标量场 / 裁切 / ROI / ICP / 合并） | **进行中（K4 已交付，S6 性能实测待发令）** | 否（S7 待 @user 定时机） | 118 绿 |
| `robot_handeye_transform/` | 手眼矩阵 + 机器人位姿 → 点云转基座系（**只做变换，不做标定求解**） | core 已完成（批 6B）；**UI 未接线** | 否 | 11 个脚本全绿 |
| `turntable_360_stitch/` | 相机固定 + 转台旋转 → 角度标定 → 360° 点云拼接 | 已并入（主程序模式 C） | **是** | 1 脚本全绿 |
| `offline_stitch/` | 不连相机，本地图像+点云文件对 → 检测 → 拼接 → 导出 | 已并入（主程序模式 D） | **是** | ⚠️ 见下「已知问题」 |
| `postprocess_test/` | 点云后处理 v1（CloudCompare 式布局的初版） | **已冻结**，被 `cloudcompare_like` 取代 | 否 | 2 脚本全绿 |
| `coded_circle_ui/` | 编码圆标定板生成器 UI（参数化预览 + 导出 PDF/PNG） | 生成逻辑未并入 `src/`；主程序测试反向依赖本目录 | 否 | 无独立测试 |
| `sync_capture_stress/` | 多相机并发采集污染复现（双 X1 GigE 并发 `Capture()` 深度污染定位） | **待实机复现验证** | 不适用（诊断脚本） | 无 |

### 已知问题（2026-10-10 实测）

1. **`cloudcompare_like` 曾因主程序改动而 3 测试变红（已修）**：`885063e` 把
   `src/core/point_cloud_processor.py` 的 `enable_outlier_removal` 默认改成 `True`，
   与本原型「未启用任何算子 = 无操作」（D1）契约冲突。已在 `cc_workflow` 侧显式关闭，
   并把参数暴露到 UI 属性面板。详见该原型 `README.md` §后处理参数的可见性。
2. **`offline_stitch` 测试与主程序脱节（未修）**：`src/core/chain_stitcher.py:110`
   现在会传 `include_invalid=True` 给 `detect_3d`，而
   `prototypes/offline_stitch/tests/test_offline_stitch.py` 里的 `MockMarkerDetector.detect_3d()`
   未跟上该签名 → `TypeError`，exit=1。
3. **`coded_circle_ui` 是主程序测试的运行时依赖（架构倒挂）**：`test_marker_detector.py:27`
   用 `sys.path.insert` 把 `prototypes/coded_circle_ui` 加进路径再 `from generator import ...`。
   `generator.py` 至今**没有**并入 `src/`，即「原型不污染主程序」原则在实际依赖上已被打破。
4. **`turntable_360_stitch` 与 `src/` 有漂移（预期内）**：原型
   `core/turntable_calibrator.py`（408 行）与 `src/core/turntable_calibrator.py`（423 行）
   相差 73 行 —— 并入口径是 `src/` 版本，原型保留为**只读参照**，不要再迭代。

---

## 使用原则

1. **子功能隔离**：每个原型独立运行，不依赖其他原型。
2. **先测试后合并**：`tests/` 中通过测试后，再把 `core/` 中的稳定算法迁入 `src/core/`。
3. **不修改主项目 `src/`**：原型阶段不改动 `src/` 下主程序代码（唯一例外见
   `robot_handeye_transform/BASELINE.md` 记录的 K2 三行注释，已经 @user 批准）。
4. **可复用主项目模块**：原型可以通过相对路径引入 `src/core/`、`src/ui_v2/` 等已有模块。
5. **验证形态 = 交付形态**：原型独立运行时的界面/接口要按并入后的形态写
   （工作区 = `QWidget` + `set_devices`/`set_state`/`set_background_runner` 契约），
   使并入退化为「加一张模式卡片 + 一个薄壳」，而不是 UI 重写。

---

## 环境与运行约定

| 项 | 值 |
|---|---|
| Python | `D:\Program Files\Anaconda\envs\rvc\python.exe`（conda `rvc`，3.10.20） |
| 无显示器 / CI | `QT_QPA_PLATFORM=offscreen` |
| **Windows 中文控制台注意** | `robot_handeye_transform` 的测试脚本会打印 `ᵀ` 等字符，GBK 控制台抛 `UnicodeEncodeError` 导致**假失败**（2026-10-10 实测 `test_handeye_result.py` 无该变量时 exit=1）。跑该原型前设 `PYTHONIOENCODING=utf-8`；`cloudcompare_like` 实测不需要（无该变量 exit=0） |
| `PYTHONPATH` | 先 `unset`，让原型自己按"向上找仓库根"定位 `src/` |
| 测试框架 | 本工程基线**不用 pytest**，统一 `unittest` / 脚本直跑；**判据看进程退出码** |

`robot_handeye_transform` 的测试一律直跑脚本（`tests/test_*.py`），
判 pass/fail 看退出码；其 DLL oracle 默认必需，缺失时报 `[ORACLE SKIPPED]` 且 exit≠0。

---

## 新增子功能流程

1. 在 `prototypes/` 下新建子文件夹，如 `my_feature/`。
2. 内部创建 `core/`、`app/`、`tests/`，并写 `README.md`（含运行命令与验收判据）。
3. 在 `tests/` 中写单元测试，无硬件时也能验证核心逻辑。
4. 在 `app/` 中写简单 UI 或命令行脚本，方便实机调试验证。
5. 在设计文档（`docs/`）里落**可机械核验的门禁**（命令 + 通过线），不要只写"已完成"。
6. 测试稳定后，把 `core/` 中算法迁入 `src/core/`，UI 逻辑合并入主 UI；**同时更新本表**。
