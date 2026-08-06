# -*- coding: utf-8 -*-
"""
ui_v2.main_window —— 主窗口框架（空壳）。

双窗口模型的主窗口侧：
  - 顶部功能栏：设备管理 / 模式▾ / 保存会话 / 打开会话 / 后处理 / 日志 / 帮助；
  - 中央 QStackedWidget：多相机工作区（模式 A）/ 单相机工作区（模式 B），
    两种模式工作区互不干扰、各自独立状态；
  - 底部状态栏：模式 | 设备在线 n/m | 当前步骤 | 最近误差/建议。

「设备管理」随时回到启动小窗（LauncherDialog）改模式/换设备，
确认后主窗口切换工作区（有未保存工作时先弹确认）。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDockWidget, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .launcher_dialog import LauncherDialog
from .theme import ACCENT, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY
from . import icons as ui_icons
from .widgets import LoadingOverlay, LogPanel
from .widgets.device_table import DeviceInfo
from .workspaces import MobileChainWorkspace, MultiCamWorkspace


class _PostProcessDialog(QDialog):
    """后处理参数面板（两模式共用）：裁切范围 / 下采样 / 离群点滤波。

    # TODO(BACKEND): 参数应用到 PointCloudProcessor
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("后处理参数")
        self.setModal(True)
        self.setMinimumWidth(320)

        lo = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self._crop_radius = QDoubleSpinBox()
        self._crop_radius.setRange(0, 100000)
        self._crop_radius.setSuffix(" mm")
        self._crop_radius.setSpecialValueText("不裁切")
        form.addRow("裁切半径:", self._crop_radius)

        self._voxel = QDoubleSpinBox()
        self._voxel.setRange(0, 100)
        self._voxel.setDecimals(2)
        self._voxel.setSuffix(" mm")
        self._voxel.setSpecialValueText("不下采样")
        form.addRow("下采样体素:", self._voxel)

        self._outlier_nb = QSpinBox()
        self._outlier_nb.setRange(0, 100)
        self._outlier_nb.setValue(20)
        self._outlier_nb.setSpecialValueText("关闭滤波")
        form.addRow("离群点邻域:", self._outlier_nb)

        lo.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        ok = QPushButton("应用")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        lo.addLayout(btn_row)

    def params(self) -> dict:
        return {
            "crop_radius_mm": self._crop_radius.value(),
            "voxel_mm": self._voxel.value(),
            "outlier_neighbors": self._outlier_nb.value(),
        }


class MainWindowShell(QMainWindow):
    """拼接主窗口（空壳）。

    信号（接口预留，全部由后端/主控连接）：
        device_manager_reopened(str, list)  从设备管理小窗确认新模式+设备
        save_session_requested()
        open_session_requested()
        postprocess_applied(dict)
    """

    device_manager_reopened = Signal(str, list)
    """设备管理小窗确认：(mode, List[DeviceInfo])。
    # TODO(BACKEND): 断开旧设备 → 连接新设备 → 切换工作区"""

    save_session_requested = Signal()
    """保存会话（scans/<mode>_session_时间戳/，沿用 OfflineSession 逻辑）。"""

    open_session_requested = Signal()
    """打开会话并恢复对应模式工作区状态。"""

    postprocess_applied = Signal(dict)
    """后处理参数应用。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RVC 拼接工作站")
        self.resize(1280, 800)

        self._mode = LauncherDialog.MODE_MULTI_CAM
        self._devices: List[DeviceInfo] = []
        self._dirty = False  # 有未保存的标定/会话数据

        self._setup_ui()

    # ------------------------------------------------------------ UI 搭建
    def _setup_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # ===== 顶部功能栏 =====
        root.addWidget(self._build_toolbar())

        # ===== 中央双工作区 =====
        self._stack = QStackedWidget()
        self._ws_multi = MultiCamWorkspace()
        self._ws_mobile = MobileChainWorkspace()
        self._stack.addWidget(self._ws_multi)
        self._stack.addWidget(self._ws_mobile)

        # 工作区日志统一汇入日志面板与状态栏
        self._ws_multi.log_message.connect(self.log)
        self._ws_mobile.log_message.connect(self.log)
        self._ws_mobile.chain_stats_changed.connect(self._on_chain_stats)

        root.addWidget(self._stack, 1)

        # ===== 底部状态栏 =====
        root.addWidget(self._build_statusbar())

        # ===== 日志停靠面板（右侧，默认隐藏，「日志」按钮 toggle） =====
        self._log_panel = LogPanel()
        self._log_panel.setMinimumWidth(320)
        self._log_dock = QDockWidget("日志", self)
        self._log_dock.setWidget(self._log_panel)
        self._log_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self._log_dock)
        self._log_dock.setMinimumWidth(340)
        self._log_dock.hide()

        # ===== 加载遮罩 =====
        self._overlay = LoadingOverlay(central)

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

        btn_post = QToolButton()
        btn_post.setText("后处理")
        btn_post.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(btn_post, "filter", TEXT_SECONDARY, 15)
        btn_post.clicked.connect(self._open_postprocess)
        lo.addWidget(btn_post)

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
        lo.setContentsMargins(10, 4, 10, 4)
        lo.setSpacing(14)

        self._st_mode = QLabel()
        self._st_mode.setStyleSheet(f"color: {ACCENT}; font-weight: 700;")
        lo.addWidget(self._st_mode)

        self._st_devices = QLabel("设备 —")
        self._st_devices.setStyleSheet(f"color: {TEXT_SECONDARY};")
        lo.addWidget(self._st_devices)

        self._st_step = QLabel("待机")
        self._st_step.setStyleSheet(f"color: {TEXT_SECONDARY};")
        lo.addWidget(self._st_step)

        lo.addStretch(1)

        self._st_hint = QLabel("")
        self._st_hint.setStyleSheet(f"color: {TEXT_MUTED};")
        lo.addWidget(self._st_hint)

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
        else:
            self._stack.setCurrentWidget(self._ws_mobile)
            self._ws_mobile.set_devices(devices)
            self._ws_mobile.set_state("connected" if devices else "idle")
            self._btn_mode.setText("模式：单相机移动拼接 ▾")

        self._refresh_statusbar()
        self.log(f"已进入「{LauncherDialog.MODE_NAMES[mode]}」工作区"
                 f"（{len(devices)} 台设备）", "success")

    def current_mode(self) -> str:
        return self._mode

    def workspace_multi(self) -> MultiCamWorkspace:
        return self._ws_multi

    def workspace_mobile(self) -> MobileChainWorkspace:
        return self._ws_mobile

    # ------------------------------------------------------------ 设备管理（回小窗）
    def open_device_manager(self):
        """重新打开启动小窗：回填当前模式与已连接设备。

        有未保存的标定/会话数据时先弹确认；取消则保持现状。
        """
        if self._dirty and not self._confirm_discard():
            return

        dialog = LauncherDialog(self)
        dialog.restore_state(self._mode, self._devices)

        # 小窗内操作转发给后端（接口预留）
        dialog.refresh_requested.connect(
            lambda: self.log("刷新设备列表（接口预留：SDK SystemListDevices）", "info"))
        dialog.auto_ip_requested.connect(
            lambda devs: self.log(f"自动设置 IP ×{len(devs)}（接口预留）", "info"))
        dialog.network_config_requested.connect(
            lambda: self.log("打开网络配置对话框（接口预留）", "info"))

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
            self.set_mode(connected["mode"], connected["devices"])
            self.device_manager_reopened.emit(
                connected["mode"], connected["devices"])

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
        self._st_mode.setText(f"模式：{mode_name}")
        online = sum(1 for d in self._devices if d.online)
        self._st_devices.setText(f"设备在线 {online}/{len(self._devices)}")
        ws = (self._ws_multi if self._mode == LauncherDialog.MODE_MULTI_CAM
              else self._ws_mobile)
        self._st_step.setText(f"当前状态：{ws.current_state()}")

    def _on_chain_stats(self, text: str):
        self._st_hint.setText(text)

    def _log_dock_toggle(self, checked: bool):
        self._log_dock.setVisible(checked)

    def _open_postprocess(self):
        dialog = _PostProcessDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.postprocess_applied.emit(dialog.params())
            self.log(f"后处理参数已应用（接口预留）：{dialog.params()}", "info")

    def _show_help(self):
        QMessageBox.information(
            self, "关于 RVC 拼接工作站",
            "RVC 拼接工作站（UI 空壳 v2）\n\n"
            "· 多相机外参标定：固定多相机 → 标定外参 → 撤板扫描拼接\n"
            "· 单相机移动拼接：边走边拍，自动检测标记物，链式增量拼接\n\n"
            "详细操作说明见 docs/ 设计文档。")

    def closeEvent(self, event):
        """主窗口关闭即退出程序；会话未保存时弹确认。"""
        if self._dirty:
            ret = QMessageBox.question(
                self, "退出确认",
                "会话尚未保存，确定退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_overlay") and self._overlay.isVisible():
            self._overlay.resize(self.centralWidget().size())
