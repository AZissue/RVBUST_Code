"""Industrial postprocess workspace: DB snapshots in, immutable result branches out."""
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSplitter, QTabWidget, QGroupBox, QFormLayout, QDoubleSpinBox, QPushButton,
    QToolButton, QFileDialog, QMenu, QScrollArea, QComboBox)
from ui_common.industrial_viewer import IndustrialViewer
from ui_common.worker_thread import WorkerThread
from ui_common.symbols import icon
from core.frame_database import STALE_RESULT
from core.postprocess.session import CloudLayer, PostProcessSession, read_cloud, write_cloud
from core.postprocess.processing import polygon_crop_mask, voxel_downsample, random_downsample
from ..dialogs import ChineseMessageBox as QMessageBox
from ..frame_database import FrameBrowser
from ..widgets.db_properties import DbProperties
from ..industrial_ribbon import STYLE
from .selection import PolygonSelectionOverlay
from .layer_tree import CloudTreePanel


class PostprocessWindow(QDialog):
    def __init__(self, bridge, mode, parent=None):
        super().__init__(parent or bridge.shell)
        self.bridge, self.mode = bridge, mode
        self.database = bridge.frame_db.databases[mode]
        self.directory = self.database.directory
        self.session = PostProcessSession()
        self._worker = None
        self._segment = None
        self._saved = set()
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
            ('db', '从DB载入', 'layers', self.load_selected),
            ('open', '打开点云', 'folder_open', self.open_file),
            ('select', '多边形框选', 'detect', self.start_polygon),
            ('merge', '合并图层', 'stitch', self.merge_selected),
            ('undo', '撤销', 'undo', self.undo),
            ('publish', '写回DB', 'save', self.publish_selected),
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
        self.actions['publish'].setProperty('primaryAction', True)
        actions.addStretch()
        root.addLayout(actions)
        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        root.addWidget(body, 1)
        left = QSplitter(Qt.Vertical)
        left.setChildrenCollapsible(False)
        left.setMinimumWidth(300)
        self.tree_tabs = QTabWidget()
        self.source_browser = FrameBrowser(self.database)
        self.source_browser.properties.hide()
        self.source_browser.footer.hide()
        self.source_browser.tree.customContextMenuRequested.disconnect()
        self.source_browser.tree.customContextMenuRequested.connect(self._source_menu)
        self.source_browser.tree.itemDoubleClicked.connect(lambda *_: self.load_selected())
        self.tree_tabs.addTab(self.source_browser, '项目 DB')
        self.panel = CloudTreePanel(self.session)
        self.panel.visibility_changed.connect(self._visibility)
        self.panel.remove_requested.connect(self.remove_layers)
        self.panel.restore_requested.connect(self.restore_removed)
        self.panel.clear_requested.connect(lambda: self.remove_layers(list(range(len(self.session.layers)))))
        self.panel.current_changed.connect(lambda *_: self._invalidate_polygon())
        self.tree_tabs.addTab(self.panel, '处理图层')
        left.addWidget(self.tree_tabs)
        params = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QVBoxLayout(content)
        group = QGroupBox('多边形分割')
        rows = QVBoxLayout(group)
        self.segment_label = QLabel('左键添加顶点，Alt+左键撤点；右键封闭，Esc取消。')
        self.segment_label.setWordWrap(True)
        rows.addWidget(self.segment_label)
        for text, callback in [('保留框内', lambda: self.apply_segment(True)),
                               ('保留框外', lambda: self.apply_segment(False)),
                               ('取消框选', self._invalidate_polygon)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            rows.addWidget(button)
        form.addWidget(group)
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
        hint = QLabel('分割沿当前视线投影，不区分前后深度。舍去部分保留为分支。\n原始 DB 数据不变，写回时生成独立后处理结果。')
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
        self.viewer.canvas_changed.connect(self._renderer_changed)
        self.status = QLabel('从当前项目 DB 载入点云，或打开外部点云文件。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        root.addWidget(self.status)
        self._refresh()

    def _renderer_changed(self, *_):
        self._invalidate_polygon()
        self.overlay.deleteLater()
        self.overlay = PolygonSelectionOverlay(self.viewer.canvas)
        self.overlay.polygon_confirmed.connect(self.stage_polygon)
        self.overlay.cancelled.connect(self._invalidate_polygon)
        self.properties.bind_renderer(self.viewer)
        self.properties.max_button.hide()

    def _source_menu(self, pos):
        self.source_browser._select_context_target(pos)
        menu = QMenu(self)
        menu.addAction('载入选中点云到处理区', self.load_selected)
        menu.exec(self.source_browser.tree.viewport().mapToGlobal(pos))

    def _run(self, work, done):
        if self._worker is not None or self._closed:
            return False
        self._invalidate_polygon()
        worker = WorkerThread(work)
        self._worker = worker
        worker._task_name = 'postprocess'
        worker._must_finish = True
        self.bridge._workers.append(worker)
        def completed(result, error):
            if self._closed:
                return
            if error:
                self.status.setText('处理失败：' + str(error))
            else:
                self.status.setText('处理完成。')
                try:
                    done(result)
                except Exception as exc:
                    self.status.setText('更新结果失败：' + str(exc))
        def finished():
            if worker in self.bridge._workers:
                self.bridge._workers.remove(worker)
            self._worker = None
            worker.deleteLater()
            if not self._closed:
                self._refresh_controls()
                self.bridge.shell._industrial_ribbon.update_status()
        worker.result_ready.connect(completed)
        worker.finished.connect(finished)
        self._refresh_controls()
        self.status.setText('正在后台处理点云…')
        worker.start()
        return True

    def _refresh_controls(self):
        ready = self._worker is None
        for button in self.actions.values():
            button.setEnabled(ready)
        self.params.setEnabled(ready)
        self.tree_tabs.setEnabled(ready)
        self.actions['undo'].setEnabled(ready and self.session.can_undo)

    def _refresh(self, select=None, fit=False):
        self._invalidate_polygon()
        self.panel.refresh(select=select)
        # The renderer consumes array views; do not duplicate full geometry on the UI thread.
        clouds = {str(index): layer for index, layer in enumerate(self.session.layers) if layer.visible}
        self.viewer.replace_pointclouds(clouds, fit=fit)
        self._refresh_controls()

    def _visibility(self, index, visible):
        self.session.layers[index].visible = visible
        self._refresh(select=index)

    def load_selected(self, identifiers=None):
        if isinstance(identifiers, bool):
            identifiers = None
        if identifiers is None:
            identifiers = [uid for uid, _ in self.source_browser.checked_components('cloud')] or self.source_browser.selected_ids()
        identifiers = list(dict.fromkeys(identifiers))
        if not identifiers:
            self.status.setText('请在项目 DB 中勾选或选中点云。')
            return
        directory = self.directory
        with self.database._lock:
            tokens = [(uid, self.database.records[uid].revision) for uid in identifiers if uid in self.database.records]
        if len(tokens) != len(identifiers):
            self.status.setText('来源数据已变化，请重新选择点云。')
            return
        def work():
            layers = []
            for uid, revision in tokens:
                with self.database._lock:
                    self._validate_source(directory, [(uid, revision)])
                    record = self.database.records[uid]
                    _, cloud = self.database.load_frame(uid, 'cloud')
                    layers.append(CloudLayer(record.logical_name, np.asarray(cloud.points),
                        np.asarray(cloud.colors) if cloud.has_colors() else None,
                        source=f'DB · {record.logical_name}', origins=((uid, revision),)))
            return layers
        def done(layers):
            self.session.layers.extend(layers)
            self._saved.update(layer.token for layer in layers)
            self._refresh(select=len(self.session.layers)-1, fit=True)
            self.tree_tabs.setCurrentIndex(1)
            self.status.setText(f'已从 DB 载入 {len(layers)} 帧点云；原数据保持独立。')
        self._run(work, done)

    def _validate_source(self, directory, tokens):
        if self.database.directory != directory:
            raise ValueError('项目已切换，请重新打开后处理窗口。')
        for uid, revision in tokens:
            record = self.database.records.get(uid)
            if record is None or record.revision != revision or record.status == STALE_RESULT:
                raise ValueError('来源数据已删除、替换或失效，请重新载入。')

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '打开点云（请先确认左侧源文件单位）', '', '点云 (*.ply *.pcd *.xyz *.pts)')
        if path:
            unit = self.file_unit.currentData()
            def done(layer):
                self.session.layers.append(layer)
                self._refresh(select=len(self.session.layers)-1, fit=True)
                self.tree_tabs.setCurrentIndex(1)
            self._run(lambda: read_cloud(path, unit), done)

    def _selected_layer(self):
        index = self.panel.current_index()
        if index is None:
            self.status.setText('请先选择处理图层。')
            return None, None
        return index, self.session.layers[index]

    def _replace(self, index, layer):
        self.session.snapshot()
        self.session.layers[index] = layer
        self._refresh(select=index)

    def downsample(self, method):
        index, source = self._selected_layer()
        if source is None:
            return
        value = self.voxel.value() if method == 'voxel' else self.ratio.value()/100
        def work():
            data = voxel_downsample(source.points, source.colors, value) if method == 'voxel' else random_downsample(source.points, source.colors, value)
            return CloudLayer(source.name, data[0], data[1], source.visible,
                              source.source + f' | {method}({value:g})', origins=source.origins)
        self._run(work, lambda layer: self._replace(index, layer))

    def merge_selected(self):
        indices = self.panel.selected_indices()
        if len(indices) < 2:
            self.status.setText('请在处理图层树中选择至少两层。')
            return
        layers = [self.session.layers[i] for i in indices]
        def work():
            colors = (np.vstack([layer.colors if layer.colors is not None else
                                 np.tile([.66, .81, .91], (len(layer.points), 1)) for layer in layers])
                      if any(layer.colors is not None for layer in layers) else None)
            return CloudLayer(f'合并点云 ({len(layers)} 层)', np.vstack([layer.points for layer in layers]), colors,
                              source='合并：' + '、'.join(layer.name for layer in layers),
                              origins=tuple(dict.fromkeys(token for layer in layers for token in layer.origins)))
        def done(layer):
            self.session.snapshot()
            for index in reversed(indices):
                self.session.layers.pop(index)
            self.session.layers.insert(indices[0], layer)
            self._refresh(select=indices[0], fit=True)
        self._run(work, done)

    def _view(self):
        canvas = self.viewer.canvas
        return dict(center=canvas.center.copy(), rotation_matrix=canvas.rotation.matrix.copy(),
                    extent=canvas.extent, zoom=canvas.zoom, pan=canvas.pan.copy(),
                    width=max(1, canvas.width()), height=max(1, canvas.height()))

    def start_polygon(self):
        if self._selected_layer()[1] is None:
            return
        self._segment = None
        self.overlay.activate()

    def stage_polygon(self, polygon):
        index, layer = self._selected_layer()
        if layer is None:
            return
        view = self._view()
        def done(mask):
            self._segment = (index, layer, mask, view)
            self.overlay._confirmed_polygon = list(polygon)
            self.overlay._vertices = list(polygon)
            self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.overlay.show()
            self.overlay.show_confirmed(f'框内 {int(mask.sum()):,} 点 / 框外 {int((~mask).sum()):,} 点')
            self.segment_label.setText(f'框内 {int(mask.sum()):,} 点 / 框外 {int((~mask).sum()):,} 点；请选择保留范围。')
        self._run(lambda: polygon_crop_mask(layer.points, polygon, **view), done)

    def apply_segment(self, keep_inside):
        if self._segment is None:
            self.status.setText('请先完成多边形框选。')
            return
        index, source, mask, view = self._segment
        current = self._view()
        if any(not np.allclose(current[key], value) for key, value in view.items()):
            self._invalidate_polygon()
            self.status.setText('视角或视区尺寸已变化，请重新框选。')
            return
        if self.session.layers[index] is not source:
            self._invalidate_polygon()
            return
        keep = mask if keep_inside else ~mask
        if not keep.any():
            self.status.setText('保留部分为空，已拒绝分割。')
            return
        def work():
            def build(name, selected):
                return CloudLayer(name, source.points[selected], None if source.colors is None else source.colors[selected],
                                  source.visible, source.source + ' | 多边形分割', origins=source.origins)
            return build(source.name, keep), build(source.name+' · 分割分支', ~keep) if (~keep).any() else None
        def done(result):
            kept, branch = result
            self.session.snapshot()
            self.session.layers[index] = kept
            if branch is not None:
                self.session.layers.insert(index+1, branch)
            self._refresh(select=index)
        self._run(work, done)

    def _invalidate_polygon(self, *_):
        self._segment = None
        if hasattr(self, 'overlay'):
            self.overlay.clear()
        if hasattr(self, 'segment_label'):
            self.segment_label.setText('左键添加顶点，Alt+左键撤点；右键封闭，Esc取消。')

    def undo(self):
        if self._worker is not None:
            return
        if self.session.undo():
            self._refresh()

    def remove_layers(self, indices):
        if self._worker is not None or not indices:
            return
        indices = sorted(set(indices))
        self.session.removed.append([(index, self.session.layers[index]) for index in indices])
        # Recycle operations use their own restoration history.
        for index in reversed(indices):
            self.session.layers.pop(index)
        self.session._undo.clear()  # Prevent old edits resurrecting recycled layers twice.
        self._refresh()

    def restore_removed(self):
        if self._worker is not None:
            return
        if self.session.removed:
            for index, layer in self.session.removed.pop():
                self.session.layers.insert(min(index,len(self.session.layers)), layer)
            self._refresh()

    def publish_selected(self):
        indices = self.panel.selected_indices()
        if len(indices) != 1:
            self.status.setText('请选择一个处理图层写回 DB；多层请先合并或分别写回。')
            return
        layer = self.session.layers[indices[0]]
        directory = self.directory
        def work():
            import open3d as o3d
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(layer.points.copy())
            if layer.colors is not None:
                cloud.colors = o3d.utility.Vector3dVector(layer.colors.copy())
            with self.database._lock:
                self._validate_source(directory, layer.origins)
                return self.database.publish_result(cloud, [uid for uid,_ in layer.origins],
                    postprocess=True, name=layer.name + ' · 后处理')
        def done(uid):
            self._saved.add(layer.token)
            self.source_browser.refresh()
            self.bridge.shell.set_dirty(True)
            self.status.setText(f'已写回 DB：{self.database.records[uid].logical_name}；请在主程序保存会话。')
        self._run(work, done)

    def export_selected(self):
        indices = self.panel.selected_indices()
        if not indices:
            self.status.setText('请选择要导出的处理图层。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出选中图层（mm）', 'postprocess.ply', 'PLY (*.ply)')
        if path:
            layers = [self.session.layers[i] for i in indices]
            # Export selection is independent of viewport visibility.
            def done(count):
                self._saved.update(layer.token for layer in layers)
                self.status.setText(f'已导出 {count:,} 点。')
            self._run(lambda: write_cloud(str(Path(path).with_suffix('.ply')),
                [CloudLayer(layer.name, layer.points, layer.colors) for layer in layers]), done)

    def shutdown(self):
        self._closed = True
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
        pending = any(layer.token not in self._saved for layer in self.session.layers)
        if pending and QMessageBox.question(self, '关闭后处理',
                '处理区有未写回 DB 或导出的图层。关闭将丢弃这些临时图层，是否关闭？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            event.ignore()
            return
        self.shutdown()
        event.accept()
