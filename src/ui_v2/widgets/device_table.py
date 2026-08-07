# -*- coding: utf-8 -*-
"""
ui_v2.widgets.device_table —— 启动小窗的设备多选表格。

每行一台相机：☑ 勾选 | 型号 | 序列号 | IP 地址 | 状态徽标（● 在线绿 / ○ 离线灰）。
  - 点击行切换勾选（不是只能单选）；
  - 在线设备排在前面；
  - apply_filter(text) 按 型号/序列号/IP 实时过滤；
  - checked_devices() 返回当前勾选的 DeviceInfo 列表。

接口预留：set_devices() 的数据由后端设备枚举（SDK SystemListDevices）填充，
空壳阶段由调用方（run_shell）喂 mock 数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
)

from ..theme import STATUS_ERR, STATUS_OK, TEXT_MUTED


@dataclass
class DeviceInfo:
    """设备条目（UI 层数据结构，后端枚举结果转换为此结构）。"""

    model: str = ""          # 型号，如 M2600R / X1 / M2000
    serial: str = ""         # 序列号
    ip: str = ""             # IP 地址
    online: bool = True      # 在线状态
    checked: bool = False    # 勾选状态
    backend_ref: object = field(default=None, repr=False)
    """后端设备句柄/索引（SDK 设备对象或枚举下标），UI 不解释，原样回传。"""


class DeviceTable(QTableWidget):
    """设备多选表格。"""

    checked_changed = Signal(list)  # List[DeviceInfo]，当前勾选项变化时发射

    COLS = ("", "型号", "序列号", "IP 地址", "状态")
    COL_IP = 3
    COL_STATUS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: List[DeviceInfo] = []
        self._filter_text = ""
        self._show_ip_status = True  # 动态控制 IP/状态列显示

        self.setColumnCount(len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)  # 行选仅作高亮
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.itemChanged.connect(self._on_item_changed)
        self.itemClicked.connect(self._on_row_clicked)

    # ------------------------------------------------------------ 公共接口
    def set_devices(self, devices: List[DeviceInfo]):
        """填充设备列表（在线在前，其余按枚举顺序）。

        如果所有设备都没有有效 IP（如 USB 相机），则隐藏 IP/状态列，
        避免显示无意义的 "—" 和固定 "在线"。
        """
        self._devices = sorted(
            devices, key=lambda d: (not d.online,))  # 稳定排序：在线优先
        has_ip = any(bool(d.ip and d.ip.strip()) for d in self._devices)
        self._show_ip_status = has_ip
        self.setColumnHidden(self.COL_IP, not has_ip)
        self.setColumnHidden(self.COL_STATUS, not has_ip)
        self._rebuild()

    def devices(self) -> List[DeviceInfo]:
        return list(self._devices)

    def checked_devices(self) -> List[DeviceInfo]:
        return [d for d in self._devices if d.checked]

    def clear_checks(self):
        """清空全部勾选（模式切换时调用，防止残留选择误导）。"""
        for d in self._devices:
            d.checked = False
        self._rebuild()
        self.checked_changed.emit([])

    def apply_filter(self, text: str):
        """按 型号/序列号/IP 实时过滤。"""
        self._filter_text = text.strip().lower()
        for row, dev in enumerate(self._devices):
            hay = f"{dev.model} {dev.serial} {dev.ip}".lower()
            self.setRowHidden(row, bool(self._filter_text)
                            and self._filter_text not in hay)

    def set_device_online(self, serial: str, online: bool):
        """更新单台设备在线状态（断线/重连提示用）。"""
        if not self._show_ip_status:
            return
        for row, dev in enumerate(self._devices):
            if dev.serial == serial:
                dev.online = online
                item = self.item(row, self.COL_STATUS)
                if item:
                    item.setText("● 在线" if online else "○ 离线")
                    item.setForeground(
                        self._status_brush(online))
                break

    # ------------------------------------------------------------ 内部
    def _rebuild(self):
        self.blockSignals(True)
        self.setRowCount(len(self._devices))
        for row, dev in enumerate(self._devices):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked if dev.checked else Qt.Unchecked)
            self.setItem(row, 0, check)

            self.setItem(row, 1, QTableWidgetItem(dev.model or "—"))
            self.setItem(row, 2, QTableWidgetItem(dev.serial or "—"))
            if self._show_ip_status:
                self.setItem(row, self.COL_IP, QTableWidgetItem(dev.ip or "—"))
                status = QTableWidgetItem("● 在线" if dev.online else "○ 离线")
                status.setForeground(self._status_brush(dev.online))
                status.setTextAlignment(Qt.AlignCenter)
                self.setItem(row, self.COL_STATUS, status)
        self.blockSignals(False)
        self.apply_filter(self._filter_text)

    @staticmethod
    def _status_brush(online: bool):
        from PySide6.QtGui import QBrush, QColor
        return QBrush(QColor(STATUS_OK if online else TEXT_MUTED))

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() != 0:
            return
        row = item.row()
        if 0 <= row < len(self._devices):
            self._devices[row].checked = item.checkState() == Qt.Checked
            self.checked_changed.emit(self.checked_devices())

    def _on_row_clicked(self, item: QTableWidgetItem):
        """点击行任意位置切换勾选（多选交互）。"""
        row = item.row()
        check_item = self.item(row, 0)
        if check_item is None:
            return
        check_item.setCheckState(
            Qt.Unchecked if check_item.checkState() == Qt.Checked else Qt.Checked)
