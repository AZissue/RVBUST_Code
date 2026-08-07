# -*- coding: utf-8 -*-
"""
ui_v2.widgets.viewer_panel —— 3D 拼接预览面板。

直接包装 ``src/ui/viewer_3d.py`` 的 ``EmbeddedPointCloudViewer``，
保持 ui_v2 的公共接口不变，工作区无需感知底层实现。
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout

from ui.viewer_3d import EmbeddedPointCloudViewer


class ViewerPanel(QFrame):
    """3D 点云查看器面板（真实渲染）。

    信号：
        viewer_message(str)  渲染器状态/错误信息。
    """

    viewer_message = Signal(str)
    collapse_toggled = Signal(bool)
    """3D 查看器折叠/展开信号（True=展开，False=折叠）。"""

    def __init__(self, title: str = "3D 拼接预览", parent=None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._viewer = EmbeddedPointCloudViewer(self)
        self._viewer.status_changed.connect(self.viewer_message.emit)
        self._viewer.collapse_toggled.connect(self.collapse_toggled.emit)
        root.addWidget(self._viewer, 1)

    def viewer(self) -> EmbeddedPointCloudViewer:
        """返回底层 3D 查看器实例（高级操作使用）。"""
        return self._viewer

    # ------------------------------------------------------------ 公共接口（转发）
    def set_pointcloud(self, camera_id: str, pcd: Any):
        """按相机分色叠加一路点云。"""
        self._viewer.set_pointcloud(camera_id, pcd)

    def set_pointcloud_merged(self, pcd: Any):
        """设置拼接合并结果。"""
        self._viewer.set_pointcloud_merged(pcd)

    def remove_camera(self, camera_id: str):
        self._viewer.remove_camera(camera_id)

    def clear_all(self):
        self._viewer.clear_all()

    def reset_view(self):
        self._viewer.reset_view()

    def set_view_preset(self, name: str):
        self._viewer.set_view_preset(name)

    def set_point_size(self, size: int):
        self._viewer.set_point_size(size)

    def set_reference(self, camera_id: Optional[str]):
        """设置参考相机（参考相机点云显示为白色）。"""
        self._viewer.set_reference(camera_id)

    def set_highlight(self, camera_id: str, indices: Optional[list] = None):
        """高亮指定相机的部分点。"""
        self._viewer.set_highlight(camera_id, indices)

    def clear_highlight(self):
        self._viewer.clear_highlight()
