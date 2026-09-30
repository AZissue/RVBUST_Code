"""T-008 判据（r1；纯数据，照 tasks/T-008.md §2 直译）。

判据 1/2/3 改之前是红的：A 的新用例引用还不存在的
`HandEyeSDKBridge::kSdkInternalError`，所以**编不出来**，旧 exe 里没有那两条用例
（探针如实报"用例数不够"）；桥接层也还没有那个常量。
判据 4（既有测试）改之前是绿的：旧 exe 照跑照过 —— 它是"别退化"的不变量。
判据 5 同样是不变量。

发任务书前：python .trio/verify.py T-008 --pre --no-baseline
验收时：    python .trio/verify.py T-008 --no-baseline
（--no-baseline 的理由见 T-004.checks.py 顶部。）
"""

MANUAL = []

WORKINGSET = [
    "src/sdk/HandEyeSDKBridge.h",
    "src/sdk/HandEyeSDKBridge.cpp",
    "src/logic/CalibrationService.cpp",
    "src/logic/PlyPointReader.h",
]

CHECKS = [
    {
        "n": 1,
        "name": "PLY 顶点元素上的 list 属性不再静默错值",
        "cmd": ["python", "reports/tools/qt_class_probe.py", "pixel_to_3d", "19"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "SDK 内部异常不再被说成「参数无效」（文案层）",
        "cmd": ["python", "reports/tools/qt_class_probe.py", "calibration_service", "6"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 3,
        "name": "桥接层真的用了独立的 kSdkInternalError",
        "cmd": ["python", "reports/T-008/bridge_sentinel.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 4,
        "name": "既有测试不退化（unit_tests + measurement_truth）",
        "cmd": ["ctest", "--test-dir", "build", "-C", "Release", "--output-on-failure"],
        "exit": 0,
        "pre": "green",
    },
    {
        "n": 5,
        "name": "工作集守门",
        "cmd": ["python", "reports/tools/workingset_guard.py", *WORKINGSET],
        "exit": 0,
        "pre": "green",
    },
]
