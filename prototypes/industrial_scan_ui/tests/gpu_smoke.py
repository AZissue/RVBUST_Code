"""Opt-in real OpenGL integration + incremental multi-frame benchmark.

Run on each customer's representative OS/driver: no GPU vendor is selected.
This opens a temporary native Qt window, never accesses camera hardware.
"""
from pathlib import Path
import sys, argparse, time, json
import numpy as np
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from industrial_scan_ui.app.gpu_canvas import GpuCloudCanvas
from industrial_scan_ui.core.session import CloudLayer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--points-per-frame', type=int, default=5_000_000)
    parser.add_argument('--frames', type=int, default=2)
    parser.add_argument('--quality', choices=['流畅', '均衡', '细节'], default='均衡')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    app = QApplication([])
    canvas = GpuCloudCanvas()
    canvas.set_policy(args.quality)
    canvas.resize(1280, 720)
    canvas.show()
    failures = []
    canvas.render_failed.connect(failures.append)
    def wait_for(predicate, seconds=60):
        end = time.monotonic()+seconds
        while not predicate():
            app.processEvents()
            if failures:
                raise RuntimeError(failures[0])
            if time.monotonic() > end:
                raise TimeoutError('GPU test timeout')
            time.sleep(.005)
    wait_for(lambda: canvas._ready)
    rows, layers = [], []
    try:
        for number in range(args.frames):
            raw = np.random.default_rng(2026+number).random((args.points_per_frame, 3), dtype=np.float32)
            raw *= 300
            layers.append(CloudLayer(f'frame{number}', raw))
            del raw
            before = canvas.uploads
            t0 = time.perf_counter()
            canvas.set_layers(layers, fit=(number == 0))
            wait_for(lambda: not canvas.is_busy)
            canvas.repaint()
            app.processEvents()
            if failures:
                raise RuntimeError(failures[0])
            canvas.makeCurrent()
            canvas.gl.glFinish()
            canvas.doneCurrent()
            load_ms = (time.perf_counter()-t0)*1000
            measurements = {}
            expected_uploads = canvas.uploads
            # Actual mouse press/release and deferred quality restoration.
            QTest.mousePress(canvas, Qt.LeftButton, pos=QPoint(400, 300))
            assert canvas._moving
            for moving in (True, False):
                if not moving:
                    QTest.mouseRelease(canvas, Qt.LeftButton, pos=QPoint(400, 300))
                    wait_for(lambda: not canvas._moving)
                samples = []
                for _ in range(12):
                    canvas.yaw += 2
                    canvas.makeCurrent()
                    t0 = time.perf_counter()
                    # Bind widget FBO; render completion is synchronized for the test only.
                    canvas.gl.glBindFramebuffer(canvas.gl.GL_FRAMEBUFFER, canvas.defaultFramebufferObject())
                    canvas.paintGL()
                    canvas.gl.glFinish()
                    samples.append((time.perf_counter()-t0)*1000)
                    canvas.doneCurrent()
                measurements['moving' if moving else 'static'] = dict(
                    points=canvas.displayed_points, median_ms=round(float(np.median(samples)), 2),
                    p95_ms=round(float(np.percentile(samples, 95)), 2))
            assert canvas.uploads == expected_uploads, 'Camera/LOD rebuilt GPU buffers'
            assert canvas.displayed_points <= canvas.policy.static_points
            rows.append(dict(frame_count=len(layers), original_points=canvas.total_points,
                             prepare_and_upload_ms=round(load_ms, 2), new_gpu_uploads=expected_uploads-before,
                             cached_points=canvas.scene.stored_points, **measurements))
        if args.screenshot:
            canvas.grabFramebuffer().save(str(args.screenshot))
        report = dict(renderer=canvas.backend_name, viewport='1280x720', rows=rows,
                      note='Synthetic points; synchronized GPU completion, excludes compositor/input latency. Not universal client FPS.')
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        wait_for(lambda: not canvas.is_busy)
        canvas.shutdown()
        canvas.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
