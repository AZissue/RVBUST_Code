# 框架缺口笔记：verify.py 的"既有测试基线"在本仓不适用

**现象**：`python .trio/verify.py T-004`（不带 `--no-baseline`）会报

```
✗ 基线：游戏侧既有测试（? 项）
    ImportError: Start directory is not importable: 'D:\MyCode\MyHandEyeTools\tests'
```

**根因**：`.trio/verify.py::baseline()` 把"既有测试"写死成
`sys.executable -m unittest discover -s tests -t .`（骨架仓是从 python 项目抽的），
而本仓的测试是 C++ / ctest，`tests/` 不是 python 包。
`config.json` 的 `test_baseline` 无论填几都不影响这条 —— 命令本身就跑不起来。

**本仓现在的对策**：所有任务书与 `checks.py` 统一带 `--no-baseline`；
"既有测试不许减少"由**每个任务判据里的 ctest**承担
（`ctest --test-dir build -C Release`，两个 case：`unit_tests` + `measurement_truth`）。
这条写进了 `.trio/tasks/T-004.checks.py` 顶部，后续任务都引用它。

**正确修法（属骨架仓，不在本仓改）**：给 `baseline()` 加一个 config 驱动的命令，例如

```json
"test_cmd": ["ctest", "--test-dir", "build", "-C", "Release"],
"test_baseline": 2
```

`test_cmd` 缺失时保持现在的 unittest 行为（其余仓库不受影响）。
本仓不改 `.trio/verify.py`：那是每个仓库各自 vendor 的框架副本，
改了只会让本仓与骨架仓分叉，下次 `trio.py install/update` 还会被覆盖。
