"""T-008 判据（**r2 版**；纯数据，照 tasks/T-008-r2.md §2 直译）。

r1 的判据（SDK 异常码 / PLY list 属性）已经验收通过并提交 d558eec，
当时的 verify.json 抄存在 reports/T-008/verify_r1.json；这里换成 r2 的判据。

判据 1/2 改之前是红的：`formatResult()` 还不存在，
`4×4 矩阵（行主序）` 与 `逐组误差` 各出现 2 次，A 的新用例引用不到那个函数
（编译不过 → 旧 exe 里没有那条用例 → 探针如实报"用例数不够"）。
判据 3/4 是不变量，改之前就该是绿的。

发任务书前：python .trio/verify.py T-008 --pre --no-baseline
验收时：    python .trio/verify.py T-008 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

WORKINGSET = [
    "src/logic/CalibrationService.h",
    "src/logic/CalibrationService.cpp",
    "src/app/MainWindow.cpp",
    "src/ui/ToolsPanel.cpp",
]

CHECKS = [
    {
        "n": 1,
        "name": "标定正文只在 CalibrationService 里拼一次（两个字面量各 1 处）",
        "cmd": ["python", "reports/T-008/dedupe_probe.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "正文内容不因重构变形（formatResult 的用例）",
        # 7 = 5 条用例 + initTestCase + cleanupTestCase
        "cmd": ["python", "reports/tools/qt_class_probe.py", "calibration_service", "7"],
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
