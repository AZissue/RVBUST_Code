"""Read UI state for the header/footer without a second camera panel."""
from PySide6.QtCore import QObject, QTimer


class MultiCameraStatus(QObject):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.active = False
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        workspace._camera_grid.frames_changed.connect(self.refresh)

    def set_active(self, active):
        self.active = active
        if active:
            self.timer.start()
            self.refresh()
        else:
            self.timer.stop()

    def refresh(self):
        if not self.active:
            return
        window = self.workspace.window()
        if getattr(window, '_mode', '') != 'multi_cam':
            return
        devices = {f'cam{i}': device for i, device in enumerate(getattr(self.workspace, '_devices', []))}
        cards = self.workspace._camera_grid._cards
        offline = getattr(self.workspace, 'offline_preview', False)
        online_count = preview_count = 0
        status, details = [], []
        for cid, card in cards.items():
            online = bool(cid in devices and devices[cid].online and not offline)
            online_count += online
            preview_count += card._btn_preview.isChecked()
            color = '#55c88a' if online else '#dca45c' if card.current_frame() is not None else '#858585'
            state = '在线' if online else '离线数据' if card.current_frame() is not None else '离线'
            status.append(f'<span style="color:{color}">● {cid}</span>')
            details.append(f'{cid}: {state}')
        ribbon = getattr(window, '_industrial_ribbon', None)
        if ribbon:
            ribbon.camera_status.setText(f'{online_count}/{len(cards)} 在线  ' + '  '.join(status[:6]))
            ribbon.camera_status.setToolTip('\n'.join(details))
            step = {'idle': 0, 'connected': 1, 'captured': 2, 'detected': 3,
                    'calibrated': 3, 'locked': 4}.get(self.workspace.current_state(), 0)
            titles = ('连接设备', '采集数据', '检测标记', '计算外参', '扫描拼接')
            ribbon.workflow_status.setText('  ›  '.join(
                f'<span style="color:{"#eeeeee" if i == step else "#777777"}">{i+1} {title}</span>'
                for i, title in enumerate(titles)))
        summary = getattr(window, '_st_multi', None)
        if summary:
            gate = '门禁通过' if self.workspace._quality_passed else '门禁待通过'
            summary.setText(f'{online_count}/{len(cards)} 在线 · {preview_count} 路预览 · {gate}')
