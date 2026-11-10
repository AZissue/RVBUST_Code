"""Formal offline stitching workspace, using production DB and session lifecycle."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QCheckBox, QSizePolicy, QApplication
from core.offline_pairs import OfflinePairLoader
from .main_window import MainWindowShell
from .backend_bridge import BackendBridge
from version import get_version


class OfflineStitchWindow(MainWindowShell):
    def __init__(self, owner=None):
        super().__init__(owner.shell if owner else None)
        self.owner = owner
        self._offline_stitch = True
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        bridge = BackendBridge(self)
        bridge.wire_all()
        bridge._current_mode = 'mobile_chain'
        bridge.offline_preview = True
        bridge.recognition.enabled = False
        bridge.projects.projects['mobile_chain'].name = '未命名离线拼接'
        bridge.projects.update('mobile_chain')
        self._offline_preview = True
        self.set_backend_bridge(bridge)
        self.set_mode('mobile_chain', [])
        self.set_presentation('industrial')
        self.setWindowTitle('MCC · 离线拼接 · '+get_version())
        self.workflow = OfflinePairLoader(bridge.marker_detector)
        ribbon = self._industrial_ribbon
        for mode, page in ribbon._pages.items():
            if mode != 'mobile_chain':
                ribbon.pages.removeWidget(page)
                page.hide()
        row = ribbon._pages['mobile_chain'].layout()
        # Keep production command objects alive: its state synchronizer uses them.
        for i in reversed(range(row.count())):
            widget = row.itemAt(i).widget()
            if widget:
                widget.hide()
            else:
                row.takeAt(i)
        ribbon._group(row, '加载离线数据', [
            ('load_pairs', '加载数据目录', 'folder_open', self.select_directory),
        ], 'mobile_chain')
        ribbon._group(row, '项目', [
            ('new', '新建会话', 'folder_open', bridge.projects.new_dialog),
            ('manage', '会话管理', 'layers', bridge.projects.manage),
            ('open', '打开会话', 'folder_open', self.open_session_requested.emit),
            ('save', '保存会话', 'save', self.save_session_requested.emit),
            ('export', '导出点云', 'layers', lambda: bridge.stitching.export()),
        ], 'mobile_chain')
        ribbon._group(row, '拼接', [
            ('stitch', '执行拼接', 'stitch', lambda: bridge.stitching.execute()),
        ], 'mobile_chain')
        ribbon._group(row, '视图', [
            ('restore', '返回视图', 'undo', ribbon.restore_view),
            ('fit', '适配视图', 'reset_view', ribbon.fit_view),
        ], 'mobile_chain')
        ribbon._group(row, '后处理', [
            ('postprocess', '点云后处理', 'layers', bridge.open_postprocess),
        ], 'mobile_chain')
        row.addStretch(1)
        self.recursive = QCheckBox('递归扫描子目录')
        self.recursive.setChecked(True)
        row.addWidget(self.recursive)
        ribbon.update_status()
        ribbon.mode_label.setText('离线拼接')
        self._btn_devices.hide()
        self._st_devices.hide()
        presentation = self.workspace_mobile()._industrial
        presentation.view_pages.preview_button.hide()
        properties = presentation.frame_browser.properties
        properties.tabs.setTabVisible(properties.tabs.indexOf(properties.capture), False)
        ribbon.experiment_button.hide()
        ribbon.offline_button.hide()
        ribbon.mode_label.setText('离线拼接')
        # Hidden acquisition workspaces must not impose their widths on this file-only window.
        self._stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(1050, 650)
        self.log('正式离线拼接：会话手动保存到 sessions；可载入旧实验会话。')
        self.log('加载离线数据：同名 PNG / PLY 配对，数字编号排序；在DB选择图像或点云检查，勾选原始点云执行拼接。源文件只读。')

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, '加载离线数据：同编号 PNG / PLY')
        if directory:
            self.load_directory(directory)

    def load_directory(self, directory):
        bridge = self._backend_bridge
        if not bridge.can_change_workspace():
            return
        database = bridge.frame_db.databases['mobile_chain']
        recursive = self.recursive.isChecked()
        self.show_loading('正在加载离线文件对与标记...')
        def work():
            pairs = self.workflow.load_directory(directory, recursive=recursive)
            if not pairs:
                raise ValueError('未找到同名图像/PLY文件对')
            imported, failed = [], []
            for pair in pairs:
                try:
                    frame = self.workflow.load_pair(pair)
                    frame.kind = 'raw'
                    uid = database.ingest(frame, purpose='扫描数据', camera='离线相机', logical_name=pair.name)
                    imported.append(uid)
                except Exception as exc:
                    failed.append(f'{pair.name}：{exc}')
            return imported, failed
        def done(result, error):
            self.hide_loading()
            bridge.frame_db.browsers['mobile_chain'].refresh()
            self._industrial_ribbon.update_status()
            if error:
                self.log('离线加载失败：' + str(error), 'error')
                return
            imported, failed = result
            if imported:
                bridge.projects.mark_changed('mobile_chain')
            self.log(f'已加载 {len(imported)} 对离线数据；原始图像与点云已加入DB。')
            for message in failed:
                self.log('加载失败：' + message, 'error')
        return bridge._run_background(work, done, must_finish=True, name='project_offline_pair_import')

    def _refresh_statusbar(self):
        super()._refresh_statusbar()
        if getattr(self, '_offline_stitch', False):
            self._st_mode.setText('离线拼接')

    def open_device_manager(self):
        self.log('离线拼接使用本地文件，无需连接设备。', 'info')

    def closeEvent(self, event):
        if not self._backend_bridge.can_change_workspace():
            self.log('请等待当前离线任务完成后关闭。', 'warn')
            event.ignore()
            return
        editor = getattr(self._backend_bridge, '_postprocess_window', None)
        if editor is not None and not editor._closed:
            editor.close()
            if not editor._closed:
                event.ignore()
                return
        super().closeEvent(event)
        if event.isAccepted():
            self._backend_bridge.cleanup()
            if self.owner:
                self.owner.shell._offline_stitch_window = None
                if not self.owner.shell.isVisible():
                    # Startup can enter this owned window while its host stays hidden.
                    # Qt does not emit lastWindowClosed for an owned secondary window.
                    QApplication.instance().quit()
