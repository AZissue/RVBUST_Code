"""Select a portable renderer; expose every fallback to the user."""
from PySide6.QtWidgets import QApplication
from ui_common.industrial_scene.canvas import CloudCanvas


def create_canvas(parent=None, renderer='auto'):
    if renderer not in ('auto', 'gpu', 'software'):
        raise ValueError('Unknown renderer')
    platform = QApplication.platformName().lower()
    if renderer == 'software' or (renderer == 'auto' and platform in ('offscreen', 'minimal')):
        return CloudCanvas(parent)
    from ui_common.industrial_scene.gpu_canvas import GpuCloudCanvas
    return GpuCloudCanvas(parent)
