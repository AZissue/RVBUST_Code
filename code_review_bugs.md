# MultiCameraCalibration 代码审查 — 潜在 Bug 报告

> 审查日期: 2026-07-23
> 审查范围: `src/core/` 与 `src/ui/` 全部源代码

---

## Bug 1: `calibration_engine.py` — `inlier_count` 与 `inlier_mask` 不一致

### 位置

`src/core/calibration_engine.py` 第 174、191-192、208 行（`calibrate_pair` 方法）

### 问题描述

`calibrate_pair()` 分两阶段选内点：

1. **RANSAC 阶段**（第 143-148 行）：用随机采样+阈值筛选，内点索引存于 `best_inliers`
2. **Refine 阶段**（第 161 行）：用所有内点重新求解 R,T，然后**重新计算**所有点的误差（第 171 行）

关键问题在第 174 行：
```python
inlier_mask = errs < ransac_threshold  # refine 后重新算的内点掩码
```

但最终结果中：
```python
# 第 208 行：inlier_count 用的是 RANSAC 阶段的 best_inliers
'inlier_count': int(len(best_inliers)),

# 第 199 行：rms_mm 用的是 refine 后的 inlier_mask
rms_mm: float(np.sqrt(np.mean(inlier_errs ** 2)))
```

其中 `inlier_errs = errs[inlier_mask]`（第 192 行）。

**后果**：`inlier_count` 和 `rms_mm` 统计的是两个可能不同的内点集合。虽然 refine 后误差通常更小，`inlier_mask` 包含的点数通常 ≥ `best_inliers`，但在边缘情况下（refine 后某点误差刚好跨过阈值），两者会不一致。用户看到的结果会有歧义。

### 解决方案

将 `inlier_count` 改为使用 refine 后的 `inlier_mask`：

```python
# 修改第 208 行
'inlier_count': int(inlier_mask.sum()),
```

同时将 `details` 中的 `is_inlier` 与 `inlier_count` 保持同一数据源。

### 修改涉及的行

- `calibration_engine.py:208` — `inlier_count` 值

---

## Bug 2: `main_window.py` — Tab 切换时未刷新相机列表

### 位置

`src/ui/main_window.py` 第 732-740 行（`_sync_camera_lists` 方法）及第 453-465 行（`_setup_ui` 中 left_tabs 创建）

### 问题描述

`_sync_camera_lists()` 根据当前激活的 Tab 决定向标定面板传递哪些 ID：

```python
def _sync_camera_lists(self):
    if self._station_mode_active():         # 第 736 行
        ids = self.station_manager.get_station_ids()
    else:
        ids = [cid for cid in self.cards.keys() if cid != self.PHYSICAL_ID]
    self.calibration_panel.set_camera_ids(ids)
```

`_station_mode_active()` 检查 `self.left_tabs.currentIndex() == 1`（第 732 行）。

问题是：QTabWidget 的 Tab 切换事件**没有连接**到 `_sync_camera_lists()`。`_setup_ui` 中只创建了 Tab 但未连接 `currentChanged` 信号。

**复现步骤**：
1. 在「多相机」Tab 下添加多台相机并完成标定
2. 切换到「单相机站位」Tab
3. 标定面板的下拉列表仍然显示物理相机 ID，而不是站位 ID

### 解决方案

在 `_setup_ui()` 中（或 `_connect_signals()` 中）连接 Tab 切换信号：

```python
# 在 _setup_ui 约第 465 行后添加
self.left_tabs.currentChanged.connect(self._on_left_tab_changed)

# 新增方法
def _on_left_tab_changed(self, index):
    self._sync_camera_lists()
    # 切换 Tab 后可能需要更新拍摄按钮的启用状态
    self._update_capture_enabled()
```

### 修改涉及的位置

- `main_window.py:465` — 添加 `currentChanged` 信号连接
- `main_window.py` 类中 — 新增 `_on_left_tab_changed` 槽函数

---

## Bug 3: `camera_card.py` — 拍摄计数虚增

### 位置

`src/ui/camera_card.py` 第 248 行

### 问题描述

```python
def update_frame(self, frame_data: FrameData, markers=None):
    ...
    self._capture_count += 1   # 第 248 行
```

`update_frame` 在以下场景都会被调用：
- 真正拍摄后（`_store_frame` → `card.update_frame`）
- **标记检测后**（`_on_detect_markers` → `card.update_frame`）
- 会话加载后（`_load_session_from` → `card.update_frame`）

每次调用都会导致 `_capture_count` +1，使得拍摄计数不能反映真实的拍摄次数。

### 解决方案

方案一（推荐）：从 frame_data 携带真正的拍摄计数信息；方案二（简单修复）：只在拍摄时更新计数，检测/加载时不调用 `update_frame` 或分离为独立方法：

```python
# 方法一：分离拍摄和更新逻辑
def update_frame(self, frame_data, markers=None):
    """更新预览（不递增拍摄计数）。"""
    ...

def update_captured(self, frame_data, markers=None):
    """更新预览并递增拍摄计数。"""
    self._capture_count += 1
    self.update_frame(frame_data, markers)
```

### 修改涉及的位置

- `camera_card.py:248` — `_capture_count` 递增逻辑
- `main_window.py` 中所有调用 `update_frame` 的地方（约 10 处），需要判断哪些是真正拍摄

---

## Bug 4: `marker_detector.py` — `_preprocess` 中 uint16 转 uint8 精度截断

### 位置

`src/core/marker_detector.py` 第 83-85 行

### 问题描述

```python
if image.dtype == np.uint16:
    image = (image / 256).astype(np.uint8)
```

uint16 范围 0-65535 → uint8 范围 0-255，除以 256 等价于右移 8 位，丢弃了低 8 位精度。

对于普通的编码圆检测，uint8 精度足够。但问题在于后续还有一段处理（第 94-95 行）：

```python
if image.max() <= 1.0:
    image = (image * 255).astype(np.uint8)
```

如果 uint16 图像的最大值恰好 ≤ 256（即所有像素只用了低 8 位），那么 `image / 256` 后最大值 ≤ 1.0，**会再次触发 `image * 255` 的缩放**，导致双重的精度损失和值范围异常。

### 复现场景

M2600 等相机在低增益/低曝光条件下返回的 uint16 图像，像素值主要集中在 0-256 区间。

### 解决方案

在 uint16→uint8 转换后，将判断移到前面，避免双重处理：

```python
if image.dtype == np.uint16:
    # 先判断实际使用到的范围
    if image.max() > 256:
        image = (image / 256).astype(np.uint8)
    else:
        image = image.astype(np.uint8)
    logger.info(f"图像 uint16 → uint8 转换")
```

### 修改涉及的位置

- `marker_detector.py:83-85`

---

## Bug 5: `pose_graph.py` — `_build_adjacency` 吞异常

### 位置

`src/core/pose_graph.py` 第 44-52 行

### 问题描述

```python
def _build_adjacency(pair_results):
    adj = {}
    for (a, b), res in pair_results.items():
        T = res.get('T') if isinstance(res, dict) else None
        if T is None:
            continue        # 静默跳过无效结果，不记日志
        T = np.asarray(T, dtype=np.float64)
        if T.shape != (4, 4):
            continue        # 静默跳过形状错误的结果
        adj.setdefault(a, []).append((b, np.linalg.inv(T)))
        adj.setdefault(b, []).append((a, T))
    return adj
```

如果 `T` 矩阵形状正确但实际上是奇异矩阵（不可逆），`np.linalg.inv(T)` 会在运行时抛出 `LinAlgError`。由于该函数没有 try/except，且调用链（`find_path_transform` → `optimize_global`）也没有捕获，会导致整个拼接/优化流程崩溃。

### 复现场景

用户保存了错误的标定结果（如三点共线导致奇异矩阵），加载后调用拼接。

### 解决方案

在 `np.linalg.inv(T)` 处添加异常捕获，跳过无法求逆的 pair 并记录日志：

```python
try:
    T_inv = np.linalg.inv(T)
except np.linalg.LinAlgError:
    logger.warning(f"pair ({a}, {b}) 矩阵不可逆，已跳过")
    continue
adj.setdefault(a, []).append((b, T_inv))
adj.setdefault(b, []).append((a, T))
```

### 修改涉及的位置

- `pose_graph.py:51` — `np.linalg.inv(T)` 调用处

---

## 汇总

| # | 文件 | 行号 | 严重度 | 类型 |
|---|------|------|--------|------|
| 1 | `calibration_engine.py` | 174, 208 | 中 | 统计不一致 |
| 2 | `main_window.py` | 465, 732-740 | 中 | 状态不同步 |
| 3 | `camera_card.py` | 248 | 低 | 计数不准确 |
| 4 | `marker_detector.py` | 83-85, 94-95 | 低 | 精度/逻辑 |
| 5 | `pose_graph.py` | 51 | 低中 | 异常未捕获 |

其中 **Bug 1** 和 **Bug 2** 建议优先修复，其余为防御性改进。
