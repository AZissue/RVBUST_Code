"""T-010 判据（纯数据，照 tasks/T-010.md §2 直译）。

判据 1 改之前是红的，因为**没有任何测量**：程序不从 runtime 日志里报浮层开销，
探针读不到 `[OVERLAY] … per_frame_us=…` 行 → FAIL（"没有仪表"）。
判据 2/3 是不变量。

发任务书前：python .trio/verify.py T-010 --pre --no-baseline
验收时：    python .trio/verify.py T-010 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

WORKINGSET = [
    "src/ui/Image2DView.h",
    "src/ui/Image2DView.cpp",
    "src/ui/ViewOverlay.h",
    # ↓ 暂停中的 T-012 WIP（T-010.md §3 已明确要 B 别碰）
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
        "name": "浮层开销有仪表，且实测 ≤ 0.5 ms/帧",
        "cmd": ["python", "reports/T-010/overlay_cost.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "既有测试不退化（unit_tests + measurement_truth）",
        "cmd": ["ctest", "--test-dir", "build", "-C", "Release", "--output-on-failure"],
        "exit": 0,
        "pre": "green",
    },
    {
        "n": 3,
        "name": "工作集守门",
        "cmd": ["python", "reports/tools/workingset_guard.py", *WORKINGSET],
        "exit": 0,
        "pre": "green",
    },
]
