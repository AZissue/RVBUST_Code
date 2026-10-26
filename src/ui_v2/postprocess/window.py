"""Industrial postprocess workspace: DB snapshots in, immutable result branches out."""
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QSize, QSignalBlocker, QItemSelectionModel
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSplitter, QTabWidget, QGroupBox, QFormLayout, QDoubleSpinBox, QPushButton,
    QToolButton, QFileDialog, QMenu, QScrollArea, QComboBox)
from ui_common.industrial_viewer import IndustrialViewer
from ui_common.worker_thread import WorkerThread
from ui_common.symbols import icon
from core.frame_database import STALE_RESULT
from core.postprocess.session import CloudLayer, read_cloud, write_cloud
from core.postprocess.processing import polygon_crop_mask, voxel_downsample, random_downsample
from ..frame_database import FrameBrowser
from ..widgets.db_properties import DbProperties
from ..industrial_ribbon import STYLE
from ..dialogs import ChineseMessageBox as QMessageBox
from .selection import PolygonSelectionOverlay
from .viewport_tools import MiddlePan, SegmentationToolbar


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
        self._busy_kind = None
        self._loading_ids = None
        self._worker = None
        self._segment = None
        self._closed = False
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
        root.addWidget(header)
        actions = QHBoxLayout()
        self.actions = {}
        for key, text, glyph, callback in (
            ('open', '导入点云', 'folder_open', self.open_file),
            ('merge', '合并点云', 'stitch', self.merge_selected),
            ('undo', '撤销处理', 'undo', self.undo),
            ('export', '导出选中', 'save', self.export_selected),
            ('fit', '适配视图', 'reset_view', lambda: self.viewer.reset_view())):
            button = QToolButton()
            button.setText(text)
            button.setIcon(icon(glyph, '#dddddd', 23))
            button.setIconSize(QSize(23, 23))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setMinimumSize(78, 58)
            button.clicked.connect(callback)
            actions.addWidget(button)
            self.actions[key] = button
        actions.addStretch()
        root.addLayout(actions)
        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        root.addWidget(body, 1)
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
        params = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QVBoxLayout(content)
        group = QGroupBox('下采样')
        rows = QFormLayout(group)
        self.voxel = QDoubleSpinBox()
        self.voxel.setRange(.01, 100000)
        self.voxel.setValue(2)
        self.voxel.setSuffix(' mm')
        rows.addRow('体素尺寸', self.voxel)
        voxel_button = QPushButton('体素下采样')
        voxel_button.clicked.connect(lambda: self.downsample('voxel'))
        rows.addRow(voxel_button)
        self.ratio = QDoubleSpinBox()
        self.ratio.setRange(.1, 100)
        self.ratio.setValue(50)
        self.ratio.setSuffix(' %')
        rows.addRow('随机保留', self.ratio)
        random_button = QPushButton('随机抽样')
        random_button.clicked.connect(lambda: self.downsample('random'))
        rows.addRow(random_button)
        form.addWidget(group)
        group = QGroupBox('外部文件')
        rows = QFormLayout(group)
        self.file_unit = QComboBox()
        self.file_unit.addItem('毫米 mm', 'mm')
        self.file_unit.addItem('米 m（载入后转为 mm）', 'm')
        rows.addRow('源文件单位', self.file_unit)
        form.addWidget(group)
        hint = QLabel('分割沿当前视线投影，不区分前后深度。舍去部分保留为分支。\n处理完成自动新增 DB 后处理结果，原始数据保留。')
        hint.setWordWrap(True)
        form.addWidget(hint)
        form.addStretch()
        scroll.setWidget(content)
        params.addTab(scroll, '处理参数')
        self.viewer = IndustrialViewer()
        self.viewer.toolbar.hide()
        self.properties = DbProperties()
        self.properties.bind_renderer(self.viewer)
        self.properties.max_button.hide()
        self.properties.tabs.removeTab(3)
        self.properties.tabs.removeTab(2)
        self.properties.tabs.removeTab(0)
        self.properties.tabs.tabBar().hide()
        params.addTab(self.properties, '3D 显示')
        left.addWidget(params)
        left.setSizes([380, 340])
        self.params = params
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

    def _renderer_changed(self, *_):
        self._invalidate_polygon()
        self.overlay.deleteLater()
        self.overlay = PolygonSelectionOverlay(self.viewer.canvas)
        self.overlay.polygon_confirmed.connect(self.stage_polygon)
        self.overlay.cancelled.connect(self._invalidate_polygon)
        self._install_viewport_tools()
        self.properties.bind_renderer(self.viewer)
        self.properties.max_button.hide()

    def _install_viewport_tools(self):
        canvas = self.viewer.canvas
        self._middle_pan = MiddlePan(canvas)
        self.segment_tools = SegmentationToolbar(canvas, dict(
            draw=self.start_polygon, close=lambda: self.overlay._confirm(),
            back=lambda: self.overlay.remove_last_vertex(),
            inside=lambda: self.apply_segment(True), outside=lambda: self.apply_segment(False),
            cancel=self._invalidate_polygon))
        self.actions['select'] = self.segment_tools.buttons['draw']
        self.overlay.changed.connect(self._refresh_segment_tools)
        canvas.view_changed.connect(self._selection_view_changed)
        self._refresh_segment_tools()

    def _refresh_segment_tools(self):
        self.segment_tools.refresh(ready=self._worker is None,
            available=self._active_uid in self._clouds, overlay=self.overlay,
            staged=self._segment is not None)

    def _selection_view_changed(self):
        if self.overlay.active or self._segment is not None:
            self._invalidate_polygon()
            self.status.setText('视角已移动，旧框选已清除；可点击右上角多边形重新框选。')

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
            self.status.setText('项目已切换，请重新打开后处理窗口。')
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
            self.status.setText(message)
            self.bridge.shell.log(message, 'success')
        work = self.database.restore_last_removal if recover else lambda: self.database.remove(identifiers)
        self._run(work, done)

    def _selection_requested(self, *_):
        if self._syncing or self._closed:
            return
        items = self.source_browser.tree.selectedItems()
        if items and all(item.data(0, Qt.UserRole + 2) == 'image' for item in items):
            return
        identifiers = self.source_browser.selected_ids()
        if identifiers:
            self.load_selected(identifiers)

    def _checks_requested(self, checked):
        if not self._syncing and not self._closed:
            self.load_selected([uid for uid, component in checked if component == 'cloud'])

    def _run(self, work, done, *, kind='edit', preserve_selection=False):
        if self._worker is not None or self._closed:
            return False
        if not preserve_selection:
            self._invalidate_polygon()
        worker = WorkerThread(work)
        self._worker, self._busy_kind = worker, kind
        worker._task_name = 'postprocess'
        worker._must_finish = True
        self.bridge._workers.append(worker)

        def completed(result, error):
            if self._closed:
                return
            if error:
                if preserve_selection:
                    self._invalidate_polygon()
                self.status.setText('处理失败：' + str(error))
            else:
                self.status.setText('处理完成。')
                try:
                    done(result)
                except Exception as exc:
                    if preserve_selection:
                        self._invalidate_polygon()
                    self.status.setText('更新结果失败：' + str(exc))

        def finished():
            if worker in self.bridge._workers:
                self.bridge._workers.remove(worker)
            self._worker, self._busy_kind = None, None
            worker.deleteLater()
            if not self._closed:
                self._refresh_controls()
                self.bridge.shell._industrial_ribbon.update_status()
                if self._pending_load is not None:
                    pending, self._pending_load = self._pending_load, None
                    self.load_selected(pending)
        worker.result_ready.connect(completed)
        worker.finished.connect(finished)
        self._refresh_controls()
        self.status.setText('正在后台读取点云…' if kind == 'load' else '正在处理并更新 DB…')
        worker.start()
        return True

    def _refresh_controls(self):
        ready = self._worker is None
        for button in self.actions.values():
            button.setEnabled(ready)
        self.source_browser.setEnabled(ready)
        self.params.setEnabled(ready)
        self.actions['undo'].setEnabled(ready and bool(self._undo))
        self.actions['merge'].setEnabled(ready and len(self._display_ids) > 1)
        self.actions['select'].setEnabled(ready and self._active_uid in self._clouds)
        locked = self.overlay.view_locked
        self.actions['fit'].setEnabled(ready and not locked)
        self.properties.setEnabled(ready and not locked)
        self._refresh_segment_tools()

    def _refresh_display(self, *, fit=False):
        self.viewer.replace_pointclouds(
            {uid: self._clouds[uid] for uid in self._display_ids if uid in self._clouds}, fit=fit)

    def _show_records(self, layers, *, refresh=False, fit=False, select=True):
        """GUI-only completion: model rebuilds never run in itemChanged handlers."""
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
        if self.database.directory != directory:
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

    def load_selected(self, identifiers=None):
        if isinstance(identifiers, bool) or identifiers is None:
            identifiers = self.source_browser.selected_ids() or [
                uid for uid, _ in self.source_browser.checked_components('cloud')]
        identifiers = list(dict.fromkeys(identifiers))
        if self._closed:
            return
        if self._worker is not None:
            if self._busy_kind == 'load':
                if self._pending_load == identifiers or (self._pending_load is None and self._loading_ids == identifiers):
                    return
                self._load_version += 1
                self._pending_load = identifiers
            return
        self._load_version += 1
        version = self._load_version
        if not identifiers:
            self._show_records([], select=False)
            self.status.setText('请选择或勾选 DB 点云。')
            return
        directory = self.directory
        current = self.source_browser.tree.currentItem()
        active = current.data(0, Qt.UserRole) if current is not None else None
        self._loading_ids = identifiers
        with self.database._lock:
            if any(uid not in self.database.records for uid in identifiers):
                self.status.setText('来源数据已变化，请重新选择。')
                return
            tokens = [(uid, self.database.records[uid].revision) for uid in identifiers]
        def done(layers):
            if version != self._load_version:
                return
            self._active_uid = active if active in identifiers else identifiers[0]
            self._show_records(layers, fit=True)
            self.status.setText(f'已显示 {len(layers)} 项 DB 点云；处理完成后自动新增结果。')
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
            identifiers = self.database.publish_results(entries, postprocess=True)
            for uid, layer in zip(identifiers, layers):
                layer.origins = ((uid, self.database.records[uid].revision),)
        return layers

    def _commit_operation(self, work):
        if self._worker is not None:
            return
        directory = self.directory
        before = tuple(self._clouds[uid].origins[0] for uid in self._display_ids)
        def run():
            return self._publish_layers(work(), directory)
        def done(layers):
            self._undo.append((tuple(layer.origins[0] for layer in layers), before))
            self._undo = self._undo[-8:]
            self._active_uid = None
            # Keep the retained split visible; the discard branch remains in DB.
            self._show_records(layers[:1], refresh=True)
            self.bridge.shell.set_dirty(True)
            self.status.setText(f'已自动新增 {len(layers)} 项 DB 后处理结果；请在主程序保存会话。')
        self._run(run, done)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入点云（请先确认源文件单位）', '', '点云 (*.ply *.pcd *.xyz *.pts)')
        if path:
            unit = self.file_unit.currentData()
            self._commit_operation(lambda: [read_cloud(path, unit)])

    def _selected_layer(self):
        uid = self._active_uid
        if uid not in self._clouds:
            self.status.setText('请先在 DB 树中选择点云。')
            return None, None
        return uid, self._clouds[uid]

    def downsample(self, method):
        _, source = self._selected_layer()
        if source is None:
            return
        value = self.voxel.value() if method == 'voxel' else self.ratio.value()/100
        def work():
            data = voxel_downsample(source.points, source.colors, value) if method == 'voxel' else random_downsample(source.points, source.colors, value)
            title = '体素下采样' if method == 'voxel' else '随机抽样'
            return [CloudLayer(source.name+' · '+title, data[0], data[1],
                               source=source.source, origins=source.origins)]
        self._commit_operation(work)

    def merge_selected(self):
        layers = [self._clouds[uid] for uid in self._display_ids]
        if len(layers) < 2:
            self.status.setText('请在 DB 树中勾选或多选至少两项点云。')
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
        if self._selected_layer()[1] is not None:
            self._invalidate_polygon()
            self.overlay.activate()
            self._refresh_controls()
            self.status.setText('左键添加顶点，Alt+左键撤点；右键/封闭按钮完成。中键平移，Esc取消。')

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
                self.status.setText('视角或视区尺寸已变化，请重新框选。')
                return
            self._segment = (uid, layer, mask, view)
            self.overlay.set_confirmed(polygon)
            self.overlay.show_confirmed(f'框内 {int(mask.sum()):,} 点 / 框外 {int((~mask).sum()):,} 点')
            self.status.setText(f'框内 {int(mask.sum()):,} 点 / 框外 {int((~mask).sum()):,} 点；在右上角选择保留框内或框外。')
            self._refresh_segment_tools()
        self._run(lambda: polygon_crop_mask(layer.points, polygon, **view), done,
                  preserve_selection=True)

    def apply_segment(self, keep_inside):
        if self._segment is None:
            self.status.setText('请先完成多边形框选。')
            return
        uid, source, mask, view = self._segment
        if any(not np.allclose(self._view()[key], value) for key, value in view.items()):
            self._invalidate_polygon()
            self.status.setText('视角或视区尺寸已变化，请重新框选。')
            return
        if self._clouds.get(uid) is not source:
            self._invalidate_polygon()
            return
        keep = mask if keep_inside else ~mask
        if not keep.any():
            self.status.setText('保留部分为空，已拒绝分割。')
            return
        def work():
            def build(selected, inside):
                return CloudLayer(source.name + (' · 框内' if inside else ' · 框外'),
                    source.points[selected], None if source.colors is None else source.colors[selected],
                    source=source.source, origins=source.origins)
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
            self.status.setText('已撤销处理；生成结果已移入 DB 回收区，来源数据保留。')
        self._run(work, done)

    def export_selected(self):
        identifiers = self.source_browser.selected_ids() or list(self._display_ids)
        if not identifiers:
            self.status.setText('请选择 DB 点云。')
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
        self._run(work, lambda count: self.status.setText(f'已导出 {count:,} 点。'))

    def shutdown(self):
        self._closed = True
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
            self.status.setText('正在处理或写入数据，请等待任务完成后关闭。')
            event.ignore()
            return
        self.shutdown()
        event.accept()
