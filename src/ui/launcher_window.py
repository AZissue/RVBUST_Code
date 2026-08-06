# -*- coding: utf-8 -*-
"""
启动小窗口（LauncherWindow）—— 软件启动时的模式选择与设备连接对话框。

布局：
  - 左侧：垂直分布功能选择（多相机拼接 / 单相机链式拼接）
  - 右侧：搜索设备 / 连接设备 / 自动配置IP
  - 底部：设备列表（显示枚举到的相机，支持多选）
  - 选中模式后，在右侧相机列表中选中相机，点击连接关闭小窗口

使用方式：
  launcher = LauncherWindow()
  if launcher.exec() == QDialog.Accepted:
      mode = launcher.selected_mode()       # 'multi_cam' | 'mobile_chain'
      device_indices = launcher.selected_devices()
      # 进入主窗口
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QRadioButton, QButtonGroup,
    QMessageBox, QAbstractItemView,
)

from .icons import icon_text, apply_icon


class LauncherWindow(QDialog):
    """启动小窗口：模式选择 + 设备连接。"""

    MODE_MULTI_CAM = "multi_cam"
    MODE_MOBILE_CHAIN = "mobile_chain"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MultiCameraCalibration — 选择工作模式")
        self.setMinimumSize(600, 400)
        self.setModal(True)

        self._mode = self.MODE_MULTI_CAM
        self._device_descs: List[str] = []
        self._setup_ui()
        self._center_on_screen()

    def _center_on_screen(self):
        """居中显示。"""
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )

    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)
        lo.setSpacing(12)

        # 标题
        title = QLabel("选择工作模式并连接相机")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #2979FF;")
        title.setAlignment(Qt.AlignCenter)
        lo.addWidget(title)

        # 主区域（左右分割）
        main_lo = QHBoxLayout()
        main_lo.setSpacing(12)

        # 左：功能选择
        left_lo = QVBoxLayout()
        left_lo.setSpacing(8)
        left_label = QLabel("工作模式:")
        left_label.setStyleSheet("font-weight: bold;")
        left_lo.addWidget(left_label)

        self.btn_group = QButtonGroup(self)
        self.rb_multi = QRadioButton("🎥 多相机拼接")
        self.rb_multi.setChecked(True)
        self.rb_multi.setStyleSheet("font-size: 11pt; padding: 8px;")
        self.rb_mobile = QRadioButton("🔗 单相机链式拼接")
        self.rb_mobile.setStyleSheet("font-size: 11pt; padding: 8px;")
        self.btn_group.addButton(self.rb_multi, 0)
        self.btn_group.addButton(self.rb_mobile, 1)
        left_lo.addWidget(self.rb_multi)
        left_lo.addWidget(self.rb_mobile)
        left_lo.addStretch(1)

        # 模式说明
        self.lbl_mode_desc = QLabel(
            "多相机：多台相机固定安装，\n先标定外参后扫描拼接")
        self.lbl_mode_desc.setStyleSheet("color: #8B8D98; font-size: 9pt;")
        self.lbl_mode_desc.setWordWrap(True)
        left_lo.addWidget(self.lbl_mode_desc)

        main_lo.addLayout(left_lo, 1)

        # 右：设备操作
        right_lo = QVBoxLayout()
        right_lo.setSpacing(8)

        # 搜索/连接/IP 按钮
        btn_lo = QHBoxLayout()
        self.btn_search = QPushButton(icon_text("search", "🔍 搜索设备"))
        self.btn_search.setObjectName("primaryButton")
        self.btn_search.clicked.connect(self._on_search)
        apply_icon(self.btn_search, "search")
        btn_lo.addWidget(self.btn_search)

        self.btn_connect = QPushButton(icon_text("link", "🔗 连接"))
        self.btn_connect.setObjectName("successButton")
        self.btn_connect.clicked.connect(self._on_connect)
        apply_icon(self.btn_connect, "link")
        btn_lo.addWidget(self.btn_connect)

        self.btn_auto_ip = QPushButton(icon_text("network", "⚡ 自动配置IP"))
        self.btn_auto_ip.clicked.connect(self._on_auto_ip)
        apply_icon(self.btn_auto_ip, "network")
        btn_lo.addWidget(self.btn_auto_ip)
        right_lo.addLayout(btn_lo)

        # 设备列表
        list_label = QLabel("设备列表（可多选）:")
        list_label.setStyleSheet("font-weight: bold;")
        right_lo.addWidget(list_label)
        self.device_list = QListWidget()
        self.device_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.device_list.setMinimumHeight(150)
        right_lo.addWidget(self.device_list)

        main_lo.addLayout(right_lo, 2)
        lo.addLayout(main_lo)

        # 底部按钮
        bottom_lo = QHBoxLayout()
        bottom_lo.addStretch(1)
        self.btn_ok = QPushButton("进入工作区")
        self.btn_ok.setObjectName("primaryButton")
        self.btn_ok.setMinimumWidth(120)
        self.btn_ok.clicked.connect(self.accept)
        bottom_lo.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton("退出")
        self.btn_cancel.setMinimumWidth(120)
        self.btn_cancel.clicked.connect(self.reject)
        bottom_lo.addWidget(self.btn_cancel)
        lo.addLayout(bottom_lo)

        # 信号连接
        self.rb_multi.toggled.connect(self._on_mode_changed)
        self.rb_mobile.toggled.connect(self._on_mode_changed)

    def _on_mode_changed(self):
        """模式切换时更新说明。"""
        if self.rb_multi.isChecked():
            self._mode = self.MODE_MULTI_CAM
            self.lbl_mode_desc.setText(
                "多相机：多台相机固定安装，\n先标定外参后扫描拼接")
        else:
            self._mode = self.MODE_MOBILE_CHAIN
            self.lbl_mode_desc.setText(
                "单相机：一台相机移动拍摄，\n边走边拼，实时链式拼接")

    def _on_search(self):
        """搜索设备（由主窗口调用实际枚举）。"""
        # 发射信号让主窗口枚举设备
        self.search_requested.emit()

    def _on_connect(self):
        """连接选中设备（由主窗口调用实际连接）。"""
        indices = self.selected_devices()
        if not indices:
            QMessageBox.warning(self, "未选择设备", "请先在设备列表中选择要连接的相机")
            return
        self.connect_requested.emit(indices)

    def _on_auto_ip(self):
        """自动配置 IP（由主窗口调用实际配置）。"""
        self.auto_ip_requested.emit()

    # ------------------------------------------------------------------
    # 公共接口（主窗口调用）
    # ------------------------------------------------------------------
    def set_devices(self, device_descs: List[str]):
        """填充设备列表。"""
        self._device_descs = device_descs
        self.device_list.clear()
        for i, desc in enumerate(device_descs):
            item = QListWidgetItem(f"[{i}] {desc}")
            item.setData(Qt.UserRole, i)
            self.device_list.addItem(item)

    def selected_mode(self) -> str:
        """返回选中的模式。"""
        return self._mode

    def selected_devices(self) -> List[int]:
        """返回选中的设备索引列表。"""
        return [it.data(Qt.UserRole) for it in self.device_list.selectedItems()]

    def set_connect_enabled(self, enabled: bool):
        """设置连接按钮启用状态。"""
        self.btn_connect.setEnabled(enabled)

    def set_auto_ip_enabled(self, enabled: bool):
        """设置自动配置 IP 按钮启用状态。"""
        self.btn_auto_ip.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 信号（主窗口连接）
    # ------------------------------------------------------------------
    search_requested = Signal()
    connect_requested = Signal(list)
    auto_ip_requested = Signal()
