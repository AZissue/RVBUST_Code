"""Native GPU integration check. Uses synthetic geometry and never initializes SDK."""
from pathlib import Path
import sys
import time
from unittest.mock import patch
import numpy as np
import open3d as o3d

sys.path.insert(0,str(Path(__file__).parent/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from ui_v2 import MainWindowShell,LauncherDialog,GLOBAL_QSS
from ui_v2.widgets.device_table import DeviceInfo


def main():
    app=QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setStyleSheet(GLOBAL_QSS)
    output=Path('D:/RVC_SRC/.verify_reports')
    output.mkdir(parents=True, exist_ok=True)
    with patch('core.camera_manager.CameraManager.initialize',side_effect=AssertionError('SDK prohibited')):
        launcher=LauncherDialog();launcher.show()
        launcher._industrial_cards['mobile_chain'].clicked.emit()
        launcher._on_add_test_devices()
        app.processEvents()
        assert launcher.grab().save(str(output/'production_parallel_launcher.png'))
        launcher.close()
        win=MainWindowShell();win.resize(1600,1000)
        points=np.random.default_rng(14).normal(size=(50000,3))*[120,80,12]
        cloud=o3d.geometry.PointCloud()
        cloud.points=o3d.utility.Vector3dVector(points)
        cloud.colors=o3d.utility.Vector3dVector(np.tile([.8,.4,.2],(len(points),1)))
        def wait(test):
            deadline=time.monotonic()+30
            while not test():
                app.processEvents();time.sleep(.01)
                assert time.monotonic()<deadline,'GPU timeout'
            app.processEvents()
        for mode in LauncherDialog.MODE_NAMES:
            count=4 if mode=='multi_cam' else 1
            win.set_mode(mode,[DeviceInfo(model='OFFLINE TEST',serial=f'TEST-{i}') for i in range(count)])
            win.set_presentation('industrial');win.show()
            ws=win._stack.currentWidget()
            panel=ws.viewer if mode=='turntable' else ws.viewer()
            panel.set_pointcloud_merged(cloud)
            renderer=panel.viewer()
            wait(lambda: renderer.canvas._ready and not renderer.canvas.is_busy)
            canvas=renderer.canvas
            canvas.repaint();app.processEvents()
            before=canvas.uploads
            canvas._begin_interaction()
            canvas.rotation.drag((300.,250.),(310.,258.),canvas.width(),canvas.height(),canvas._pivot_pixel())
            canvas.update();app.processEvents()
            assert canvas.uploads==before
            if mode=='mobile_chain':
                from types import SimpleNamespace
                markers=[dict(code=1,x_2d=30,y_2d=30,x_3d=10,y_3d=20,z_3d=300,valid_3d=True)]
                frame=SimpleNamespace(image_np=np.full((100,160),100,np.uint8),markers_all=[],markers=markers)
                ws.live_view().set_marker_context(frame)
            if mode=='turntable':
                ws._display_2d(np.full((100,160),100,np.uint8))
            win._btn_log.setChecked(True);app.processEvents()
            assert win.grab().save(str(output/f'production_parallel_{mode}.png'))
            panel.set_maximized(True);app.processEvents()
            assert not ws._industrial.sidebar.isVisible()
            panel.set_maximized(False);app.processEvents()
            assert ws._industrial.sidebar.isVisible()
            renderer._fallback('integration fallback')
            assert renderer.canvas.total_points==len(points)
            win.set_presentation('classic');app.processEvents()
            np.testing.assert_array_equal(np.asarray(cloud.points),points)
        win._dirty=False;win.close();app.processEvents()
    print('PASS: six-entry launcher; three native GPU workspaces; stable uploads; dock; maximize; fallback; raw data preserved; no SDK initialization')


if __name__=='__main__':main()
