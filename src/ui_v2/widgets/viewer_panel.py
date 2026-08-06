# -*- coding: utf-8 -*-
"""
ui_v2.widgets.viewer_panel —— 3D 拼接预览占位面板。

空壳阶段不引入 OpenGL / open3d，以占位面板呈现布局与工具栏，
**公共方法与现有 ``src/ui/viewer_3d.py`` 的 EmbeddedPointCloudViewer 对齐**，
正式接入时整体替换为真实组件即可（工作区只调用本接口，不感知实现）。

对齐接口（stub）：
  set_pointcloud(camera_id, pcd)      按相机分色叠加一路点云
  set_pointcloud_merged(pcd)          设置拼接合并结果
  remove_camera(camera_id)            移除一路点云
  clear_all()                         清空
  reset_view() / set_view_preset(s) / set_point_size(n)
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout,
)

from ..theme import BG_PANEL, BORDER, TEXT_MUTED, TEXT_SECONDARY


class ViewerPanel(QFrame):
    """3D 查看器占位（接口预留）。

    信号：
        viewer_message(str)  占位操作说明（正式组件接入后由 status_changed 替代）。
    """

    viewer_message = Signal(str)

    def __init__(self, title: str = "3D 拼接预览", parent=None):
        super().__init__(parent)
        self._title = title
        self._camera_ids: list = []

        self.setStyleSheet(
            f"ViewerPanel {{ background-color: {BG_PANEL};"
            f" border: 1px solid {BORDER}; border-radius: 6px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部工具条（与真实查看器工具栏布局保持一致） ----
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 6)
        bar.setSpacing(6)

        self._title_label = QLabel(f"🧊 {title}")
        self._title_label.setStyleSheet(
            f"font-weight: 600; color: {TEXT_SECONDARY};")
        bar.addWidget(self._title_label)
        bar.addStretch(1)

        self._display_combo = QComboBox()
        self._display_combo.addItems(["全部叠加", "合并结果"])
        self._display_combo.setFixedWidth(100)
        bar.addWidget(self._display_combo)

        for text, slot in (
            ("⟳ 重置视角", self.reset_view),
            ("⛶ 最大化", lambda: self.viewer_message.emit("最大化（接口预留）")),
        ):
            btn = QToolButton()
            btn.setText(text)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        root.addLayout(bar)

        # ---- 中央占位区 ----
        self._canvas = QLabel(
            "3D 拼接预览区\n\n（接口预留：正式接入时替换为\n"
            "EmbeddedPointCloudViewer / viewer_3d）")
        self._canvas.setAlignment(Qt.AlignCenter)
        self._canvas.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 13px; line-height: 160%;")
        root.addWidget(self._canvas, 1)

    # ------------------------------------------------------------ 公共接口（stub）
    def set_pointcloud(self, camera_id: str, pcd: Any):
        """按相机分色叠加一路点云。

        # TODO(BACKEND): 接入 EmbeddedPointCloudViewer.set_pointcloud
        """
        if camera_id not in self._camera_ids:
            self._camera_ids.append(camera_id)
        self.viewer_message.emit(
            f"[3D] 更新点云 {camera_id}（当前 {len(self._camera_ids)} 路，接口预留）")

    def set_pointcloud_merged(self, pcd: Any):
        """设置拼接合并结果。

        # TODO(BACKEND): 接入 EmbeddedPointCloudViewer.set_pointcloud_merged
        """
        self.viewer_message.emit("[3D] 更新合并点云（接口预留）")

    def remove_camera(self, camera_id: str):
        if camera_id in self._camera_ids:
            self._camera_ids.remove(camera_id)

    def clear_all(self):
        self._camera_ids.clear()
        self.viewer_message.emit("[3D] 已清空（接口预留）")

    def reset_view(self):
        self.viewer_message.emit("[3D] 重置视角（接口预留）")

    def set_view_preset(self, name: str):
        self.viewer_message.emit(f"[3D] 视角预设 {name}（接口预留）")

    def set_point_size(self, size: int):
        self.viewer_message.emit(f"[3D] 点大小 {size}（接口预留）")
