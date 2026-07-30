# -*- coding: utf-8 -*-
"""
设备管理面板（DevicePanel）—— 左面板。

功能：
  - 设备列表：QListWidget 显示枚举到的相机（SN + 型号），支持多选；
  - 添加相机：选中设备 →「添加选中相机」→ 通知主窗口动态生成 CameraPreviewCard；
  - 网口配置：一键自动配置选中/全部 GigE 相机 IP；
  - 已添加相机：紧凑列表管理，支持移除。

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


class DevicePanel(QWidget):
    """设备管理面板（仅设备枚举 / 添加 / 移除 / IP 配置）。"""

    refresh_devices_requested = Signal()          # 查找设备
    cameras_added = Signal(list)                  # 选中的设备索引列表
    camera_remove_requested = Signal(str)         # 移除已添加相机 camera_id
    auto_configure_network_requested = Signal(list)  # 对指定设备索引自动配置 IP（空列表=所有）

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

        # ---- 设备列表 ----
        self.grp_devices = make_group_box("device_list", "📷 设备列表")
        dev_lo = QVBoxLayout(self.grp_devices)
        apply_group_icon(self.grp_devices)

        self.device_list = QListWidget()
        self.device_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.device_list.setMaximumHeight(140)
        dev_lo.addWidget(self.device_list)

        dev_btn_lo = QHBoxLayout()
        self.btn_refresh = QPushButton(icon_text("search", "🔍 查找设备"))
        self.btn_refresh.setObjectName("primaryButton")
        self.btn_refresh.clicked.connect(self.refresh_devices_requested.emit)
        apply_icon(self.btn_refresh, "search")
        dev_btn_lo.addWidget(self.btn_refresh)

        self.btn_add = QPushButton(icon_text("add", "➕ 添加选中相机"))
        self.btn_add.setObjectName("successButton")
        self.btn_add.clicked.connect(self._on_add_selected)
        apply_icon(self.btn_add, "add")
        dev_btn_lo.addWidget(self.btn_add)
        dev_lo.addLayout(dev_btn_lo)

        self.btn_auto_ip = QPushButton(icon_text("network", "⚡ 自动配置 IP"))
        self.btn_auto_ip.setObjectName("primaryButton")
        self.btn_auto_ip.setEnabled(False)
        self.btn_auto_ip.setToolTip("对选中的网口相机一键配置 IP；未选中则对所有网口相机配置")
        self.btn_auto_ip.clicked.connect(self._on_auto_configure_network)
        apply_icon(self.btn_auto_ip, "network")
        dev_lo.addWidget(self.btn_auto_ip)
        lo.addWidget(self.grp_devices)

        # ---- 已添加相机（紧凑列表，卡片在中央网格）----
        self.grp_list = make_group_box("added_cameras", "🎛 已添加相机")
        list_lo = QVBoxLayout(self.grp_list)
        apply_group_icon(self.grp_list)
        self.list_cameras = QListWidget()
        self.list_cameras.setSelectionMode(QAbstractItemView.SingleSelection)
        list_lo.addWidget(self.list_cameras)
        self.btn_remove = QPushButton(icon_text("disconnect", "✖ 移除选中相机"))
        self.btn_remove.setObjectName("dangerButton")
        self.btn_remove.clicked.connect(self._on_remove_selected)
        apply_icon(self.btn_remove, "disconnect")
        list_lo.addWidget(self.btn_remove)
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

    def device_count(self) -> int:
        return self.device_list.count()

    def _on_add_selected(self):
        indices = [it.data(Qt.UserRole) for it in self.device_list.selectedItems()]
        if indices:
            self.cameras_added.emit(sorted(indices))

    def _on_auto_configure_network(self):
        """发送自动配置 IP 请求：选中设备索引，未选中则空列表（表示全部）。"""
        indices = [it.data(Qt.UserRole) for it in self.device_list.selectedItems()]
        self.auto_configure_network_requested.emit(sorted(indices))

    def set_auto_configure_enabled(self, enabled: bool):
        """有网口设备时启用自动配置 IP 按钮。"""
        self.btn_auto_ip.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 已添加相机列表（预览卡片在中央网格，此处为紧凑管理列表）
    # ------------------------------------------------------------------
    def add_camera_entry(self, camera_id: str, desc: str = ""):
        text = f"{camera_id}  {desc}" if desc else camera_id
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, camera_id)
        self.list_cameras.addItem(item)

    def remove_camera_entry(self, camera_id: str):
        for i in range(self.list_cameras.count()):
            if self.list_cameras.item(i).data(Qt.UserRole) == camera_id:
                self.list_cameras.takeItem(i)
                return

    def update_camera_entry(self, camera_id: str, desc: str):
        for i in range(self.list_cameras.count()):
            if self.list_cameras.item(i).data(Qt.UserRole) == camera_id:
                self.list_cameras.item(i).setText(f"{camera_id}  {desc}")
                return

    @property
    def camera_ids(self) -> List[str]:
        return [self.list_cameras.item(i).data(Qt.UserRole)
                for i in range(self.list_cameras.count())]

    def _on_remove_selected(self):
        item = self.list_cameras.currentItem()
        if item is not None:
            self.camera_remove_requested.emit(item.data(Qt.UserRole))
