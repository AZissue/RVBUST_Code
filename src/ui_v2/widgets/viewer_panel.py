# -*- coding: utf-8 -*-
"""
ui_v2.widgets.viewer_panel —— 3D 拼接预览面板。

直接包装 ``src/ui_common/point_cloud_viewer.py`` 的 ``EmbeddedPointCloudViewer``，
保持 ui_v2 的公共接口不变，工作区无需感知底层实现。
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout

if TYPE_CHECKING:
    from ..contracts import PointCloudView


class ViewerPanel(QFrame):
    """3D 点云查看器面板（真实渲染）。

    信号：
        viewer_message(str)  渲染器状态/错误信息。
    """

    viewer_message = Signal(str)
    collapse_toggled = Signal(bool)
    """3D 查看器折叠/展开信号（True=展开，False=折叠）。"""
    maximize_toggled = Signal(bool)
    """3D 查看器最大化/恢复信号（True=最大化，False=恢复）。"""

    def __init__(self, title: str = "3D 拼接预览", parent=None, *, renderer_factory=None):
        super().__init__(parent)
        self._title = title
        self._clouds = {}
        self._merged = None
        self._database_cloud = None
        self._reference = None
        self._rotation_geometry = (None, None)
        self._industrial_enabled = False
        self._retired = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if renderer_factory is None:
            from ui_common.point_cloud_viewer import EmbeddedPointCloudViewer
            renderer_factory = EmbeddedPointCloudViewer
        factory = renderer_factory
        self._renderer_factory = factory
        self._viewer = factory(parent=self)
        from ..contracts import PointCloudView
        if not isinstance(self._viewer, PointCloudView):
            raise TypeError("Renderer must implement ui_v2.contracts.PointCloudView")
        self._viewer.status_changed.connect(self.viewer_message.emit)
        self._viewer.collapse_toggled.connect(self.collapse_toggled.emit)
        self._viewer.maximize_toggled.connect(self.maximize_toggled.emit)
        root.addWidget(self._viewer, 1)

    def set_industrial(self, enabled):
        if self._industrial_enabled == enabled:
            return
        old = self._viewer
        if enabled:
            from ui_common.industrial_viewer import IndustrialViewer
            candidate = IndustrialViewer(parent=self)
        else:
            candidate = self._renderer_factory(parent=self)
        candidate.status_changed.connect(self.viewer_message.emit)
        candidate.collapse_toggled.connect(self.collapse_toggled.emit)
        candidate.maximize_toggled.connect(self.maximize_toggled.emit)
        self.layout().replaceWidget(old, candidate)
        self._viewer = candidate
        self._industrial_enabled = enabled
        old.hide()
        if hasattr(old, 'shutdown'):
            old.shutdown()
        self._retired.append(old)
        self._release_retired()
        candidate.set_reference(self._reference)
        if enabled:
            candidate.set_rotation_geometry(*self._rotation_geometry)
        for key, pcd in self._clouds.items():
            candidate.set_pointcloud(key, pcd)
        if self._merged is not None:
            candidate.set_pointcloud_merged(self._merged)
        candidate.show()
        if enabled and self._database_cloud is not None:
            candidate.show_database_frame(self._database_cloud)

    def _release_retired(self):
        from PySide6.QtCore import QTimer
        pending = []
        for renderer in self._retired:
            if hasattr(renderer, 'is_busy') and renderer.is_busy():
                pending.append(renderer)
            else:
                renderer.close()
                renderer.deleteLater()
        self._retired = pending
        if pending:
            QTimer.singleShot(50, self._release_retired)

    def shutdown(self):
        for renderer in [self._viewer, *self._retired]:
            if hasattr(renderer, 'shutdown'):
                renderer.shutdown()

    def viewer(self) -> PointCloudView:
        """返回底层 3D 查看器实例（高级操作使用）。"""
        return self._viewer

    # ------------------------------------------------------------ 公共接口（转发）
    def set_pointcloud(self, camera_id: str, pcd: Any):
        """按相机分色叠加一路点云。"""
        if pcd is None:
            self._clouds.pop(camera_id, None)
        else:
            self._clouds[camera_id] = pcd
        self._viewer.set_pointcloud(camera_id, pcd)

    def set_pointcloud_merged(self, pcd: Any):
        """设置拼接合并结果。"""
        self._merged = pcd
        self._viewer.set_pointcloud_merged(pcd)

    def remove_camera(self, camera_id: str):
        self._clouds.pop(camera_id, None)
        self._viewer.remove_camera(camera_id)

    def clear_all(self):
        self._clouds.clear()
        self._merged = None
        self._database_cloud = None
        self._viewer.clear_all()

    def reset_view(self):
        self._viewer.reset_view()

    def show_database_frame(self, cloud):
        self._database_cloud = cloud
        if hasattr(self._viewer, 'show_database_frame'):
            self._viewer.show_database_frame(cloud)

    def set_view_preset(self, name: str):
        self._viewer.set_view_preset(name)

    def set_point_size(self, size: int):
        self._viewer.set_point_size(size)

    def set_reference(self, camera_id: Optional[str]):
        """设置参考相机；新版保留原始颜色，旧版沿用参考色规则。"""
        self._reference = camera_id
        self._viewer.set_reference(camera_id)

    def set_rotation_geometry(self, axis=None, center=None):
        self._rotation_geometry = (axis, center)
        if hasattr(self._viewer, 'set_rotation_geometry'):
            self._viewer.set_rotation_geometry(axis, center)

    def set_highlight(self, camera_id: str, indices: Optional[list] = None):
        """高亮指定相机的部分点。"""
        self._viewer.set_highlight(camera_id, indices)

    def clear_highlight(self):
        self._viewer.clear_highlight()

    def is_collapsed(self) -> bool:
        """返回 3D 查看区域当前是否处于折叠状态。"""
        return self._viewer.is_collapsed()

    def set_collapsed(self, collapsed: bool):
        """外部设置折叠状态。"""
        self._viewer.set_collapsed(collapsed)

    def set_maximized(self, on: bool):
        """外部同步最大化按钮勾选状态。"""
        self._viewer.set_maximized(on)
