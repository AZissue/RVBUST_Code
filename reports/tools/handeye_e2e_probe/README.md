# handeye_e2e_probe —— 手眼标定位姿格式的端到端探针

`reports/阶段7-位姿格式预设与试算.md` 第 6 节那几张表的**复现工具**。
它不是单元测试：单元测试验的是我们自己的换算，这里验的是**换算 + 真 HandEyeSDK**
合起来的结果。**只读代码，不改工程。**

## 它证明什么

| 脚本 | 要回答的问题 |
|---|---|
| `probe8.py` | 卡片里写**轴角弧度**时：旧的"当欧拉算"与新的"旋转矢量预设"分别得到什么？ |
| `probe9.py` | 新的欧拉 RPY 路径**是不是**还是"整行原样喂 SDK"（既有 FANUC 结果没被挪动）？ |

两个脚本都会打印 HandEyeSDK 的 `totalMeanError`、恢复出的 4×4 矩阵，
并与合成数据的真值 X 逐项比较。

## 怎么跑

```bash
# 1) 配置 + 构建（VS 2026；SDK 路径写在 CMakeLists.txt 顶部）
cmake -S reports/tools/handeye_e2e_probe -B <某个 build 目录> \
      -G "Visual Studio 18 2026" -A x64 \
      -DQt5_DIR="D:/Program Files/Qt/5.14.2/msvc2017_64/lib/cmake/Qt5"
cmake --build <某个 build 目录> --config Release

# 2) 跑（numpy 必需；脚本里的 EXE / QT_BIN 路径按你的机器改）
python probe8.py
python probe9.py
```

`CMakeLists.txt` 里的 `set(APP ...)` 指向本仓库 `src/`，`set(SDK ...)` 指向
`third_party/HandEyeSDK`，另外 `probe8.py` / `probe9.py` 里的 `ROOT` / `QT_BIN`
是路径常量 —— 换机器要改这三处。

## 组成

- `main.cpp` + `CMakeLists.txt` 的 `he_sdk_probe` 目标：**直接调 SDK** 的探针
  （`touch` 模式跑 TcpTouch 标定并打印误差与矩阵；`calib` / 默认模式查格式接受性）。
- `e2e_main.cpp` + `he_app_e2e` 目标：把**程序自己的** `logic/CalibrationService.cpp`
  与 `sdk/HandEyeSDKBridge.cpp` 编进控制台程序，调 `CalibrationService::calibrate()`，
  与 GUI 走同一条路。

## 注意

- 合成数据是**故意**的：`probe8.py` 与 `probe9.py` 用同一份数据（`default_rng(7)`），
  所以两次运行的数字可以直接对照。
- `probe9.py` 里 SDK 直接读的是逗号分隔的 `pose.txt`，也就是我们的
  `normalizePoseLine` 会写出的那种行；A/B 两边的**数字完全一致**才算通过
  （实测 `totalMeanError` 相同、矩阵 `max|delta| = 0`）。
