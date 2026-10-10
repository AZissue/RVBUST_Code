# -*- coding: utf-8 -*-
"""
独立宿主（批 4.5 创建 / M2a-1 一次性 UI 复刻）—— 原型独立运行时的 QMainWindow 壳。

为什么单独一个文件：合入形态下这个壳由主程序提供 ——
  启动小窗（LauncherDialog）选功能 → MainWindowShell（顶栏 / 状态栏 / QStackedWidget）
  → 第 4 张卡片对应的 `RobotWorkspace`。
原型阶段先用这个最小壳把**同一套接口**拉起来，避免"验证的形态 ≠ 最终形态"
（QMainWindow 嵌 QMainWindow 是合入时的第一类返工）。

M2a-1（设计语言复刻，文档：docs/原型UI一次性复刻方案与截图验收标准_20260923.md §5）：
  - 应用主程序 `GLOBAL_QSS`：token 唯一来源 `ui_v2.theme`，本目录**禁硬编码色值**（U2/S5）；
  - 顶栏照 `src/ui_v2/main_window.py:149-207`（模式徽章 + QToolButton 组 + 右侧日志开关）；
  - 状态栏照 `main_window.py:209-266`（模式 / 设备 / 状态点 / 步骤 ｜ 最近一条日志）；
  - 日志面板用 `ui_v2.widgets.floating_log_panel.FloatingLogPanel`（叠加层，不再是裸
    `QPlainTextEdit`）+ 定位适配（照 `main_window.py:547 _position_log_panel`）。

盘上边界（@lead §5 范围【假设】）：顶栏只放原型有的功能（帮助 / 日志）。主程序的
"设备管理 / 保存会话 / 打开会话 / 参数调试" 依赖后端与 Launcher，原型无对应数据 →
本轮不做；这些动作在原型里已由左控制面板承担。

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

from PySide6.QtCore import Qt                            # noqa: E402
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout,  # noqa: E402
                               QLabel, QMainWindow, QMessageBox,
                               QToolButton, QVBoxLayout, QWidget)

from window import RobotWorkspace        # noqa: E402  同目录（路径引导在 window 内）

# ---- 设计语言唯一来源：ui_v2.theme（window 已把仓库 src 挂进 sys.path）----
from ui_v2 import icons as ui_icons      # noqa: E402
from ui_v2.theme import (ACCENT, ACCENT_DIM, BG_CARD, BG_PANEL,  # noqa: E402
                         BORDER, GLOBAL_QSS, RADIUS, SPACE, STATUS_OK,
                         STATUS_WARN, TEXT_MUTED, TEXT_PRIMARY,
                         TEXT_SECONDARY)
from ui_v2.widgets.floating_log_panel import FloatingLogPanel  # noqa: E402

# 工作区 A3 状态 → 状态栏状态点颜色（合入形态下由 BackendBridge 推 set_state）
_STATE_DOT = {"idle": TEXT_MUTED, "matrix_loaded": STATUS_WARN,
              "verified": STATUS_OK}
_STATE_TEXT = {"idle": "待机", "matrix_loaded": "矩阵已加载 · 未 VERIFIED",
               "verified": "已 VERIFIED"}


class RobotHandEyeHost(QMainWindow):
    """宿主壳：顶栏 + 工作区 + 状态栏（+ 浮动日志叠加层）+ 注入后台 runner。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手眼变换原型（批 4.5：合入形态工作区 + 独立宿主）")
        self.resize(1400, 850)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toolbar = self._build_toolbar()
        outer.addWidget(self._toolbar)

        self.workspace = RobotWorkspace()
        outer.addWidget(self.workspace, 1)

        self._statusbar = self._build_statusbar()
        outer.addWidget(self._statusbar)

        # 浮动日志面板：叠加层（不挤占中央工作区），「日志」按钮 toggle
        self._log_panel = FloatingLogPanel(self)
        self._log_panel.closed.connect(self._on_log_panel_closed)
        self._log_panel.hide()

        self.workspace.log_message.connect(self._on_workspace_log)
        self.workspace.set_background_runner(self._run_background)
        self._refresh_statusbar()

    # ------------------------------------------------------------------ 顶栏
    def _build_toolbar(self) -> QWidget:
        """顶栏（照 main_window.py:149-207 口径：模式徽章 ｜ QToolButton 组）。"""
        bar = QWidget()
        bar.setObjectName("hostToolbar")
        bar.setStyleSheet(
            f"QWidget#hostToolbar {{ background-color: {BG_PANEL}; "
            f"border-bottom: 1px solid {BORDER}; }}")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(4)

        badge = QLabel("手眼变换")
        badge.setStyleSheet(
            f"background-color: {ACCENT_DIM}; color: {ACCENT}; border: none; "
            f"border-radius: 10px; padding: 1px 8px; font-weight: 700;")
        lo.addWidget(badge)

        sep = QLabel("｜")
        sep.setStyleSheet(f"color: {TEXT_MUTED};")
        lo.addWidget(sep)

        btn_help = QToolButton()
        btn_help.setText("帮助")
        btn_help.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(btn_help, "help", TEXT_SECONDARY, 15)
        btn_help.clicked.connect(self._show_help)
        lo.addWidget(btn_help)

        lo.addStretch(1)

        self._btn_log = QToolButton()
        self._btn_log.setText("日志")
        self._btn_log.setCheckable(True)
        self._btn_log.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(self._btn_log, "terminal", TEXT_SECONDARY, 15)
        self._btn_log.toggled.connect(self._log_dock_toggle)
        lo.addWidget(self._btn_log)

        return bar

    # ---------------------------------------------------------------- 状态栏
    def _build_statusbar(self) -> QWidget:
        """状态栏（照 main_window.py:209-266 口径）。"""
        bar = QWidget()
        bar.setObjectName("hostStatusbar")
        bar.setStyleSheet(
            f"QWidget#hostStatusbar {{ background-color: {BG_PANEL}; "
            f"border-top: 1px solid {BORDER}; }}")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 5, 10, 5)
        lo.setSpacing(10)

        left = QFrame()
        left.setStyleSheet(
            f"QFrame {{ background-color: {BG_CARD}; border: none; "
            f"border-radius: {RADIUS}; }}")
        left_lo = QHBoxLayout(left)
        left_lo.setContentsMargins(8, 3, 8, 3)
        left_lo.setSpacing(8)

        self._st_mode = QLabel("手眼变换")
        self._st_mode.setStyleSheet(
            f"background-color: {ACCENT_DIM}; color: {ACCENT}; border: none; "
            f"border-radius: 10px; padding: 1px 8px; font-weight: 700;")
        left_lo.addWidget(self._st_mode)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {BORDER};")
        left_lo.addWidget(sep)

        self._st_devices = QLabel("设备 —")
        self._st_devices.setStyleSheet(f"color: {TEXT_SECONDARY};")
        left_lo.addWidget(self._st_devices)

        self._st_state_dot = QLabel("●")
        self._st_state_dot.setStyleSheet(
            f"color: {_STATE_DOT['idle']}; font-size: 12px;")
        left_lo.addWidget(self._st_state_dot)

        self._st_step = QLabel(_STATE_TEXT["idle"])
        self._st_step.setStyleSheet(f"color: {TEXT_SECONDARY};")
        left_lo.addWidget(self._st_step)

        lo.addWidget(left)
        lo.addStretch(1)

        right = QFrame()
        right.setStyleSheet(
            f"QFrame {{ background-color: {BG_CARD}; border: none; "
            f"border-radius: {RADIUS}; }}")
        right_lo = QHBoxLayout(right)
        right_lo.setContentsMargins(8, 3, 8, 3)

        self._st_hint = QLabel("")
        self._st_hint.setStyleSheet(f"color: {TEXT_MUTED};")
        right_lo.addWidget(self._st_hint)
        lo.addWidget(right, 1)

        return bar

    def _refresh_statusbar(self):
        """状态点/步骤取自工作区合入形态状态（`current_state()`）。"""
        state = self.workspace.current_state()
        self._st_state_dot.setStyleSheet(
            f"color: {_STATE_DOT.get(state, TEXT_MUTED)}; font-size: 12px;")
        self._st_step.setText(_STATE_TEXT.get(state, state))

    # ------------------------------------------------------------------ 日志
    def set_log_visible(self, visible: bool):
        """显示/隐藏浮动日志面板（截图脚本与外部调用用；等价于点「日志」）。"""
        self._btn_log.setChecked(bool(visible))

    def _log_dock_toggle(self, checked: bool):
        if checked:
            self._position_log_panel()
            self._log_panel.show()
            self._log_panel.raise_()
        else:
            self._log_panel.hide()

    def _on_log_panel_closed(self):
        """用户点面板关闭按钮：隐藏面板并取消顶栏「日志」勾选。"""
        self._btn_log.setChecked(False)
        self._log_panel.hide()

    def _position_log_panel(self):
        """把浮动日志面板定位到窗口右侧偏下（避开顶栏与状态栏），照 main_window.py:547。"""
        margin = SPACE
        panel_w = self._log_panel.width()
        panel_h = self._log_panel.height()
        x = self.width() - panel_w - margin
        toolbar_h = self._toolbar.height() if self._toolbar else 42
        status_h = self._statusbar.height() if self._statusbar else 28
        y = self.height() - panel_h - status_h - margin
        x = max(margin, x)
        y = max(toolbar_h + margin, y)
        self._log_panel.move(x, y)

    def _on_workspace_log(self, text: str, level: str = "info"):
        self._log_panel.append(str(text), level)
        self._st_hint.setText(str(text))
        self._sync_workspace_state()

    def _sync_workspace_state(self):
        """A3 状态 → 合入形态 `set_state`（合入后由 BackendBridge 推，原型侧由工作区推导）。

        不这么做状态栏状态点会一直停在 idle（工作区自身只刷新面板上的状态标签）。
        """
        ws = self.workspace
        if ws.handeye is None:
            state = "idle"
        elif getattr(ws.handeye, "validated", False):
            state = "verified"
        else:
            state = "matrix_loaded"
        if state != ws.current_state():
            ws.set_state(state)
        self._refresh_statusbar()

    # ------------------------------------------------------------------ 帮助
    def _show_help(self):
        QMessageBox.information(
            self, "手眼变换原型 · 使用说明",
            "1) 填 handeye.json 路径（或手填 16 个数）→ 选单位与安装方式 → 加载\n"
            "2) 录入位姿（手动 / Mock 序列 / CSV 回放）\n"
            "3) 「拍一帧 → 变到基座系」\n"
            "4) ≥3 个离面姿态戳点 → 运行戳点门禁 → VERIFIED 后才允许导出\n\n"
            "判别下限 ≈ 1.0 mm：显示正常不等于精度保证（A9）。")

    # ------------------------------------------------------------------ 注入
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

    # ------------------------------------------------------------------ 事件
    def resizeEvent(self, event):
        """窗口尺寸变化时重定位浮动日志面板（V7/S7：900×600 也不许跑出窗外）。"""
        super().resizeEvent(event)
        if getattr(self, "_log_panel", None) is not None and self._log_panel.isVisible():
            self._position_log_panel()


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    frames = 0
    if "--smoke" in argv:
        i = argv.index("--smoke")
        frames = int(argv[i + 1]) if len(argv) > i + 1 and argv[i + 1].isdigit() else 3
    app = QApplication.instance() or QApplication(argv[:1])
    app.setStyleSheet(GLOBAL_QSS)       # M2a-1：设计语言唯一来源（U7）
    host = RobotHandEyeHost()
    host.show()
    if frames > 0:
        return host.workspace.run_smoke(frames)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
