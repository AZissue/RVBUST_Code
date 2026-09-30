# T-007 验收证据（A）— 四种机器人协议的分派收敛成一处

日期：2026-09-30　　结论：**通过**

## 1. 判据（`python .trio/verify.py T-007 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | 复制粘贴的四份收敛成一处 | ✓ | `reports/T-007/dispatch_consolidated.py` → `PASS` |
| 2 | 只动 `MainWindow.{h,cpp}` | ✓ | `reports/tools/workingset_guard.py` |
| 3 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2` |
| 4 | 机器人链路真机不变量 | ✓ | `reports/T-007/robot_simulate_probe.py` → `PASS`（100.000 / 110.000，进程存活） |

## 2. 改前的红 / 绿（`--pre`）

```
✗ [判据 1] 四种协议的分派从复制粘贴四份收敛成一处
✓ [判据 2] 工作集守门：只动 MainWindow.h / MainWindow.cpp
✓ [判据 3] 既有测试不退化
✓ [判据 4] 机器人链路真机不变量：模拟连接 + 两次读位姿
```

判据 1 的"改前"实测值（探针自己打的 before/now）：

| 指标 | 改前 | 门槛 | 改后 |
|---|---|---|---|
| `机器人已连接（` | 8 | ≤2 | 2 |
| `机器人连接失败：%1` | 8 | ≤2 | 2 |
| `setRobotConnected(true)` | 5 | ≤2 | 2 |
| `MainWindow.cpp` 行数 | 2144 | ≤2080 | 2035（净 −109 行） |

## 3. A 独立复核的要点

- 新的分派点只有一处：`MainWindow::robotReaderFor(int protocol)`（`MainWindow.cpp:1167`），
  返回 `RobotPose::Reader*`；连接、读取位姿、取错误、断开、模拟连接全部走它。
  "加第五种协议"= 加一个 case + 一个成员，**一处**。
- 四个适配器文件**一行没动**（工作集守门 + `git diff --stat` 只有
  `MainWindow.cpp` −109/+50、`MainWindow.h` +8）。
- 逐协议的特有动作被保留在连接前那一段里：埃夫特无额外配置、
  NRC/UR 各设 `setTimeoutMs(1500)`、Modbus 才组装 `ModbusConfig`
  （format 1/2/默认 ↔ Int32Scaled/Int16Scaled/Float32，scale/unitId/startAddress）。
- 连接成功/失败的提示与日志文案与改前逐字相同（探针的字符串计数就是按原文量的）。
- `onRobotDisconnect` / `onRobotSimulateConnect` 改成对 0..3 四个号各断一次，
  与改前"显式断四个"等价。

## 4. 判据 4 的探针是怎么做的（可复现）

`reports/T-007/robot_simulate_probe.py`：真起 `HandEyeCalibrationTool.exe`，
用 `.codex-loop/tools/ui.py`（UIA + posted mouse messages，不抢物理鼠标）点
工具 → 机器人通信 → 模拟连接成功 → 拍照位姿 ×2，然后读
`build/src/Release/logs/app_<date>.log`。

> 现场教训（写下来给下一个写探针的人）：**工具面板是独立顶层窗口**，
> 把面板里控件的鼠标消息投到主窗口句柄上永远打不中（第一版探针就是这么失败的，
> 表现是"页面没切出来"）。必须用 `EnumWindows` 按标题找到面板自己的 HWND 再投。
