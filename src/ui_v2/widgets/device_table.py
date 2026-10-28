# -*- coding: utf-8 -*-
"""
ui_v2.widgets.device_table —— 启动小窗的设备多选表格。

每行一台相机：☑ 勾选 | 型号 | 序列号 | 设备状态 | IP 地址。
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
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHeaderView, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QWidget,
)

from ..theme import ACCENT, STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_MUTED, TEXT_PRIMARY


# 紧凑排版参数：数据字体比启动窗默认 12px 略小，行高/表头同步收紧。
DATA_FONT_PX = 11
ROW_HEIGHT = 25
HEADER_HEIGHT = 26
CHECK_COLUMN_WIDTH = 34
SERIAL_MIN_WIDTH = 112
SERIAL_MAX_WIDTH = 190
STATUS_MIN_WIDTH = 64
STATUS_MAX_WIDTH = 92
IP_MIN_WIDTH = 84
IP_MAX_WIDTH = 118

# 短标签 | 完整语义（tooltip 前缀）| 颜色；状态含义与后端枚举保持一致。
STATUS_LABELS = {
    'idle': ('空闲', '空闲', STATUS_OK),
    'busy': ('占用', '被占用', STATUS_ERR),
    'subnet_mismatch': ('跨网段', 'IP不在同一网段', STATUS_WARN),
    'ip_conflict': ('IP冲突', '网络地址冲突', STATUS_ERR),
    'unreachable': ('不可达', '网络设备不可达', STATUS_WARN),
    'connected': ('已连接', '本程序已连接', '#64B5F6'),
    'unknown': ('未知', '状态未知', TEXT_MUTED),
    'offline': ('离线', '设备已离线', TEXT_MUTED),
    'test': ('测试', '测试设备', STATUS_OK),
}


@dataclass
class DeviceInfo:
    """设备条目（UI 层数据结构，后端枚举结果转换为此结构）。"""

    model: str = ""          # 型号，如 M2600R / X1 / M2000
    serial: str = ""         # 序列号
    ip: str = ""             # IP 地址
    online: bool = True      # 在线状态
    checked: bool = False    # 勾选状态
    backend_ref: object = field(default=None, repr=False)
    status: str = "unknown"
    status_detail: str = "尚未查询设备状态"
    """后端设备句柄/索引（SDK 设备对象或枚举下标），UI 不解释，原样回传。"""


class ModernCheckBox(QCheckBox):
    """自定义现代风格勾选框：圆角矩形 + 白色对勾，无焦点虚线框。"""

    CHECK_SIZE = 18
    RADIUS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setText("")
        self.setCursor(Qt.PointingHandCursor)
        # 隐藏原生 indicator，完全自绘
        self.setStyleSheet("QCheckBox::indicator { width: 0px; height: 0px; }")
        self.setFixedSize(self.CHECK_SIZE, self.CHECK_SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        size = self.CHECK_SIZE
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2

        if self.isChecked():
            painter.setBrush(QBrush(QColor(ACCENT)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x, y, size, size, self.RADIUS, self.RADIUS)
            # 白色对勾
            painter.setPen(
                QPen(QColor(TEXT_PRIMARY), 2.5,
                     Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(int(x + size * 0.25), int(y + size * 0.52),
                             int(x + size * 0.44), int(y + size * 0.70))
            painter.drawLine(int(x + size * 0.42), int(y + size * 0.70),
                             int(x + size * 0.75), int(y + size * 0.30))
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#555555"), 1.5))
            painter.drawRoundedRect(x + 0.5, y + 0.5, size - 1, size - 1,
                                    self.RADIUS, self.RADIUS)


class DeviceTable(QTableWidget):
    """设备多选表格。"""

    checked_changed = Signal(list)  # List[DeviceInfo]，当前勾选项变化时发射

    COLS = ("", "型号", "序列号", "设备状态", "IP 地址")
    COL_MODEL = 1
    COL_SERIAL = 2
    COL_STATUS = 3
    COL_IP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: List[DeviceInfo] = []
        self._filter_text = ""
        self._check_widgets: List[ModernCheckBox] = []

        # 数据字体固定为 11px，避免受外层 QSS 12px 影响；表头同步收紧。
        self._data_font = QFont(self.font())
        self._data_font.setPixelSize(DATA_FONT_PX)
        self._ip_font = QFont(self._data_font)
        families = set(QFontDatabase.families())
        for family in ('Consolas', 'Cascadia Mono', 'Courier New'):
            if family in families:
                self._ip_font.setFamily(family)
                break
        self._ip_font.setStyleHint(QFont.TypeWriter)
        self._ip_font.setPixelSize(DATA_FONT_PX)
        self.setFont(self._data_font)
        self.setObjectName('deviceTable')
        self.setStyleSheet(
            'QTableWidget#deviceTable { font-size: %dpx; }'
            'QTableWidget#deviceTable QHeaderView::section '
            '{ padding: 2px 5px; font-size: %dpx; }'
            % (DATA_FONT_PX, DATA_FONT_PX))

        self.setColumnCount(len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setMinimumSectionSize(22)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.NoSelection)  # 禁用行选高亮，避免虚线框
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setFocusPolicy(Qt.NoFocus)  # 去掉焦点虚线框
        self.setWordWrap(False)          # 所有数据保持单行
        self.setTextElideMode(Qt.ElideMiddle)  # 长型号/长 SN 中间省略，保留首尾

        header = self.horizontalHeader()
        header.setMinimumSectionSize(26)
        header.setStretchLastSection(False)
        header.setFixedHeight(HEADER_HEIGHT)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)   # 型号吃掉剩余空间
        header.setSectionResizeMode(2, QHeaderView.Interactive)  # 序列号按内容限宽
        header.setSectionResizeMode(3, QHeaderView.Interactive)  # 状态只按短标签适配
        header.setSectionResizeMode(4, QHeaderView.Interactive)  # IP 紧凑宽度
        self.setColumnWidth(0, CHECK_COLUMN_WIDTH)
        self.setColumnWidth(self.COL_SERIAL, SERIAL_MIN_WIDTH)
        self.setColumnWidth(self.COL_STATUS, STATUS_MIN_WIDTH)
        self.setColumnWidth(self.COL_IP, IP_MIN_WIDTH)

        self.itemClicked.connect(self._on_row_clicked)

    # ------------------------------------------------------------ 公共接口
    def set_devices(self, devices: List[DeviceInfo]):
        """稳定排序，按序列号恢复勾选；USB 只隐藏 IP，状态始终显示。"""
        selected = {d.serial for d in self._devices if d.checked and d.serial}
        for device in devices:
            if device.serial in selected:
                device.checked = True
        self._devices = sorted(devices, key=lambda d: (
            not d.online, d.status not in ('idle', 'connected')))
        has_ip = any(bool(d.ip and d.ip.strip()) for d in self._devices)
        self.setColumnHidden(self.COL_IP, not has_ip)
        self.setColumnHidden(self.COL_STATUS, False)
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
        for row, dev in enumerate(self._devices):
            if dev.serial == serial:
                dev.online = online
                dev.status = 'unknown'
                dev.status_detail = '重新上线，需刷新查询状态' if online else '设备已离线'
                self._set_status(row, dev)
                break

    # ------------------------------------------------------------ 内部
    def _rebuild(self):
        self.blockSignals(True)
        self.setRowCount(len(self._devices))
        self._check_widgets = []
        for row, dev in enumerate(self._devices):
            # 现代风格勾选框，居中放置；行高收紧但保留整行点击热区
            chk = ModernCheckBox()
            chk.setChecked(dev.checked)
            chk.toggled.connect(lambda checked, r=row: self._on_check_toggled(r, checked))
            self._check_widgets.append(chk)

            wrapper = QWidget()
            wrapper_layout = QHBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(4, 2, 4, 2)
            wrapper_layout.setAlignment(Qt.AlignCenter)
            wrapper_layout.addWidget(chk)
            self.setCellWidget(row, 0, wrapper)

            self._set_text_item(row, self.COL_MODEL, dev.model or "—")
            self._set_text_item(row, self.COL_SERIAL, dev.serial or "—")
            self._set_text_item(row, self.COL_IP, dev.ip or "—", font=self._ip_font)
            self._set_status(row, dev)
        self._layout_columns()
        self.blockSignals(False)
        self.apply_filter(self._filter_text)

    def _set_text_item(self, row, column, text, font=None):
        """单行数据单元格：完整文本放 tooltip，超宽时由表格中间省略。"""
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        if font is not None:
            item.setFont(font)
        self.setItem(row, column, item)

    def _status_style(self, dev):
        """返回 (短标签, 完整语义, 颜色)；测试设备沿用空闲绿但标注“测试”。"""
        key = dev.status
        if key == 'unknown' and not dev.online:
            key = 'offline'
        if dev.backend_ref is None and dev.status == 'idle':
            key = 'test'
        return STATUS_LABELS.get(key, STATUS_LABELS['unknown'])

    def _layout_columns(self):
        """序列号/状态/IP 按内容限宽，型号占用剩余空间，避免长文本撑宽整表。"""
        fm = QFontMetrics(self._data_font)
        serial_need = fm.horizontalAdvance('序列号') + 28
        status_need = fm.horizontalAdvance('设备状态') + 24
        ip_fm = QFontMetrics(self._ip_font)
        ip_need = ip_fm.horizontalAdvance('IP 地址') + 26
        for dev in self._devices:
            serial_need = max(serial_need, fm.horizontalAdvance(dev.serial or '—') + 28)
            status_need = max(status_need,
                              fm.horizontalAdvance(self._status_style(dev)[0]) + 24)
            ip_need = max(ip_need, ip_fm.horizontalAdvance(dev.ip or '—') + 26)
        self.setColumnWidth(self.COL_SERIAL,
                            max(SERIAL_MIN_WIDTH, min(SERIAL_MAX_WIDTH, serial_need)))
        self.setColumnWidth(self.COL_STATUS,
                            max(STATUS_MIN_WIDTH, min(STATUS_MAX_WIDTH, status_need)))
        self.setColumnWidth(self.COL_IP,
                            max(IP_MIN_WIDTH, min(IP_MAX_WIDTH, ip_need)))

    def _set_status(self, row, dev):
        label, full_label, color = self._status_style(dev)
        detail = (dev.status_detail or '').strip()
        # 短标签用于列内显示；tooltip 必须保留完整语义、识别依据或错误详情。
        tooltip = detail
        if full_label not in detail:
            tooltip = f'{full_label}；{detail}' if detail else full_label
        item = QTableWidgetItem(label)
        item.setForeground(QBrush(QColor(color)))
        item.setToolTip(tooltip)
        item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, self.COL_STATUS, item)

    def _on_check_toggled(self, row: int, checked: bool):
        """勾选框状态变化时同步数据并发射信号。"""
        if 0 <= row < len(self._devices):
            self._devices[row].checked = checked
            self.checked_changed.emit(self.checked_devices())

    def _on_row_clicked(self, item: QTableWidgetItem):
        """点击行任意位置切换勾选（多选交互）。"""
        row = item.row()
        if 0 <= row < len(self._check_widgets):
            chk = self._check_widgets[row]
            chk.setChecked(not chk.isChecked())
