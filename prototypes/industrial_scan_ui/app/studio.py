"""Small function entrance and a single main window with replaceable workspaces."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSpinBox, QPushButton, QScrollArea, QWidget, QMainWindow, QMessageBox)
from ui_v2.widgets.mode_card import ModeCard
from .window import STYLE


class FunctionLauncher(QDialog):
    def __init__(self, registry, parent=None, *, selected=None, camera_count=None):
        super().__init__(parent)
        if not registry.entries():
            raise ValueError('尚未注册功能')
        self.registry = registry
        self.setWindowTitle('MCC · 选择功能')
        self.resize(860, 540)
        self.setMinimumSize(720, 460)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.addWidget(QLabel('MCC / 重建工作站', objectName='brand'))
        root.addWidget(QLabel('选择工作方案后进入对应界面 · 离线原型', objectName='muted'))
        body = QHBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        choices = QWidget()
        items = QVBoxLayout(choices)
        items.setContentsMargins(0, 0, 10, 0)
        self.cards = {}
        for spec in registry.entries():
            card = ModeCard(spec.icon, spec.title, spec.description)
            card.clicked.connect(lambda key=spec.key: self.select_function(key))
            self.cards[spec.key] = card
            items.addWidget(card)
        items.addStretch()
        scroll.setWidget(choices)
        body.addWidget(scroll, 3)
        info = QGroupBox('功能与设备')
        details = QVBoxLayout(info)
        self.title = QLabel()
        self.title.setWordWrap(True)
        details.addWidget(self.title)
        self.description = QLabel()
        self.description.setWordWrap(True)
        details.addWidget(self.description)
        details.addWidget(QLabel('2D相机画面槽位'))
        self.camera_count = QSpinBox()
        details.addWidget(self.camera_count)
        self.rule = QLabel()
        self.rule.setWordWrap(True)
        details.addWidget(self.rule)
        details.addStretch()
        note = QLabel('此入口用于离线界面与数据验证。设备连接仍使用正式主程序的设备管理流程。')
        note.setWordWrap(True)
        details.addWidget(note)
        body.addWidget(info, 2)
        root.addLayout(body, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.enter_button = QPushButton('进入功能', objectName='primary')
        self.enter_button.clicked.connect(self.accept)
        actions.addWidget(self.enter_button)
        root.addLayout(actions)
        self.select_function(selected or registry.entries()[0].key)
        if camera_count is not None:
            self.camera_count.setValue(camera_count)

    def select_function(self, key):
        spec = self.registry.get(key)
        self.selected_key = key
        for name, card in self.cards.items():
            card.setChecked(name == key)
        self.title.setText(spec.title)
        self.description.setText(spec.description)
        self.camera_count.setRange(spec.minimum_cameras, spec.maximum_cameras)
        self.camera_count.setValue(spec.default_cameras)
        self.camera_count.setEnabled(spec.minimum_cameras != spec.maximum_cameras)
        self.rule.setText('该功能无需相机，可直接处理已有文件。' if spec.maximum_cameras == 0 else
                          '多相机至少2路；槽位可载入各相机独立2D图像。' if spec.minimum_cameras > 1 else
                          '单相机工作方案，固定1路2D预览。')


class StudioWindow(QMainWindow):
    def __init__(self, registry, key, *, camera_count=None, renderer='auto', load_demo=True):
        super().__init__()
        self.registry = registry
        self.renderer = renderer
        self.resize(1440, 900)
        self.setMinimumSize(1000, 660)
        workspace = registry.create(key, camera_count=camera_count, renderer=renderer, load_demo=load_demo)
        self._install(key, workspace)

    def _install(self, key, workspace):
        self.key = key
        self.workspace = workspace
        self.setCentralWidget(workspace)
        workspace.function_selection_requested.connect(self.choose_function)
        workspace.function_button.show()
        self.setWindowTitle('MCC · '+self.registry.get(key).title+' · 离线原型')

    def choose_function(self):
        if self.workspace._busy or self.workspace.session.state in ('scanning', 'paused'):
            self.workspace.log('请先完成当前任务再切换功能。', 'warn')
            return
        dialog = FunctionLauncher(self.registry, self, selected=self.key,
                                  camera_count=self.workspace.camera_count)
        if dialog.exec() == QDialog.Accepted:
            self.switch_to(dialog.selected_key, dialog.camera_count.value())

    def switch_to(self, key, camera_count=None):
        spec = self.registry.get(key)
        count = spec.default_cameras if camera_count is None else camera_count
        if key == self.key and count == self.workspace.camera_count:
            return True
        old = self.workspace
        if old.session.state in ('scanning', 'paused') or not old.can_leave():
            return False
        try:
            candidate = self.registry.create(key, camera_count=count, renderer=self.renderer, load_demo=False)
        except Exception as exc:
            QMessageBox.warning(self, '功能打开失败', str(exc))
            return False
        old.shutdown()
        self._install(key, candidate)
        return True

    def closeEvent(self, event):
        if not self.workspace.close():
            event.ignore()
            return
        event.accept()
