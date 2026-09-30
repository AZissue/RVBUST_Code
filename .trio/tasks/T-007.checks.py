"""T-007 判据（纯数据，照 tasks/T-007.md §2 直译）。

判据 1（分派收敛）改之前是红的：A 实测 MainWindow.cpp 里
「机器人已连接（」8 处 / 「机器人连接失败：%1」8 处 / setRobotConnected(true) 5 处 /
行数 2144 —— 全都在门槛之上。
判据 2/3/4 是不变量，改之前就该是绿的（判据 4 是真机探针，A 已实测 100.000/110.000）。

发任务书前：python .trio/verify.py T-007 --pre --no-baseline
验收时：    python .trio/verify.py T-007 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

CHECKS = [
    {
        "n": 1,
        "name": "四种协议的分派从复制粘贴四份收敛成一处",
        "cmd": ["python", "reports/T-007/dispatch_consolidated.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "工作集守门：只动 MainWindow.h / MainWindow.cpp",
        "cmd": ["python", "reports/tools/workingset_guard.py",
                "src/app/MainWindow.h", "src/app/MainWindow.cpp"],
        "exit": 0,
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
        "name": "机器人链路真机不变量：模拟连接 + 两次读位姿（值不同、进程存活）",
        "cmd": ["python", "reports/T-007/robot_simulate_probe.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "green",
    },
]
