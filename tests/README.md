# MCC 测试

项目级回归脚本统一存放在本目录，文件名沿用搬迁前的名称。原型和独立工具的测试由各自目录维护。

在项目根目录运行选定脚本，例如：

```powershell
$MccPython = 'D:/Program Files/Anaconda/envs/rvc/python.exe'
$env:QT_QPA_PLATFORM = 'offscreen'
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
& $MccPython tests/test_ui_architecture.py
& $MccPython -m unittest tests.test_frame_database tests.test_recognition_parameters
```

已有测试之间的 fixture 导入由 `_bootstrap.py` 支持。新增脚本在模块文档及 `__future__` 导入之后加入 `import _bootstrap`；项目文件通过 `_bootstrap.PROJECT_ROOT` 定位。运行时仍以项目根目录为工作目录，部分历史子进程命令使用相对路径。

按功能选择回归，查看脚本后再执行。部分历史脚本在导入时即运行断言或初始化 SDK，全目录收集会执行这些代码。离屏测试、真实设备、原生 GPU 与性能验证分别记录。新增测试的存放和数据写入约束见根目录 `AGENTS.md`。
