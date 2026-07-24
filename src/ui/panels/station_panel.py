# -*- coding: utf-8 -*-
"""
站位面板（StationPanel）—— 左面板「单相机站位」Tab（Phase 5）。

单相机多站位模式：1 台物理相机移动到不同站位各拍一帧，每个站位
注册为虚拟相机（station_N）参与标定与拼接。

功能区：
  - 物理相机：设备枚举（单选）+ 连接 / 断开 + 状态显示；
  - 站位采集：「拍摄站位」大按钮 + 「新会话」；
  - 站位列表：已拍站位（"站位 N - HH:MM:SS"），支持删除 / 清空。

所有业务动作通过信号发给主窗口，面板本身不触碰 core 模块。
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QAbstractItemView,
)

from ..icons import icon_text, apply_icon, make_group_box, apply_group_icon


def station_label(station_id: str) -> str:
    """station_N → "站位 N"（中文 UI 显示）。"""
    return f"站位 {station_id.split('_')[-1]}"


class StationPanel(QWidget):
    """单相机多站位采集面板。"""

    refresh_devices_requested = Signal()      # 查找设备
    connect_requested = Signal(int)           # 连接选中设备（设备索引）
    disconnect_requested = Signal()           # 断开物理相机
    capture_station_requested = Signal()      # 拍摄站位
    station_removed = Signal(str)             # 删除站位 station_id
    stations_cleared = Signal()               # 清空站位
    new_session_requested = Signal()          # 新会话

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(6)

        # ---- 物理相机 ----
        self.grp_cam = make_group_box("camera", "📷 物理相机")
        cam_lo = QVBoxLayout(self.grp_cam)
        apply_group_icon(self.grp_cam)

        self.device_list = QListWidget()
        self.device_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.device_list.setMaximumHeight(110)
        cam_lo.addWidget(self.device_list)

        cam_btn_lo = QHBoxLayout()
        self.btn_refresh = QPushButton(icon_text("search", "🔍 查找设备"))
        self.btn_refresh.setObjectName("primaryButton")
        self.btn_refresh.clicked.connect(self.refresh_devices_requested.emit)
        apply_icon(self.btn_refresh, "search")
        cam_btn_lo.addWidget(self.btn_refresh)
        self.btn_connect = QPushButton(icon_text("link", "🔗 连接"))
        self.btn_connect.setObjectName("successButton")
        self.btn_connect.clicked.connect(self._on_connect_selected)
        apply_icon(self.btn_connect, "link")
        cam_btn_lo.addWidget(self.btn_connect)
        self.btn_disconnect = QPushButton(icon_text("disconnect", "✖ 断开"))
        self.btn_disconnect.setObjectName("dangerButton")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)
        apply_icon(self.btn_disconnect, "disconnect")
        cam_btn_lo.addWidget(self.btn_disconnect)
        cam_lo.addLayout(cam_btn_lo)

        self.lbl_cam_status = QLabel("物理相机: 未连接")
        self.lbl_cam_status.setObjectName("infoLabel")
        self.lbl_cam_status.setWordWrap(True)
        cam_lo.addWidget(self.lbl_cam_status)
        lo.addWidget(self.grp_cam)

        # ---- 站位采集 ----
        self.grp_cap = make_group_box("station", "📍 站位采集")
        cap_lo = QVBoxLayout(self.grp_cap)
        apply_group_icon(self.grp_cap)

        self.btn_capture = QPushButton(icon_text("capture", "📸 拍摄站位"))
        self.btn_capture.setObjectName("primaryButton")
        self.btn_capture.setEnabled(False)  # 物理相机连接后启用
        self.btn_capture.setMinimumHeight(44)
        self.btn_capture.setStyleSheet("font-size: 11pt; font-weight: bold;")
        self.btn_capture.setToolTip("把当前取景拍为一帧并立即存盘，注册为新站位")
        self.btn_capture.clicked.connect(self.capture_station_requested.emit)
        apply_icon(self.btn_capture, "capture", size=20)
        cap_lo.addWidget(self.btn_capture)

        self.btn_new_session = QPushButton(icon_text("new_session", "🆕 新会话（清空站位重新开始）"))
        self.btn_new_session.clicked.connect(self.new_session_requested.emit)
        apply_icon(self.btn_new_session, "new_session")
        cap_lo.addWidget(self.btn_new_session)

        self.lbl_session = QLabel("会话: （首次拍摄自动创建）")
        self.lbl_session.setObjectName("infoLabel")
        self.lbl_session.setWordWrap(True)
        cap_lo.addWidget(self.lbl_session)
        lo.addWidget(self.grp_cap)

        # ---- 站位列表 ----
        self.grp_list = make_group_box("batch", "🗂 站位列表")
        list_lo = QVBoxLayout(self.grp_list)
        apply_group_icon(self.grp_list)
        self.list_stations = QListWidget()
        self.list_stations.setSelectionMode(QAbstractItemView.SingleSelection)
        list_lo.addWidget(self.list_stations)

        sta_btn_lo = QHBoxLayout()
        self.btn_remove = QPushButton(icon_text("disconnect", "✖ 删除选中站位"))
        self.btn_remove.setObjectName("dangerButton")
        self.btn_remove.clicked.connect(self._on_remove_selected)
        apply_icon(self.btn_remove, "disconnect")
        sta_btn_lo.addWidget(self.btn_remove)
        self.btn_clear = QPushButton(icon_text("clear", "🗑 清空"))
        self.btn_clear.clicked.connect(self.stations_cleared.emit)
        apply_icon(self.btn_clear, "clear")
        sta_btn_lo.addWidget(self.btn_clear)
        list_lo.addLayout(sta_btn_lo)
        lo.addWidget(self.grp_list, 1)

    # ------------------------------------------------------------------
    # 设备列表
    # ------------------------------------------------------------------
    def set_devices(self, device_descs: List[str]):
        """填充枚举到的设备列表（每项携带索引）。"""
        self.device_list.clear()
        for i, desc in enumerate(device_descs):
            item = QListWidgetItem(f"[{i}] {desc}")
            item.setData(Qt.UserRole, i)
            self.device_list.addItem(item)
        if self.device_list.count() > 0:
            self.device_list.setCurrentRow(0)

    def _on_connect_selected(self):
        item = self.device_list.currentItem()
        if item is not None:
            self.connect_requested.emit(item.data(Qt.UserRole))

    # ------------------------------------------------------------------
    # 连接状态
    # ------------------------------------------------------------------
    def set_connected(self, connected: bool, desc: str = ""):
        """更新物理相机连接状态显示与按钮可用性。"""
        self.btn_disconnect.setEnabled(connected)
        self.btn_capture.setEnabled(connected)
        self.lbl_cam_status.setText(
            f"物理相机: {desc}" if connected else "物理相机: 未连接")

    def set_capture_enabled(self, enabled: bool):
        """主窗口同步「拍摄站位」可用状态（物理相机已连接时启用）。"""
        self.btn_capture.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 站位列表
    # ------------------------------------------------------------------
    def add_station(self, station_id: str, time_str: str = ""):
        """添加站位条目："站位 N - HH:MM:SS"。"""
        text = station_label(station_id)
        if time_str:
            text += f" - {time_str}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, station_id)
        self.list_stations.addItem(item)

    def remove_station(self, station_id: str):
        for i in range(self.list_stations.count()):
            if self.list_stations.item(i).data(Qt.UserRole) == station_id:
                self.list_stations.takeItem(i)
                return

    def clear_stations(self):
        self.list_stations.clear()

    @property
    def station_ids(self) -> List[str]:
        return [self.list_stations.item(i).data(Qt.UserRole)
                for i in range(self.list_stations.count())]

    def _on_remove_selected(self):
        item = self.list_stations.currentItem()
        if item is not None:
            self.station_removed.emit(item.data(Qt.UserRole))

    def set_session_path(self, text: str):
        """显示当前站位会话路径。"""
        self.lbl_session.setText(f"会话: {text}" if text else "会话: （首次拍摄自动创建）")
