"""T-009 判据（纯数据，照 tasks/T-009.md §2 直译）。

判据 1 改之前是红的，而且是**真复现**（不是结构性推断）：黑洞地址 10.255.255.1
让 `waitForConnected(1500)` 在 UI 线程上等满，程序自带的看门狗记下
`[WATCHDOG] UI stall 1575 ms`。判据 2/3/4 是不变量。

发任务书前：python .trio/verify.py T-009 --pre --no-baseline
验收时：    python .trio/verify.py T-009 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

WORKINGSET = [
    "src/app/MainWindow.h",
    "src/app/MainWindow.cpp",
    # ↓ 暂停中的 T-012 WIP，一直躺在工作树里（T-009.md §3 已明确要 B 别碰）。
    "src/logic/MeasureTools.h",
    "src/logic/MeasureTools.cpp",
    "src/ui/MeasurePage.h",
    "src/ui/MeasurePage.cpp",
    "src/ui/MeasurePages.cpp",
    "src/ui/ToolsPanel.h",
]

CHECKS = [
    {
        "n": 1,
        "name": "连机器人不再冻 UI（点连接后无新的 [WATCHDOG] UI stall）",
        "cmd": ["python", "reports/T-009/ui_stall_probe.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "机器人链路仍然通（模拟连接 + 两次读位姿）",
        "cmd": ["python", "reports/T-007/robot_simulate_probe.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "green",
    },
    {
        "n": 3,
        "name": "既有测试不退化（unit_tests + measurement_truth）",
        "cmd": ["ctest", "--test-dir", "build", "-C", "Release", "--output-on-failure"],
        "exit": 0,
        "pre": "green",
    },
    {
        "n": 4,
        "name": "工作集守门",
        "cmd": ["python", "reports/tools/workingset_guard.py", *WORKINGSET],
        "exit": 0,
        "pre": "green",
    },
]
