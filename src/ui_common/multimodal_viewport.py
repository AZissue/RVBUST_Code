"""Shared 2D/3D workspace: persistent widgets, exclusive pages and split comparison."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QToolButton,QButtonGroup,QLabel

class MultimodalViewport(QWidget):
    view_changed=Signal(str)
    def __init__(self, scene, image, parent=None):
        super().__init__(parent)
        self._view='3d'; self._comparison_sizes=[700,500]
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(3)
        self.bar=QWidget();row=QHBoxLayout(self.bar);row.setContentsMargins(0,0,0,0)
        self.buttons={};group=QButtonGroup(self)
        for key,title in (('3d','3D点云'),('2d','2D图像'),('joint','对照')):
            button=QToolButton();button.setText(title);button.setCheckable(True)
            button.setStyleSheet('QToolButton {padding:5px 14px;background:#292c30;border:1px solid #41454a;color:#cccccc;} QToolButton:checked {color:#ffffff;background:#513031;border-bottom:2px solid #d12d30;}')
            button.clicked.connect(lambda checked=False,k=key:self.set_view(k))
            group.addButton(button);row.addWidget(button);self.buttons[key]=button
        row.addStretch();self.context=QLabel('当前帧');self.context.setStyleSheet('color:#b0b6bd;');row.addWidget(self.context)
        root.addWidget(self.bar)
        self.splitter=QSplitter(Qt.Horizontal);self.splitter.setChildrenCollapsible(False)
        self.scene_host=QWidget();self.image_host=QWidget()
        for host,content in ((self.scene_host,scene),(self.image_host,image)):
            layout=QVBoxLayout(host);layout.setContentsMargins(0,0,0,0);layout.addWidget(content)
            host.setMinimumWidth(180);self.splitter.addWidget(host)
        self.scene,self.image=scene,image
        self.splitter.setStretchFactor(0,1);self.splitter.setStretchFactor(1,1)
        root.addWidget(self.splitter,1);self.set_view('3d')

    def set_view(self,view):
        if view not in self.buttons: raise ValueError('未知视图：'+str(view))
        if self._view=='joint':
            sizes=self.splitter.sizes()
            if min(sizes)>0:self._comparison_sizes=sizes
        self._view=view
        self.buttons[view].setChecked(True)
        self.scene_host.setVisible(view!='2d');self.image_host.setVisible(view!='3d')
        self.scene.show();self.image.show()
        if view=='joint':self.splitter.setSizes(self._comparison_sizes)
        self.view_changed.emit(view)

    def current_view(self):return self._view
    def set_context(self,text):self.context.setText(text);self.context.setToolTip(text)
