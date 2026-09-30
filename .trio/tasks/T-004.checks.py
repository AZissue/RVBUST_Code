"""T-004 判据（纯数据，照 tasks/T-004.md §2 直译）。

判据 1 是"坏头部不再带走进程"，判据 3 是"既有测试不退化"——两条在改之前**都必须是红的**
（A 已经先把两条红线用例写进 tests/test_pixel_to_3d.cpp 了）。
判据 2 是不变量（工作集守门），改之前就该是绿的。

发任务书前：python .trio/verify.py T-004 --pre --no-baseline
验收时：    python .trio/verify.py T-004 --no-baseline

**为什么带 --no-baseline**：verify.py 的"既有测试基线"写死跑
`python -m unittest discover -s tests -t .`（骨架仓按 python 项目写的），
而本仓的测试是 C++ / ctest，`tests/` 不是 python 包 → 那条基线必然 ImportError。
本仓真正管"既有测试不退化"的是判据 3（ctest 两个 case 全过）。
这条框架缺口记在 T-008（清理包）里修：给 verify.py 的 baseline() 加一个 config 驱动的
测试命令（本仓指向 ctest），在那之前所有任务都带 --no-baseline。
"""

MANUAL = []

CHECKS = [
    {
        "n": 1,
        "name": "坏头部（声称顶点数远超文件内容）报错返回，进程存活",
        "cmd": ["python", "reports/T-004/ply_probe.py"],
        "exit": 0,
        "stdout_has": "PASS",
        "pre": "red",
    },
    {
        "n": 2,
        "name": "工作集守门：本轮只动了 src/logic/PlyPointReader.h",
        "cmd": ["python", "reports/T-004/workingset_guard.py"],
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
