"""T-006 判据（纯数据，照 tasks/T-006.md §2 直译）。

判据 1、3 改之前都是红的：A 已经把三条新用例（ascii 不变量 + 两条二进制类型）
编进 unit_tests.exe，其中两条二进制用例现在失败（passed 15 / failed 2）。
判据 2 是不变量。

发任务书前：python .trio/verify.py T-006 --pre --no-baseline
验收时：    python .trio/verify.py T-006 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

CHECKS = [
    {
        "n": 1,
        # 18 = 16 条用例（12 条既有含 T-004 的两条 + 4 条 T-006：ascii 不变量、
        # int32、short/ushort/uchar、认不出的属性类型不许悄悄挪位）+ init/cleanup。
        "name": "PLY 的 x/y/z 按声明类型解码；认不出的属性类型绝不给错值",
        "cmd": ["python", "reports/tools/qt_class_probe.py", "pixel_to_3d", "18"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "工作集守门：本轮只动了 src/logic/PlyPointReader.h",
        "cmd": ["python", "reports/tools/workingset_guard.py", "src/logic/PlyPointReader.h"],
        "exit": 0,
        "pre": "green",
    },
    {
        "n": 3,
        "name": "既有测试不退化（unit_tests + measurement_truth）",
        "cmd": ["ctest", "--test-dir", "build", "-C", "Release", "--output-on-failure"],
        "exit": 0,
        "pre": "red",
    },
]
