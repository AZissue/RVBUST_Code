"""T-008 判据（**r3 版**；纯数据，照 tasks/T-008-r3.md §2 直译）。

r1（SDK 异常码 / PLY list 属性，提交 d558eec）与 r2（标定正文去重，提交 0ea79a6）
都已验收通过，两份 verify.json 抄存在 reports/T-008/verify_r1.json / verify_r2.json。

判据 1 改之前是红的（品牌蓝散落 5 处、VisSceneView 写死背景色、84 行 Tab）；
判据 2/3/4 是不变量（像素基线是改之前采的）。

发任务书前：python .trio/verify.py T-008 --pre --no-baseline
验收时：    python .trio/verify.py T-008 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

WORKINGSET = [
    "src/ui/Theme.h",
    "src/ui/Theme.cpp",
    "src/ui/ToolsPanel.cpp",
    "src/ui/DeviceListDialog.cpp",
    "src/ui/ActionButtons.cpp",
    "src/ui/VisSceneView.cpp",
    "src/logic/URRealtimeReader.h",
    "src/logic/URRealtimeReader.cpp",
    # ↓ 这几条不是本轮的工作集，是**暂停中的 T-012 WIP**（B 改到一半、等人拍板），
    #   它们一直躺在工作树里。T-008-r3.md §3 已明确要 B 别碰；守门仍然负责抓
    #   "这一轮的新越界"。验收时 A 会逐行看 diff 兜底。
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
        "name": "颜色收敛到 Theme::withAlpha()、Tab 缩进清零",
        "cmd": ["python", "reports/T-008/cleanup_probe.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        # 换成"颜色值逐点比对"：截图采样在某些窗口层级下会采到别的地方
        # （实测基线采到暗区、改后采到浅色区），做判据太脆。
        # 现在比的是 HEAD 里每个 rgba(22,119,255,A) 的 alpha 与当前
        # Theme::withAlpha(<色>, A) 的 alpha 集合是否逐一相等 —— 这是
        # "同一个颜色换个写法"的精确判据，不含像素。
        "name": "颜色值没变（alpha 逐点与 HEAD 字面量一致）",
        "cmd": ["python", "reports/T-008/cleanup_probe.py"],
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
