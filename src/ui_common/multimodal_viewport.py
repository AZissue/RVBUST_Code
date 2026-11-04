"""Shared 2D/3D workspace: persistent widgets, exclusive pages and top-right comparison overlay."""
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QToolButton,QButtonGroup,QLabel

class MultimodalViewport(QWidget):
    view_changed=Signal(str)
    def __init__(self, scene, image, parent=None):
        super().__init__(parent)
        self._view='3d'
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
        self.content=QWidget()
        self.content.installEventFilter(self)
        content_layout=QVBoxLayout(self.content);content_layout.setContentsMargins(0,0,0,0)
        self.scene_host=QWidget(self.content);self.image_host=QWidget(self.content)
        self.image_host.setObjectName('comparisonImageHost')
        self.image_host.setStyleSheet('QWidget#comparisonImageHost {background:#252525;border:1px solid #484848;border-radius:4px;}')
        for host,widget in ((self.scene_host,scene),(self.image_host,image)):
            layout=QVBoxLayout(host);layout.setContentsMargins(0,0,0,0);layout.addWidget(widget)
        content_layout.addWidget(self.scene_host)
        self.scene,self.image=scene,image
        root.addWidget(self.content,1);self.set_view('3d')

    def set_view(self,view):
        if view not in self.buttons: raise ValueError('未知视图：'+str(view))
        self._view=view
        self.buttons[view].setChecked(True)
        self.scene_host.setVisible(view!='2d');self.image_host.setVisible(view!='3d')
        self.scene.show();self.image.show()
        self._layout_image()
        self.view_changed.emit(view)

    def _layout_image(self):
        if self._view=='2d':
            self.image_host.setGeometry(self.content.rect())
        elif self._view=='joint':
            width=min(380,max(260,int(self.content.width()*.28)),max(1,self.content.width()-24))
            height=min(480,max(300,int(self.content.height()*.6)),max(1,self.content.height()-24))
            self.image_host.setGeometry(max(0,self.content.width()-width-12),12,width,height)
        if self._view!='3d':self.image_host.raise_()

    def eventFilter(self,obj,event):
        if obj is self.content and event.type() in (QEvent.Resize,QEvent.Show):
            self._layout_image()
        return False

    def current_view(self):return self._view
    def set_context(self,text):self.context.setText(text);self.context.setToolTip(text)
