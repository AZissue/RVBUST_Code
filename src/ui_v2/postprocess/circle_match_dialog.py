"""Triangle prototype adapter using production task, image-preview and DB APIs."""
import copy
import numpy as np
from PySide6.QtCore import Qt,QTimer,QPointF
from PySide6.QtGui import QPainter,QColor,QPen,QPolygonF
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,
    QSpinBox,QDoubleSpinBox,QPushButton,QLabel,QCheckBox,QDialogButtonBox,QPlainTextEdit)
from ui_common.image_preview import AspectRatioLabel,numpy_to_qpixmap
from .parameter_guard import ParameterGuard
from ..dialogs import localize_buttons

class GeometryImagePreview(AspectRatioLabel):
    def __init__(self):
        super().__init__()
        self.triangle=[]

    def clear_image(self):
        self.triangle=[]
        super().clear_image()

    def paintEvent(self,event):
        super().paintEvent(event)
        if not self.triangle or self._pixmap is None or self._pixmap.isNull():return
        pw,ph=self._pixmap.width(),self._pixmap.height()
        scale=min(self.width()/pw,self.height()/ph)
        sw,sh=int(pw*scale),int(ph*scale)
        x,y=(self.width()-sw)//2,(self.height()-sh)//2
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#ffcc55'),2,Qt.DashLine))
        painter.drawPolygon(QPolygonF([QPointF(x+u*sw,y+v*sh) for u,v in self.triangle]))

class CircleMatchDialog(QDialog):
    def __init__(self,editor):
        super().__init__(editor)
        self.editor=editor
        self.analysis=None
        self.tokens=None
        self._busy=False
        self.setWindowTitle('圆点识别 · 三角形几何匹配拼接（实验）')
        self.resize(1080,820)
        layout=QVBoxLayout(self)
        note=QLabel('两帧原始2D图像 + 逐像素有序点云（mm）。支持实心圆点和灰心黑环，按3D三角边长匹配。\n'
            '图像内序号不是编码；匹配成功后两侧相同编号才是对应圆点。等边/重复图案多解时拒绝拼接。')
        note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();layout.addLayout(form)
        self.reference,self.moving=QComboBox(),QComboBox()
        rows=[row for row in editor.database.records.values() if row.kind=='raw']
        selected=[uid for uid in editor._display_ids if uid in editor.database.records and editor.database.records[uid].kind=='raw']
        rows.sort(key=lambda row:(row.uid not in selected,row.created,row.frame_id))
        for combo in (self.reference,self.moving):
            for row in rows:
                combo.addItem(f'{row.logical_name} · {row.uid[:6]}',row.uid)
        if len(rows)>1:self.moving.setCurrentIndex(1)
        form.addRow('固定参考帧',self.reference);form.addRow('待变换移动帧',self.moving)
        self.polarity=QComboBox();self.polarity.addItem('黑圆点 / 浅色背景','dark');self.polarity.addItem('白圆点 / 深色背景','light')
        form.addRow('圆点极性',self.polarity)
        self.auto=QCheckBox('自动Otsu灰度阈值');self.auto.setChecked(True)
        self.threshold=QSpinBox();self.threshold.setRange(0,255);self.threshold.setValue(100);self.threshold.setEnabled(False)
        self.auto.toggled.connect(lambda value:self.threshold.setEnabled(not value))
        threshold_row=QHBoxLayout();threshold_row.addWidget(self.auto);threshold_row.addWidget(self.threshold)
        form.addRow('图像分割',threshold_row)
        def numeric(low,high,value,decimals=2):
            spin=QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(decimals);spin.setValue(value);return spin
        self.min_radius=numeric(1,999,3);self.max_radius=numeric(2,1000,60)
        radius_row=QHBoxLayout();radius_row.addWidget(self.min_radius);radius_row.addWidget(QLabel('至'));radius_row.addWidget(self.max_radius)
        form.addRow('圆点半径范围（像素）',radius_row)
        self.circularity=numeric(.1,1,.65);form.addRow('最小圆度',self.circularity)
        self.edge=numeric(.001,100,1,3);self.point=numeric(.001,100,2,3)
        tolerance_row=QHBoxLayout();tolerance_row.addWidget(QLabel('边长'));tolerance_row.addWidget(self.edge)
        tolerance_row.addWidget(QLabel('圆心对应距离'));tolerance_row.addWidget(self.point)
        form.addRow('几何容差（mm）',tolerance_row)
        self.relative=numeric(0,10,1);self.short_edge=numeric(.001,10000,5,3)
        limits=QHBoxLayout();limits.addWidget(QLabel('边长相对容差%'));limits.addWidget(self.relative)
        limits.addWidget(QLabel('最短三角边mm'));limits.addWidget(self.short_edge)
        form.addRow('边长附加约束',limits)
        self.minimum=QSpinBox();self.minimum.setRange(3,24);self.minimum.setValue(3);form.addRow('最少对应圆点',self.minimum)
        self.analyze_button=QPushButton('识别圆点并计算三角匹配');self.analyze_button.clicked.connect(self.analyze)
        layout.addWidget(self.analyze_button)
        images=QHBoxLayout();layout.addLayout(images,1)
        self.images=[GeometryImagePreview(),GeometryImagePreview()]
        for label in self.images: images.addWidget(label,1)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.report.setMinimumHeight(110);self.report.setMaximumHeight(170)
        layout.addWidget(self.report)
        self.confirm=QCheckBox('我已核对两侧相同编号对应同一物理圆点，并确认单位为毫米')
        self.confirm.toggled.connect(self.refresh);layout.addWidget(self.confirm)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);localize_buttons(buttons)
        self.execute_button=buttons.button(QDialogButtonBox.Ok);self.execute_button.setText('确认并生成拼接结果')
        self.execute_button.setAutoDefault(False)
        self.cancel_button=buttons.button(QDialogButtonBox.Cancel);self.cancel_button.setDefault(True)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.controls=[self.reference,self.moving,self.polarity,self.auto,self.threshold,self.min_radius,
                       self.max_radius,self.circularity,self.edge,self.point,self.relative,self.short_edge,self.minimum]
        self.guard=ParameterGuard(self)
        for control in self.controls:
            control.installEventFilter(self.guard)
            signal=(control.currentIndexChanged if isinstance(control,QComboBox) else
                    control.toggled if isinstance(control,QCheckBox) else control.valueChanged)
            signal.connect(self.invalidate)
        self.refresh()

    def invalidate(self,*_):
        self.analysis=None;self.tokens=None;self.confirm.setChecked(False)
        self.report.setPlainText('输入或参数已变化，请重新识别匹配。')
        for label in self.images: label.clear_image()
        self.refresh()

    def refresh(self,*_):
        self.execute_button.setEnabled(not self._busy and self.analysis is not None
            and self.analysis['match'] is not None and self.confirm.isChecked())
        self.analyze_button.setEnabled(not self._busy and self.reference.currentData() is not None
            and self.moving.currentData() is not None and self.reference.currentData()!=self.moving.currentData())

    def analyze(self):
        editor=self.editor
        if self._busy or not editor._parameter_gate():return
        try:
            from prototypes.circle_geometry_match.core.circles import CircleParameters
            from prototypes.circle_geometry_match.core.matching import MatchParameters
            from prototypes.circle_geometry_match.core.pipeline import analyze_pair
        except ImportError as exc:
            self.report.setPlainText('原型模块未安装或未随程序分发：'+str(exc))
            return
        uids=[self.reference.currentData(),self.moving.currentData()]
        if None in uids or len(set(uids))!=2:return
        try:
            circle=CircleParameters(polarity=self.polarity.currentData(),threshold=-1 if self.auto.isChecked() else self.threshold.value(),
                min_radius=self.min_radius.value(),max_radius=self.max_radius.value(),circularity=self.circularity.value())
            matching=MatchParameters(edge_tolerance=self.edge.value(),relative_tolerance=self.relative.value()/100,
                point_tolerance=self.point.value(),min_matches=self.minimum.value(),min_edge=self.short_edge.value())
            circle.validate();matching.validate()
            records=[copy.deepcopy(editor.database.records[uid]) for uid in uids]
        except (ValueError,KeyError) as exc:
            self.report.setPlainText(str(exc));return
        self.invalidate();self._busy=True
        for control in self.controls:control.setEnabled(False)
        self.cancel_button.setEnabled(False);self.refresh()
        directory=editor.directory
        tokens=tuple((row.uid,row.revision) for row in records)
        def work():
            with editor.database._lock:
                editor._validate_source(directory,tokens)
                result=analyze_pair(directory,*records,circle,matching)
                editor._validate_source(directory,tokens)
            return result
        def finished(result=None,error=None):
            if error:self.report.setPlainText('识别/匹配失败：'+str(error))
            else:
                self.analysis=result;self.tokens=tokens
                self.show_analysis(result)
            def release():
                if editor._closed:return
                if editor._worker is not None:
                    QTimer.singleShot(10,release);return
                self._busy=False
                for control in self.controls:control.setEnabled(True)
                self.threshold.setEnabled(not self.auto.isChecked())
                self.cancel_button.setEnabled(True);self.refresh()
            QTimer.singleShot(0,release)
        editor._run(work,lambda result:finished(result),kind='probe',on_error=lambda error:finished(error=error))
        self.report.setPlainText('正在后台读取原始数据、识别圆点和检查几何匹配歧义…')

    def show_analysis(self,result):
        match=result['match'];labels=[{},{}]
        if match:
            for number,(r,m) in enumerate(match['pairs'],1):labels[0][r]=number;labels[1][m]=number
        counts=[]
        for side,(frame,view) in enumerate(zip(result['frames'],self.images)):
            image=frame['image'];h,w=image.shape[:2];view._ratio=w/h
            view.setPixmap(numpy_to_qpixmap(image))
            markers=[];valid_number=0
            for dot in frame['dots']:
                code='无深度'
                color='#ff5555'
                if dot['valid_3d']:
                    code=str(labels[side].get(valid_number,'未配对'))
                    color='#55ee88' if valid_number in labels[side] else '#ffcc55'
                    valid_number+=1
                markers.append(dict(x=dot['pixel'][0]/w,y=dot['pixel'][1]/h,code=code,
                                    valid_3d=dot['valid_3d'],display_color=color))
            view.triangle=([np.asarray(frame['valid_dots'][pair[side]]['pixel'])/[w,h]
                            for pair in match['triangle_pairs']] if match else [])
            view.set_markers(markers)
            counts.append(f'{"参考" if side==0 else "移动"}：2D圆点{len(frame["dots"])}，有效3D圆心{len(frame["valid_dots"])}')
        if match:
            triangles=[np.asarray([frame['valid_dots'][pair[side]]['xyz'] for pair in match['triangle_pairs']])
                       for side,frame in enumerate(result['frames'])]
            lengths=[np.linalg.norm(tri[[0,0,1]]-tri[[1,2,2]],axis=1) for tri in triangles]
            counts += ['三角边长mm：参考 '+', '.join(f'{value:.3f}' for value in lengths[0])+
                       '；移动 '+', '.join(f'{value:.3f}' for value in lengths[1])]
            lines=counts+[f'对应{len(match["pairs"])}对；圆心RMS {match["rms"]:.4f} mm；最大误差 {max(match["errors"]):.4f} mm。',
                '移动 → 参考刚体变换（平移mm；不拟合尺度、不自动ICP）：',np.array2string(match['transform'],precision=6)]
            lines += [f'对应{i}: 参考像素{np.round(result["frames"][0]["valid_dots"][r]["pixel"],2)} ↔ '
                      f'移动像素{np.round(result["frames"][1]["valid_dots"][m]["pixel"],2)}，误差 {error:.4f} mm'
                      for i,((r,m),error) in enumerate(zip(match['pairs'],match['errors']),1)]
            self.report.setPlainText('\n'.join(lines))
        else:self.report.setPlainText('\n'.join(counts+['未通过：'+result['error']]))

    def accept(self):
        self.refresh()
        if self.execute_button.isEnabled():super().accept()

    def reject(self):
        if not self._busy:super().reject()

    def closeEvent(self,event):
        if self._busy:event.ignore()
        else:super().closeEvent(event)
