from __future__ import annotations

import ctypes
import os
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFormLayout, QLabel, QPlainTextEdit, QProgressBar, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class TaskCenter(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("任务名称", "类型", "状态", "进度", "开始时间", "任务 ID"))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 210)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 160)
        self.table.setColumnWidth(4, 130)
        self.tabs.addTab(self.table, "任务队列")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        self.tabs.addTab(self.log_view, "运行日志")
        self.system_page = QWidget()
        system_layout = QFormLayout(self.system_page)
        self.cpu_label = QLabel(f"{os.cpu_count() or 1} 个逻辑核心  ·  后台线程 0 / 4")
        self.memory_label = QLabel("正在读取…")
        self.device_label = QLabel("演示设备  ·  已连接")
        system_layout.addRow("计算资源", self.cpu_label)
        system_layout.addRow("系统内存", self.memory_label)
        system_layout.addRow("采集设备", self.device_label)
        self.tabs.addTab(self.system_page, "系统状态")
        self.rows: dict[str, int] = {}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_memory)
        self.timer.start(2000)
        self._update_memory()

    def add_task(self, record) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.rows[record.task_id] = row
        self.table.setItem(row, 0, QTableWidgetItem(record.name))
        self.table.setItem(row, 1, QTableWidgetItem(record.kind))
        self.table.setItem(row, 2, QTableWidgetItem(record.status))
        self.table.setCellWidget(row, 3, QProgressBar())
        self.table.setItem(row, 4, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self.table.setItem(row, 5, QTableWidgetItem(record.task_id))
        self.update_task(record)

    def update_task(self, record) -> None:
        row = self.rows.get(record.task_id)
        if row is None:
            self.add_task(record)
            return
        status_item = self.table.item(row, 2)
        status_item.setText(record.status)
        progress = self.table.cellWidget(row, 3)
        progress.setValue(record.progress)

    def append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"{timestamp}  {level:<7}  {message}")
        if level == "ERROR":
            self.tabs.setCurrentWidget(self.log_view)

    def set_active_threads(self, count: int) -> None:
        self.cpu_label.setText(f"{os.cpu_count() or 1} 个逻辑核心  ·  后台线程 {count} / 4")

    def _update_memory(self) -> None:
        class MemoryStatus(ctypes.Structure):
            _fields_ = (("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong))
        try:
            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            self.memory_label.setText(f"可用 {status.available / 1024**3:.1f} GB / 总计 {status.total / 1024**3:.1f} GB  ·  负载 {status.load}%")
        except (AttributeError, OSError):
            self.memory_label.setText("当前平台暂不支持读取")
