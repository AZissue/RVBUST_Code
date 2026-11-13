"""Industrial postprocess workspace: DB snapshots in, immutable result branches out."""
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QSize, QSignalBlocker, QItemSelectionModel, QTimer
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSplitter, QToolButton, QFileDialog, QMenu, QScrollArea, QGroupBox)
from ui_common.industrial_viewer import IndustrialViewer
from ui_common.worker_thread import WorkerThread
from ui_common.symbols import icon
from core.frame_database import STALE_RESULT
from core.postprocess.session import CloudLayer, read_cloud, write_cloud
from core.postprocess.processing import polygon_crop_mask, voxel_downsample, random_downsample
from ..widgets import FloatingLogPanel
from ..frame_database import FrameBrowser
from ..industrial_ribbon import STYLE
from ..dialogs import ChineseMessageBox as QMessageBox
from .selection import PolygonSelectionOverlay
from .viewport_tools import SegmentationToolbar
from .downsample_dialog import DownsampleDialog
from .import_dialog import ImportDialog


class PostprocessWindow(QDialog):
    def __init__(self, bridge, mode, parent=None):
        super().__init__(parent or bridge.shell)
        self.bridge, self.mode = bridge, mode
        self.database = bridge.frame_db.databases[mode]
        self.directory = self.database.directory
        self._clouds = {}
        self._display_ids = []
        self._active_uid = None
        self._undo = []
        self._syncing = False
        self._selection_generation = 0
        self._load_version = 0
        self._pending_load = None
        self._pending_intermediates = None
        self._busy_kind = None
        self._loading_ids = None
        self._worker = None
        self._segment = None
        self._closed = False
        self._import_unit = 'mm'
        self._downsample_state = {'method': 'voxel', 'voxel': 2.0, 'ratio': 50.0}
        self.setWindowTitle('MCC · 点云后处理')
        self.setWindowModality(Qt.WindowModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setObjectName('industrialRibbon')
        self.setStyleSheet(STYLE)
        self.resize(1440, 900)
        self.setMinimumSize(1050, 650)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        header = QWidget(objectName='studioHeader')
        line = QHBoxLayout(header)
        line.addWidget(QLabel('MCC', objectName='studioLogo'))
        line.addWidget(QLabel('SCAN STUDIO', objectName='studioBrand'))
        line.addWidget(QLabel('点云后处理', objectName='studioMode'))
        line.addStretch()
        line.addWidget(QLabel('当前项目 · mm', objectName='studioBadge'))
        self._btn_log = QToolButton()
        self._btn_log.setText('运行日志')
        self._btn_log.setIcon(icon('terminal', '#dddddd', 15))
        self._btn_log.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn_log.setCheckable(True)
        self._btn_log.toggled.connect(self._toggle_log)
        line.addWidget(self._btn_log)
        root.addWidget(header)
        self.operation_bar = QWidget()
        actions = QHBoxLayout(self.operation_bar)
        actions.setContentsMargins(4, 0, 4, 0)
        actions.setSpacing(4)
        self.actions = {}
        for key, text, glyph, callback in (
            ('open', '导入点云', 'folder_open', self.open_import_dialog),
            ('downsample', '下采样', 'cloud_sample', self.open_downsample_dialog),
            ('manual', '手动配准', 'cloud_register', self.open_manual_registration),
            ('intermediate', '提取中间帧', 'layers', self.extract_intermediates),
            ('icp', 'ICP精配准', 'cloud_register', self.open_icp_dialog),
            ('merge', '合并点云', 'cloud_merge', self.merge_selected),
            ('select', '多边形框选', 'polygon', self.start_polygon),
            ('undo', '撤销处理', 'undo', self.undo),
            ('export', '导出选中', 'cloud_export', self.export_selected),
            ('probe', '点云探针', 'cloud_probe', self.open_probe_dialog),
            ('fit', '适配视图', 'reset_view', lambda: self.viewer.reset_view()),
            *self.extra_actions()):
            button = QToolButton()
            button.setText(text)
            button.setIcon(icon(glyph, '#dddddd', 23))
            button.setIconSize(QSize(23, 23))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setMinimumSize(78, 58)
            button.clicked.connect(callback)
            actions.addWidget(button)
            self.actions[key] = button
        self.actions['downsample'].setToolTip(
            '下采样：体素下采样或随机抽样；参数在独立弹窗设置；结果新增到 DB，原始数据保留')
        self.actions['open'].setToolTip('导入点云：在独立弹窗确认源文件单位后选择文件')
        self.actions['icp'].setToolTip('选择一项原始拼接结果按来源帧重建，或勾选两项点云精配准；新增结果，保留全部有效点')
        self.actions['probe'].setToolTip('点云探针：检测点间距与重合比例，结果显示在数据属性中；点击分析后开始只读计算')
        self.actions['select'].setCheckable(True)
        self.actions['select'].setToolTip('选取分割：左键添加顶点，封闭后选择保留方向并点击快捷删除')
        self.actions['select'].setAccessibleName('多边形框选')
        actions.addStretch()
        root.addWidget(self.operation_bar)
        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        self._content_split = QSplitter(Qt.Vertical)
        self._content_split.setChildrenCollapsible(False)
        root.addWidget(self._content_split, 1)
        self._content_split.addWidget(body)
        self._log_panel = FloatingLogPanel(self, docked=True)
        self._content_split.addWidget(self._log_panel)
        self._log_panel.closed.connect(lambda: self._btn_log.setChecked(False))
        self._log_panel.hide()
        self._shared_log = bridge.shell._log_panel
        self._log_panel.records.extend(self._shared_log.records)
        self._log_signal = getattr(self._shared_log, 'record_added', None)
        self._log_sync_timer = QTimer(self)
        self._log_sync_timer.setInterval(250)
        self._log_sync_timer.timeout.connect(self._sync_log_history)
        if self._log_signal is not None:
            self._log_signal.connect(self._receive_log)
        else:
            # An already running shell may still own the earlier log widget.
            self._log_sync_timer.start()
        left = QSplitter(Qt.Vertical)
        left.setChildrenCollapsible(False)
        left.setMinimumWidth(300)
        self.source_browser = FrameBrowser(self.database)
        self.source_browser.properties.hide()
        self.source_browser.footer.hide()
        self.source_browser.tree.customContextMenuRequested.disconnect()
        self.source_browser.tree.customContextMenuRequested.connect(self._source_menu)
        self.source_browser.tree.itemSelectionChanged.connect(self._selection_requested)
        self.source_browser.tree.itemClicked.connect(self._selection_requested)
        self.source_browser.checked_components_changed.connect(self._checks_requested)
        left.addWidget(self.source_browser)
        self.viewer = IndustrialViewer()
        self.viewer.toolbar.hide()
        # Reuse the DB inspector so selection and metadata retain one owner.
        self.properties = self.source_browser.properties
        from .probe_panel import ProbePanel
        self.probe_dialog = QDialog(self)
        self.probe_dialog.setWindowTitle('点云探针 · 当前点云（mm）')
        self.probe_dialog.resize(640, 650)
        self.probe_dialog.setMinimumSize(460, 380)
        probe_layout = QVBoxLayout(self.probe_dialog)
        probe_scroll = QScrollArea()
        probe_scroll.setWidgetResizable(True)
        probe_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.probe = ProbePanel()
        probe_scroll.setWidget(self.probe)
        probe_layout.addWidget(probe_scroll)
        self.probe.analyze.connect(self.analyze_probe)
        self._probe_report = None
        self._probe_reports = {}
        self.probe_reference = QGroupBox('后处理参考值 · 手动设置')
        self.probe_reference.setStyleSheet('QGroupBox { border:1px solid #618477; border-radius:5px; margin-top:10px; padding:10px 6px 6px; color:#a8e4c5; }')
        reference_layout = QVBoxLayout(self.probe_reference)
        self.probe_reference_text = QLabel()
        self.probe_reference_text.setTextFormat(Qt.PlainText)
        self.probe_reference_text.setWordWrap(True)
        self.probe_reference_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.probe_reference_text.setStyleSheet('color:#c8f0d9; font-size:13px; font-weight:600;')
        reference_layout.addWidget(self.probe_reference_text)
        self.properties.data_layout.insertWidget(0, self.probe_reference)
        self.probe_reference.hide()
        self.probe_properties = QLabel('尚未检测：点击顶部“点云探针”分析当前点云。')
        self.probe_properties.setWordWrap(True)
        self.probe_properties.setTextFormat(Qt.PlainText)
        self.probe_properties.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.properties.data_layout.addWidget(QLabel('点云检测结果（只读参考）'))
        self.properties.data_layout.addWidget(self.probe_properties)
        # Retain the key for shared renderer binding; hide only this control.
        self.properties.options['marker_centers'].hide()
        self.properties.bind_renderer(self.viewer)
        self.properties.max_button.hide()
        self.properties.tabs.removeTab(3)
        self.properties.tabs.removeTab(2)
        left.addWidget(self.properties)
        self.properties.show()
        left.setStretchFactor(0, 1)
        left.setStretchFactor(1, 1)
        left.setSizes([280, 440])
        body.addWidget(left)
        body.addWidget(self.viewer)
        body.setSizes([330, 1110])
        self.overlay = PolygonSelectionOverlay(self.viewer.canvas)
        self.overlay.polygon_confirmed.connect(self.stage_polygon)
        self.overlay.cancelled.connect(self._invalidate_polygon)
        self._install_viewport_tools()
        self.viewer.canvas_changed.connect(self._renderer_changed)
        self.status = QLabel('在 DB 树中选择或勾选点云；处理完成后自动生成 DB 结果。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        root.addWidget(self.status)
        self._refresh_controls()

    def _receive_log(self, record):
        if self._closed:
            return
        self._log_panel.records.append(record)
        self._log_panel._schedule()

    def _sync_log_history(self):
        if self._closed:
            return
        records = list(self._shared_log.records)
        if records != list(self._log_panel.records):
            self._log_panel.records.clear()
            self._log_panel.records.extend(records)
            self._log_panel._schedule()

    def _toggle_log(self, checked):
        self.status.setVisible(not checked)
        self._log_panel.setVisible(checked)
        if checked:
            height = self._content_split.height()
            self._content_split.setSizes([max(160, height - 240), 240])

    def _set_status(self, message):
        self.status.setText(message)
        level = 'error' if '失败' in message else 'warn' if any(
            word in message for word in ('拒绝', '请先', '已变化', '不能')) else 'info'
        self.bridge.shell.log(message, level)

    def _parameter_gate(self):
        return (self._worker is None and not self._closed and self.bridge.can_change_workspace()
                and self.database is self.bridge.frame_db.databases[self.mode]
                and self.database.directory == self.directory)

    def _input_snapshot(self):
        return (self.database, self.database.directory, self._active_uid, tuple(self._display_ids),
                tuple((uid, self.database.records[uid].revision if uid in self.database.records else None)
                      for uid in self._display_ids))

    def create_import_dialog(self):
        dialog = ImportDialog(self._import_unit, self)
        dialog.unit_changed.connect(lambda unit: setattr(self, '_import_unit', unit))
        return dialog

    def open_import_dialog(self):
        if not self._parameter_gate():
            return
        snapshot = self._input_snapshot()
        dialog = self.create_import_dialog()
        accepted = []
        dialog.accepted.connect(lambda: accepted.append(dialog.unit()))
        if dialog.exec() == QDialog.Accepted:
            if snapshot != self._input_snapshot() or not self._parameter_gate():
                self._set_status('输入或项目已变化，请重新打开导入参数。')
                return
            self.open_file(accepted[0], snapshot=snapshot)

    def _renderer_changed(self, *_):
        self._invalidate_polygon()
        self.overlay.deleteLater()
        self.overlay = PolygonSelectionOverlay(self.viewer.canvas)
        self.overlay.polygon_confirmed.connect(self.stage_polygon)
        self.overlay.cancelled.connect(self._invalidate_polygon)
        self._install_viewport_tools()
        self.properties.bind_renderer(self.viewer)
        self.properties.max_button.hide()
        self._refresh_controls()

    def _install_viewport_tools(self):
        canvas = self.viewer.canvas
        self.segment_tools = SegmentationToolbar(canvas, dict(
            close=lambda: self.overlay._confirm(),
            back=lambda: self.overlay.remove_last_vertex(),
            delete=lambda: self.apply_segment(self.segment_tools.buttons['inside'].isChecked()),
            color_filter=self.extra_segment_action(),
            cancel=self._invalidate_polygon))
        self.overlay.changed.connect(self._refresh_segment_tools)
        canvas.view_changed.connect(self._selection_view_changed)
        self._refresh_segment_tools()

    def _refresh_segment_tools(self):
        ready = (self._worker is None and not self._closed and self.bridge.can_change_workspace()
                 and self.database is self.bridge.frame_db.databases[self.mode]
                 and self.database.directory == self.directory)
        record = self.database.records.get(self._active_uid)
        available = (self._active_uid in self._clouds and record is not None
                     and record.status != STALE_RESULT
                     and self._clouds[self._active_uid].origins == ((record.uid, record.revision),))
        self.actions['select'].setEnabled(ready and available)
        self.actions['select'].setChecked(self.overlay.active)
        self.segment_tools.refresh(ready=ready,
            available=available, overlay=self.overlay,
            staged=self._segment is not None,
            color_available=available and self._clouds[self._active_uid].colors is not None)

    def extra_actions(self):
        return ()

    def extra_segment_action(self):
        return None

    def refresh_extra_actions(self, ready):
        pass

    def _selection_view_changed(self):
        if self.overlay.active or self._segment is not None:
            self._invalidate_polygon()
            self._set_status('视角已移动，旧框选已清除；可点击顶部多边形框选重新绘制。')

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.overlay.active:
            self._invalidate_polygon()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _source_menu(self, pos):
        self.source_browser._select_context_target(pos)
        menu = QMenu(self)
        menu.addAction('显示选中点云', self.load_selected)
        menu.addAction('导出选中点云…', self.export_selected)
        menu.addSeparator()
        ready = self._worker is None and not self._closed and self.bridge.can_change_workspace()
        action = menu.addAction('删除选中点云', self.delete_selected)
        action.setEnabled(ready and bool(self._selected_cloud_ids()))
        action = menu.addAction('恢复上次删除', lambda: self._mutate_database(recover=True))
        action.setEnabled(ready and bool(self.database.removed))
        menu.exec(self.source_browser.tree.viewport().mapToGlobal(pos))

    def _selected_cloud_ids(self):
        identifiers = set()
        def visit(item):
            if item.data(0, Qt.UserRole + 2) == 'image':
                return
            uid = item.data(0, Qt.UserRole)
            if uid in self.database.records:
                identifiers.add(uid)
            else:
                for index in range(item.childCount()):
                    visit(item.child(index))
        for item in self.source_browser.tree.selectedItems():
            visit(item)
        return [uid for uid in self.database.records if uid in identifiers]

    def delete_selected(self):
        self._mutate_database()

    def _mutate_database(self, *, recover=False):
        if self._closed or self._worker is not None or not self.bridge.can_change_workspace():
            return
        if (self.database is not self.bridge.frame_db.databases[self.mode]
                or self.database.directory != self.directory):
            self._set_status('项目已切换，请重新打开后处理窗口。')
            return
        identifiers = self._selected_cloud_ids()
        if not recover:
            if not identifiers:
                return
            text = f'从DB移除选中的 {len(identifiers)} 项点云？数据移至项目回收区，可恢复。'
            if any(self.database.records[uid].kind == 'raw' for uid in identifiers):
                text += '\n选中的原始帧会连同对应2D图像一并移除。'
            if QMessageBox.question(self, '删除选中点云', text,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        elif not self.database.removed:
            return
        controller = self.bridge.frame_db
        previous_results = {uid for uid, row in self.database.records.items() if row.kind == 'result'}
        frames = controller._frames()
        self._pending_load = None
        self._load_version += 1
        controller.restore(self.mode)
        def done(moves):
            controller._finish_mutation(self.mode, moves, previous_results, frames)
            self._undo = [entry for entry in self._undo
                          if all(uid in self.database.records for tokens in entry for uid, _ in tokens)]
            remaining = [self._clouds[uid] for uid in self._display_ids if uid in self.database.records]
            self._show_records(remaining, refresh=True)
            self.bridge.shell.set_dirty(True)
            verb = '恢复' if recover else '删除'
            message = f'已{verb} {len(moves)} 项DB点云。'
            self._set_status(message)
        work = self.database.restore_last_removal if recover else lambda: self.database.remove(identifiers)
        self._run(work, done)

    def _selection_requested(self, *_):
        if self._syncing or self._closed:
            return
        items = self.source_browser.tree.selectedItems()
        if items and all(item.data(0, Qt.UserRole + 2) == 'image' for item in items):
            return
        if items and all(item.data(0, Qt.UserRole + 3) for item in items):
            # Virtual operation frames select outputs for explicit actions only.
            return
        identifiers = self.source_browser.selected_ids()
        if identifiers:
            self.load_selected(identifiers)

    def _checks_requested(self, checked):
        if not self._syncing and not self._closed:
            self.load_selected([uid for uid, component in checked if component == 'cloud'])

    def _run(self, work, done, *, kind='edit', preserve_selection=False, on_error=None):
        if self._worker is not None or self._closed:
            return False
        if not preserve_selection:
            self._invalidate_polygon()
        from time import perf_counter
        started = perf_counter()
        timer = QTimer(self)
        timer.setInterval(500)
        def update_progress():
            if not self._closed:
                phase = (getattr(self,'_progress_state',None) or {}).get('stage','后台处理并更新DB')
                self.status.setText(f'{phase}… 已用时 {perf_counter()-started:.1f} 秒')
        timer.timeout.connect(update_progress)
        timer.start()
        worker = WorkerThread(work)
        self._worker, self._busy_kind = worker, kind
        worker._task_name = 'postprocess'
        worker._must_finish = True
        self.bridge._workers.append(worker)

        def completed(result, error):
            timer.stop()
            if self._closed:
                return
            if error:
                if preserve_selection:
                    self._invalidate_polygon()
                self._set_status('处理失败：' + str(error))
                if on_error:
                    on_error(error)
            else:
                self._set_status('处理完成。')
                try:
                    done(result)
                except Exception as exc:
                    if preserve_selection:
                        self._invalidate_polygon()
                    self._set_status('更新结果失败：' + str(exc))

        def finished():
            timer.stop()
            timer.deleteLater()
            self._progress_state = None
            if worker in self.bridge._workers:
                self.bridge._workers.remove(worker)
            self._worker, self._busy_kind = None, None
            worker.deleteLater()
            if not self._closed:
                self._refresh_controls()
                self.bridge.shell._industrial_ribbon.update_status()
                if self._pending_load is not None:
                    pending, self._pending_load = self._pending_load, None
                    self._pending_intermediates = None
                    self.load_selected(pending)
                elif self._pending_intermediates is not None:
                    uid, self._pending_intermediates = self._pending_intermediates, None
                    if self._display_ids == [uid]:
                        self.extract_intermediates(automatic=True)
        worker.result_ready.connect(completed)
        worker.finished.connect(finished)
        self._refresh_controls()
        self._set_status('正在后台读取点云…' if kind == 'load' else '正在处理并更新 DB…')
        worker.start()
        return True

    def _refresh_controls(self):
        ready = self._worker is None
        for button in self.actions.values():
            button.setEnabled(ready)
        self.source_browser.setEnabled(ready)
        self.actions['undo'].setEnabled(ready and bool(self._undo))
        self.actions['manual'].setEnabled(self._parameter_gate() and len(self._display_ids) == 2)
        self.actions['intermediate'].setEnabled(self._parameter_gate() and len(self._display_ids) == 1)
        self.actions['icp'].setEnabled(self._parameter_gate() and len(self._display_ids) in (1, 2))
        self.actions['merge'].setEnabled(ready and len(self._display_ids) > 1)
        self.actions['downsample'].setEnabled(ready and self._active_uid in self._clouds)
        self.actions['select'].setEnabled(ready and self._active_uid in self._clouds)
        locked = self.overlay.view_locked
        self.actions['fit'].setEnabled(ready and not locked)
        self.properties.setEnabled(ready and not locked)
        self.actions['probe'].setEnabled(self._parameter_gate() and self._active_uid in self._clouds)
        self.probe.setEnabled(self._parameter_gate())
        self._refresh_probe_properties()
        self.refresh_extra_actions(ready)
        self._refresh_segment_tools()

    def _refresh_display(self, *, fit=False):
        self.viewer.replace_pointclouds(
            {uid: self._clouds[uid] for uid in self._display_ids if uid in self._clouds}, fit=fit)

    def _show_records(self, layers, *, refresh=False, fit=False, select=True):
        """GUI-only completion: model rebuilds never run in itemChanged handlers."""
        self.probe.reset()
        self._probe_report = None
        self._invalidate_polygon()
        self._clouds = {layer.origins[0][0]: layer for layer in layers}
        self._display_ids = list(self._clouds)
        if self._active_uid not in self._clouds:
            self._active_uid = next(iter(self._clouds), None)
        self._syncing = True
        try:
            if refresh:
                self.source_browser.refresh()
            with QSignalBlocker(self.source_browser.tree):
                for (uid, component), item in self.source_browser._component_items.items():
                    if component == 'cloud':
                        item.setCheckState(0, Qt.Checked if uid in self._clouds else Qt.Unchecked)
                if select:
                    self.source_browser.tree.clearSelection()
                    for uid in self._display_ids:
                        item = self.source_browser._component_items.get((uid, 'cloud'))
                        if item is not None:
                            item.setSelected(True)
                    current = self.source_browser._component_items.get((self._active_uid, 'cloud'))
                    self.source_browser.tree.setCurrentItem(current, 0, QItemSelectionModel.NoUpdate)
                    if current is not None:
                        self.source_browser.tree.scrollToItem(current)
            self.source_browser._selection_changed()
            self.source_browser._publish_checks()
        finally:
            self._syncing = False
        self._refresh_display(fit=fit)
        self._refresh_controls()

    def _validate_source(self, directory, tokens):
        if (self.database.directory != directory
                or self.database is not self.bridge.frame_db.databases[self.mode]):
            raise ValueError('项目已切换，请重新打开后处理窗口。')
        for uid, revision in tokens:
            record = self.database.records.get(uid)
            if record is None or record.revision != revision or record.status == STALE_RESULT:
                raise ValueError('来源数据已删除、替换或失效，请重新选择。')

    def _read_records(self, directory, tokens):
        layers = []
        with self.database._lock:
            self._validate_source(directory, tokens)
            for uid, revision in tokens:
                record = self.database.records[uid]
                _, cloud = self.database.load_frame(uid, 'cloud')
                layers.append(CloudLayer(record.logical_name, np.asarray(cloud.points),
                    np.asarray(cloud.colors) if cloud.has_colors() else None,
                    source=f'DB · {record.logical_name}', origins=((uid, revision),)))
        return layers

    def load_selected(self, identifiers=None, *, auto_intermediates=False):
        if isinstance(identifiers, bool) or identifiers is None:
            identifiers = self.source_browser.selected_ids() or [
                uid for uid, _ in self.source_browser.checked_components('cloud')]
        identifiers = list(dict.fromkeys(identifiers))
        if self._closed:
            return
        if self._worker is not None:
            if self._busy_kind in ('load', 'probe'):
                if self._pending_load == identifiers or (self._pending_load is None and self._loading_ids == identifiers):
                    return
                self._load_version += 1
                self._pending_load = identifiers
            return
        self._load_version += 1
        version = self._load_version
        if not identifiers:
            self._show_records([], select=False)
            self._set_status('请选择或勾选 DB 点云。')
            return
        directory = self.directory
        current = self.source_browser.tree.currentItem()
        active = current.data(0, Qt.UserRole) if current is not None else None
        self._loading_ids = identifiers
        with self.database._lock:
            if any(uid not in self.database.records for uid in identifiers):
                self._set_status('来源数据已变化，请重新选择。')
                return
            tokens = [(uid, self.database.records[uid].revision) for uid in identifiers]
        def done(layers):
            if version != self._load_version:
                return
            self._active_uid = active if active in identifiers else identifiers[0]
            self._show_records(layers, fit=True)
            self._set_status(f'已显示 {len(layers)} 项 DB 点云；处理完成后自动新增结果。')
            if auto_intermediates and len(identifiers) == 1:
                row = self.database.records[identifiers[0]]
                if row.kind == 'result' and not row.intermediate_of and row.purpose != '后处理结果' and len(row.source_transforms) >= 2:
                    self._pending_intermediates = row.uid
        self._run(lambda: self._read_records(directory, tokens), done, kind='load')

    def _publish_layers(self, layers, directory):
        """Worker-only: validate provenance and atomically publish all outputs."""
        import open3d as o3d
        entries = []
        for layer in layers:
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(layer.points.copy())
            if layer.colors is not None:
                cloud.colors = o3d.utility.Vector3dVector(layer.colors.copy())
            entries.append((cloud, [uid for uid, _ in layer.origins], layer.name))
        with self.database._lock:
            self._validate_source(directory, [token for layer in layers for token in layer.origins])
            identifiers = self.database.publish_results(entries, postprocess=True,
                output_roles=[layer.output_role for layer in layers],
                registration_transform=layers[0].registration_transform if len(layers) == 1 else None,
                source_transforms=layers[0].source_transforms if len(layers) == 1 else None,
                parent_transforms=layers[0].parent_transforms if len(layers) == 1 else None,
                per_source_transforms=[layer.source_transforms or {} for layer in layers],
                intermediate_of=layers[0].intermediate_of if layers else "")
            for uid, layer in zip(identifiers, layers):
                layer.origins = ((uid, self.database.records[uid].revision),)
        return layers

    def _commit_operation(self, work, *, display_all=False, diagnostic=None, on_error=None):
        if self._worker is not None:
            return
        directory = self.directory
        before = tuple(self._clouds[uid].origins[0] for uid in self._display_ids)
        def run():
            layers = work()
            if getattr(self,'_progress_state',None) is not None:
                self._progress_state['stage'] = '写入DB结果（保留完整点云）'
            return self._publish_layers(layers, directory)
        def done(layers):
            self._undo.append((tuple(layer.origins[0] for layer in layers), before))
            self._undo = self._undo[-8:]
            self._active_uid = None
            # Keep the retained split visible; the discard branch remains in DB.
            self._show_records(layers if display_all else layers[:1], refresh=True)
            self.bridge.shell.set_dirty(True)
            self._set_status(f'已自动新增 {len(layers)} 项 DB 后处理结果；原始数据保留，请在主程序保存会话。' +
                                ('\n'+diagnostic() if diagnostic else ''))
        self._run(run, done, on_error=on_error)

    def open_file(self, unit=None, *, snapshot=None):
        if not self._parameter_gate():
            return
        unit = unit or self._import_unit
        snapshot = snapshot or self._input_snapshot()
        path, _ = QFileDialog.getOpenFileName(self, '导入点云（请先确认源文件单位）', '', '点云 (*.ply *.pcd *.xyz *.pts)')
        if path:
            if snapshot != self._input_snapshot() or not self._parameter_gate():
                self._set_status('输入或项目已变化，请重新导入。')
                return
            self._commit_operation(lambda: [read_cloud(path, unit)])

    def _selected_layer(self):
        uid = self._active_uid
        if uid not in self._clouds:
            self._set_status('请先在 DB 树中选择点云。')
            return None, None
        return uid, self._clouds[uid]

    def open_probe_dialog(self):
        if not self._parameter_gate() or self._active_uid not in self._clouds:
            return
        self.probe_dialog.show()
        self.probe_dialog.raise_()
        self.probe_dialog.activateWindow()

    def _probe_key(self):
        with self.database._lock:
            self._validate_source(self.directory, [])
            row = self.database.records.get(self._active_uid)
            if row is None or row.uid != self._active_uid or row.status == STALE_RESULT:
                raise ValueError('当前点云已删除或失效')
            sources = tuple((uid, self.database.records[uid].revision
                             if uid in self.database.records else None) for uid in row.source_ids)
            return (str(self.directory.resolve()), row.uid, row.revision, sources,
                    self.probe.threshold.value(), self.probe.confirmed.isChecked(), self._load_version)

    def analyze_probe(self):
        if self._worker is not None or self._closed:
            return
        source = self._clouds.get(self._active_uid)
        if source is None:
            return
        try:
            key = self._probe_key()
        except ValueError as exc:
            self.probe.text.setText(str(exc))
            return
        def work():
            from time import perf_counter
            from core.postprocess.probe import spacing, coverage, source_reason
            start = perf_counter()
            stats = spacing(source.points)
            tau = key[4] or 3*stats.get('p50', 0)
            with self.database._lock:
                self._validate_source(self.directory, [(key[1], key[2])])
                records = [self.database.records.get(uid) for uid, _ in key[3]]
                reason = source_reason(records, key[5])
            if not reason and tau <= 0:
                reason = 'P50为0或有效点不足，请设置正阈值'
            directions = []
            if not reason:
                tokens = key[3]
                # One target tree per direction, at most two source clouds live.
                for i in range(len(tokens)):
                    for j in range(i+1, len(tokens)):
                        for a, b in ((i, j), (j, i)):
                            layers = self._read_records(self.directory, [tokens[a], tokens[b]])
                            row = coverage(layers[0].points, layers[1].points, tau)
                            directions.append((layers[0].name, layers[1].name, row))
                            del layers
            return dict(spacing=stats, tau=tau, reason=reason,
                        directions=directions, seconds=perf_counter()-start)
        def done(report):
            try:
                if key != self._probe_key() or self._closed:
                    return
            except ValueError:
                return
            self._probe_report = (key, report)
            self.probe.show_report(report)
            from .probe_panel import reference_text
            name = f'检测对象：{source.name}\n'
            references = reference_text(report['spacing']).splitlines()
            summary = '\n'.join(references[:3])
            notes = '\n'.join(references[3:])
            self._probe_reports[key[:4]] = (
                name + summary + '\nICP仅供已粗对齐时起步参考；请手动设置。',
                name + self.probe.text.text() + ('\n\n参考值说明\n' + notes if notes else ''))
            self.probe.text.setText('检测完成。请在左侧“数据属性”的“点云检测结果”中查看；可关闭本窗口继续操作。')
            self._refresh_probe_properties()
            self.properties.tabs.setCurrentIndex(0)
        self._run(work, done, kind='probe', preserve_selection=True)

    def _refresh_probe_properties(self):
        reference = ''
        try:
            key = self._probe_key()[:4]
            reference, text = self._probe_reports.get(key, ('', '尚未检测：点击顶部“点云探针”分析当前点云。'))
            if self._active_uid not in self._clouds:
                reference = ''
                text = '请选择点云后进行检测。'
        except ValueError:
            text = '当前点云不可用或已失效，请重新选择并检测。'
        self.probe_properties.setText(text)
        self.probe_reference_text.setText(reference)
        self.probe_reference.setVisible(bool(reference))

    def create_downsample_dialog(self):
        source = self._clouds.get(self._active_uid)
        dialog = DownsampleDialog(
            source.name if source is not None else '',
            len(source.points) if source is not None else 0,
            self._downsample_state,
            self,
        )
        dialog.parameters_changed.connect(self._remember_downsample_parameters)
        return dialog

    def _remember_downsample_parameters(self, parameters):
        self._downsample_state = dict(parameters)

    def open_downsample_dialog(self):
        if self._worker is not None or self._closed:
            return
        _, source = self._selected_layer()
        if source is None:
            return
        dialog = self.create_downsample_dialog()
        accepted_parameters = []
        # WA_DeleteOnClose may destroy the C++ dialog before exec() returns.
        dialog.accepted.connect(lambda: accepted_parameters.append(dialog.parameters()))
        accepted = dialog.exec() == QDialog.Accepted
        if accepted:
            parameters = accepted_parameters[0]
            method = parameters['method']
            self.downsample(method, parameters[method])

    def downsample(self, method, value=None):
        if method not in ('voxel', 'random'):
            raise ValueError('未知下采样方法。')
        _, source = self._selected_layer()
        if source is None:
            return
        if value is None:
            value = 2.0 if method == 'voxel' else .5
        elif method == 'random':
            value = float(value) / 100
        else:
            value = float(value)
        def work():
            data = voxel_downsample(source.points, source.colors, value) if method == 'voxel' else random_downsample(source.points, source.colors, value)
            title = '体素下采样' if method == 'voxel' else '随机抽样'
            return [CloudLayer(source.name+' · '+title, data[0], data[1],
                               source=source.source, origins=source.origins)]
        self._commit_operation(work)

    def open_manual_registration(self):
        if not self._parameter_gate() or len(self._display_ids) != 2:
            return
        from .manual_registration_dialog import ManualRegistrationDialog
        from .icp_dialog import ICPDialog
        snapshot = self._input_snapshot()
        dialog = ManualRegistrationDialog([(uid,self._clouds[uid]) for uid in self._display_ids],self)
        if dialog.exec() != QDialog.Accepted:
            dialog.deleteLater()
            return
        reference_uid, (a,b) = dialog.selection()
        dialog.deleteLater()
        params_dialog = ICPDialog([(reference_uid,self._clouds[reference_uid].name)],self)
        params_dialog.setWindowTitle('手动配准 · ICP优化参数')
        params_dialog.note.setText('先使用已选共有点计算刚体变换，再执行ICP优化，最终合并两项点云为独立DB结果。计算体素仅用于加速，输出保留全部有效点和颜色；ICP失败时整批不发布。')
        params_dialog.reference.setEnabled(False)
        if params_dialog.exec() == QDialog.Accepted:
            _, params = params_dialog.parameters()
            self.register_manual(reference_uid,a,b,params,snapshot=snapshot)
        params_dialog.deleteLater()

    def register_manual(self, reference_uid, a, b, params, *, snapshot=None):
        if (not self._parameter_gate() or len(self._display_ids)!=2 or reference_uid not in self._display_ids
                or (snapshot is not None and snapshot != self._input_snapshot())):
            self._set_status('输入或项目已变化，请重新选择共有点。')
            return
        reference=self._clouds[reference_uid]
        moving=self._clouds[next(uid for uid in self._display_ids if uid!=reference_uid)]
        directory=self.directory
        tokens=reference.origins+moving.origins
        reports=[]
        progress={'stage':'准备手动配准'}
        self._progress_state=progress
        def work():
            from core.postprocess.manual_registration import register_manual
            self._validate_source(directory,tokens)
            output,message=register_manual(reference,moving,a,b,params,progress=lambda text:progress.update(stage=text))
            self._validate_source(directory,tokens)
            reports.append(message)
            return [output]
        self._commit_operation(work,diagnostic=lambda:'\n'.join(reports),
            on_error=lambda error:QMessageBox.warning(self,'手动配准失败',str(error)))

    def extract_intermediates(self, *, automatic=False):
        if not self._parameter_gate() or len(self._display_ids) != 1:
            return
        uid = self._display_ids[0]
        existing = [key for key,row in self.database.records.items() if row.intermediate_of == uid and row.status != STALE_RESULT]
        if existing:
            self.load_selected(existing)
            return
        directory = self.directory
        tokens = self._clouds[uid].origins
        def work():
            from core.postprocess.source_poses import source_poses
            from core.point_cloud_processor import PointCloudProcessor
            self._validate_source(directory,tokens)
            row = self.database.records[uid]
            if row.kind != 'result' or row.purpose == '后处理结果' or row.intermediate_of:
                raise ValueError('请选择原始拼接结果，避免从裁剪结果恢复已删除的区域')
            poses = source_poses(self.database,uid)
            layers = []
            for index,(key,(revision,pose)) in enumerate(poses.items(),1):
                frame, cloud = self.database.load_frame(key,'cloud')
                cloud,_ = PointCloudProcessor._filter_valid(cloud)
                raw = self.database.records[key]
                layers.append(CloudLayer(f'配准中间帧 {index:03d} · {raw.camera} · 原帧{raw.frame_id:03d}',
                    np.asarray(cloud.points) @ pose[:3,:3].T + pose[:3,3],
                    np.asarray(cloud.colors) if cloud.has_colors() else None,
                    origins=((key,revision),), source_transforms={key:pose.tolist()}, intermediate_of=uid))
            self._validate_source(directory,tokens)
            return layers
        self._commit_operation(work,display_all=True,
            on_error=(lambda error:self._set_status('自动补齐中间帧失败：'+str(error)+'；请检查来源或点击提取中间帧查看。')) if automatic else
            (lambda error:QMessageBox.warning(self,'提取中间帧失败',str(error))))

    def open_icp_dialog(self):
        if not self._parameter_gate() or len(self._display_ids) not in (1, 2):
            self._set_status('请选择一项拼接结果，或勾选两项已粗略对齐的点云。')
            return
        from .icp_dialog import ICPDialog
        snapshot = self._input_snapshot()
        rebuild = len(self._display_ids) == 1
        inputs = [(uid, self._clouds[uid].name) for uid in self._display_ids]
        if rebuild:
            try:
                uid = self._display_ids[0]
                row = self.database.records[uid]
                if row.kind != 'result' or row.purpose == '后处理结果':
                    raise ValueError('请选择原始拼接结果；后处理分支或单个原始帧无法按来源重建')
                from core.postprocess.source_poses import source_poses
                poses = source_poses(self.database, uid)
                if len(poses) < 2:
                    raise ValueError('至少需要两帧来源数据和拼接位姿，请重新执行拼接')
                inputs = [(key, f'采集帧{self.database.records[key].frame_id:03d} · {self.database.records[key].logical_name}') for key in poses]
            except ValueError as exc:
                QMessageBox.warning(self, '无法重建ICP', str(exc))
                return
        dialog = ICPDialog(inputs, self, rebuild=rebuild)
        if dialog.exec() == QDialog.Accepted:
            reference_uid, params = dialog.parameters()
            if rebuild:
                self.register_stitched_icp(reference_uid, params, snapshot=snapshot)
            else:
                self.register_icp(reference_uid, params, snapshot=snapshot)

    def register_stitched_icp(self, reference_uid, params, *, snapshot=None):
        if (not self._parameter_gate() or len(self._display_ids) != 1
                or (snapshot is not None and snapshot != self._input_snapshot())):
            self._set_status('输入或项目已变化，请重新打开ICP参数。')
            return
        uid = self._display_ids[0]
        directory = self.directory
        tokens = self._clouds[uid].origins
        reports = []
        def work():
            from core.postprocess.icp_registration import refine_stitched
            self._validate_source(directory, tokens)
            output, message = refine_stitched(self.database, uid, reference_uid, params)
            self._validate_source(directory, tokens)
            reports.append(message)
            return [output]
        self._commit_operation(work, diagnostic=lambda: '\n'.join(reports),
            on_error=lambda error: QMessageBox.warning(self, '来源帧ICP失败', str(error)))

    def register_icp(self, reference_uid, params, *, snapshot=None):
        if (not self._parameter_gate() or len(self._display_ids) != 2
                or reference_uid not in self._display_ids
                or (snapshot is not None and snapshot != self._input_snapshot())):
            self._set_status('输入或项目已变化，请重新打开ICP参数。')
            return
        reference = self._clouds[reference_uid]
        moving = self._clouds[next(uid for uid in self._display_ids if uid != reference_uid)]
        tokens = tuple(token for layer in (reference, moving) for token in layer.origins)
        directory = self.directory
        report = []
        def work():
            self._validate_source(directory, tokens)
            from core.postprocess.icp_registration import refine_icp
            output, message = refine_icp(reference, moving, params)
            self._validate_source(directory, tokens)
            report.append(message)
            return [output]
        def failed(error):
            QMessageBox.warning(self, 'ICP精配准失败', str(error))
        self._commit_operation(work, diagnostic=lambda: '\n'.join(report), on_error=failed)

    def merge_selected(self):
        layers = [self._clouds[uid] for uid in self._display_ids]
        if len(layers) < 2:
            self._set_status('请在 DB 树中勾选或多选至少两项点云。')
            return
        def work():
            colors = (np.vstack([layer.colors if layer.colors is not None else
                                 np.tile([.66, .81, .91], (len(layer.points), 1)) for layer in layers])
                      if any(layer.colors is not None for layer in layers) else None)
            return [CloudLayer(f'合并点云 ({len(layers)} 帧)', np.vstack([layer.points for layer in layers]), colors,
                               source='DB 合并', origins=tuple(dict.fromkeys(
                                   token for layer in layers for token in layer.origins)))]
        self._commit_operation(work)

    def _view(self):
        canvas = self.viewer.canvas
        return dict(center=canvas.center.copy(), rotation_matrix=canvas.rotation.matrix.copy(),
                    extent=canvas.extent, zoom=canvas.zoom, pan=canvas.pan.copy(),
                    width=max(1, canvas.width()), height=max(1, canvas.height()))

    def start_polygon(self):
        if self._worker is not None or self._closed or not self.bridge.can_change_workspace():
            return
        if self._selected_layer()[1] is not None:
            self._invalidate_polygon()
            self.overlay.activate()
            self._refresh_controls()
            self._set_status('左键添加顶点，Alt+左键撤点；右键/封闭按钮完成。中键设旋转中心，Esc取消。')

    def stage_polygon(self, polygon):
        if self._worker is not None or self._closed:
            return
        uid, layer = self._selected_layer()
        if layer is None:
            return
        self._invalidate_polygon()
        self.overlay.set_confirmed(polygon)
        generation = self._selection_generation
        view = self._view()
        def done(mask):
            if generation != self._selection_generation:
                return
            if any(not np.allclose(self._view()[key], value) for key, value in view.items()):
                self._invalidate_polygon()
                self._set_status('视角或视区尺寸已变化，请重新框选。')
                return
            self._segment = (uid, layer, mask, view)
            self.overlay.set_confirmed(polygon)
            self.overlay.show_confirmed(f'框内 {int(mask.sum()):,} 点 / 框外 {int((~mask).sum()):,} 点')
            self._set_status(f'框内 {int(mask.sum()):,} 点 / 框外 {int((~mask).sum()):,} 点；选择保留方向后点击快捷删除，另一侧保存为分支，原始数据保留。')
            self._refresh_segment_tools()
        self._run(lambda: polygon_crop_mask(layer.points, polygon, **view), done,
                  preserve_selection=True)

    def apply_segment(self, keep_inside):
        if self._worker is not None or self._closed or not self.bridge.can_change_workspace():
            return
        if self._segment is None:
            self._set_status('请先完成多边形框选。')
            return
        uid, source, mask, view = self._segment
        if any(not np.allclose(self._view()[key], value) for key, value in view.items()):
            self._invalidate_polygon()
            self._set_status('视角或视区尺寸已变化，请重新框选。')
            return
        if self._clouds.get(uid) is not source:
            self._invalidate_polygon()
            return
        keep = mask if keep_inside else ~mask
        if not keep.any():
            self._set_status('保留部分为空，已拒绝分割。')
            return
        def work():
            def build(selected, inside):
                return CloudLayer(source.name + (' · 框内' if inside else ' · 框外'),
                    source.points[selected], None if source.colors is None else source.colors[selected],
                    source=source.source, origins=source.origins,
                    output_role='inside' if inside else 'outside')
            layers = [build(keep, keep_inside)]
            if (~keep).any():
                layers.append(build(~keep, not keep_inside))
            return layers
        self._commit_operation(work)

    def _invalidate_polygon(self, *_):
        self._selection_generation += 1
        self._segment = None
        if hasattr(self, 'overlay'):
            self.overlay.clear()
        if hasattr(self, 'properties'):
            ready = self._worker is None
            self.actions['fit'].setEnabled(ready)
            self.properties.setEnabled(ready)

    def undo(self):
        if self._worker is not None or not self._undo:
            return
        outputs, before = self._undo[-1]
        directory = self.directory
        def work():
            from core.utils import rvc_sdk_lock
            with rvc_sdk_lock, self.database._lock:
                self._validate_source(directory, outputs)
                identifiers = {uid for uid, _ in outputs}
                if any(identifiers.intersection(record.source_ids) for uid, record in self.database.records.items()
                       if uid not in identifiers):
                    raise ValueError('此结果已有派生数据，不能撤销。')
                layers = self._read_records(directory, before)
                self.database.remove(identifiers)
                return layers
        def done(layers):
            self._undo.pop()
            self._active_uid = None
            self._show_records(layers, refresh=True)
            self.bridge.shell.set_dirty(True)
            self._set_status('已撤销处理；生成结果已移入 DB 回收区，来源数据保留。')
        self._run(work, done)

    def export_selected(self):
        identifiers = self.source_browser.selected_ids() or list(self._display_ids)
        if not identifiers:
            self._set_status('请选择 DB 点云。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出选中 DB 点云（mm）', 'postprocess.ply', 'PLY (*.ply)')
        if not path:
            return
        path = str(Path(path).with_suffix('.ply'))
        directory = self.directory
        with self.database._lock:
            tokens = [(uid, self.database.records[uid].revision) for uid in identifiers if uid in self.database.records]
        def work():
            if len(tokens) != len(identifiers):
                raise ValueError('来源数据已变化')
            with self.database._lock:
                self._validate_source(directory, tokens)
                if Path(path).resolve().is_relative_to(directory.resolve()):
                    raise ValueError('不能导出到当前 DB 内部，请选择其他目录')
                if len(identifiers) == 1:
                    self.database.export_cloud(identifiers[0], path)
                    return self.database.records[identifiers[0]].points
                layers = self._read_records(directory, tokens)
            return write_cloud(path, layers)
        self._run(work, lambda count: self._set_status(f'已导出 {count:,} 点。'))

    def shutdown(self):
        if self._closed:
            return
        self._log_sync_timer.stop()
        if self._log_signal is not None:
            self._log_signal.disconnect(self._receive_log)
        self._closed = True
        self.probe_dialog.close()
        self._pending_load = None
        if self._worker is not None:
            self._worker.wait()
        self.viewer.shutdown()
        if getattr(self.bridge, '_postprocess_window', None) is self:
            self.bridge._postprocess_window = None

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self._worker is not None:
            self._set_status('正在处理或写入数据，请等待任务完成后关闭。')
            event.ignore()
            return
        self.shutdown()
        event.accept()
