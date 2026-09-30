"""T-003 判据（纯数据，照 solutions/S-003.md §5 直译）。

判据 1 是人眼判的并排截图；判据 2 是代码层解耦 + 冒烟，由独立脚本跑。
按人 2026-09-30 的新要求：A 只验"人提的这条需求"，不再做全量回归抽查
（其他功能由人自己检查，发现问题再回灌）。

发任务书前：python .trio/verify.py T-003 --pre --no-baseline
（判据 2 必须红——它测的就是"3D 有专属底色 / 没共用实现"这个现状。）
"""

MANUAL = [1]

CHECKS = [
    {
        "n": 2,
        "name": "代码层解耦：共用同一浮层实现与样式、3D 无专属底色、程序能起",
        "cmd": ["python", "reports/T-003/overlay_decoupled.py"],
        "exit": 0,
        "pre": "red",
    },
]
