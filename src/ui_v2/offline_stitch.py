"""Formal offline stitching workspace, using production DB and session lifecycle."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QCheckBox, QSizePolicy, QApplication
from core.offline_pairs import OfflinePairLoader
from .main_window import MainWindowShell
from .backend_bridge import BackendBridge
from .dialogs import ChineseMessageBox as QMessageBox
from version import get_version


class OfflineStitchWindow(MainWindowShell):
    def __init__(self, owner=None, *, on_return=None):
        # An owned native window minimizes onto the desktop when its host is hidden.
        super().__init__()
        self.owner = owner
        if owner is not None:
            # Close/return explicitly decides whether the application should exit.
            self.setAttribute(Qt.WA_QuitOnClose, False)
        self._on_return = on_return if on_return is not None else (
            owner.shell.open_device_manager if owner else None)
        self._returning_to_launcher = False
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
        ribbon._group(row, '导出', [
            ('export', '导出点云', 'layers', lambda: bridge.stitching.export()),
        ], 'mobile_chain')
        ribbon._group(row, '拼接', [
            ('stitch', '标记物拼接', 'stitch', lambda: bridge.stitching.execute()),
            ('stitch_selected', '拼接所选帧', 'stitch', self.stitch_selected),
            ('fpfh', 'FPFH几何匹配', 'cloud_register', self.open_fpfh),
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
        ribbon.offline_button.hide()
        ribbon.return_button.setVisible(self._on_return is not None)
        ribbon.mode_label.setText('离线拼接')
        # Hidden acquisition workspaces must not impose their widths on this file-only window.
        self._stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(1050, 650)
        self.log('离线拼接：加载本地数据，拼接后通过「导出点云」保存结果。')
        ribbon.commands['mobile_chain', 'stitch_selected'].setToolTip(
            '按 Ctrl 或 Shift 多选原始帧或其点云行，再点击此按钮，仅拼接高亮选中的帧')
        self.log('加载离线数据：同名 PNG / PLY 配对，数字编号排序；在DB选择图像或点云检查，勾选原始点云执行拼接。源文件只读。')

    def postprocess_editor_type(self):
        from .postprocess.fpfh_editor import FPFHEditor
        return FPFHEditor

    def stitch_selected(self):
        bridge = self._backend_bridge
        if not bridge.can_change_workspace():
            self.log('请等待当前任务完成后再拼接所选帧。', 'warn')
            return
        browser = bridge.frame_db.browsers['mobile_chain']
        items = browser.tree.selectedItems()
        database = browser.database
        if any(item.data(0, Qt.UserRole) not in database.records
               or item.data(0, Qt.UserRole + 2) == 'image'
               or database.records[item.data(0, Qt.UserRole)].kind != 'raw' for item in items):
            self.log('请按 Ctrl 或 Shift 多选原始帧或点云行，再点击「拼接所选帧」。', 'warn')
            return
        identifiers = browser.selected_ids()
        if len(identifiers) < 2:
            self.log('请按 Ctrl 或 Shift 至少选择两帧原始数据。', 'warn')
            return
        self.log('所选拼接输入：' + '、'.join(database.records[uid].logical_name for uid in identifiers))
        bridge.stitching.execute(('mobile_chain', identifiers, True,
                                 bridge.stitching.plane_filters.get('mobile_chain')))

    def open_fpfh(self):
        if not self._backend_bridge.can_change_workspace():
            self.log('请等待当前任务完成后再进入FPFH几何匹配。', 'warn')
            return None
        editor = self._backend_bridge.open_postprocess()
        if editor is not None:
            editor.request_fpfh()
        return editor

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
            next_frame_id = max((record.frame_id for record in database.records.values()), default=0) + 1
            for pair in pairs:
                try:
                    frame = self.workflow.load_pair(pair)
                    frame.kind = 'raw'
                    frame.frame_id = next_frame_id
                    uid = database.ingest(frame, purpose='扫描数据', camera='离线相机', logical_name=pair.name)
                    imported.append(uid)
                    next_frame_id += 1
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

    def return_to_launcher(self):
        if self._on_return is None or self._returning_to_launcher:
            return
        self._returning_to_launcher = True
        if self.close():
            self._on_return()
        else:
            self._returning_to_launcher = False

    def _close_event_impl(self, event):
        if any(project.dirty for project in self._backend_bridge.projects.projects.values()):
            answer = QMessageBox.warning(
                self, '退出离线拼接',
                '退出将清理本次离线拼接数据。需要保留的结果请先导出点云。是否放弃本次数据并退出？',
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Discard:
                event.ignore()
                return
        self._log_panel.detach_loggers()
        event.accept()

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
                if not self._returning_to_launcher and not self.owner.shell.isVisible():
                    # Startup can enter this owned window while its host stays hidden.
                    # Qt does not emit lastWindowClosed for an owned secondary window.
                    QApplication.instance().quit()
