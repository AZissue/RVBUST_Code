"""Device rows mirror production controls; polling reads UI state only."""
from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QToolButton, QScrollArea, QCheckBox)


class MultiCameraOverview(QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.rows = {}
        self._cards = ()
        self.setMinimumHeight(110)
        self.setMaximumHeight(245)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        header = QHBoxLayout()
        header.addWidget(QLabel('设备与取景'), 1)
        manage = QToolButton()
        self.manage_button = manage
        manage.setText('管理 / 添加')
        manage.setToolTip('打开现有设备管理流程，选择或重新连接相机')
        manage.clicked.connect(self._manage)
        header.addWidget(manage)
        layout.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(3)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.refresh()
        workspace._camera_grid.frames_changed.connect(self.refresh)

    def _manage(self):
        window = self.workspace.window()
        if hasattr(window, '_btn_devices'):
            window._btn_devices.click()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self):
        grid = self.workspace._camera_grid
        cards = tuple(grid._cards.items())
        if cards != self._cards:
            self._cards = cards
            self.rows.clear()
            while self.list_layout.count():
                item = self.list_layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()
            for cid, card in cards:
                row = QWidget()
                row.setMaximumHeight(58)
                line = QHBoxLayout(row)
                line.setContentsMargins(5, 4, 5, 4)
                labels = QVBoxLayout()
                name, detail = QLabel(), QLabel()
                detail.setStyleSheet('color:#929292;font-size:11px;')
                labels.addWidget(name)
                labels.addWidget(detail)
                line.addLayout(labels, 1)
                preview = QCheckBox('预览')
                preview.setToolTip('此相机的2D预览开关；复用正式采集控制')
                preview.toggled.connect(lambda checked, source=card._btn_preview:
                    source.click() if source.isEnabled() and source.isChecked() != checked else None)
                line.addWidget(preview)
                self.list_layout.addWidget(row)
                self.rows[cid] = (name, detail, preview)
            self.list_layout.addStretch(1)
        devices = getattr(self.workspace, '_devices', [])
        offline = getattr(self.workspace, 'offline_preview', False)
        online_count = preview_count = 0
        status = []
        for index, (cid, card) in enumerate(cards):
            device = next((device for i, device in enumerate(devices) if cid == f'cam{i}'), None)
            online = bool(device and device.online and not offline)
            online_count += online
            preview_count += card._btn_preview.isChecked()
            color = '#55c88a' if online else '#dca45c' if card.current_frame() is not None else '#858585'
            state = '在线' if online else '离线数据' if card.current_frame() is not None else '离线'
            name, detail, preview = self.rows[cid]
            name.setText(f'<span style="color:{color}">●</span> <b>{cid}</b> · {state}')
            name.setToolTip(card._name.toolTip() or card._name.text())
            frame = card.current_frame()
            size = f'{frame.image_np.shape[1]} × {frame.image_np.shape[0]}' if frame is not None and frame.image_np is not None else '等待图像'
            detail.setText(size + ' · ' + card.preview_rate_text())
            detail.setToolTip(f'{device.model} · {device.serial} · {device.ip}' if device else '会话中的相机数据，未确认实体连接')
            with QSignalBlocker(preview):
                preview.setChecked(card._btn_preview.isChecked())
                preview.setEnabled(card._btn_preview.isEnabled())
            status.append(f'<span style="color:{color}">● {cid}</span>')
        window = self.workspace.window()
        if hasattr(window, '_btn_devices'):
            self.manage_button.setEnabled(window._btn_devices.isEnabled())
        if getattr(window, '_mode', '') == 'multi_cam':
            ribbon = getattr(window, '_industrial_ribbon', None)
            if ribbon:
                ribbon.camera_status.setText(f'{online_count}/{len(cards)} 在线  ' + '  '.join(status[:6]))
                ribbon.camera_status.setToolTip('\n'.join(f'{cid}: {self.rows[cid][0].text()}' for cid, _ in cards))
                state = self.workspace.current_state()
                step = {'idle': 0, 'connected': 1, 'captured': 2, 'detected': 3, 'calibrated': 3, 'locked': 4}.get(state, 0)
                titles = ('连接设备', '采集数据', '检测标记', '计算外参', '扫描拼接')
                ribbon.workflow_status.setText('  ›  '.join(
                    f'<span style="color:{"#eeeeee" if i == step else "#777777"}">{i+1} {title}</span>'
                    for i, title in enumerate(titles)))
            summary = getattr(window, '_st_multi', None)
            if summary:
                gate = '门禁通过' if self.workspace._quality_passed else '门禁待通过'
                summary.setText(f'{online_count}/{len(cards)} 在线 · {preview_count} 路预览 · {gate}')
