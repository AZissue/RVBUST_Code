"""T-002 判据（纯数据，照 solutions/S-002.md §4 判据表直译）。

判据 6 是人眼判的（截图），列进 MANUAL。
发任务书前：python .trio/verify.py T-002 --pre --no-baseline
（判据 1 必须红——它测的就是"提示还在视窗里"这个现状。）

注意 --no-baseline：框架自带的"既有测试基线"跑的是 Python unittest discovery，
本仓 tests/ 是 C++ 目录，会直接 ImportError（已在群里报过）。既有测试用判据 4 的 ctest 兜。
"""

MANUAL = [6]

CHECKS = [
    {
        "n": 1,
        "name": "3D 视窗里不再有「识别后可点击…」提示（且日志里有）",
        "cmd": ["python", "reports/T-002/probe_pickhint.py"],
        "exit": 0,
        "pre": "red",
    },
    {
        "n": 2,
        "name": "回归：工具面板 15 项逐项选中不崩",
        "cmd": ["python", "reports/T-003/repro_crash.py"],
        "exit": 0,
        "pre": "green",
    },
    {
        "n": 3,
        "name": "回归：连相机后预览/拍照不崩（SN I1GM112B652）",
        "cmd": ["python", "reports/T-002/repro_camera_crash.py"],
        "exit": 0,
        "stdout_has": "拍照 存活 12 秒",
        "pre": "green",
    },
    {
        "n": 4,
        "name": "既有 ctest 全过",
        "cmd": ["ctest", "--test-dir", "build", "-C", "Release",
                "--output-on-failure"],
        "exit": 0,
        "stdout_has": "100% tests passed",
        "pre": "green",
    },
    {
        "n": 5,
        "name": "工作集不越界",
        "cmd": ["python", "reports/T-003/workingset_guard.py"],
        "exit": 0,
    },
]
