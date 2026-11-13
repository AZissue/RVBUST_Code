# 转台 360° 拼接原型（在线相机版）

> 位置：`D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\turntable_360_stitch`  
> 目标：验证「相机固定 + 手动旋转转台 → 角度标定 → 等角度分步拍摄 → 360° 实时拼接」的可行性。  
> 范围：**仅保留在线相机功能，不控制转台**。

---

## 核心思路

1. **标定**：在转台上放置标记物，拍摄 frame_0000（参考帧）；手动旋转转台一小段角度后拍摄 frame_0001。
2. **角度估计**：从两帧中匹配同一组标记点的 3D 坐标，用 Kabsch 求刚体变换 `(R, t)`，分解出旋转轴 `axis`、旋转角 `θ`、旋转中心 `center`。
3. **步数推算**：`step_count = round(360° / θ)`。
4. **扫描**：按 `θ` 每次手动旋转转台，依次拍摄 frame_0001、frame_0002 ...
5. **拼接**：第 `i` 帧点云绕 `axis` 旋转 `-i·θ`（过 `center`）变换到参考系，全部合并。

---

## 目录结构

```
turntable_360_stitch/
├── core/
│   └── turntable_calibrator.py      # 核心算法
├── app/
│   └── simple_ui.py                 # PySide6 在线 UI
├── tests/
│   └── test_synthetic.py            # 无硬件单元测试
└── README.md
```

| 文件 | 作用 |
|---|---|
| `core/turntable_calibrator.py` | 核心算法：Kabsch、轴角分解、旋转中心估计、点云变换合并、合成数据生成、在线会话管理 |
| `app/simple_ui.py` | PySide6 UI：在线连接相机、拍摄、标定、采集、实时拼接；2D 预览与 3D 点云水平分布 |
| `tests/test_synthetic.py` | 无 UI 单元测试：角度/轴估计精度、完整 360° 拼接、噪声鲁棒性 |

---

## 快速验证（无硬件）

```bash
cd D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\turntable_360_stitch\tests
"D:\Program Files\Anaconda\envs\rvc\python.exe" test_synthetic.py
```

预期：不同角度下角度误差 < 0.5°、轴误差 0、中心垂距误差 < 2mm、360° 拼接 AABB 正常。

---

## 启动 UI

```bash
cd D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\turntable_360_stitch\app
"D:\Program Files\Anaconda\envs\rvc\python.exe" simple_ui.py
```

### UI 布局

- **左侧**：控制面板（相机连接、标定、步进采集、拼接输出）。
- **右侧上方**：水平分布
  - **左**：2D 预览窗口，实时显示当前相机画面。
  - **右**：3D 点云查看器，显示单帧/叠加/合并结果。
- **右侧下方**：日志面板。

### 使用步骤

1. **相机连接**
   - 点击 **「初始化 RVC」**。
   - 在设备列表中选择相机，点击 **「连接相机」**。
   - 选择标记物类型：**编码圆** 或 **非对称圆标定板**。

2. **在线标定**
   - 点击 **「2D 预览」** 确认标记物在视野中。
   - 在转台上放置标记物，点击 **「拍摄 frame0」**。
   - 手动旋转转台一小段角度，点击 **「拍摄 frame1」**。
   - 程序会自动检测标记点，点击 **「在线标定转台」**。
   - 得到旋转角 `θ` 和 360° 所需步数。

3. **步进采集**
   - 按 `θ` 每次手动旋转转台。
   - 点击 **「拍摄当前步」**，依次采集 step 1、step 2 ...
   - 勾选 **「自动实时拼接」**：每采集一帧后自动拼接并刷新 3D 视图。
   - 也可点击 **「开始自动采集」**，设置间隔秒数，程序会按间隔提示并自动拍摄。

4. **拼接与保存**
   - 点击 **「拼接并显示」** 手动触发拼接。
   - 点击 **「保存合并 PLY」** 导出合并点云。
   - 点击 **「保存会话」** 导出所有原始帧、图像、markers 与标定参数。

### 标记物说明

- **编码圆**：需要在转台上放置带编码的圆形标记物（如 RVC 编码圆标定板）。检测后会按 `code` 匹配两帧中的同一标记。
- **非对称圆标定板**：使用 OpenCV 非对称圆网格检测，按圆心顺序索引匹配。

---

## 算法说明

### 旋转中心估计的轴向任意性

由 `(R - I)c = -t` 求出的旋转中心 `c`，其沿旋转轴方向的分量是任意的。  
**这对拼接没有影响**：把中心沿轴平移任意距离，绕该轴的旋转变换结果不变。  
因此测试报告中只检查「中心到真实轴线的垂直距离」，不检查沿轴坐标。

### 与项目现有模块的关系

- 可复用：`../../../src/core/camera_manager.py`（相机拍摄）、`../../../src/core/marker_detector.py`（标记检测）、`../../../src/core/stitch_engine.py`（点云合并思想）。
- 当前独立：不修改原项目代码，便于快速迭代验证。
- 未来集成：验证通过后，可把 `core/turntable_calibrator.py` 中的 `TurntableCalibrator` / `OnlineTurntableSession` 迁入 `src/core/`，在主 UI 增加「转台拼接」入口。
