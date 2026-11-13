"""Opt-in native validation of the multi-function host and nested GPU viewport."""
from pathlib import Path
import argparse
import sys,time
import numpy as np
HERE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(HERE.parents[1]/'src'),str(HERE.parent)]
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPainter,QColor,QFont
from industrial_scan_ui.core.functions import default_registry
from industrial_scan_ui.app.studio import StudioWindow
from industrial_scan_ui.app.canvas import CloudCanvas


def make_markers(points):
    return [dict(code=i+1,x_2d=100+(i%4)*100,y_2d=130+(i//4)*140,
                 x_3d=float(x),y_3d=float(y),z_3d=float(z),valid_3d=True)
            for i,(x,y,z) in enumerate(points)]


def image_fixture(name, background):
    image=QImage(640,480,QImage.Format_RGB32);image.fill(QColor(background))
    painter=QPainter(image);painter.setFont(QFont('Consolas',20))
    painter.setPen(QColor('#dce5ef'));painter.drawText(30,55,name+' / OFFLINE TEST')
    for row in range(4):
        for col in range(7):
            painter.fillRect(80+col*65,100+row*65,65,65,QColor('#aab3be' if (row+col)%2 else '#313d4e'))
    painter.end();return image


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report-dir',type=Path,default=HERE.parents[1]/'outputs'/'ui-studio-verification')
    args=parser.parse_args()
    app=QApplication([])
    shell=StudioWindow(default_registry(),'multi_cam',renderer='gpu',load_demo=False)
    shell.resize(1600,1000);shell.show()
    def ready():
        deadline=time.monotonic()+30
        while shell.workspace.canvas.is_busy or not getattr(shell.workspace.canvas,'_ready',False):
            app.processEvents();time.sleep(.005)
            if time.monotonic()>deadline:raise TimeoutError('GPU workspace initialization timed out')
    ready();win=shell.workspace
    points=np.random.default_rng(7).normal(size=(8,3))*30+[0,0,500]
    for i,cid in enumerate(win.camera_ids):
        win.set_camera_observation(cid,image_fixture(cid,['#344052','#324849','#40374b','#45412f'][i]),
                                   make_markers(points-[i*8,0,0]))
    win.start_scan()
    while win._busy:app.processEvents();time.sleep(.005)
    assert all(r['success'] for r in win.extrinsics.values())
    win.log_toggle.setChecked(True);app.processEvents();win.canvas.repaint()
    assert win.canvas._failure is None
    report=args.report_dir;report.mkdir(parents=True,exist_ok=True)
    shell.grab().save(str(report/'studio_multi_ready.png'))
    gpu=win.canvas;gpu._fail('native integration fallback fixture')
    deadline=time.monotonic()+10
    while not isinstance(win.canvas,CloudCanvas):
        app.processEvents()
        if time.monotonic()>deadline:raise TimeoutError('Nested viewer fallback failed')
    assert win.camera_split.indexOf(win.canvas)>=0
    assert not win.marker_inspector.isVisible()
    win._dirty=False
    assert shell.switch_to('turntable')
    ready();win=shell.workspace
    angle=np.deg2rad(30);r=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
    win.set_calibration_frame(0,image_fixture('FRAME 0','#344052'),make_markers(points))
    win.set_calibration_frame(1,image_fixture('FRAME 1','#324849'),make_markers(points@r.T))
    win.calibrate_turntable();app.processEvents();win.canvas.repaint()
    assert win.calibration_result['step_count']==12
    assert win.canvas._failure is None
    shell.grab().save(str(report/'studio_turntable_ready.png'))
    win._dirty=False
    assert shell.switch_to('mobile_chain')
    ready();assert shell.workspace.mode_key=='mobile_chain'
    assert 'core.camera_manager' not in sys.modules
    assert 'core.marker_detector' not in sys.modules
    shell.workspace._dirty=False;shell.close()
    print('PASS: multi-camera GPU layout, offline math, nested fallback, three-mode switching; no camera modules')


if __name__=='__main__':main()
