"""Two independent industrial viewports for ordered 3D landmark pairs."""
import numpy as np
from PySide6.QtCore import Qt, QEvent, QTimer, QPointF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLabel,
    QPushButton, QWidget, QDialogButtonBox, QTableWidget, QTableWidgetItem)
from ui_common.industrial_viewer import IndustrialViewer
from .parameter_guard import ParameterGuard
from core.postprocess.manual_registration import landmark_transform

class PickOverlay(QWidget):
    def __init__(self, viewer, changed):
        super().__init__(viewer.canvas)
        self.viewer, self.changed = viewer, changed
        self.points = []
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.bind(viewer.canvas)
        viewer.canvas_changed.connect(self.bind)
        self.timer = QTimer(self); self.timer.timeout.connect(self.update); self.timer.start(100)

    def bind(self, canvas):
        self.setParent(canvas); self.canvas = canvas
        canvas.installEventFilter(self); self.setGeometry(canvas.rect()); self.show()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(self.canvas.rect())
        if (event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton
                and event.modifiers() & Qt.ShiftModifier):
            point = self.canvas.pick_pivot(event.position())
            if point is not None:
                # Snap depth-unprojected hit to an actual input vertex.
                cloud = self.layer.points
                point = cloud[np.argmin(np.sum((cloud-point)**2,axis=1))].copy()
                if not any(np.linalg.norm(point-other)<1e-8 for other in self.points):
                    self.points.append(point); self.changed(); self.update()
            return True
        return False

    def paintEvent(self, event):
        if not self.points:
            return
        points = np.asarray(self.points)
        if hasattr(self.canvas,'project'):
            xy, _ = self.canvas.project(points)
        else:
            matrix = np.asarray(self.canvas._matrix().data()).reshape(4,4,order='F')
            clip = np.c_[points-self.canvas.center,np.ones(len(points))] @ matrix.T
            ndc = clip[:,:2]/clip[:,3,None]
            xy = np.c_[(ndc[:,0]+1)*self.width()/2,(1-ndc[:,1])*self.height()/2]
        painter = QPainter(self); painter.setPen(QColor('#ffcc44'))
        for number,(x,y) in enumerate(xy,1):
            painter.drawEllipse(QPointF(float(x),float(y)),6,6)
            painter.drawText(QPointF(float(x)+8,float(y)-8),str(number))

class ManualRegistrationDialog(QDialog):
    def __init__(self, inputs, parent=None):
        super().__init__(parent)
        self.inputs = inputs
        self.setWindowTitle('手动配准 · 共有点 + ICP')
        self.resize(1250,820)
        root = QVBoxLayout(self)
        header = QHBoxLayout(); header.addWidget(QLabel('固定参考'))
        self.reference = QComboBox()
        self.guard = ParameterGuard(self)
        self.reference.installEventFilter(self.guard)
        for uid, layer in inputs: self.reference.addItem(layer.name,uid)
        header.addWidget(self.reference,1); root.addLayout(header)
        root.addWidget(QLabel('Shift+左键拾取共有点；两侧按相同编号对应，至少3对且不共线。普通左键旋转、右键平移、滚轮缩放。'))
        views = QHBoxLayout(); root.addLayout(views,1)
        self.viewers=[]; self.pickers=[]
        for title in ('固定参考点云','待移动点云'):
            column=QVBoxLayout(); column.addWidget(QLabel(title)); views.addLayout(column,1)
            viewer=IndustrialViewer(); viewer.toolbar.hide(); column.addWidget(viewer,1)
            picker=PickOverlay(viewer,self.refresh_pairs)
            self.viewers.append(viewer); self.pickers.append(picker)
            undo=QPushButton('撤销本侧最后一个点'); undo.clicked.connect(lambda checked=False,p=picker:self.remove_last(p))
            column.addWidget(undo)
        self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(['对应编号','参考 XYZ (mm)','移动 XYZ (mm)'])
        self.table.setMaximumHeight(140); self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table)
        self.summary=QLabel(); root.addWidget(self.summary)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.execute=buttons.button(QDialogButtonBox.Ok); self.execute.setText('共有点配准并设置ICP')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        self.reference.currentIndexChanged.connect(self.reset_inputs)
        self.reset_inputs()

    def reset_inputs(self):
        index=self.reference.currentIndex(); self.ordered=[self.inputs[index],self.inputs[1-index]]
        for viewer,picker,(uid,layer) in zip(self.viewers,self.pickers,self.ordered):
            picker.points=[]; picker.layer=layer
            viewer.replace_pointclouds({uid:layer},fit=True)
        self.refresh_pairs()

    def remove_last(self,picker):
        if picker.points: picker.points.pop()
        self.refresh_pairs()

    def refresh_pairs(self):
        if len(self.pickers)!=2: return
        a,b=[picker.points for picker in self.pickers]
        self.table.setRowCount(max(len(a),len(b)))
        for i in range(self.table.rowCount()):
            for col,value in enumerate((str(i+1), ', '.join(f'{v:.3f}' for v in a[i]) if i<len(a) else '待选', ', '.join(f'{v:.3f}' for v in b[i]) if i<len(b) else '待选')):
                self.table.setItem(i,col,QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        try:
            _,rms=landmark_transform(a,b)
            self.summary.setText(f'{len(a)}对共有点，初始拟合RMS：{rms:.4f} mm。请检查同编号是否为同一位置。')
            valid=True
        except ValueError as exc:
            self.summary.setText(str(exc)); valid=False
        if hasattr(self,'execute'): self.execute.setEnabled(valid)

    def selection(self):
        return self.ordered[0][0], [np.array(p.points).copy() for p in self.pickers]

    def done(self,result):
        for picker in self.pickers: picker.timer.stop()
        for viewer in self.viewers: viewer.shutdown()
        super().done(result)
