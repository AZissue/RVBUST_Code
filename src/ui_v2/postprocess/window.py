"""Industrial postprocess workspace: DB snapshots in, immutable result branches out."""
from pathlib import Path
from dataclasses import asdict
import numpy as np
from PySide6.QtCore import Qt, QSize, QSignalBlocker, QItemSelectionModel, QTimer
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSplitter, QToolButton, QFileDialog, QMenu, QScrollArea)
from ui_common.industrial_viewer import IndustrialViewer
from ui_common.worker_thread import WorkerThread
from ui_common.symbols import icon
from core.frame_database import STALE_RESULT
from core.postprocess.session import CloudLayer, read_cloud, write_cloud
from core.postprocess.processing import polygon_crop_mask, voxel_downsample, random_downsample
from core.postprocess.color_correction import ColorParameters, NoColorCorrection, correct_color_layers
from ..widgets import FloatingLogPanel
from ..frame_database import FrameBrowser
from ..industrial_ribbon import STYLE
from ..dialogs import ChineseMessageBox as QMessageBox
from .selection import PolygonSelectionOverlay
from .viewport_tools import SegmentationToolbar
from .downsample_dialog import DownsampleDialog
from .import_dialog import ImportDialog
from .color_dialog import ColorDialog


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
        self._import_unit = 'mm'
        self._color_state = dict(asdict(ColorParameters()), reference=None, aligned=False)
        self._last_color_report = []
        self._color_comparison = ((), ())
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
            ('color', '颜色统一', 'color_palette', self.open_color_dialog),
            ('compare', '对比原色', 'color_compare', self.compare_color_source),
            ('merge', '合并点云', 'cloud_merge', self.merge_selected),
            ('select', '多边形框选', 'polygon', self.start_polygon),
            ('undo', '撤销处理', 'undo', self.undo),
            ('export', '导出选中', 'cloud_export', self.export_selected),
            ('probe', '点云探针', 'cloud_probe', self.open_probe_dialog),
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
        self.actions['downsample'].setToolTip(
            '下采样：体素下采样或随机抽样；参数在独立弹窗设置；结果新增到 DB，原始数据保留')
        self.actions['open'].setToolTip('导入点云：在独立弹窗确认源文件单位后选择文件')
        self.actions['color'].setToolTip('颜色统一：在独立弹窗设置参数，生成独立 DB 结果')
        self.actions['probe'].setToolTip('点云探针：打开间距、重合度分析与体素参考；点击分析后开始只读计算')
        self.actions['select'].setCheckable(True)
        self.actions['select'].setToolTip('选取分割：左键添加顶点，封闭后选择保留方向并点击快捷删除')
        self.actions['select'].setAccessibleName('多边形框选')
        actions.addStretch()
        root.addWidget(self.operation_bar)
        self.actions['compare'].setCheckable(True)
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
        self.probe.adopt.connect(self.adopt_probe_voxel)
        self._probe_report = None
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

    def create_color_dialog(self):
        inputs = [(uid, self._clouds[uid].name, len(self._clouds[uid].points)) for uid in self._display_ids]
        dialog = ColorDialog(inputs, self._active_uid, self._color_state, self)
        dialog.parameters_changed.connect(lambda state: setattr(self, '_color_state', dict(state)))
        return dialog

    def open_color_dialog(self):
        if not self._parameter_gate() or not self._display_ids:
            return
        snapshot = self._input_snapshot()
        dialog = self.create_color_dialog()
        accepted = []
        dialog.accepted.connect(lambda: accepted.append(dialog.parameters()))
        if dialog.exec() == QDialog.Accepted:
            state = accepted[0]
            params = ColorParameters(**{key: state[key] for key in asdict(ColorParameters()) if key in state})
            self.correct_colors(params, reference_uid=state['reference'], aligned=state['aligned'], snapshot=snapshot)

    def _color_params(self):
        return ColorParameters(**{key: value for key, value in self._color_state.items()
                                 if key in asdict(ColorParameters())})

    @staticmethod
    def _color_params_text(params):
        return (f'算法={params.algorithm}，预下采样={params.voxel_size:g}mm，尺度={params.scale:g}mm，强度={params.strength:.0%}，上限={params.max_gain:g}，'
                f'接缝融合={params.seam_strength:.0%}，样本上限={params.sample_limit}，重叠距离={params.overlap_distance:g}mm')

    def _show_color_diagnostic(self, params, reports, heading='颜色统一'):
        self._last_color_report = reports
        self._last_color_params = asdict(params)
        lines = [heading+'；'+self._color_params_text(params)]
        for row in reports:
            row.setdefault('params', asdict(params))
            text = (f"{row.get('name', '点云')}：{row.get('status', '拒绝')}，样本{row.get('samples', 0)}，"
                    f"格/支持{row.get('nodes', 0)}/{row.get('supported_nodes', 0)}，几何分区{row.get('components', 1)}，重叠内点{row.get('matches', 0)}")
            if 'output_points' in row:
                text += f"，点数{row['input_points']:,}→{row['output_points']:,}"
            if 'gain_min' in row:
                text += (f"，估计增益{np.round(row.get('estimated_gain_min', row.get('estimated_gain', [1]*3)), 3).tolist()}"
                         f"..{np.round(row.get('estimated_gain_max', row.get('estimated_gain', [1]*3)), 3).tolist()}"
                         f"，应用{np.round(row['gain_min'], 3).tolist()}..{np.round(row['gain_max'], 3).tolist()}"
                         f"，变化>5%/{row.get('changed_gt5_fraction', 0):.1%}、>10%/{row.get('changed_gt10_fraction', 0):.1%}"
                         f"，分布保留{row.get('distribution_retention', 1):.1%}，截断{row.get('clipped_fraction', 0):.2%}"
                         f"，实际强度{row.get('actual_strength', params.strength):.1%}")
                if row.get('adaptive_scale', 1) < 1:
                    text += f"，受高光限制，实际幅度k={row['adaptive_scale']:.1%}"
                if row.get('material_warning'):
                    text += '；可能抹平材质，建议降低强度'
            if row.get('reason'):
                text += '；'+row['reason']
            lines.append(text)
        message = '\n'.join(lines)
        self.bridge.shell.log(message, 'info')
        self.status.setToolTip(message)
        return message

    def compare_color_source(self):
        sources, results = self._color_comparison
        if (self._worker is not None or self._closed or not sources or not results
                or not self.bridge.can_change_workspace() or self.database.directory != self.directory
                or self.database is not self.bridge.frame_db.databases[self.mode]):
            return
        target = results if tuple(self._display_ids) == sources else sources
        if any(uid not in self.database.records or self.database.records[uid].status == STALE_RESULT for uid in target):
            self._set_status('对比来源或结果已变化，请重新生成颜色统一结果。')
            return
        # Only UID lists are retained. Reload on demand; never keep a second
        # permanent full-size colour cache just to compare the original.
        self.load_selected(list(target))

    def correct_colors(self, params=None, *, reference_uid=None, aligned=None, snapshot=None):
        if snapshot is not None and snapshot != self._input_snapshot():
            self._set_status('输入、来源修订或项目已变化，请重新打开参数。')
            return
        if (self._worker is not None or self._closed or not self.bridge.can_change_workspace()
                or self.database is not self.bridge.frame_db.databases[self.mode]
                or self.database.directory != self.directory):
            self._set_status('正在处理或项目已切换，不能执行颜色统一。')
            return
        identifiers = list(self._display_ids)
        if not identifiers:
            self._set_status('请先显示至少一项有色点云。')
            return
        with self.database._lock:
            if any(uid not in self.database.records or self.database.records[uid].status == STALE_RESULT
                    or self._clouds[uid].origins != ((uid, self.database.records[uid].revision),)
                    for uid in identifiers):
                self._set_status('来源数据已变化，请重新显示后执行颜色统一。')
                return
        if len(identifiers) > 1 and (not (self._color_state['aligned'] if aligned is None else aligned) or any(
                self.database.records[uid].kind == 'raw' for uid in identifiers)):
            self._set_status('多云需同一坐标系，重叠区用于估计；原始未配准帧请先拼接，并确认坐标系。')
            return
        layers = [self._clouds[uid] for uid in identifiers]
        if any(layer.colors is None for layer in layers):
            self._set_status('颜色统一拒绝无色或混合有色/无色输入，不会补造原始颜色。')
            return
        reference = reference_uid if reference_uid is not None else self._color_state.get('reference')
        if reference_uid is not None and reference_uid not in identifiers:
            self._set_status('参考点云已变化，请重新打开颜色参数。')
            return
        reference = identifiers.index(reference) if reference in identifiers else identifiers.index(
            self._active_uid) if self._active_uid in identifiers else 0
        params = params or self._color_params()
        try:
            params.validate()
        except ValueError as exc:
            self._set_status(self._show_color_diagnostic(params, [dict(status='参数拒绝', reason=str(exc))]))
            return
        reports = []
        def work():
            try:
                if params.algorithm == 'image_fusion':
                    from core.postprocess.image_color_fusion import source_poses, fuse_image_colors
                    pairs = [fuse_image_colors(self.database, layer, source_poses(self.database, uid), params)
                             for uid, layer in zip(identifiers, layers)]
                    outputs, details = [p[0] for p in pairs], [p[1] for p in pairs]
                else:
                    outputs, details = correct_color_layers(layers, reference=reference, params=params)
            except NoColorCorrection as exc:
                reports.extend(dict(row, name=layer.name) for layer, row in zip(layers, exc.reports))
                raise
            reports.extend(dict(row, name=layer.name) for layer, row in zip(layers, details))
            return outputs
        def diagnostic():
            self._color_comparison = (tuple(identifiers), tuple(self._display_ids))
            self._refresh_controls()
            return self._show_color_diagnostic(params, reports)
        def failed(error):
            details = reports or [dict(status='拒绝', reason=str(error))]
            self._set_status(self._show_color_diagnostic(params, details, '颜色统一未发布：'+str(error)))
        self._set_status('正在颜色统一；'+self._color_params_text(params))
        self._commit_operation(work, display_all=True, diagnostic=diagnostic, on_error=failed)


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
            staged=self._segment is not None)

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
        self._set_status('正在后台读取点云…' if kind == 'load' else '正在处理并更新 DB…')
        worker.start()
        return True

    def _refresh_controls(self):
        ready = self._worker is None
        for button in self.actions.values():
            button.setEnabled(ready)
        self.source_browser.setEnabled(ready)
        self.actions['undo'].setEnabled(ready and bool(self._undo))
        self.actions['merge'].setEnabled(ready and len(self._display_ids) > 1)
        self.actions['downsample'].setEnabled(ready and self._active_uid in self._clouds)
        self.actions['select'].setEnabled(ready and self._active_uid in self._clouds)
        locked = self.overlay.view_locked
        self.actions['fit'].setEnabled(ready and not locked)
        self.properties.setEnabled(ready and not locked)
        self.actions['color'].setEnabled(ready and not self._closed and bool(self._display_ids)
            and self.bridge.can_change_workspace()
            and self.database is self.bridge.frame_db.databases[self.mode]
            and self.database.directory == self.directory)
        self.actions['probe'].setEnabled(self._parameter_gate() and self._active_uid in self._clouds)
        self.probe.setEnabled(self._parameter_gate())
        sources, results = self._color_comparison
        comparable = bool(sources and results and tuple(self._display_ids) in (sources, results)
            and all(uid in self.database.records and self.database.records[uid].status != STALE_RESULT
                    for uid in (*sources, *results)))
        self.actions['compare'].setEnabled(ready and comparable)
        self.actions['compare'].setText('返回校正结果' if comparable and tuple(self._display_ids) == sources else '对比原色')
        self.actions['compare'].setChecked(comparable and tuple(self._display_ids) == sources)
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

    def load_selected(self, identifiers=None):
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
                output_roles=[layer.output_role for layer in layers])
            for uid, layer in zip(identifiers, layers):
                layer.origins = ((uid, self.database.records[uid].revision),)
        return layers

    def _commit_operation(self, work, *, display_all=False, diagnostic=None, on_error=None):
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
        self.probe.apply.setEnabled(False)
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
        self._run(work, done, kind='probe', preserve_selection=True)

    def adopt_probe_voxel(self, value):
        if self._probe_report is None:
            return
        try:
            if self._probe_report[0] != self._probe_key():
                return
        except ValueError:
            return
        self._downsample_state.update(method='voxel', voxel=float(value))
        # Populate the existing dialog; only its explicit Execute action processes.
        self.open_downsample_dialog()

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
