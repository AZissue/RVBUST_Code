"""T-001 的判据（纯数据，照 solutions/S-001.md §4 判据表直译）。

判据 2、3 是人眼判的（截图），列进 MANUAL——不会被悄悄跳过，也不会算自动通过。

A 验收：`python .trio/verify.py T-001`；发任务书前：`python .trio/verify.py T-001 --pre`
（判据 1 必须红——它测的就是"现在会崩"这个新行为）。
"""

MANUAL = [2, 3]

CHECKS = [
    {
        "n": 1,
        "name": "真机：工具列表逐项选中不崩（含「像素→3D」）",
        "cmd": ["python", "reports/T-003/repro_crash.py"],
        "exit": 0,
        "pre": "red",
    },
    {
        "n": 4,
        "name": "既有 ctest 全过（2 个测试、unit_tests 不减少）",
        "cmd": ["ctest", "--test-dir", "build", "-C", "Release",
                "--output-on-failure"],
        "exit": 0,
        "stdout_has": "100% tests passed",
        "pre": "green",
    },
    {
        "n": 5,
        "name": "工作集不越界（不许动 logic/sdk/app/tests/CMake 等）",
        "cmd": ["python", "reports/T-003/workingset_guard.py"],
        "exit": 0,
    },
    {
        "n": 6,
        "name": "真机：连相机后「预览」/「拍照」不崩（SN I1GM112B652）",
        "cmd": ["python", "reports/T-002/repro_camera_crash.py"],
        "exit": 0,
        "stdout_has": "拍照 存活 12 秒",
        "pre": "red",
    },
]
