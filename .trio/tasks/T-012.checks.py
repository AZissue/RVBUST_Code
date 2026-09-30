"""T-012 判据（纯数据，照 tasks/T-012.md §2 直译）。

判据 1/2 是真机精度（五特征里的四个，各一次独立拍照）；改之前五条全红
（Ø6 +0.2648、Ø5 −0.263、Ø63.5 48.28 只有真值的 76%、Ø26 与 Ø9 连读数都没有）。
判据 3/4 是不变量。

每条真机判据 ≈ 90 秒（两个特征，各起一次程序、各连一次相机）。

发任务书前：python .trio/verify.py T-012 --pre --no-baseline
验收时：    python .trio/verify.py T-012 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

WORKINGSET = [
    "src/logic/MeasureTools.h",
    "src/logic/MeasureTools.cpp",
    "src/logic/MeasureMethods.h",
    "src/ui/MeasurePage.h",
    "src/ui/MeasurePage.cpp",
    "src/ui/MeasurePages.cpp",
    "src/ui/ToolsPanel.h",
    "src/ui/ToolsPanel.cpp",
    "src/app/MainWindow.cpp",
]

CHECKS = [
    {
        "n": 1,
        "name": "孔径：Ø6 / Ø5 真机 ≤0.2%×标称",
        "cmd": ["python", "reports/T-012/accuracy_probe.py",
                "--reps", "1", "--only", "hole_d6_disc,plate_low_d5"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "圆环：Ø26 / Ø63.5 真机 ≤0.2%×标称",
        "cmd": ["python", "reports/T-012/accuracy_probe.py",
                "--reps", "1", "--only", "hub_d26,disc_d63_5"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
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
