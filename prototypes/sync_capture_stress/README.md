# sync_capture_stress —— 多相机并发采集污染复现脚本

> 日期：2026-10-09 ｜ 状态：**待实机复现验证**

## 背景

MCC 主程序（`src/core/camera_manager.py` sync-capture）用 `ThreadPoolExecutor`
让多台相机**同时在各自线程里执行 `Capture() + GetImage() + GetPointMap()`**。
2026-10-09 实机（两台 RVC-I540，X1，GigE）观察到：

- **并发拍摄时 cam1 深度数据被污染**：标定帧 Z 范围从正常的 [307, 344]mm
  劣化为 [258.8, 401.6]mm（飞点散布 143mm），扫描帧 47% 像素无效；
  cam0 同场并发却始终干净。
- **串行拍摄一切正常**：同硬件同场景，MCC 串行标定帧与 RVCManager
  单拍结果一致（有效点率、Z 界完全吻合）。

主程序已加全局采集锁把并发采集串行化兜底（见 `CHANGELOG.md` Unreleased），
本原型用于**定位 SDK 层根因**：并发到底为什么、在什么条件下污染数据。

## 运行

```bash
"D:/Program Files/Anaconda/envs/rvc/python.exe" \
    prototypes/sync_capture_stress/app/repro_sync_capture.py \
    --rounds 10 --indices 0 1
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--rounds` | 10 | 每种模式每相机拍摄轮数 |
| `--indices` | 全部 | 参与测试的设备索引 |
| `--mode` | all | `serial` / `concurrent` / `barrier` / `all` |
| `--json` | 不导出 | 结果 JSON 路径 |

## 判定逻辑

对每相机每帧计算健康指标：

- `valid_ratio`：有限非零点占比（结构化光深度完整度）
- `z_span_p99_p1`：Z 的 P99−P1（紧致性；飞点会把它拉大）
- `z_mad_outlier_ratio`：偏离 Z 中位数超过 20×MAD 的点占比（飞点率）
- `image_mean`：2D 图亮度均值（排除曝光变化这个混杂因素）

以 **serial 模式为每相机基线**，concurrent / barrier 模式下任一指标
相对基线恶化超过阈值（valid_ratio −10pp、z_span ×1.5、飞点率 +5pp）
即判定该相机在该模式下被污染，exit code = 1。

## 三种模式的设计意图

- `serial`：一台拍完再拍下一台（已知干净 → 基线）
- `concurrent`：**逐帧复刻 MCC sync-capture**——每相机一个线程，触发即
  `Capture()`，各自完成后取图，循环 N 轮
- `barrier`：所有线程 `Barrier` 同步起点一起触发（排除"触发时差"因素，
  验证是否只要采集区间重叠就会污染）

若 `barrier` 干净而 `concurrent` 污染 → 与触发时序/采集重叠相关；
若两者都污染 → SDK 双机并发采集本身存在共享状态问题，需 RVBUST 确认
`Capture()` 的线程安全口径。
