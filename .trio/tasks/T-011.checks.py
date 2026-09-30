"""T-011 判据（纯数据，照 tasks/T-011.md §2 直译）。

判据 1 改之前是红的：预览 worker 捕获裸 this（`[this, gen, token]`），
析构路径也没有 waitForFinished。判据 2/3/4 是不变量。

注意判据 2 要真起 5 次程序（每次连相机+预览+关窗口，约 30 s），整份 verify 约 3 分钟。

发任务书前：python .trio/verify.py T-011 --pre --no-baseline
验收时：    python .trio/verify.py T-011 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

WORKINGSET = [
    "src/logic/CameraManager.h",
    "src/logic/CameraManager.cpp",
    # ↓ 不是本轮工作集：暂停中的 T-012 WIP 一直躺在工作树里（T-011.md §5 已明确要 B 别碰）。
    #   守门仍负责抓这一轮的新越界，验收时 A 还会逐行看 diff。
    "src/app/MainWindow.cpp",
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
        "name": "预览 worker 的生命周期被绑住（不捕获裸 this 或析构显式等待）",
        "cmd": ["python", "reports/T-011/preview_lifetime.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "真机：连相机→预览→关窗口 ×5 不崩、退出码正常",
        "cmd": ["python", "reports/T-011/exit_cycles.py", "5"],
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
