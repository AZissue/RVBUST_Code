"""Real bundled-data acceptance, optionally with native GPU screenshots.

Run --native for hardware-independent desktop OpenGL verification.
Camera SDK initialization, enumeration and capture are forbidden in this check.
"""
import argparse
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--native', action='store_true')
args = parser.parse_args()
if not args.native:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from core.camera_manager import CameraManager
from ui_v2 import MainWindowShell
from ui_v2.backend_bridge import BackendBridge
from ui_v2.composition import UiComposition

app = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
UiComposition().configure(app)
report = ROOT.parent.parent / '.verify_reports'
report.mkdir(exist_ok=True)


def wait_for(condition, timeout=120):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError('Offline preview did not finish')
        time.sleep(.01)


with patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK initialization forbidden')), \
     patch.object(CameraManager, 'find_devices', side_effect=AssertionError('device enumeration forbidden')):
    win = MainWindowShell()
    bridge = BackendBridge(win)
    bridge.wire_all()
    win.set_backend_bridge(bridge)
    win.show()
    try:
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            complete = []
            bridge.open_offline_preview(mode, lambda *result: complete.append(result))
            wait_for(lambda: bool(complete))
            assert complete[0][0], complete
            assert bridge.camera_manager.get_connected_ids() == []
            assert win.current_mode() == mode and win.current_presentation() == 'industrial'
            if mode == 'multi_cam':
                assert len(bridge.fixed_workflow.frames_calib) == 2
                bridge._on_multi_calibrate()
                wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
                app.processEvents()
                assert win.workspace_multi().current_state() == 'locked'
                assert len(bridge.fixed_workflow.frames_scan) == 2
            elif mode == 'mobile_chain':
                assert len(bridge.mobile_workflow.get_station_evaluations()) == 2
                assert len(win.workspace_mobile().viewer()._merged.points) > 1000000
                source = ROOT / 'offline_test_data' / 'stool' / 'frame_2.zip'
                bridge._on_mobile_station_selected(1)
                ok, message = bridge.mobile_workflow.undo_last_station()
                assert ok, message
                assert source.exists()
                assert (ROOT / 'offline_test_data' / 'stool' / '.cache' / '2.ply').exists()
            else:
                assert win.workspace_turntable().session.frame0 is not None
                assert win.workspace_turntable().session.frame1 is not None
                assert not win.workspace_turntable().btn_capture_frame1.isEnabled()
            viewer = (win.workspace_multi().viewer() if mode == 'multi_cam' else
                      win.workspace_mobile().viewer() if mode == 'mobile_chain' else win.workspace_turntable().viewer)
            canvas = viewer._viewer.canvas
            wait_for(lambda: not canvas.is_busy)
            for _ in range(20):
                app.processEvents()
                time.sleep(.02)
            assert win.grab().save(str(report / f'offline_{mode}.png'))
            print('PASS', mode, complete[0][1], flush=True)
    finally:
        # Wait CPU preparation before destroying Qt/OpenGL owners.
        wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
        bridge.cleanup()
        win._dirty = False
        win.close()
        app.processEvents()
