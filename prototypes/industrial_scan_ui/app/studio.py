"""Small function entrance and a single main window with replaceable workspaces."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QLineEdit, QPushButton, QScrollArea, QWidget, QMainWindow, QMessageBox)
from ui_v2.widgets.mode_card import ModeCard
from ui_v2.widgets.device_table import DeviceTable
from ui_common.worker_thread import WorkerThread
from .devices import DeviceService
from .window import STYLE


class FunctionLauncher(QDialog):
    def __init__(self, registry, parent=None, *, selected=None, camera_count=None, service=None):
        super().__init__(parent)
        if not registry.entries():
            raise ValueError('尚未注册功能')
        self.registry = registry
        self.service = service or DeviceService()
        self._owns_service = service is None
        self._worker = None
        self.connected_devices = []
        self.offline = False
        self.result_count = 0
        self.setWindowTitle('MCC · 选择功能')
        self.resize(1060, 600)
        self.setMinimumSize(960, 560)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.addWidget(QLabel('MCC / 重建工作站', objectName='brand'))
        root.addWidget(QLabel('选择工作方案 → 连接相机 → 进入工作区', objectName='muted'))
        body = QHBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        choices = QWidget()
        self.choices = choices
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
        info = QGroupBox('连接设备')
        self.info = info
        details = QVBoxLayout(info)
        self.title = QLabel()
        self.title.setWordWrap(True)
        details.addWidget(self.title)
        self.description = QLabel()
        self.description.setWordWrap(True)
        details.addWidget(self.description)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索型号 / 序列号 / IP')
        toolbar.addWidget(self.search, 1)
        self.refresh_button = QPushButton('刷新设备')
        self.refresh_button.clicked.connect(self.refresh_devices)
        toolbar.addWidget(self.refresh_button)
        details.addLayout(toolbar)
        self.device_table = DeviceTable()
        self.search.textChanged.connect(self.device_table.apply_filter)
        self.device_table.checked_changed.connect(self._selection_changed)
        details.addWidget(self.device_table, 1)
        self.rule = QLabel()
        self.rule.setWordWrap(True)
        details.addWidget(self.rule)
        self.message = QLabel('点击“刷新设备”搜索相机。')
        self.message.setWordWrap(True)
        details.addWidget(self.message)
        body.addWidget(info, 4)
        root.addLayout(body, 1)
        actions = QHBoxLayout()
        self.preview_button = QPushButton('离线预览')
        self.preview_button.clicked.connect(self.enter_offline)
        actions.addWidget(self.preview_button)
        actions.addStretch()
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.enter_button = QPushButton('连接并进入', objectName='primary')
        self.enter_button.clicked.connect(self.connect_devices)
        actions.addWidget(self.enter_button)
        root.addLayout(actions)
        self.select_function(selected or registry.entries()[0].key)
        self._preview_count = camera_count

    def select_function(self, key):
        spec = self.registry.get(key)
        self.selected_key = key
        for name, card in self.cards.items():
            card.setChecked(name == key)
        self.title.setText(spec.title)
        self.description.setText(spec.description)
        self.device_table.clear_checks()
        self.rule.setText('该功能无需相机，可直接处理已有文件。' if spec.maximum_cameras == 0 else
                          '选择2～16台相机；每台已连接相机自动创建一个2D窗口。' if spec.minimum_cameras > 1 else
                          '选择1台相机；连接后创建一个2D窗口。')
        self._selection_changed([])

    def _selection_changed(self, selected):
        spec = self.registry.get(self.selected_key)
        if spec.maximum_cameras == 1 and len(selected) > 1:
            # Keep the newly checked camera, automatically clear the former choice.
            previous = getattr(self, '_previous_serials', set())
            keep = next((d for d in selected if d.serial not in previous), selected[-1])
            for row, device in enumerate(self.device_table.devices()):
                if device.checked and device is not keep:
                    checkbox = self.device_table._check_widgets[row]
                    checkbox.blockSignals(True)
                    device.checked = False
                    checkbox.setChecked(False)
                    checkbox.blockSignals(False)
            selected = [keep]
        self._previous_serials = {d.serial for d in selected}
        valid = spec.minimum_cameras <= len(selected) <= spec.maximum_cameras
        self.enter_button.setEnabled(valid and all(d.online for d in selected))

    def _run(self, operation, done):
        if self._worker is not None:
            return
        self.info.setEnabled(False)
        self.choices.setEnabled(False)
        self.enter_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        worker = WorkerThread(operation)
        self._worker = worker
        self._result = (None, None)
        worker.result_ready.connect(self._save_result)
        def finish():
            result, error = self._result
            self._worker = None
            worker.deleteLater()
            self.info.setEnabled(True)
            self.choices.setEnabled(True)
            self.preview_button.setEnabled(True)
            self._selection_changed(self.device_table.checked_devices())
            if error:
                self.message.setText('操作失败：' + str(error))
            else:
                done(result)
        worker.finished.connect(finish)
        worker.start()

    def _save_result(self, result, error):
        self._result = result, error

    def refresh_devices(self):
        self.message.setText('正在搜索相机…')
        def ready(devices):
            self.device_table.set_devices(devices)
            self._selection_changed(self.device_table.checked_devices())
            self.message.setText(f'发现 {len(devices)} 台相机；请选择需要连接的设备。')
        self._run(self.service.enumerate, ready)

    def connect_devices(self):
        selected = self.device_table.checked_devices()
        spec = self.registry.get(self.selected_key)
        if not spec.minimum_cameras <= len(selected) <= spec.maximum_cameras:
            return
        if spec.maximum_cameras == 0:
            self.enter_offline()
            return
        self.message.setText('正在连接相机…')
        def ready(devices):
            if len(devices) != len(selected):
                self.message.setText('连接数量不符，请重新连接。')
                return
            self.connected_devices = devices
            self.result_count = len(devices)
            self.accept()
        self._run(lambda: self.service.connect(selected), ready)

    def enter_offline(self):
        spec = self.registry.get(self.selected_key)
        self.service.close()
        self.offline = True
        self.result_count = (self._preview_count if self._preview_count is not None
                             else spec.minimum_cameras)
        self.accept()

    def reject(self):
        if self._worker is not None:
            return
        if self._owns_service:
            self.service.close()
        super().reject()

    def closeEvent(self, event):
        if self._worker is not None:
            event.ignore()
            return
        super().closeEvent(event)


class StudioWindow(QMainWindow):
    def __init__(self, registry, key, *, camera_count=None, renderer='auto', load_demo=True,
                 service=None, devices=None):
        super().__init__()
        self.registry = registry
        self.renderer = renderer
        self.service = service or DeviceService()
        self.resize(1440, 900)
        self.setMinimumSize(1000, 660)
        if devices:
            camera_count = len(devices)
        workspace = registry.create(key, camera_count=camera_count, renderer=renderer, load_demo=load_demo)
        self._install(key, workspace)
        self._apply_devices(devices or [])

    def _apply_devices(self, devices):
        previous = [d.serial for d in getattr(self.workspace, '_devices', [])]
        self.workspace.set_devices(devices)
        if previous != [d.serial for d in devices]:
            self.workspace.marker_inspector.set_frame(None, [])
            if hasattr(self.workspace, 'clear_calibration'):
                self.workspace.clear_calibration()
            if hasattr(self.workspace, 'observations'):
                self.workspace.observations.clear()
                self.workspace._invalidate_extrinsics()
        if devices:
            self.workspace.device_label.setText(f'已连接 {len(devices)} 台相机 · 采集算法仍为离线原型')
            self.workspace.set_connection_status(f'已连接 {len(devices)} 台相机')
            if hasattr(self.workspace, 'camera_grid'):
                grid = self.workspace.camera_grid
                grid.set_cameras(self.workspace.camera_ids, {
                    f'cam{i+1}': f'相机{i+1} · {d.model} · {d.serial}' for i,d in enumerate(devices)})
                for cid in self.workspace.camera_ids:
                    grid.card(cid).set_compact_preview()
                # A rebuilt grid must never keep an old camera's calibration input.
                self.workspace.observations.clear()
                self.workspace._invalidate_extrinsics()
        else:
            self.workspace.set_connection_status('离线预览 · 未连接相机')
        self.workspace.preview_button.setEnabled(bool(devices))

    def capture_previews(self):
        workspace = self.workspace
        if workspace._busy or workspace.session.state in ('scanning', 'paused'):
            return
        def ready(frames):
            if hasattr(workspace, 'camera_grid'):
                # A new 2D capture has no measured 3D markers. Invalidate old pairs.
                workspace.observations.clear()
                workspace._invalidate_extrinsics()
            for cid, frame in frames.items():
                if frame is None:
                    workspace.log(f'{cid} 获取2D画面失败，请检查连接与曝光参数。', 'warn')
                    if hasattr(workspace, 'camera_grid'):
                        workspace.camera_grid.set_frame(cid, None)
                    else:
                        workspace.marker_inspector.set_frame(None, [])
                    continue
                if hasattr(workspace, 'camera_grid'):
                    workspace.camera_grid.set_frame(cid, frame)
                else:
                    workspace.marker_inspector.set_frame(frame.image_np, [], frame_id='相机实时2D预览')
            workspace.log('已刷新相机2D画面；编码圆及深度需另行检测。', task='设备预览')
        workspace._run(self.service.capture_previews, ready, task='读取相机2D画面')

    def _install(self, key, workspace):
        self.key = key
        self.workspace = workspace
        self.setCentralWidget(workspace)
        workspace.function_selection_requested.connect(self.choose_function)
        workspace.function_button.show()
        workspace.preview_button = QPushButton('刷新相机2D画面')
        workspace.preview_button.setEnabled(False)
        workspace.preview_button.clicked.connect(self.capture_previews)
        workspace.parameter_layout.insertWidget(0, workspace.preview_button)
        self.setWindowTitle('MCC · '+self.registry.get(key).title+' · 离线原型')

    def choose_function(self):
        if self.workspace._busy or self.workspace.session.state in ('scanning', 'paused'):
            self.workspace.log('请先完成当前任务再切换功能。', 'warn')
            return
        if not self.workspace.can_leave():
            return
        dialog = FunctionLauncher(self.registry, self, selected=self.key, service=self.service)
        if dialog.exec() == QDialog.Accepted:
            if self.switch_to(dialog.selected_key, dialog.result_count, check_leave=False):
                if dialog.offline:
                    self.service.close()
                self._apply_devices(dialog.connected_devices)
            else:
                self.service.close()
                self._apply_devices([])
        elif not self.service.connected:
            self._apply_devices([])

    def switch_to(self, key, camera_count=None, *, check_leave=True):
        spec = self.registry.get(key)
        count = spec.default_cameras if camera_count is None else camera_count
        if key == self.key and count == self.workspace.camera_count:
            return True
        old = self.workspace
        if old._busy or old.session.state in ('scanning', 'paused') or (check_leave and not old.can_leave()):
            return False
        try:
            candidate = self.registry.create(key, camera_count=count, renderer=self.renderer, load_demo=False)
        except Exception as exc:
            QMessageBox.warning(self, '功能打开失败', str(exc))
            return False
        old.shutdown()
        self._install(key, candidate)
        self._apply_devices([])
        return True

    def closeEvent(self, event):
        if not self.workspace.close():
            event.ignore()
            return
        event.accept()
        self.service.close()
