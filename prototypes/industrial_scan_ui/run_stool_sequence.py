"""Temporary real-scan accumulation demo. Uses the reusable workbench image/marker inspector.

Prepare with prepare_stool_sequence.py, then run with --cache <folder>.
--video <mp4> exports the actual Qt/OpenGL workbench and leaves it interactive.
"""
import argparse,json,sys,time
from pathlib import Path
import numpy as np
import cv2
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parents[1]/'src'),str(HERE.parent)]
from PySide6.QtCore import Qt,QTimer,QEvent,QRectF
from PySide6.QtGui import QPainter,QColor,QImage,QFont
from PySide6.QtWidgets import QApplication,QWidget
from industrial_scan_ui.app.window import ScanWorkbench
from industrial_scan_ui.core.session import CloudLayer
from industrial_scan_ui.core.trackball import multiply,axis_angle

class MarkerOverlay(QWidget):
    def __init__(self,canvas):
        super().__init__(canvas)
        self.canvas=canvas;self.record=None;self.image=None;self.stage=0;self.phase=''
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        canvas.installEventFilter(self);self.setGeometry(canvas.rect());self.show()
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Resize:self.setGeometry(self.canvas.rect())
        return False
    def set_record(self,record,image):
        self.record=record;self.image=QImage(str(image));self.update()
    def paintEvent(self,event):
        if not self.record:return
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont('Microsoft YaHei',9))
        p.setPen(Qt.NoPen);p.setBrush(QColor(24,30,36,220))
        p.drawRoundedRect(QRectF(16,66,270,62),6,6)
        p.setPen(QColor('#e5edf1'));p.drawText(28,90,f'逐帧拼接  {self.stage:02d} / 08   {self.phase}')
        p.setPen(QColor('#b8d983'));p.drawText(28,113,'真实离线数据 · 参考网格已关闭')

class SequenceDemo:
    interval=3.4
    duration=8*interval+2.0
    def __init__(self,cache):
        self.cache=Path(cache);self.records=json.loads((self.cache/'sequence.json').read_text(encoding='utf-8'))
        self.layers=[]
        for r in self.records:
            z=np.load(self.cache/f"frame_{r['frame']}.npz")
            self.layers.append(CloudLayer(f"扫描帧 {r['frame']:02d}",z['points'],z['colors'],source=f"离线实测 {r['frame']}.ply · 原始有效 {r['original_points']:,} 点 · 采样预览"))
        self.win=ScanWorkbench(load_demo=False,renderer='gpu');self.win.resize(1920,1080)
        self.win.setWindowTitle('MCC · 凳子逐帧拼接与编码圆识别 · 临时演示')
        self.win.grid_toggle.setChecked(False);self.win.show()
        self.c=self.win.canvas;self.overlay=MarkerOverlay(self.c)
        self.index=-1
        allpts=np.concatenate([l.points[::20] for l in self.layers]);lo,hi=np.quantile(allpts,[.005,.995],axis=0)
        self.extent=float(np.linalg.norm(hi-lo))
        colors=np.concatenate([l.colors[::20] for l in self.layers])
        red=(colors[:,0]>colors[:,1]*1.8)&(colors[:,0]>colors[:,2]*1.8)&(colors[:,0]>.3)
        self.center=allpts[red].mean(0);self.center[2]=120
        self.timer=QTimer();self.timer.setInterval(33);self.timer.timeout.connect(self.tick)
        self.win.scan_button.clicked.disconnect();self.win.scan_button.clicked.connect(self.replay)
        self.win._actions['scan'].clicked.disconnect();self.win._actions['scan'].clicked.connect(self.replay)
        self.set_time(0)
    def wait_ready(self):
        deadline=time.time()+45
        while self.c.is_busy or self.c.scene is None:
            QApplication.processEvents();time.sleep(.01)
            if time.time()>deadline:raise RuntimeError('GPU cache preparation timed out')
    def set_time(self,t):
        index=min(7,int(t/self.interval))
        if index!=self.index:
            self.index=index;self.win.session.layers=self.layers[:index+1]
            self.win._refresh(fit=False,select=index);self.wait_ready()
            r=self.records[index]
            reference=next((item for item in self.records[:index] if item['frame']==r['reference']),None)
            self.win.set_frame_observation(r['frame'],self.cache/f'image_{index+1}.jpg',r['markers'],
                layer_index=index,reference_id=r['reference'],
                reference_markers=reference['markers'] if reference else None,
                used_codes=r.get('used_codes'),rejected_codes=r.get('rejected_codes',[]),
                registration_accepted=r.get('registration_accepted'))
            self.overlay.set_record(r,self.cache/f'image_{index+1}.jpg')
            r=self.records[index]
            display=self.win.marker_inspector.display
            self.win.log(f"帧 {index+1:02d} 叠加 · 有效编码圆 {display.green_count+display.red_count} · 红圈 {display.red_count} · 参考帧 {r['reference'] or '首帧'}")
        # Hold the new scan, then orbit smoothly by 9 degrees before the next addition.
        u=np.clip((t-index*self.interval-.9)/1.8,0,1);u=u*u*(3-2*u)
        yaw=-12+(index+u)*9
        self.c.rotation.quaternion=multiply(axis_angle([1,0,0],-63),axis_angle([0,0,1],yaw))
        self.c.center=self.center.copy();self.c.extent=self.extent;self.c.zoom=1.05;self.c.pan[:]=0
        self.overlay.stage=index+1;self.overlay.phase='叠加完成' if u==0 else ('视角转动' if u<1 else '等待下一帧')
        if t>=8*self.interval:self.overlay.phase='拼接展示完成'
        self.win.progress.setValue(round((index+1)/8*100));self.win.progress_text.setText(f'{index+1} / 8 帧')
        self.win.state_label.setText('离线逐帧拼接')
        self.win.scan_button.setText('重新播放逐帧拼接')
        self.c._notify_view_changed();self.overlay.update()
        self.win.marker_inspector.raise_()
    def replay(self):
        self.index=-1;self.started=time.monotonic();self.timer.start()
    def tick(self):
        t=time.monotonic()-self.started;self.set_time(min(t,self.duration))
        if t>=self.duration:self.timer.stop()

def to_bgr(q):
    q=q.convertToFormat(QImage.Format_RGB888)
    a=np.frombuffer(q.bits(),np.uint8).reshape(q.height(),q.bytesPerLine())[:,:q.width()*3].reshape(q.height(),q.width(),3)
    return cv2.cvtColor(a,cv2.COLOR_RGB2BGR)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--video',type=Path);parser.add_argument('--preview',type=Path)
    parser.add_argument('--preview-time',type=float,default=26)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args();app=QApplication([]);demo=SequenceDemo(args.cache)
    if args.verify:
        for stage in range(8):
            demo.set_time(stage*demo.interval+.01);app.processEvents()
            assert len(demo.win.session.layers)==stage+1
            assert not demo.win.grid_toggle.isChecked() and not demo.c.grid
            assert demo.c.displayed_points==600000*(stage+1)
            display=demo.win.marker_inspector.display
            assert display.red_codes <= display.paired_codes
            assert display.green_count+display.red_count+display.yellow_count==len(display.rows)
            assert demo.c._failure is None
            assert len(demo.c._marker_points)==34
            if stage:assert display.red_count>=3
            else:assert display.green_count==34 and display.red_count==0
        demo.set_time(0);assert len(demo.win.session.layers)==1
        print('PASS: eight accumulated GPU stages, marker colors, grid disabled, replay reset',flush=True)
        demo.c.shutdown();return
    if args.preview:
        demo.set_time(args.preview_time);app.processEvents();demo.c.repaint();app.processEvents();demo.win.grab().save(str(args.preview))
        print('PREVIEW',demo.center,demo.extent,flush=True);demo.c.shutdown();return
    if args.video:
        args.video.parent.mkdir(parents=True,exist_ok=True)
        writer=cv2.VideoWriter(str(args.video),cv2.VideoWriter_fourcc(*'mp4v'),30,(1920,1080));assert writer.isOpened()
        count=round(demo.duration*30)
        for i in range(count):
            demo.set_time(i/30);app.processEvents();demo.c.repaint();demo.overlay.repaint();app.processEvents()
            writer.write(cv2.resize(to_bgr(demo.win.grab().toImage()),(1920,1080)))
            if i in [0,110,420,count-1]:demo.win.grab().save(str(args.video.parent/f'sequence_{i:04d}.png'))
            if i%102==0:print('RENDER',i,'/',count,flush=True)
        writer.release();print('VIDEO DONE',flush=True)
    else:demo.replay()
    app.exec()

if __name__=='__main__':main()
