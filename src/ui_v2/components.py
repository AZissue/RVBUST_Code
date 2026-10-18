"""Replaceable presentation components; factories must honor contracts.py."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable


def _image_preview(**kwargs):
    from ui_common.image_preview import AspectRatioLabel
    return AspectRatioLabel(**kwargs)


def _point_cloud_view(**kwargs):
    from ui_common.point_cloud_viewer import EmbeddedPointCloudViewer
    return EmbeddedPointCloudViewer(**kwargs)


@dataclass(frozen=True)
class UiComponents:
    """Inject renderer/preview implementations without editing any controller."""
    image_preview_factory: Callable = _image_preview
    point_cloud_view_factory: Callable = _point_cloud_view

    def create_preview(self, *, ratio=4.0 / 3.0, parent=None):
        preview = self.image_preview_factory(ratio=ratio, parent=parent)
        from .contracts import ImagePreview
        if not isinstance(preview, ImagePreview):
            raise TypeError("Preview must implement ui_v2.contracts.ImagePreview")
        return preview

    def create_viewer(self, title="3D 拼接预览", parent=None):
        from .widgets.viewer_panel import ViewerPanel
        return ViewerPanel(title, parent, renderer_factory=self.point_cloud_view_factory)
