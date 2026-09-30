"""T-005 判据（纯数据，照 tasks/T-005.md §2 直译）。

判据 1（新行为）改之前必须是红的：A 写的 tests/test_save_export.cpp 会调用
还不存在的 `DataManager::lastExportError()`，所以新测试**编不出来** ——
此时 unit_tests.exe 还是旧的、报告里没有 save_export 这一类，探针如实报 FAIL。
判据 3（既有测试）改之前是绿的：旧 exe 照跑照过，它就是"别退化"的不变量。

发任务书前：python .trio/verify.py T-005 --pre --no-baseline
验收时：    python .trio/verify.py T-005 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部：骨架仓的基线通道写死 python unittest，
  本仓是 ctest；真实基线由判据 3 承担。）
"""

MANUAL = []

WORKINGSET = [
    "src/logic/DataManager.h",
    "src/logic/DataManager.cpp",
    "src/logic/CaptureFlow.h",
    "src/logic/CaptureFlow.cpp",
]

CHECKS = [
    {
        "n": 1,
        "name": "导出失败被上报 + 界面不假成功 + 备份带版本/恢复跳过损坏文件",
        "cmd": ["python", "reports/tools/qt_class_probe.py", "save_export", "8"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "工作集守门",
        "cmd": ["python", "reports/tools/workingset_guard.py", *WORKINGSET],
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
]
