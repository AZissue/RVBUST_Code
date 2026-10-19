"""Select a portable renderer; expose every fallback to the user."""
from PySide6.QtWidgets import QApplication
from .canvas import CloudCanvas


def create_canvas(parent=None, renderer='auto'):
    if renderer not in ('auto', 'gpu', 'software'):
        raise ValueError('Unknown renderer')
    platform = QApplication.platformName().lower()
    if renderer == 'software' or (renderer == 'auto' and platform in ('offscreen', 'minimal')):
        return CloudCanvas(parent)
    from .gpu_canvas import GpuCloudCanvas
    return GpuCloudCanvas(parent)
