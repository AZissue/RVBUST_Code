# -*- coding: utf-8 -*-
"""
ui_v2.launcher_dialog —— 启动小窗（重构版，空壳）。

模态对话框，左右分栏，默认约 900×560，居中显示：
  - 左侧 ① 工作模式：两张可选中卡片（默认选中「多相机外参标定」）+ 模式说明；
  - 右侧 ② 设备管理：搜索过滤 / 刷新 / 自动设置IP / 网络配置 / 多选设备表格；
  - 底部：已选数量提示（模式联动）+ 取消 / 连接设备。

模式-设备数量规则（连接按钮启用条件）：
  - 多相机外参标定：必须选中 ≥2 台；
  - 单相机移动拼接：必须且只能选中 1 台；
  - 切换模式时清空设备多选，防止残留选择误导。

接口预留（信号全部由主窗口/后端连接）：
  refresh_requested()              重新枚举设备（SDK SystemListDevices）
  auto_ip_requested(list)          自动设置 IP（勾选设备列表）
  network_config_requested()       网络配置对话框（GigE 网卡选择）
  connect_requested(str, list)     连接设备（模式, DeviceInfo 列表）
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from .theme import (
    ACCENT, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY,
)
from . import icons as ui_icons
from .widgets import DeviceInfo, DeviceTable, ModeCard


class LauncherDialog(QDialog):
    """启动小窗：模式选择 + 设备管理 + 连接分流。"""

    MODE_MULTI_CAM = "multi_cam"        # 模式 A：多相机外参标定
    MODE_MOBILE_CHAIN = "mobile_chain"  # 模式 B：单相机移动拼接

    MODE_NAMES = {
        MODE_MULTI_CAM: "多相机外参标定",
        MODE_MOBILE_CHAIN: "单相机移动拼接",
    }

    # ---------------------------------------------------------------- 信号（接口预留）
    refresh_requested = Signal()
    """刷新设备列表。# TODO(BACKEND): 接 SDK SystemListDevices 枚举"""

    auto_ip_requested = Signal(list)
    """自动设置 IP（参数为勾选设备）。"""

    network_config_requested = Signal()
    """网络配置对话框（GigE 网卡选择 + 静态 IP）。"""

    connect_requested = Signal(str, list)
    """连接设备：(mode, List[DeviceInfo])。全部成功后由调用方 accept() 本对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RVC 拼接工作站")
        self.setModal(True)
        self.resize(900, 560)

        self._mode = self.MODE_MULTI_CAM
        self._setup_ui()
        self._refresh_connect_state()
        self._center_on_screen()

    # ------------------------------------------------------------ UI 搭建
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # ===== 标题栏 =====
        head = QHBoxLayout()
        title = QLabel("RVC 拼接工作站")
        title.setObjectName("sectionTitle")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        head.addWidget(title)
        head.addStretch(1)
        logo = QLabel("RVC")
        logo.setStyleSheet(
            f"color: {ACCENT}; font-size: 17px; font-weight: 800;")
        head.addWidget(logo)
        root.addLayout(head)

        # ===== 主区域（左右分栏） =====
        main = QHBoxLayout()
        main.setSpacing(14)

        # ---- 左侧：工作模式 ----
        left = QVBoxLayout()
        left.setSpacing(10)
        mode_label = QLabel("① 工作模式")
        mode_label.setObjectName("sectionTitle")
        left.addWidget(mode_label)

        self.card_multi = ModeCard(
            "camera_multi", "多相机外参标定",
            "多台相机固定安装，先标定外参，后撤板扫描拼接")
        self.card_multi.clicked.connect(
            lambda: self._set_mode(self.MODE_MULTI_CAM))
        left.addWidget(self.card_multi)

        self.card_mobile = ModeCard(
            "chain", "单相机移动拼接",
            "一台相机移动拍摄，自动检测标记物，边走边拼")
        self.card_mobile.clicked.connect(
            lambda: self._set_mode(self.MODE_MOBILE_CHAIN))
        left.addWidget(self.card_mobile)

        self._mode_desc = QLabel()
        self._mode_desc.setWordWrap(True)
        self._mode_desc.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; padding: 4px 2px;")
        left.addWidget(self._mode_desc)
        left.addStretch(1)
        main.addLayout(left, 2)

        # ---- 右侧：设备管理 ----
        right = QVBoxLayout()
        right.setSpacing(8)
        dev_label = QLabel("② 设备管理")
        dev_label.setObjectName("sectionTitle")
        right.addWidget(dev_label)

        # 搜索行
        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索 型号 / IP / 序列号")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.addAction(
            ui_icons.icon("search", TEXT_SECONDARY, 15),
            QLineEdit.LeadingPosition)
        self._search_edit.textChanged.connect(self._on_filter)
        search_row.addWidget(self._search_edit, 1)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.setToolTip("重新枚举设备")
        ui_icons.apply(self._btn_refresh, "refresh", TEXT_SECONDARY, 15)
        self._btn_refresh.clicked.connect(self.refresh_requested)
        search_row.addWidget(self._btn_refresh)

        # TODO(TEMP): 临时添加两台测试设备，便于无真实多机环境时进入主界面排查问题
        self._btn_add_test = QPushButton("+ 测试设备")
        self._btn_add_test.setToolTip("临时添加 2 台测试相机（TEST-A / TEST-B）")
        self._btn_add_test.clicked.connect(self._on_add_test_devices)
        search_row.addWidget(self._btn_add_test)

        right.addLayout(search_row)

        # 网络操作行
        net_row = QHBoxLayout()
        self._btn_auto_ip = QPushButton("自动设置IP")
        self._btn_auto_ip.setToolTip("为勾选设备自动配置网络（参考 AutoConfigureNetwork）")
        ui_icons.apply(self._btn_auto_ip, "bolt", TEXT_SECONDARY, 15)
        self._btn_auto_ip.clicked.connect(self._on_auto_ip)
        net_row.addWidget(self._btn_auto_ip)
        self._btn_net_cfg = QPushButton("网络配置…")
        self._btn_net_cfg.setToolTip("GigE 相机网卡选择 + 静态 IP")
        ui_icons.apply(self._btn_net_cfg, "network", TEXT_SECONDARY, 15)
        self._btn_net_cfg.clicked.connect(self.network_config_requested)
        net_row.addWidget(self._btn_net_cfg)
        net_row.addStretch(1)
        right.addLayout(net_row)

        # 设备多选表格
        self._table = DeviceTable()
        self._table.checked_changed.connect(self._on_checked_changed)
        right.addWidget(self._table, 1)

        # 底部模式-数量提示
        self._rule_hint = QLabel()
        self._rule_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        right.addWidget(self._rule_hint)
        main.addLayout(right, 3)

        root.addLayout(main, 1)

        # ===== 底部按钮行 =====
        bottom = QHBoxLayout()
        self._selection_label = QLabel()
        self._selection_label.setStyleSheet("font-size: 12px;")
        bottom.addWidget(self._selection_label)
        bottom.addStretch(1)

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setMinimumWidth(100)
        self._btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self._btn_cancel)

        self._btn_connect = QPushButton("连接设备")
        self._btn_connect.setObjectName("primary")
        self._btn_connect.setMinimumWidth(140)
        ui_icons.apply(self._btn_connect, "arrow_right", "#FFFFFF", 15)
        self._btn_connect.clicked.connect(self._on_connect)
        bottom.addWidget(self._btn_connect)
        root.addLayout(bottom)

        self._set_mode(self._mode)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)

    # ------------------------------------------------------------ 模式联动
    def _set_mode(self, mode: str):
        """切换模式：更新卡片态 / 说明 / 数量提示，并清空设备多选。"""
        self._mode = mode
        self.card_multi.setChecked(mode == self.MODE_MULTI_CAM)
        self.card_mobile.setChecked(mode == self.MODE_MOBILE_CHAIN)

        if mode == self.MODE_MULTI_CAM:
            self._mode_desc.setText(
                "多台相机固定安装，先标定外参（一次性），撤掉标定板后"
                "反复扫描拼接。适合固定工位、产线巡检。")
        else:
            self._mode_desc.setText(
                "一台相机边走边拍，每帧自动检测标记物、自动配准增量拼接。"
                "适合现场扫描、大件测量。")

        # 不同模式设备要求不同，清空多选防止残留选择误导
        self._table.clear_checks()
        self._refresh_connect_state()

    def _refresh_connect_state(self):
        """模式-设备数量规则：连接按钮启用条件 + 底部提示。"""
        n = len(self._table.checked_devices())
        if self._mode == self.MODE_MULTI_CAM:
            self._rule_hint.setText("多相机外参标定：至少需要 2 台相机")
            ok = n >= 2
            if n == 0:
                hint, color = "未选择设备", TEXT_MUTED
            elif n < 2:
                hint, color = f"已选 {n} 台 / 多相机模式至少需要 2 台", ACCENT
            else:
                hint, color = f"已选 {n} 台 ✓", STATUS_OK
        else:
            self._rule_hint.setText("单相机移动拼接：必须且只能选中 1 台相机")
            ok = n == 1
            if n == 0:
                hint, color = "未选择设备", TEXT_MUTED
            elif n > 1:
                hint, color = (
                    f"已选 {n} 台 / 单相机移动拼接仅支持 1 台相机，"
                    "请取消多余选择"), ACCENT
            else:
                hint, color = "已选 1 台 ✓", STATUS_OK

        self._selection_label.setText(hint)
        self._selection_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._btn_connect.setEnabled(ok)

    # ------------------------------------------------------------ 事件
    def _on_filter(self, text: str):
        self._table.apply_filter(text)

    def _on_add_test_devices(self):
        """临时：向设备表追加两台测试相机，方便进入主界面检查。"""
        existing = self._table.devices()
        test_devices = [
            DeviceInfo(model="TEST-A", serial="SN_TEST_A", online=True),
            DeviceInfo(model="TEST-B", serial="SN_TEST_B", online=True),
        ]
        # 避免重复添加
        existing_serials = {d.serial for d in existing}
        for d in test_devices:
            if d.serial not in existing_serials:
                existing.append(d)
        self._table.set_devices(existing)
        self._refresh_connect_state()

    def _on_checked_changed(self, _checked: list):
        self._refresh_connect_state()

    def _on_auto_ip(self):
        """自动设置 IP：对勾选设备执行（未勾选时提示）。

        # TODO(BACKEND): 接自动网络配置逻辑；执行中由主窗口显示加载遮罩
        """
        self.auto_ip_requested.emit(self._table.checked_devices())

    def _on_connect(self):
        """连接设备：校验已在 _refresh_connect_state 完成，这里只发信号。

        # TODO(BACKEND): 调 CameraManager 逐台连接并显示进度；
        全部成功 → accept()；部分失败 → 弹窗列出失败设备，可重试或仅用成功的进入。
        """
        self.connect_requested.emit(self._mode, self._table.checked_devices())

    # ------------------------------------------------------------ 公共接口
    def selected_mode(self) -> str:
        return self._mode

    def selected_devices(self) -> List[DeviceInfo]:
        return self._table.checked_devices()

    def set_devices(self, devices: List[DeviceInfo]):
        """填充设备列表（后端枚举结果）。"""
        self._table.set_devices(devices)
        if not devices:
            self._rule_hint.setText("未检测到相机（可检查网络或稍后刷新）")
        self._refresh_connect_state()

    def set_busy(self, busy: bool, text: str = ""):
        """连接/枚举进行中：禁用操作按钮（加载遮罩由主窗口统一控制）。"""
        for btn in (self._btn_connect, self._btn_refresh,
                    self._btn_auto_ip, self._btn_net_cfg):
            btn.setEnabled(not busy)
        if not busy:
            self._refresh_connect_state()

    # ------------------------------------------------------------ 回填（设备管理重开时用）
    def restore_state(self, mode: str, devices: List[DeviceInfo]):
        """回填当前模式与已连接设备勾选状态。"""
        self._set_mode(mode)
        self._table.set_devices(devices)
        self._refresh_connect_state()
