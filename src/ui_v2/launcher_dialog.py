# -*- coding: utf-8 -*-
"""Production function entrance: industrial gray/red design and existing device ports.

The launcher emits device operations to BackendBridge; it never initializes the SDK.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QPropertyAnimation, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QGroupBox, QScrollArea, QWidget,
)

from .theme import (
    ACCENT, LAUNCHER_QSS, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY,
)
from . import icons as ui_icons
from .widgets import DeviceInfo, DeviceTable, ModeCard
from ui_common.log_summary import LogSummary
from ui_common.loading import LoadingOverlay
from core.utils import logger


class LauncherDialog(QDialog):
    """启动小窗：模式选择 + 设备管理 + 连接分流。"""

    MODE_MULTI_CAM = "multi_cam"        # 模式 A：多相机外参标定
    MODE_MOBILE_CHAIN = "mobile_chain"  # 模式 B：单相机移动拼接
    MODE_TURNTABLE = "turntable"        # 模式 C：转台 360° 拼接
    MODE_ROBOT = "robot_stitch"         # 模式 D：机器人手眼拼接（仅新版）

    MODE_NAMES = {
        MODE_MULTI_CAM: "多相机外参标定",
        MODE_MOBILE_CHAIN: "单相机移动拼接",
        MODE_TURNTABLE: "转台 360° 拼接",
        MODE_ROBOT: "机器人手眼拼接",
    }

    # ---------------------------------------------------------------- 信号（接口预留）
    refresh_requested = Signal()
    """刷新设备列表。# TODO(BACKEND): 接 SDK SystemListDevices 枚举"""

    auto_ip_requested = Signal(list)
    """自动设置 IP（参数为勾选设备）。"""

    connect_requested = Signal(str, list)
    """连接设备：(mode, List[DeviceInfo])。全部成功后由调用方 accept() 本对话框。"""

    offline_requested = Signal(str)
    """使用项目自带数据进入新版工作区，不连接相机。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MCC · 选择功能")
        self.setStyleSheet(LAUNCHER_QSS)
        self.setModal(True)
        self.resize(1060, 620)
        self.setMinimumSize(960, 580)
        self._busy = False
        self._auto_ip_busy = False
        self._connecting = False

        self._mode = self.MODE_MULTI_CAM
        self._presentation = 'classic'
        self._setup_ui()
        self.log_summary.attach_logger(logger)
        self.finished.connect(lambda *_: self.log_summary.detach_loggers())
        self._refresh_connect_state()
        self._center_on_screen()

    # ------------------------------------------------------------ UI 搭建
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(8)
        root.addWidget(QLabel("MCC / 重建工作站", objectName="launcherBrand"))
        root.addWidget(QLabel("选择工作方案 → 连接相机 → 进入工作区",
                             objectName="launcherSubtitle"))
        main = QHBoxLayout()
        main.setSpacing(16)

        scroll = QScrollArea()
        self._entry_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._mode_choices = QWidget()
        left = QVBoxLayout(self._mode_choices)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        left.addWidget(QLabel('现有工作区', objectName='launcherHint'))
        self.card_multi = ModeCard(
            "camera_multi", "多相机外参标定",
            "多台相机固定安装，设置参考相机，标定外参后进行固定工位拼接。")
        self.card_mobile = ModeCard(
            "chain", "单相机移动链式拼接",
            "一台相机移动拍摄，检测编码圆，逐帧配准并累积点云。")
        self.card_turntable = ModeCard(
            "loop", "转台拼接",
            "先完成 frame0 / frame1 转台标定，再按固定角度旋转、采集与拼接。")
        self._cards = {
            self.MODE_MULTI_CAM: self.card_multi,
            self.MODE_MOBILE_CHAIN: self.card_mobile,
            self.MODE_TURNTABLE: self.card_turntable,
        }
        for mode, card in self._cards.items():
            card.setFixedHeight(100)
            card.clicked.connect(lambda key=mode: self._set_mode(key))
            left.addWidget(card)
        left.addWidget(QLabel('新版工作区 · 试用', objectName='launcherHint'))
        self._industrial_cards = {}
        for mode, title, description, icon in (
            (self.MODE_MULTI_CAM, '多相机外参标定 · 新版', '多路相机画面与3D视图；沿用正式标定、质量门禁及扫描流程。', 'camera_multi'),
            (self.MODE_MOBILE_CHAIN, '单相机移动链式拼接 · 新版', '大型3D视图、右上角2D、左侧机位及底部日志；真实采集接线。', 'chain'),
            (self.MODE_TURNTABLE, '转台拼接 · 新版', '左侧标定及步进采集，右上角2D；沿用正式转台会话与保存。', 'loop'),
            (self.MODE_ROBOT, '机器人手眼拼接 · 新版', '手眼矩阵与机器人绝对位姿驱动点云转基座系；支持手动和CSV位姿。', 'calibrate'),
        ):
            card = ModeCard(icon, title, description)
            card.setFixedHeight(100)
            card.clicked.connect(lambda key=mode: self._set_mode(key, 'industrial'))
            self._industrial_cards[mode] = card
            left.addWidget(card)
        left.addStretch(1)
        scroll.setWidget(self._mode_choices)
        main.addWidget(scroll, 3)

        self._device_panel = QGroupBox("连接设备")
        right = QVBoxLayout(self._device_panel)
        right.setContentsMargins(12, 16, 12, 12)
        right.setSpacing(8)
        self._mode_title = QLabel(objectName="launcherModeTitle")
        right.addWidget(self._mode_title)
        self._mode_desc = QLabel(objectName="launcherHint")
        self._mode_desc.setWordWrap(True)
        self._mode_desc.setMinimumHeight(40)
        right.addWidget(self._mode_desc)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索型号 / 序列号 / IP")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.addAction(ui_icons.icon("search", TEXT_SECONDARY, 15),
                                    QLineEdit.LeadingPosition)
        self._search_edit.textChanged.connect(self._on_filter)
        search_row.addWidget(self._search_edit, 1)
        self._btn_refresh = QPushButton("刷新设备")
        self._btn_refresh.setToolTip("重新搜索 USB 与网口相机")
        ui_icons.apply(self._btn_refresh, "refresh", TEXT_SECONDARY, 15)
        self._btn_refresh.clicked.connect(self.refresh_requested)
        search_row.addWidget(self._btn_refresh)
        right.addLayout(search_row)

        self._table = DeviceTable()
        self._table.checked_changed.connect(self._on_checked_changed)
        right.addWidget(self._table, 1)
        net_row = QHBoxLayout()
        self._btn_auto_ip = QPushButton("自动设置 IP")
        self._btn_auto_ip.setToolTip("为选中的网口相机配置网络；未选中时处理所有网口相机")
        ui_icons.apply(self._btn_auto_ip, "bolt", TEXT_SECONDARY, 15)
        self._btn_auto_ip.clicked.connect(self._on_auto_ip)
        net_row.addWidget(self._btn_auto_ip)
        net_row.addStretch(1)
        self._btn_add_test = QPushButton("添加测试设备")
        self._btn_add_test.setToolTip("仅供界面调试：添加 TEST-A～TEST-D，不代表已连接真实相机")
        self._btn_add_test.clicked.connect(self._on_add_test_devices)
        net_row.addWidget(self._btn_add_test)
        right.addLayout(net_row)
        self._device_hint = QLabel("正在等待设备列表…", objectName="launcherHint")
        self._device_hint.setWordWrap(True)
        right.addWidget(self._device_hint)
        self._rule_hint = QLabel(objectName="launcherHint")
        self._rule_hint.setWordWrap(True)
        self._rule_hint.setMinimumHeight(36)
        right.addWidget(self._rule_hint)
        main.addWidget(self._device_panel, 4)
        root.addLayout(main, 1)

        bottom = QHBoxLayout()
        self._selection_label = QLabel("未选择设备")
        bottom.addWidget(self._selection_label, 1)
        self._btn_offline = QPushButton("离线预览 · 凳子数据")
        self._btn_offline.setToolTip("无需相机，自动加载项目内的第 1、2 帧原始图像和点云")
        self._btn_offline.clicked.connect(self._on_offline)
        bottom.addWidget(self._btn_offline)
        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setMinimumWidth(80)
        self._btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self._btn_cancel)
        self._btn_connect = QPushButton("连接并进入")
        self._btn_connect.setObjectName("primary")
        self._btn_connect.setMinimumWidth(120)
        ui_icons.apply(self._btn_connect, "arrow_right", "#FFFFFF", 16)
        self._btn_connect.clicked.connect(self._on_connect)
        bottom.addWidget(self._btn_connect)
        root.addLayout(bottom)
        self.log_summary = LogSummary(self)
        root.addWidget(self.log_summary)
        self._set_mode(self._mode)
        self._connection_overlay = self._build_connection_overlay()
        self._fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self._fade_animation.setDuration(200)
        self._fade_animation.finished.connect(self.accept)

    def _build_connection_overlay(self) -> LoadingOverlay:
        return LoadingOverlay(self, block_input=True)

    def show_connection_overlay(self, text: str = "正在连接相机..."):
        """显示全屏连接遮罩。"""
        self._connecting = True
        self._update_busy_controls()
        self._connection_overlay.show_message(text)

    def hide_connection_overlay(self):
        """隐藏连接遮罩。"""
        self._connection_overlay.hide_overlay()
        self._connecting = False
        self._update_busy_controls()

    def fade_out_and_accept(self):
        """小窗淡出后关闭，实现与主窗口的平滑过渡。

        注意：不要提前隐藏连接遮罩，否则遮罩瞬间消失后小窗内容会闪一下；
        直接对整个窗口做 opacity 动画，遮罩会随窗口一起淡出。
        """
        self._fade_animation.setStartValue(1.0)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_connection_overlay"):
            self._connection_overlay.setGeometry(self.rect())

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - self.width()) // 2,
                      geo.y() + (geo.height() - self.height()) // 2)

    # ------------------------------------------------------------ 模式联动
    def _set_mode(self, mode: str, presentation='classic'):
        """切换模式：更新卡片态 / 说明 / 数量提示，并清空设备多选。"""
        if self._is_busy() or mode not in self.MODE_NAMES or presentation not in ('classic', 'industrial'):
            return
        self._mode = mode
        self._presentation = presentation
        self._mode_title.setText(self.MODE_NAMES[mode] + (' · 新版' if presentation == 'industrial' else ''))
        for key, card in self._cards.items():
            card.setChecked(key == mode and presentation == 'classic')
        for key, card in self._industrial_cards.items():
            card.setChecked(key == mode and presentation == 'industrial')
        selected_card = (self._industrial_cards if presentation == 'industrial' else self._cards)[mode]
        QTimer.singleShot(0, lambda: self._entry_scroll.ensureWidgetVisible(selected_card, 0, 8))

        if mode == self.MODE_MULTI_CAM:
            self._mode_desc.setText(
                "多台相机固定安装，先标定外参（一次性），撤掉标定板后"
                "反复扫描拼接。适合固定工位、产线巡检。")
        elif mode == self.MODE_MOBILE_CHAIN:
            self._mode_desc.setText(
                "一台相机边走边拍，每帧自动检测标记物、自动配准增量拼接。"
                "适合现场扫描、大件测量。")
        elif mode == self.MODE_TURNTABLE:
            self._mode_desc.setText(
                "相机固定对准转台，转台上放置物体/标记物；拍摄两帧标定转台角度后，"
                "按固定角度手动旋转并采集，最终拼接成 360° 完整点云。")
        else:
            self._mode_desc.setText(
                "加载手眼矩阵，录入机器人绝对位姿，将多帧相机点云转到基座系。"
                "通过戳点验证后导出合并结果。")

        # 不同模式设备要求不同，清空多选防止残留选择误导
        self._table.clear_checks()
        self._refresh_connect_state()

    def _refresh_connect_state(self):
        """模式-设备数量规则：连接按钮启用条件 + 底部提示。"""
        n = len(self._table.checked_devices())
        if self._mode == self.MODE_MULTI_CAM:
            self._rule_hint.setText("选择至少 2 台相机；每台连接相机对应一个独立 2D 窗口。")
            ok = n >= 2
            if n == 0:
                hint, color = "未选择设备", TEXT_MUTED
            elif n < 2:
                hint, color = f"已选 {n} 台 / 多相机模式至少需要 2 台", ACCENT
            else:
                hint, color = f"已选 {n} 台 · 待连接", STATUS_OK
        elif self._mode in (self.MODE_MOBILE_CHAIN, self.MODE_ROBOT):
            label = self.MODE_NAMES[self._mode]
            self._rule_hint.setText(f"选择 1 台相机；{label}使用单相机采集。")
            ok = n == 1
            if n == 0:
                hint, color = "未选择设备", TEXT_MUTED
            elif n > 1:
                hint, color = (
                    f"已选 {n} 台 / {label}仅支持 1 台相机，"
                    "请取消多余选择"), ACCENT
            else:
                hint, color = "已选 1 台 · 待连接", STATUS_OK
        else:
            self._rule_hint.setText("选择 1 台相机；进入工作区后显示一个 2D 窗口及转台标定功能。")
            ok = n == 1
            if n == 0:
                hint, color = "未选择设备", TEXT_MUTED
            elif n > 1:
                hint, color = (
                    f"已选 {n} 台 / 转台模式仅支持 1 台相机，"
                    "请取消多余选择"), ACCENT
            else:
                hint, color = "已选 1 台 · 待连接", STATUS_OK

        self._selection_label.setText(hint)
        self._selection_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._btn_connect.setEnabled(ok and not self._is_busy())
        self._btn_offline.setVisible(self._presentation == 'industrial')
        self._btn_offline.setEnabled(not self._is_busy())

    # ------------------------------------------------------------ 事件
    def _on_offline(self):
        if self._presentation == 'industrial' and not self._is_busy():
            self.offline_requested.emit(self._mode)

    def _on_filter(self, text: str):
        self._table.apply_filter(text)

    def _on_add_test_devices(self):
        """临时：向设备表追加四台测试相机，方便查看多机布局效果。"""
        existing = self._table.devices()
        test_devices = [
            DeviceInfo(model="TEST-A", status="idle", status_detail="测试设备，不查询SDK", serial="SN_TEST_A", online=True),
            DeviceInfo(model="TEST-B", status="idle", status_detail="测试设备，不查询SDK", serial="SN_TEST_B", online=True),
            DeviceInfo(model="TEST-C", status="idle", status_detail="测试设备，不查询SDK", serial="SN_TEST_C", online=True),
            DeviceInfo(model="TEST-D", status="idle", status_detail="测试设备，不查询SDK", serial="SN_TEST_D", online=True),
        ]
        # 避免重复添加
        existing_serials = {d.serial for d in existing}
        for d in test_devices:
            if d.serial not in existing_serials:
                existing.append(d)
        self.set_devices(existing)

    def _on_checked_changed(self, _checked: list):
        self._refresh_connect_state()

    def _on_auto_ip(self):
        """自动设置 IP：对勾选设备执行（未勾选时提示）。

        # TODO(BACKEND): 接自动网络配置逻辑；执行中由主窗口显示加载遮罩
        """
        selected = self._table.checked_devices()
        candidates = selected or self._table.devices()
        if candidates and not any(isinstance(d.backend_ref, int) for d in candidates):
            logger.warning('测试设备不支持自动配置 IP；请接入真实 GigE 相机并刷新设备列表。')
            return
        self.auto_ip_requested.emit(selected)

    def report_auto_ip_result(self, results, error=None):
        """Render completion after enumeration so failures remain visible."""
        if error:
            self.log_summary.append(f'自动配置 IP 失败：{error}', 'error')
            return
        results = list(results or [])
        failures = [str(message) for _, ok, message in results if not ok]
        if not results:
            self.log_summary.append('未找到可配置的 GigE 相机，请检查设备连接后刷新。', 'warn')
        elif failures:
            succeeded = sum(bool(ok) for _, ok, _ in results)
            prefix = f'自动配置 IP：{succeeded} 台成功，{len(failures)} 项未完成。'
            self.log_summary.append(prefix + '；'.join(failures), 'warn')
        else:
            self.log_summary.append(f'自动配置 IP 完成：{len(results)} 台成功。', 'success')

    def showEvent(self, event):
        super().showEvent(event)
        self.log_summary.attach_logger(logger)

    def _on_connect(self):
        """连接设备：校验已在 _refresh_connect_state 完成，这里只发信号。

        # TODO(BACKEND): 调 CameraManager 逐台连接并显示进度；
        全部成功 → accept()；部分失败 → 弹窗列出失败设备，可重试或仅用成功的进入。
        """
        self._refresh_connect_state()
        if self._btn_connect.isEnabled():
            self.connect_requested.emit(self._mode, self._table.checked_devices())

    # ------------------------------------------------------------ 公共接口
    def selected_mode(self) -> str:
        return self._mode

    def selected_presentation(self):
        return self._presentation

    def selected_devices(self) -> List[DeviceInfo]:
        return self._table.checked_devices()

    def set_devices(self, devices: List[DeviceInfo]):
        """填充设备列表（后端枚举结果）。"""
        self._table.set_devices(devices)
        self._update_device_hint()
        self._refresh_connect_state()

    def _update_device_hint(self):
        devices = self._table.devices()
        tests = sum(not isinstance(d.backend_ref, int) for d in devices)
        self._device_hint.setText(
            f"发现 {len(devices)} 台设备" + (f"（含 {tests} 台测试设备，仅供调试）" if tests else "；请选择需要连接的相机。")
            if devices else "未检测到相机，请检查电源、网络或 USB 连接后刷新。")

    def _is_busy(self):
        return self._busy or self._auto_ip_busy or self._connecting

    def _update_busy_controls(self):
        busy = self._is_busy()
        for widget in (self._mode_choices, self._search_edit, self._table,
                       self._btn_refresh, self._btn_auto_ip, self._btn_add_test,
                       self._btn_cancel):
            widget.setEnabled(not busy)
        self._refresh_connect_state()

    def set_busy(self, busy: bool, text: str = ""):
        self._busy = busy
        if text:
            self._device_hint.setText(text)
        elif not busy:
            self._update_device_hint()
        self._update_busy_controls()

    def set_auto_ip_busy(self, busy: bool):
        self._auto_ip_busy = busy
        self._btn_auto_ip.setText("配置中…" if busy else "自动设置 IP")
        self._update_busy_controls()

    def reject(self):
        if not self._is_busy():
            super().reject()

    def closeEvent(self, event):
        if self._is_busy():
            event.ignore()
            return
        super().closeEvent(event)

    # ------------------------------------------------------------ 回填（设备管理重开时用）
    def restore_state(self, mode: str, devices: List[DeviceInfo], presentation='classic'):
        """回填当前模式与已连接设备勾选状态。"""
        self._set_mode(mode, presentation)
        self.set_devices(devices)
