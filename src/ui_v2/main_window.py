# -*- coding: utf-8 -*-
"""
ui_v2.main_window —— 主窗口框架（空壳）。

双窗口模型的主窗口侧：
  - 顶部功能栏：设备管理 / 模式▾ / 保存会话 / 打开会话 / 参数调试 / 日志 / 帮助；
  - 中央 QStackedWidget：多相机工作区（模式 A）/ 单相机工作区（模式 B）/
    转台工作区（模式 C），各模式互不干扰、各自独立状态；
  - 底部状态栏：模式 | 设备在线 n/m | 当前步骤 | 最近误差/建议。

「设备管理」随时回到启动小窗（LauncherDialog）改模式/换设备，
确认后主窗口切换工作区（有未保存工作时先弹确认）。

注：后处理功能入口已移除，后续将单独增加后处理设置/预览页面。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from .launcher_dialog import LauncherDialog
from .theme import ACCENT, ACCENT_DIM, BG_CARD, BORDER, STATUS_OK, STATUS_WARN, TEXT_MUTED, TEXT_SECONDARY
from . import icons as ui_icons
from .widgets import FloatingLogPanel, LoadingOverlay
from .widgets.device_table import DeviceInfo
from .workspaces import MobileChainWorkspace, MultiCamWorkspace, TurntableWorkspace

if False:
    # 仅类型提示，避免循环导入
    from .backend_bridge import BackendBridge


class MainWindowShell(QMainWindow):
    """拼接主窗口（空壳）。

    信号（接口预留，全部由后端/主控连接）：
        device_manager_reopened(str, list)  从设备管理小窗确认新模式+设备
        save_session_requested()
        open_session_requested()
    """

    device_manager_reopened = Signal(str, list)
    """设备管理小窗确认：(mode, List[DeviceInfo])。
    # TODO(BACKEND): 断开旧设备 → 连接新设备 → 切换工作区"""

    save_session_requested = Signal()
    """保存会话（scans/<mode>_session_时间戳/，沿用 OfflineSession 逻辑）。"""

    session_save_finished = Signal(bool, str)
    """会话保存完成信号：(success, message)。"""

    open_session_requested = Signal()
    """打开会话并恢复对应模式工作区状态。"""

    param_debug_requested = Signal()
    """参数调试：断开当前相机并打开 RVC 官方调试工具 RVCManager。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RVC 拼接工作站")

        # 根据当前屏幕可用区域设置初始窗口大小，避免在小分辨率屏幕上显示不全
        from PySide6.QtGui import QCursor
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = min(1600, int(geo.width() * 0.9))
            h = min(1000, int(geo.height() * 0.9))
            self.resize(max(1280, w), max(800, h))
        else:
            self.resize(1280, 800)

        self._center_on_screen()

        self._mode = LauncherDialog.MODE_MULTI_CAM
        self._devices: List[DeviceInfo] = []
        self._dirty = False  # 有未保存的标定/会话数据
        self._backend_bridge: Optional['BackendBridge'] = None

        self._setup_ui()

    def _center_on_screen(self):
        """根据当前鼠标所在屏幕的可用区域把主窗口居中。"""
        from PySide6.QtGui import QCursor
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - self.width()) // 2,
                      geo.y() + (geo.height() - self.height()) // 2)

    # ------------------------------------------------------------ UI 搭建
    def _setup_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # ===== 顶部功能栏 =====
        self._toolbar = self._build_toolbar()
        root.addWidget(self._toolbar)

        # ===== 中央三工作区 =====
        self._stack = QStackedWidget()
        self._ws_multi = MultiCamWorkspace()
        self._ws_mobile = MobileChainWorkspace()
        self._ws_turntable = TurntableWorkspace()
        self._stack.addWidget(self._ws_multi)
        self._stack.addWidget(self._ws_mobile)
        self._stack.addWidget(self._ws_turntable)

        # 工作区日志统一汇入日志面板与状态栏
        self._ws_multi.log_message.connect(self.log)
        self._ws_mobile.log_message.connect(self.log)
        self._ws_turntable.log_message.connect(self.log)
        self._ws_mobile.chain_stats_changed.connect(self._on_chain_stats)
        self._ws_mobile.dirty_changed.connect(self.set_dirty)
        self._ws_turntable.dirty_changed.connect(self.set_dirty)

        root.addWidget(self._stack, 1)

        # ===== 底部状态栏 =====
        self._statusbar = self._build_statusbar()
        root.addWidget(self._statusbar)

        # ===== 浮动日志面板（叠加层，默认隐藏，「日志」按钮 toggle） =====
        self._log_panel = FloatingLogPanel(self)
        self._log_panel.closed.connect(self._on_log_panel_closed)
        self._log_panel.hide()

        # ===== 加载遮罩（覆盖整个主窗口，而非仅 central widget） =====
        self._overlay = LoadingOverlay(self)
        self._overlay.hide()

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background-color: #26272E; border-bottom: 1px solid #3A3D46;")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(4)

        self._btn_devices = QToolButton()
        self._btn_devices.setText("设备管理")
        self._btn_devices.setToolTip("重新选择模式与设备")
        self._btn_devices.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(self._btn_devices, "gear", TEXT_SECONDARY, 15)
        self._btn_devices.clicked.connect(self.open_device_manager)
        lo.addWidget(self._btn_devices)

        self._btn_mode = QToolButton()
        self._btn_mode.setText("模式：多相机外参标定 ▾")
        self._btn_mode.setToolTip("点击回到启动小窗切换模式")
        self._btn_mode.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(self._btn_mode, "swap", TEXT_SECONDARY, 15)
        self._btn_mode.clicked.connect(self.open_device_manager)
        lo.addWidget(self._btn_mode)

        sep1 = QLabel("｜")
        sep1.setStyleSheet(f"color: {TEXT_MUTED};")
        lo.addWidget(sep1)

        btn_save = QToolButton()
        btn_save.setText("保存会话")
        btn_save.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(btn_save, "save", TEXT_SECONDARY, 15)
        btn_save.clicked.connect(self.save_session_requested)
        lo.addWidget(btn_save)

        btn_open = QToolButton()
        btn_open.setText("打开会话")
        btn_open.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(btn_open, "folder_open", TEXT_SECONDARY, 15)
        btn_open.clicked.connect(self.open_session_requested)
        lo.addWidget(btn_open)

        btn_param_debug = QToolButton()
        btn_param_debug.setText("参数调试")
        btn_param_debug.setToolTip("断开当前相机并打开 RVCManager 官方调试工具")
        btn_param_debug.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(btn_param_debug, "sliders", TEXT_SECONDARY, 15)
        btn_param_debug.clicked.connect(self.open_param_debug)
        lo.addWidget(btn_param_debug)

        lo.addStretch(1)

        self._btn_log = QToolButton()
        self._btn_log.setText("日志")
        self._btn_log.setCheckable(True)
        self._btn_log.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(self._btn_log, "terminal", TEXT_SECONDARY, 15)
        self._btn_log.toggled.connect(self._log_dock_toggle)
        lo.addWidget(self._btn_log)

        btn_help = QToolButton()
        btn_help.setText("帮助")
        btn_help.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(btn_help, "help", TEXT_SECONDARY, 15)
        btn_help.clicked.connect(self._show_help)
        lo.addWidget(btn_help)

        return bar

    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background-color: #26272E; border-top: 1px solid #3A3D46;")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 5, 10, 5)
        lo.setSpacing(10)

        # ---- 左侧状态组：模式徽章 | 设备 | 状态点 ----
        left_group = QFrame()
        left_group.setStyleSheet(
            f"QFrame {{ background-color: {BG_CARD}; border: none;"
            f" border-radius: 6px; }}"
        )
        left_lo = QHBoxLayout(left_group)
        left_lo.setContentsMargins(8, 3, 8, 3)
        left_lo.setSpacing(8)

        self._st_mode = QLabel()
        self._st_mode.setStyleSheet(
            f"background-color: {ACCENT_DIM}; color: {ACCENT};"
            f" border: none; border-radius: 10px;"
            f" padding: 1px 8px; font-weight: 700;")
        left_lo.addWidget(self._st_mode)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {BORDER};")
        left_lo.addWidget(sep)

        self._st_devices = QLabel("设备 —")
        self._st_devices.setStyleSheet(f"color: {TEXT_SECONDARY};")
        left_lo.addWidget(self._st_devices)

        self._st_state_dot = QLabel("●")
        self._st_state_dot.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        left_lo.addWidget(self._st_state_dot)

        self._st_step = QLabel("待机")
        self._st_step.setStyleSheet(f"color: {TEXT_SECONDARY};")
        left_lo.addWidget(self._st_step)

        lo.addWidget(left_group)
        lo.addStretch(1)

        # ---- 右侧提示组：最近一条日志/操作建议 ----
        right_group = QFrame()
        right_group.setStyleSheet(
            f"QFrame {{ background-color: {BG_CARD}; border: none;"
            f" border-radius: 6px; }}"
        )
        right_lo = QHBoxLayout(right_group)
        right_lo.setContentsMargins(8, 3, 8, 3)

        self._st_hint = QLabel("")
        self._st_hint.setStyleSheet(f"color: {TEXT_MUTED};")
        right_lo.addWidget(self._st_hint)
        lo.addWidget(right_group, 1)

        self._refresh_statusbar()
        return bar

    # ------------------------------------------------------------ 模式与工作区
    def set_mode(self, mode: str, devices: List[DeviceInfo]):
        """进入指定模式工作区（启动小窗连接成功后调用）。"""
        self._mode = mode
        self._devices = list(devices)

        if mode == LauncherDialog.MODE_MULTI_CAM:
            self._stack.setCurrentWidget(self._ws_multi)
            self._ws_multi.set_devices(devices)
            self._ws_multi.set_state("connected" if devices else "idle")
            self._btn_mode.setText("模式：多相机外参标定 ▾")
        elif mode == LauncherDialog.MODE_MOBILE_CHAIN:
            self._stack.setCurrentWidget(self._ws_mobile)
            self._ws_mobile.set_devices(devices)
            self._ws_mobile.set_state("connected" if devices else "idle")
            self._btn_mode.setText("模式：单相机移动拼接 ▾")
        else:
            self._stack.setCurrentWidget(self._ws_turntable)
            if self._backend_bridge is not None:
                self._ws_turntable.set_camera_manager(
                    self._backend_bridge.camera_manager,
                    self._backend_bridge.marker_detector,
                )
            self._ws_turntable.set_devices(devices)
            self._ws_turntable.set_state("connected" if devices else "idle")
            self._btn_mode.setText("模式：转台 360° 拼接 ▾")

        self._refresh_statusbar()
        self.log(f"已进入「{LauncherDialog.MODE_NAMES[mode]}」工作区"
                 f"（{len(devices)} 台设备）", "success")

    def current_mode(self) -> str:
        return self._mode

    def workspace_multi(self) -> MultiCamWorkspace:
        return self._ws_multi

    def workspace_mobile(self) -> MobileChainWorkspace:
        return self._ws_mobile

    def workspace_turntable(self) -> TurntableWorkspace:
        return self._ws_turntable

    def set_backend_bridge(self, bridge: 'BackendBridge'):
        """设置后端桥接器引用（用于设备枚举等 core 操作）。"""
        self._backend_bridge = bridge

    # ------------------------------------------------------------ 参数调试（打开 RVCManager）
    def open_param_debug(self):
        """回到设备连接页面，断开当前相机，打开 RVC 官方调试工具 RVCManager。"""
        if self._dirty and not self._confirm_discard():
            return

        # 先让后端断开相机并启动官方调试工具
        self.param_debug_requested.emit()
        # 再打开设备管理小窗，方便用户调试完成后重新连接
        self.open_device_manager()

    # ------------------------------------------------------------ 设备管理（回小窗）
    def open_device_manager(self):
        """重新打开启动小窗：回填当前模式与已连接设备。

        有未保存的标定/会话数据时先弹确认；取消则保持现状。
        """
        if self._dirty and not self._confirm_discard():
            return

        dialog = LauncherDialog(self)

        # 如有 backend_bridge，先真实枚举设备，再恢复当前勾选状态
        if self._backend_bridge is not None:
            devices = self._backend_bridge.enumerate_devices()
            dialog.set_devices(devices)
        dialog.restore_state(self._mode, self._devices)

        # 小窗内操作转发给后端
        def _do_refresh():
            if self._backend_bridge is not None:
                dialog.set_devices(self._backend_bridge.enumerate_devices())
            else:
                self.log("刷新设备列表（backend_bridge 未设置）", "warn")

        def _do_auto_ip(devices: list):
            if self._backend_bridge is not None:
                dialog.set_auto_ip_busy(True)

                def on_finished(_results, _error):
                    if not dialog.isVisible():
                        return
                    dialog.set_auto_ip_busy(False)
                    dialog.set_devices(self._backend_bridge.enumerate_devices())

                self._backend_bridge.auto_configure_network(
                    devices, on_finished=on_finished)
            else:
                self.log("自动设置 IP（backend_bridge 未设置）", "warn")

        dialog.refresh_requested.connect(_do_refresh)
        dialog.auto_ip_requested.connect(_do_auto_ip)

        connected = {"mode": None, "devices": []}

        def _on_connect(mode: str, devices: list):
            # TODO(BACKEND): CameraManager 逐台连接并显示进度；
            # 部分失败 → 弹窗列出失败设备，可重试或仅用成功的进入
            connected["mode"] = mode
            connected["devices"] = devices
            dialog.accept()

        dialog.connect_requested.connect(_on_connect)

        if dialog.exec() == QDialog.Accepted and connected["mode"]:
            self._dirty = False
            # 与 backend 的 camera_id 分配顺序对齐：真实设备在前，测试设备在后
            ordered_devices = connected["devices"]
            if self._backend_bridge is not None:
                ordered_devices = self._backend_bridge.get_ordered_devices(
                    connected["devices"])

            prev_mode = self._mode
            prev_devices = list(self._devices)
            new_mode = connected["mode"]

            # 先切换到新模式的 UI 布局（不等待连接结果）
            self.set_mode(new_mode, ordered_devices)

            if self._backend_bridge is not None:
                self.show_loading("正在连接设备...")

                def _on_reconnect_finished(success: bool, message: str):
                    try:
                        self._backend_bridge.connection_finished.disconnect(
                            _on_reconnect_finished)
                    except RuntimeError:
                        pass
                    self.hide_loading()
                    if success:
                        self.log(message, "success")
                        return
                    # 连接失败：弹窗提示并回退到之前的模式
                    self.log(f"设备连接失败: {message}", "error")
                    suggestion = self._connection_failure_suggestion(message)
                    ret = QMessageBox.warning(
                        self, "设备连接失败",
                        f"{message}\n\n{suggestion}\n\n是否返回之前的模式？",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if ret == QMessageBox.Yes and prev_mode:
                        self.set_mode(prev_mode, prev_devices)
                        # 尝试恢复旧设备连接（如果有）
                        self._backend_bridge._on_device_manager_reopened(
                            prev_mode, prev_devices, show_loading=False)
                    # No 则停留在新模式，由用户在小窗或设备管理中重试

                self._backend_bridge.connection_finished.connect(
                    _on_reconnect_finished)
                self._backend_bridge._on_device_manager_reopened(
                    new_mode, ordered_devices, show_loading=False)
            else:
                self.device_manager_reopened.emit(
                    connected["mode"], ordered_devices)

    @staticmethod
    def _connection_failure_suggestion(message: str) -> str:
        """根据连接失败消息返回排查建议。"""
        msg = message or ""
        if "测试设备" in msg or "测试相机" in msg or "仅布局" in msg:
            return (
                "排查建议：\n"
                "  1. 测试相机仅用于 UI 布局预览，不能替代真实相机进入工作区；\n"
                "  2. 请检查真实 RVC 相机是否已上电、网线/USB 是否连接正常；\n"
                "  3. 点击「刷新」重新枚举设备后勾选真实相机。"
            )
        if "占用" in msg or "RVCManager" in msg:
            return (
                "排查建议：\n"
                "  1. 若刚使用过「参数调试」打开 RVCManager，请关闭 RVCManager 后再连接；\n"
                "  2. 检查任务管理器，结束其他占用相机的进程；\n"
                "  3. 重新点击「设备管理」进入小窗后再次连接。"
            )
        if "至少需要" in msg:
            return (
                "排查建议：\n"
                "  1. 多相机外参标定至少需要 2 台真实相机，转台至少需要 1 台；\n"
                "  2. 检查失败相机的连接状态，排除网线松动或 IP 冲突；\n"
                "  3. 尝试点击「自动设置 IP」修复网络配置。"
            )
        return (
            "排查建议：\n"
            "  1. 检查相机是否上电、网线/USB 是否连接正常；\n"
            "  2. 点击「自动设置 IP」修复 GigE 相机网络配置；\n"
            "  3. 关闭 RVCManager 等可能占用相机的软件后重试。"
        )

    def _confirm_discard(self) -> bool:
        """未保存数据确认框。

        # TODO(BACKEND): 由会话脏标记驱动（_dirty 目前为壳内占位）
        """
        ret = QMessageBox.question(
            self, "未保存的工作",
            "当前有未保存的标定/会话数据，切换模式或设备将丢失。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return ret == QMessageBox.Yes

    # ------------------------------------------------------------ 日志与状态
    def log(self, message: str, level: str = "info"):
        """统一日志入口（状态栏双通道提示）。

        # TODO(BACKEND): 对接 core.utils.logger
        """
        self._log_panel.append(message, level)
        self._st_hint.setText(message)

    def show_loading(self, text: str = "处理中..."):
        """耗时操作遮罩（拍摄/标定/拼接/自动设IP 统一入口）。"""
        self._overlay.show_message(text)

    def hide_loading(self):
        self._overlay.hide_overlay()

    def set_dirty(self, dirty: bool):
        """标记有未保存的标定/会话数据。"""
        self._dirty = dirty

    # ------------------------------------------------------------ 内部
    def _refresh_statusbar(self):
        mode_name = LauncherDialog.MODE_NAMES.get(self._mode, self._mode)
        self._st_mode.setText(mode_name)
        online = sum(1 for d in self._devices if d.online)
        total = len(self._devices)
        self._st_devices.setText(f"设备 {online}/{total} 在线")

        if self._mode == LauncherDialog.MODE_MULTI_CAM:
            ws = self._ws_multi
        elif self._mode == LauncherDialog.MODE_MOBILE_CHAIN:
            ws = self._ws_mobile
        else:
            ws = self._ws_turntable
        state = ws.current_state()
        self._st_step.setText(state)

        # 状态点颜色：在线/工作流推进为绿色，idle/异常为灰色/黄色
        if state in ("connected", "captured", "detected", "calibrated", "locked"):
            dot_color = STATUS_OK
        elif state == "idle":
            dot_color = TEXT_MUTED
        else:
            dot_color = STATUS_WARN
        self._st_state_dot.setStyleSheet(
            f"color: {dot_color}; font-size: 12px;")

    def _on_chain_stats(self, text: str):
        self._st_hint.setText(text)

    def _log_dock_toggle(self, checked: bool):
        if checked:
            self._position_log_panel()
            self._log_panel.show()
            self._log_panel.raise_()
        else:
            self._log_panel.hide()

    def _on_log_panel_closed(self):
        """用户点击日志面板关闭按钮：隐藏面板并取消顶部日志按钮勾选。"""
        self._btn_log.setChecked(False)
        self._log_panel.hide()

    def _position_log_panel(self):
        """把浮动日志面板定位到主窗口右侧偏下（不挤占顶部工具栏）。"""
        margin = 8
        panel_w = self._log_panel.width()
        panel_h = self._log_panel.height()
        x = self.width() - panel_w - margin
        # 避开顶部工具栏和底部状态栏
        toolbar_h = self._toolbar.height() if self._toolbar else 42
        status_h = self._statusbar.height() if self._statusbar else 28
        y = self.height() - panel_h - status_h - margin
        # 确保不超出窗口
        x = max(margin, x)
        y = max(toolbar_h + margin, y)
        self._log_panel.move(x, y)

    def _show_help(self):
        from version import get_version
        QMessageBox.information(
            self, "关于 RVC 拼接工作站",
            f"RVC 拼接工作站  {get_version()}\n\n"
            "【多相机外参标定】\n"
            "  1. 固定安装 2 台及以上 RVC 相机\n"
            "  2. 拍摄标定板/编码圆，检测标记物\n"
            "  3. 计算相机间外参（pair RMS、内点率）\n"
            "  4. 外参锁定后撤掉标定板，扫描并拼接点云\n\n"
            "【单相机移动拼接】\n"
            "  1. 连接 1 台 RVC 相机\n"
            "  2. 开始取景，移动相机到不同机位\n"
            "  3. 逐个拍摄机位，自动检测标记物并增量配准\n"
            "  4. 重合度不足时重拍，支持撤销/删除/全局优化\n\n"
            "提示：无真实多机环境时，可在启动小窗点击『+ 测试设备』临时添加虚拟相机。")

    def closeEvent(self, event):
        """主窗口关闭即退出程序；有未保存数据时提示保存并等待完成。"""
        if self._dirty:
            ret = QMessageBox.warning(
                self, "会话未保存",
                "当前会话包含未保存的拍摄数据，是否保存？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save)
            if ret == QMessageBox.Cancel:
                event.ignore()
                return
            if ret == QMessageBox.Save:
                self.save_session_requested.emit()
                # 同步等待保存完成，避免异步保存被主线程退出中断导致文件半写
                self._wait_for_session_save(event)
                return
        event.accept()

    def _wait_for_session_save(self, event):
        """用局部事件循环等待会话保存完成，再 accept/ignore 关闭事件。"""
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop(self)
        finished = {"ok": False, "msg": ""}

        def _on_finished(ok: bool, msg: str):
            finished["ok"] = ok
            finished["msg"] = msg
            loop.quit()

        self.session_save_finished.connect(_on_finished)

        # 超时保险：30 秒后强制退出等待
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(30000)

        loop.exec()

        timer.stop()
        self.session_save_finished.disconnect(_on_finished)

        if finished["ok"]:
            self.log(f"关闭前已保存: {finished['msg']}", "success")
            event.accept()
        else:
            # 保存失败/超时，询问是否仍要关闭
            ret = QMessageBox.warning(
                self, "保存未完成",
                f"会话保存可能未完成：{finished['msg']}\n是否仍要关闭程序？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)
            if ret == QMessageBox.Yes:
                event.accept()
            else:
                event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_overlay") and self._overlay.isVisible():
            self._overlay.setGeometry(0, 0, self.width(), self.height())
        if hasattr(self, "_log_panel") and self._log_panel.isVisible():
            self._position_log_panel()
