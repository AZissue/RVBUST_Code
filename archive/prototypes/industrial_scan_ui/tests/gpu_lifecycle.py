"""Opt-in native-window validation of queued scenes and explicit fallback."""
from pathlib import Path
import sys, time
import numpy as np
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from industrial_scan_ui.app.window import ScanWorkbench
from industrial_scan_ui.app.canvas import CloudCanvas
from industrial_scan_ui.core.session import CloudLayer


def main():
    app = QApplication([])
    win = ScanWorkbench(load_demo=False, renderer='gpu')
    win.show()
    def wait_for(predicate):
        end = time.monotonic()+30
        while not predicate():
            app.processEvents()
            if time.monotonic() > end:
                raise TimeoutError('native integration timeout')
            time.sleep(.005)
    wait_for(lambda: getattr(win.canvas, '_ready', False))
    gpu = win.canvas
    for count in (1000, 2000, 3000):
        layer = CloudLayer(str(count), np.random.default_rng(count).random((count, 3)))
        win.session.layers = [layer]
        win._refresh(fit=True)
    wait_for(lambda: not gpu.is_busy)
    assert gpu.scene.original_points == 3000, 'stale scene replaced latest request'
    assert gpu.displayed_points == 3000
    gpu.repaint()
    app.processEvents()
    assert len(gpu._buffers) == 1
    win.set_frame_observation(1, None, [dict(code=7,x_2d=10,y_2d=10,
        x_3d=.5,y_3d=.5,z_3d=.5,valid_3d=True,world=[.5,.5,.5])])
    gpu.repaint()
    app.processEvents()
    assert gpu._marker_buffer is not None, 'marker VBO was not uploaded'
    uploads = gpu.uploads
    marker_buffer = gpu._marker_buffer
    gpu.set_view('顶视')
    gpu.repaint()
    assert gpu.uploads == uploads and gpu._marker_buffer == marker_buffer
    assert len(win.marker_inspector.world_overlay.points) == 1
    # Dock resize changes viewport dimensions, never the scene/camera buffers.
    rotation = gpu.rotation.matrix.copy()
    center, pan, zoom = gpu.center.copy(), gpu.pan.copy(), gpu.zoom
    win.log_toggle.setChecked(True)
    app.processEvents()
    win.content_splitter.setSizes([450, 200])
    app.processEvents()
    win.log_toggle.setChecked(False)
    app.processEvents()
    gpu.repaint()
    assert gpu.uploads == uploads and gpu._failure is None
    np.testing.assert_array_equal(gpu.rotation.matrix, rotation)
    np.testing.assert_array_equal(gpu.center, center)
    np.testing.assert_array_equal(gpu.pan, pan)
    assert gpu.zoom == zoom
    win.session.layers = []
    win._refresh()
    wait_for(lambda: not gpu.is_busy)
    gpu.repaint()
    app.processEvents()
    assert not gpu._buffers, 'deleted frame retained GPU allocation'
    assert not gpu._marker_points, 'deleted frame retained marker annotations'
    # Deliberately exercise the visible downgrade path; not an actual driver failure.
    gpu._fail('验收测试主动触发渲染失败')
    wait_for(lambda: isinstance(win.canvas, CloudCanvas))
    assert '兼容' in win.status.text()
    assert win.log_toggle.isChecked()
    assert not win.render_quality.isEnabled()
    assert win.marker_inspector.viewport is win.canvas
    assert win.marker_inspector.parent() is win.canvas
    assert win.marker_inspector.world_overlay.viewport is win.canvas
    win._dirty = False
    win.close()
    assert not win.isVisible()
    print('GPU latest-scene coalescing, buffer removal, explicit fallback and cleanup: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
