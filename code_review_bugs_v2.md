# MultiCameraCalibration 代码审查 v2 — 新增功能相关问题报告

> 审查日期: 2026-07-23
> 审查范围: 新增标定板检测以及位姿法标定相关全部代码
> 版本对比: v1 报告中的 Bug 1~5 已修复（inlier_count 一致性、Tab 切换同步、拍摄计数、uint16 精度、pose_graph 异常捕获）

---

## 新增功能概述

本次新增的功能：
1. **`CalibBoardDetector`**（`calib_board_detector.py`）— 非对称圆标定板 2D 检测 + 3D 圆心提取 + 位姿求解
2. **`MarkerDetector` 扩展** — 支持 `MARKER_TYPE_CODED_CIRCLE` / `MARKER_TYPE_ASYMMETRIC_GRID` 两种模式切换
3. **`CalibrationEngine.calibrate_pair_by_board_pose`** — 通过标定板位姿求 cam→ref 外参
4. **`FrameData` 扩展** — 新增 `board_pose` / `board_pattern` / `board_pattern_name` 字段
5. **`OfflineSession` 扩展** — 批量检测时同步保存标定板位姿
6. **`main_window.py` / `calibration_panel.py` / `camera_card.py` UI 适配**

---

## Bug 1（严重）: `calib_board_detector.py` — 物点坐标排列顺序与 OpenCV 不匹配

### 位置

`src/core/calib_board_detector.py` 第 329-347 行（`_build_object_points` 方法）

### 问题描述

`cv2.findCirclesGrid` 返回的图像圆心按 **行优先（row-major）** 排列：
```
(row0_col0, row0_col1, ..., row0_colN, row1_col0, ...)
```

但 `_build_object_points` 构造的物点坐标是 **列优先（column-major）** 排列：
```python
for i in range(cols):       # 外层 = 列 ← 错误！
    for j in range(rows):   # 内层 = 行
        idx = i * rows + j
        x = i * d
        y = (j + 0.5 * (i % 2)) * d
```

这导致传递给 `_solve_board_pose` 的物点与像点**一一对应关系错误**。例如：
- 图像上的第 1 个点（row0_col0）匹配物点索引 0 = (0, 0) ✓
- 图像上的第 2 个点（row0_col1）匹配物点索引 1 = (0, d) ✗（应为 (d, 0.5d)）
- 图像上的第 12 个点（row1_col0）匹配物点索引 11 = 实际是 col2_row3，完全错位

**后果**: `_solve_board_pose`（SVD Kabsch）基于错误的点对应关系求解，输出的 `T_board_in_cam` 完全错误。后续位姿法标定基于错误位姿计算外参，导致整条链路结果不可用。

### 复现场景

任何使用标定板检测 + 位姿法标定的场景均会触发。当前测试文件 `test_board_tmp.py` 由于自身的 `build_4x11_board_points` 也使用相同的列优先顺序，**自洽但不正确**，无法检测到该问题。

### 解决方案

将循环顺序改为行优先，同时保持非对称偏移量正确：

```python
@staticmethod
def _build_object_points(spec: Dict) -> np.ndarray:
    cols = spec['cols']
    rows = spec['rows']
    d = float(spec['spacing_mm'])

    obj_pts = np.zeros((rows * cols, 3), dtype=np.float64)
    for j in range(rows):          # 外层 = 行（row-major）
        for i in range(cols):      # 内层 = 列
            idx = j * cols + i
            x = i * d
            # 非对称偏移：奇数列向下偏移半格（特征点仍为 cols*rows 个）
            y = (j + 0.5 * (i % 2)) * d
            obj_pts[idx] = [x, y, 0.0]
    return obj_pts
```

### 修改涉及的位置

- `calib_board_detector.py:340-347` — `_build_object_points` 循环顺序
- `test_board_tmp.py:18-24` — `build_4x11_board_points` 循环顺序（保持同步）

---

## Bug 2（中）: `main_window.py` — `board_rms_mm` 未存储到 FrameData

### 位置

`src/ui/main_window.py` 第 856-865 行（`_on_detect_markers` 中标定板结果回写）
`src/core/frame_data.py` 第 54-56 行（FrameData 字段定义）

### 问题描述

`CalibBoardDetector.detect()` 的返回结果包含 `rms_mm`（圆心重投影误差 RMS），但 `main_window.py:_on_detect_markers` 在标定板模式下只存储了三项：
```python
frame.board_pose = br.get('T_board_in_cam')
frame.board_pattern = br.get('pattern_size')
frame.board_pattern_name = br.get('pattern_name')
```

没有存储 `rms_mm`。而 `calibrate_pair_by_board_pose` 的调用处试图通过 `getattr` 读取：
```python
rms_ref_mm=getattr(frame_ref, 'board_rms_mm', 0.0),   # line 919
rms_cam_mm=getattr(frame_cam, 'board_rms_mm', 0.0),   # line 920
```

`FrameData` **没有 `board_rms_mm` 字段**，所以始终返回默认值 `0.0`。

### 后果

```python
# calibration_engine.py:256
rms_mm = float(max(rms_ref_mm, rms_cam_mm))  # = max(0.0, 0.0) = 0.0
```

标定板位姿法的标定结果中 `rms_mm`、`mean_mm`、`max_mm` 全部为 0.0。虽然不会导致崩溃，但给用户的 RMS 信息完全不可用，且质量评分（优/良/合格/差）因 RMS=0 始终显示为"优"（`rms_mm < 0.5`），**误导用户**。

### 解决方案

**方案一**（推荐）：为 `FrameData` 增加 `board_rms_mm` 字段：
```python
# frame_data.py
board_rms_mm: float = 0.0
```

并在 `_on_detect_markers` 中写入：
```python
frame.board_rms_mm = br.get('rms_mm', 0.0)
```

同时 `save` / `load` 中序列化该字段。

**方案二**：直接在 `_on_calibrate_pair_board_pose` 中用 `frame_ref.board_pose` 重算误差，不依赖单独存储的 RMS。但计算成本高且与检测阶段 RMS 含义不同。

### 修改涉及的位置

- `frame_data.py:54-56` — 增加 `board_rms_mm` 字段
- `frame_data.py:127-130` — save 方法序列化
- `frame_data.py:166-175` — load 方法反序列化
- `main_window.py:856-865` — 回写时存储 `board_rms_mm`
- `main_window.py:919-920` — 读取时用 `frame_ref.board_rms_mm` 替代 `getattr`
- `offline_session.py:192-201, 254-267, 280-291` — 序列化/反序列化/回写

---

## Bug 3（中）: `calibration_engine.py` — `calibrate_pair_by_board_pose` 的 RMS 恒为 0

### 位置

`src/core/calibration_engine.py` 第 256 行

### 问题描述

本 Bug 是 Bug 2 的结果，但因为后果严重单独列出。

```python
# 因 frame.board_rms_mm 不存在，getattr 返回 0.0，所以：
rms_mm = float(max(rms_ref_mm, rms_cam_mm))  # = max(0.0, 0.0) = 0.0
```

导致标定结果的 `rms_mm`、`mean_mm`、`min_mm`、`max_mm`、`rms_all_mm` 全部为 0.0。

标定结果表显示 RMS = 0.0000 mm，质量评分"优"，用户据此判断标定精度极高，但实际上是因为误差未被正确传递。

### 解决方案

Bug 2 修复后自然解决。

---

## Bug 4（中）: `calib_board_detector.py` — `_detect_pattern` 使用了不兼容的 `CALIB_CB_FAST_CHECK` 标志

### 位置

`src/core/calib_board_detector.py` 第 233 行

### 问题描述

```python
flags=cv2.CALIB_CB_ASYMMETRIC_GRID | cv2.CALIB_CB_FAST_CHECK,
```

`cv2.CALIB_CB_FAST_CHECK` 是为棋盘格（checkerboard）检测设计的快速预检标志。用于非对称圆标定板时，OpenCV 的行为**未定义**：

- 部分 OpenCV 版本（如 4.8.x）在非棋盘格模式下会**静默忽略**该标志，无影响
- 其他版本可能导致 `findCirclesGrid` 返回 `found=False` 而**完全错过有效的标定板图像**

### 复现场景

若用户使用 OpenCV 4.9+，标定板检测成功率可能显著下降甚至完全失效。

### 解决方案

```python
flags=cv2.CALIB_CB_ASYMMETRIC_GRID,
```

移除 `CALIB_CB_FAST_CHECK` 标志。

### 修改涉及的位置

- `calib_board_detector.py:233`

---

## Bug 5（低）: `calib_board_detector.py` — Blob 检测参数可能与高分辨率图像不兼容

### 位置

`src/core/calib_board_detector.py` 第 206-222 行

### 问题描述

`SimpleBlobDetector` 参数中 `minArea=50`（像素）和 `maxArea=20000`（像素）是硬编码的。

对于 5MP/12MP 等高分辨率相机，标定板圆心在图像中可能占据数百甚至上千像素，当圆心区域超过 20000 像素时，Blob 检测器会将圆心过滤掉。反之，低分辨率图像（如 VGA）圆心可能小于 50 像素而被过滤。

### 复现场景

- 5MP 相机（2592×1944），标定板距相机较近时，单个圆心直径可能超过 160 像素（面积 > 20000）
- VGA 相机（640×480），标定板距相机较远时，单个圆心直径可能小于 8 像素（面积 < 50）

### 解决方案

根据图像尺寸动态缩放最小/最大面积阈值，或在文档中提示用户根据实际图像调整：

```python
# 根据图像对角线长度动态缩放面积阈值
diag = np.sqrt(w**2 + h**2)
scale = diag / 1000.0  # 以 VGA 对角线为基准
params.minArea = max(10, int(50 * scale))
params.maxArea = min(100000, int(20000 * scale))
```

### 修改涉及的位置

- `calib_board_detector.py:206-222` — `_create_blob_detector` 方法参数

---

## Bug 6（低）: `main_window.py` — 切换标记物类型时 `pair_results` 清空但标定面板不刷新

### 位置

`src/ui/main_window.py` 第 1031-1047 行（`_on_marker_type_changed`）

### 问题描述

切换标记物类型会清空 `pair_results` 和标定面板结果，**但未清空保存到文件的标定结果**。用户切换类型后，如果立即「加载标定结果」，会加载之前类型的结果，而当前检测器类型与结果不匹配。

另外，已被删除的 `pair_results` 条目在本函数前后没有调用过 `save_calibration`，因此内存中的结果丢失，但磁盘上的旧标定文件不会被影响。

### 复现场景

1. 编码圆模式下标定完成 → 保存标定结果 → 切换到标定板模式
2. 点击「加载标定结果」→ 加载的是之前编码圆模式的标定 → 但当前是标定板模式
3. 用户可能不会意识到加载的结果与当前模式不兼容

### 解决方案

在 `_on_marker_type_changed` 中添加友好的提示：

```python
self._log("[INFO] 标记物类型已切换，已清空当前标定结果"
          + ("（如有已保存的标定文件，请重新加载前确认兼容性）"
             if self.calibration_engine.pair_results else ""))
```

并在加载标定后检查结果中是否包含 board 相关字段，以确定兼容性。

---

## 汇总

| # | 文件 | 行号 | 严重度 | 类型 |
|---|------|------|--------|------|
| 1 | `calib_board_detector.py` | 340-347 | **严重** | 物点排列顺序错误，导致整条链路结果错误 |
| 2 | `main_window.py` / `frame_data.py` | 857-920 / 54 | **中** | `board_rms_mm` 丢失，RMS 始终为 0 |
| 3 | `calibration_engine.py` | 256 | **中** | Bug 2 的后果，标定结果 RMS=0，质量评分误导 |
| 4 | `calib_board_detector.py` | 233 | **中** | `CALIB_CB_FAST_CHECK` 在不兼容的 OpenCV 版本上失效 |
| 5 | `calib_board_detector.py` | 206-222 | **低** | Blob 参数硬编码，高/低分辨率图像可能检测失败 |
| 6 | `main_window.py` | 1031-1047 | **低** | 切换标记物类型后加载旧标定文件存在兼容性风险 |

---

## 备注

上一轮报告中发现的 5 个问题均已修复，检查确认：
- ✅ Bug 1: `calibration_engine.py:208` — `inlier_count` 已改为 `inlier_mask.sum()`
- ✅ Bug 2: `main_window.py:565` — 已连接 `left_tabs.currentChanged` 信号
- ✅ Bug 3: `camera_card.py:248` — `update_frame` / `update_captured` 已分离
- ✅ Bug 4: `marker_detector.py:128-133` — uint16 处理已加入低动态范围判断
- ✅ Bug 5: `pose_graph.py:51-52` — 已加入 try/except 捕获不可逆矩阵
