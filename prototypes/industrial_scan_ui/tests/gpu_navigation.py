"""Native GL verification: continuous dragging, depth pivot and cached LOD."""
from pathlib import Path
import argparse, json, sys, time
import numpy as np
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from industrial_scan_ui.app.gpu_canvas import GpuCloudCanvas
from industrial_scan_ui.core.session import CloudLayer
from ui_common.industrial_scene.render_cache import RenderPolicy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--points-per-frame', type=int, default=5_000_000)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    view = GpuCloudCanvas()
    view.resize(1280, 720)
    view.show()
    errors = []
    view.render_failed.connect(errors.append)
    def wait_for(predicate):
        deadline = time.monotonic()+60
        while not predicate():
            app.processEvents()
            if errors:
                raise RuntimeError(errors[0])
            if time.monotonic() > deadline:
                raise TimeoutError('native navigation timeout')
            time.sleep(.005)
    wait_for(lambda: view._ready)
    try:
        # Point at the centre, an offset surface point and background. Verify the
        # same QMatrix4x4 used by the shader, not just the pure math controller.
        fixture = CloudLayer('pick fixture', [[-10, -10, 1], [0, 0, 1], [10, 10, 1]])
        view.set_layers([fixture], fit=True)
        wait_for(lambda: not view.is_busy)
        view.set_view('顶视')
        view.point_size = 9
        view.repaint()
        app.processEvents()
        hit = view.pick_pivot(QPointF(view.width()/2, view.height()/2))
        assert hit is not None, 'Rendered point cannot be picked from depth'
        np.testing.assert_allclose(hit, [0, 0, 1], atol=.03)
        assert view.pick_pivot(QPointF(10, 10)) is None, 'Background became a pivot'
        # The centre point is absent from the moving draw prefix. A middle
        # press before the LOD timer fires must restore and render static depth.
        policy = view.policy
        view.policy = RenderPolicy(static_points=3, moving_points=1)
        view.center = np.array([0., 0., 5.])
        QTest.mousePress(view, Qt.RightButton, pos=QPoint(500, 300))
        QTest.mouseRelease(view, Qt.RightButton, pos=QPoint(500, 300))
        view.repaint()
        assert view._moving and view.displayed_points == 1
        assert view.pick_pivot(QPointF(view.width()/2, view.height()/2)) is None
        QTest.mouseClick(view, Qt.MiddleButton, pos=QPoint(view.width()//2, view.height()//2))
        np.testing.assert_allclose(view.center, [0, 0, 1], atol=.03)
        assert not view._moving and view.displayed_points == 3
        assert not view._restore.isActive()
        center_before = view.center.copy()
        QTest.mouseClick(view, Qt.MiddleButton, pos=QPoint(10, 10))
        np.testing.assert_array_equal(view.center, center_before)
        view.policy = policy
        before_matrix = np.asarray(view._matrix().data()).reshape(4, 4, order='F')
        point = np.r_[-view.center, 1.]
        before = before_matrix @ point
        pivot = np.array([5., 3., 0.])
        view.set_pivot(pivot)
        after_matrix = np.asarray(view._matrix().data()).reshape(4, 4, order='F')
        after = after_matrix @ np.r_[-pivot, 1.]
        np.testing.assert_allclose(before[:2], after[:2], atol=1e-6)
        layers = []
        view.point_size = 2
        for number in range(2):
            raw = np.random.default_rng(number).random((args.points_per_frame, 3), dtype=np.float32)
            raw *= 300
            layers.append(CloudLayer(str(number), raw))
            del raw
            view.set_layers(layers, fit=(number == 0))
            wait_for(lambda: not view.is_busy)
            view.repaint()
            app.processEvents()
        uploads = view.uploads
        timings, positions_tested = [], 0
        for preset in ('顶视', '正视', '右视', '等轴测'):
            view.set_view(preset)
            for x, y in [(640, 360), (4, 4), (1274, 4), (4, 714), (1274, 714)]:
                QTest.mousePress(view, Qt.LeftButton, pos=QPoint(x, y))
                for step in range(1, 5):
                    rotation_before = view.rotation.matrix.copy()
                    event = QMouseEvent(QEvent.MouseMove, QPointF(x+step, y+step), QPointF(x+step, y+step),
                                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
                    start = time.perf_counter()
                    QApplication.sendEvent(view, event)
                    view.repaint()
                    app.processEvents()
                    timings.append((time.perf_counter()-start)*1000)
                    assert np.linalg.norm(view.rotation.matrix-rotation_before) > 1e-7
                    assert view._moving
                    assert view.displayed_points <= view.policy.moving_points
                    positions_tested += 1
                QTest.mouseRelease(view, Qt.LeftButton, pos=QPoint(x+4, y+4))
                # Regrabbing before the detail timer fires should not stall.
        wait_for(lambda: not view._moving)
        view.repaint()
        app.processEvents()
        assert view.uploads == uploads, 'Rotation or LOD re-uploaded source buffers'
        assert view.displayed_points == min(view.total_points, view.policy.static_points)
        assert not errors, errors
        report = dict(renderer=view.backend_name, original_points=view.total_points,
                      static_points=view.displayed_points, moving_points=view.policy.moving_points,
                      tested_one_pixel_moves=positions_tested, extra_uploads=view.uploads-uploads,
                      event_and_repaint_median_ms=round(float(np.median(timings)), 2),
                      event_and_repaint_p95_ms=round(float(np.percentile(timings, 95)), 2),
                      note='Native Qt synthetic-event/repaint timings; not universal customer FPS. Depth pivot and background tests passed.')
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        wait_for(lambda: not view.is_busy)
        view.shutdown()
        view.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
