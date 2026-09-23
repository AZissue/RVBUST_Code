# -*- coding: utf-8 -*-
"""
独立宿主（批 4.5）—— 原型独立运行时的最小 QMainWindow 壳。

为什么单独一个文件：合入形态下这个壳由主程序提供 ——
  启动小窗（LauncherDialog）选功能 → MainWindowShell（顶栏 / 状态栏 / QStackedWidget）
  → 第 4 张卡片对应的 `RobotWorkspace`。
原型阶段先用这个最小壳把**同一套接口**拉起来，避免"验证的形态 ≠ 最终形态"
（QMainWindow 嵌 QMainWindow 是合入时的第一类返工）。

接口对齐（实读 src/ui_v2/main_window.py:124-132 + backend_bridge.py:1966）：
  - 工作区日志：`workspace.log_message(str, str)` → 本宿主日志面板
  - 工作区状态：`workspace.set_state(...)` / `workspace.set_devices(...)`
  - 后台任务：`workspace.set_background_runner(self._run_background)`，
    签名 `_run_background(work, on_done, must_finish=False, name=None)`，
    回调口径 `on_done(result, error)` —— 与 BackendBridge 完全一致。

⚠️ 本宿主的 runner 是**同步桩（stub）**：原型独立运行不应出现第二个后台池
（1.0.10「全工程只留一个后台池」）。合入后由 BackendBridge 的真实 runner 替换，
工作区侧零改动（只换注入的是谁）。

直接跑（无相机也可）：
  python app/main.py                 # 交互
  python app/main.py --smoke 3       # 无人值守：自动跑 3 帧，退出码 0/1（offscreen 亦可）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import (QApplication, QMainWindow,  # noqa: E402
                               QPlainTextEdit, QVBoxLayout, QWidget)

from window import RobotWorkspace        # noqa: E402  同目录（路径引导在 window 内）


class RobotHandEyeHost(QMainWindow):
    """最小宿主壳：工作区 + 日志面板 + 注入后台 runner。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手眼变换原型（批 4.5：合入形态工作区 + 独立宿主）")
        self.resize(1400, 850)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        self.workspace = RobotWorkspace()
        outer.addWidget(self.workspace, 1)

        # 日志面板：合入后由 MainWindowShell 的 FloatingLogPanel 承担，
        # 这里只是让原型独立跑时日志可见（工作区本身不含日志控件）。
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        outer.addWidget(self.log_box)

        self.workspace.log_message.connect(self._on_workspace_log)
        self.workspace.set_background_runner(self._run_background)

    def _on_workspace_log(self, text: str, level: str = "info"):
        self.log_box.appendPlainText(f"[{level}] {text}" if level != "info" else str(text))

    def _run_background(self, work, on_done, must_finish=False, name=None):
        """后台执行桩：与 BackendBridge._run_background 同签名。

        同步执行（原型独立宿主不建第二后台池）；`must_finish` / `name` 仅是为
        签名对齐而接收，原型独立运行时无资源清理语义（合入后由 bridge 真实实现）。
        """
        try:
            result = work()
        except Exception as e:      # noqa: BLE001  与 bridge 同口径：异常走 error 回调
            on_done(None, e)
            return
        on_done(result, None)


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    frames = 0
    if "--smoke" in argv:
        i = argv.index("--smoke")
        frames = int(argv[i + 1]) if len(argv) > i + 1 and argv[i + 1].isdigit() else 3
    app = QApplication.instance() or QApplication(argv[:1])
    host = RobotHandEyeHost()
    host.show()
    if frames > 0:
        return host.workspace.run_smoke(frames)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
