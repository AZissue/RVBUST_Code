"""Industrial raw acquisition and explicit, independently archived stitching."""
from collections import deque
from pathlib import Path
from weakref import WeakKeyDictionary
import copy
from time import perf_counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                              QFileDialog, QFormLayout, QLabel)
from .dialogs import ChineseMessageBox as QMessageBox
from .dialogs import localize_buttons
from .stitch_failure import show_stitch_failure
from .feature_recognition import FEATURE_RECOGNITION, FEATURE_RESULT_PREFIX
from core.frame_database import STALE_RESULT
from core.calibration_engine import CalibrationEngine
from core.mobile_chain_workflow import MobileChainWorkflow


class ExplicitStitching:
    def __init__(self, bridge):
        self.bridge = bridge
        self.plane_filters = {}
        self._feature_stitcher = None
        self._feature_queue = deque()
        self._feature_observations = WeakKeyDictionary()
        self.feature_busy = False
        self.feature_matching = False
        self._pending_feature_stitch = None

    def _uses_features(self, mode):
        return (mode == 'mobile_chain'
                and getattr(self.bridge.shell, 'feature_recognition_enabled', False)
                and self.bridge.recognition.config(mode)['marker_type'] == FEATURE_RECOGNITION)

    def _features(self):
        if self._feature_stitcher is None:
            from prototypes.superpoint_lightglue.automatic import FeatureStitching
            self._feature_stitcher = FeatureStitching()
        return self._feature_stitcher

    def feature_roi(self):
        return self.bridge.projects.projects['mobile_chain'].feature_roi

    def feature_settings(self):
        return self.bridge.projects.projects['mobile_chain'].feature_settings

    def workpiece_roi(self):
        return self.bridge.projects.projects['mobile_chain'].workpiece_roi

    def workpiece_mask(self):
        return self.bridge.projects.projects['mobile_chain'].workpiece_mask

    def show_feature_mask(self):
        return self.bridge.projects.projects['mobile_chain'].show_feature_mask

    def set_workpiece_roi(self, roi):
        self._set_feature_parameter('workpiece_roi', roi, '工件 ROI')

    def set_workpiece_mask(self, settings):
        self._set_feature_parameter('workpiece_mask', settings, '二值化掩膜')

    def set_show_feature_mask(self, enabled):
        # Rendering never changes the input constraints used by queued matching jobs.
        bridge = self.bridge
        if bridge._current_mode != 'mobile_chain' or not self._uses_features('mobile_chain'):
            return
        project = bridge.projects.projects['mobile_chain']
        project.show_feature_mask = enabled
        self.bridge.projects.mark_changed('mobile_chain')
        self._refresh_feature_image(select_latest=enabled)

    def _refresh_feature_image(self, *, select_latest=False):
        bridge = self.bridge
        database = bridge.frame_db.databases['mobile_chain']
        displayed = bridge.frame_db._displayed.get('mobile_chain')
        row = database.records.get(displayed[0]) if displayed else None
        if row and row.kind == 'raw' and displayed[1].image_np is not None:
            bridge.shell.workspace_mobile()._industrial.show_database_image(
                displayed[1], refresh=True, feature_mode=True,
                feature=self.feature_observation('mobile_chain', row.uid))
        elif select_latest:
            latest = next((r for r in reversed(database.records.values()) if r.kind == 'raw'), None)
            if latest:
                bridge.frame_db.select('mobile_chain', latest.uid, 'image')

    def set_feature_roi(self, roi):
        self._set_feature_parameter('feature_roi', roi, '2D 匹配 ROI')

    def set_feature_settings(self, settings):
        self._set_feature_parameter('feature_settings', settings, '2D 特征配准参数')

    def _set_feature_parameter(self, name, value, label):
        bridge = self.bridge
        mode = 'mobile_chain'
        if bridge._current_mode != mode or not self._uses_features(mode) or not bridge.can_change_workspace():
            return
        project = bridge.projects.projects[mode]
        if getattr(project, name) == value:
            return
        setattr(project, name, value)
        self._feature_observations.pop(project.database, None)
        bridge.projects.mark_changed(mode)
        self._refresh_feature_image()
        self._feature_queue = deque(entry for entry in self._feature_queue if entry[0] is not project.database)
        for row in project.database.records.copy().values():
            if row.kind == 'raw' and row.pointcloud_aligned is not False:
                self._enqueue_feature_capture(project.database, row.uid)
        bridge.shell.log(f'已更新{label}。后台将更新像素匹配缓存，点击「执行拼接」进行配准。', 'info')

    def configure_feature_roi(self, *, workpiece=False):
        from prototypes.superpoint_lightglue.dialog import choose_matching_region
        from prototypes.superpoint_lightglue.pipeline import frame_image

        bridge = self.bridge
        mode = 'mobile_chain'
        if bridge._current_mode != mode or not self._uses_features(mode) or not bridge.can_change_workspace():
            return
        database = bridge.frame_db.databases[mode]
        selected = self._mobile_selection()
        row = (database.records[selected[0]] if len(selected) == 1 else
               next((r for r in reversed(database.records.values()) if r.kind == 'raw'
                     and r.pointcloud_aligned is not False), None))
        if row is None:
            bridge.shell.log('请先拍摄一帧，或打开包含原始 2D 图像的会话，再绘制匹配 ROI。', 'warn')
            return
        try:
            image = frame_image(database.directory, row)
        except ValueError as exc:
            bridge.shell.log(f'无法绘制匹配 ROI：{exc}', 'warn')
            return
        roi = self.workpiece_roi() if workpiece else self.feature_roi()
        context = self.feature_roi() if workpiece else self.workpiece_roi()
        title = '绘制工件 ROI' if workpiece else '绘制特征匹配 ROI'
        roi = choose_matching_region(bridge.shell, image, row.frame_id, roi, title=title,
                                     context_roi=context, workpiece=workpiece)
        if roi is not None:
            (self.set_workpiece_roi if workpiece else self.set_feature_roi)(roi)

    def feature_summary(self):
        database = self.bridge.frame_db.databases['mobile_chain']
        result = next((row for row in reversed(database.records.copy().values())
                       if row.kind == 'result' and row.status != STALE_RESULT
                       and row.logical_name.startswith(FEATURE_RESULT_PREFIX)), None)
        count = len(result.source_ids) if result else 0
        activity = (f' | 后台匹配中（待处理 {len(self._feature_queue)} 帧）' if self.feature_matching else
                    ' | 正在配准拼接' if self.feature_busy else '')
        return f'已拼接 {count} 帧{activity}'

    def feature_observation(self, mode, uid):
        if not self._uses_features(mode):
            return None
        database = self.bridge.frame_db.databases[mode]
        row = database.records.get(uid)
        entry = self._feature_observations.get(database, {}).get(uid)
        if not row or not entry or row.revision != entry.revision:
            return None
        if entry.reference_uid is not None:
            reference = database.records.get(entry.reference_uid)
            if not reference or reference.revision != entry.reference_revision:
                return None
        return entry

    def _record_feature_observations(self, database, entries):
        cache = self._feature_observations.setdefault(database, {})
        cache.update((entry.uid, entry) for entry in entries)
        displayed = self.bridge.frame_db._displayed.get('mobile_chain')
        if (self.bridge._current_mode == 'mobile_chain'
                and database is self.bridge.frame_db.databases['mobile_chain']
                and displayed and displayed[0] in cache and displayed[1].image_np is not None):
            uid, frame, _ = displayed
            self.bridge.shell.workspace_mobile()._industrial.show_database_image(
                frame, refresh=True, feature_mode=True, feature=self.feature_observation('mobile_chain', uid))

    def _show_feature_result(self, database, result):
        bridge = self.bridge
        row = database.records[result.uid]
        ws = bridge.shell.workspace_mobile()
        ws.viewer().set_pointcloud_merged(result.cloud)
        moving, anchor = result.links[-1]
        path = '、'.join(f'{source:03d}→{target:03d}' for source, target in result.links)
        details = (f'{len(row.source_ids)} 帧已拼接，帧 {moving:03d} 接到 {anchor:03d}，'
                   f'本步使用 {result.references} 个参考，'
                   f'{result.inliers}/{result.shared} 对 3D 内点，拟合 RMS {result.rms:.3f} mm')
        ws.set_evaluation(result.shared, result.inliers / result.shared, result.rms, 'ok',
                          details, scope='2D 特征')
        if ws.current_state() not in ('capturing', 'evaluating'):
            ws.set_state('chaining')
        self._record_feature_observations(database, result.observations)
        bridge.shell.set_dirty(True)
        bridge.shell.log(f'SuperPoint + LightGlue：{details}。本次接入关系 {path}。', 'success')
        bridge.shell._refresh_statusbar()

    def _feature_options(self):
        return dict(roi=self.feature_roi(), settings=self.feature_settings(),
                    workpiece_roi=self.workpiece_roi(), mask_settings=self.workpiece_mask())

    def _pixel_options_key(self, options):
        from prototypes.superpoint_lightglue.matching import matching_key
        return matching_key(**options)

    def _feature_inputs(self, database, uid):
        from prototypes.superpoint_lightglue.automatic import MAX_REFERENCES
        rows = [r for r in database.records.copy().values()
                if r.kind == 'raw' and r.pointcloud_aligned is not False]
        index = next((i for i, row in enumerate(rows) if row.uid == uid), None)
        if index is None:
            return ()
        return tuple((r.uid, r.revision) for r in rows[max(0, index-MAX_REFERENCES):index+1])

    def _matching_is_current(self, database, inputs, key):
        return (self._uses_features('mobile_chain')
                and database is self.bridge.frame_db.databases['mobile_chain']
                and key == self._pixel_options_key(self._feature_options())
                and all(uid in database.records and database.records[uid].revision == revision
                        for uid, revision in inputs))

    def _sync_feature_progress(self):
        message = ('正在后台匹配 2D 特征，剩余 %d 帧' % len(self._feature_queue)
                   if self.feature_matching else
                   '正在根据像素匹配计算 3D 配准和点云拼接' if self.feature_busy else None)
        self.bridge.shell.set_background_activity('feature_matching', message)
        self.bridge.shell._refresh_statusbar()

    def _enqueue_feature_capture(self, database, uid):
        options = self._feature_options()
        inputs = self._feature_inputs(database, uid)
        self._feature_queue.append((database, uid, options, inputs))
        self._start_feature_capture()

    def _start_feature_capture(self):
        bridge = self.bridge
        if self.feature_matching or self.feature_busy or getattr(bridge, '_cleaned', False):
            self._sync_feature_progress()
            return
        while self._feature_queue:
            database, uid, options, inputs = self._feature_queue.popleft()
            key = self._pixel_options_key(options)
            if inputs and self._matching_is_current(database, inputs, key):
                break
        else:
            self._sync_feature_progress()
            return
        self.feature_matching = True
        self._sync_feature_progress()

        def done(result, error):
            self.feature_matching = False
            if self._matching_is_current(database, inputs, key):
                if error is not None:
                    bridge.shell.log(f'帧 {database.records[uid].frame_id:03d} 的 2D 匹配失败：{error}', 'warn')
                else:
                    self._record_feature_observations(database, result)
                    bridge.shell.log(f'帧 {database.records[uid].frame_id:03d} 的 2D 匹配已缓存。', 'info')
            if self._pending_feature_stitch is not None:
                self._run_feature_registration()
            else:
                self._start_feature_capture()
            self._sync_feature_progress()

        bridge._run_background(lambda: self._features().prepare(database, uid, **options), done,
                               name='feature_match')

    def _execute_features(self, database, raw_ids):
        self.feature_busy = True
        self._pending_feature_stitch = (database, tuple(raw_ids), self._feature_options())
        self._sync_feature_progress()
        if self.feature_matching:
            self.bridge.shell.log('已请求执行拼接，当前 2D 匹配完成后将使用缓存进行配准。', 'info')
        else:
            self._run_feature_registration()

    def _run_feature_registration(self):
        bridge = self.bridge
        database, raw_ids, options = self._pending_feature_stitch
        self._pending_feature_stitch = None
        self._sync_feature_progress()
        bridge.shell.log(f'正在使用像素匹配缓存对 {len(raw_ids)} 帧进行 3D 配准…', 'info')

        def done(result, error):
            self.feature_busy = False
            if error:
                if hasattr(error, 'observation'):
                    self._record_feature_observations(database, (error.observation,))
                bridge.shell.workspace_mobile().set_evaluation(0, 0, None, 'fail', str(error), scope='2D 特征')
                bridge.shell.log(f'SuperPoint + LightGlue 拼接失败：{error}', 'warn')
            else:
                self._show_feature_result(database, result)
            self._start_feature_capture()
            self._sync_feature_progress()

        bridge._run_background(lambda: self._features().stitch(database, raw_ids, **options), done,
                               must_finish=True, name='feature_stitch')

    def configure_plane_filter(self):
        bridge = self.bridge
        mode = bridge._current_mode
        if mode not in ('mobile_chain', 'turntable') or not bridge.can_change_workspace():
            return
        dialog = QDialog(bridge.shell)
        dialog.setWindowTitle('标记物平面过滤')
        layout = QFormLayout(dialog)
        settings = self.plane_filters.get(mode, {})

        def mm_input(value, minimum=0.0):
            spin = QDoubleSpinBox()
            spin.setRange(minimum, 1000)
            spin.setDecimals(2)
            spin.setSingleStep(.25)
            spin.setSuffix(' mm')
            spin.setValue(value)
            return spin

        active = QCheckBox('启用平面过滤')
        active.setChecked(bool(settings))
        height = mm_input(settings.get('clearance_mm', 1.0))
        bottom = QCheckBox('保留底边')
        bottom.setChecked('bottom_height_mm' in settings)
        lower = mm_input(settings.get('bottom_height_mm', .5))
        radius = mm_input(settings.get('radius_mm', .75), .01)
        layout.addRow(active)
        layout.addRow('主体保留高度', height)
        layout.addRow(bottom)
        layout.addRow('底边最低高度', lower)
        layout.addRow('补点半径', radius)
        note = QLabel('适用于标记物与工件底面共面的平台。相机应始终从工件侧拍摄。\n'
                      '保留高于主体高度的点；开启保留底边后，只补回靠近主体的低处点。原始帧不受影响。')
        note.setWordWrap(True)
        layout.addRow(note)
        error = QLabel('底边最低高度须低于主体保留高度。')
        layout.addRow(error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        localize_buttons(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        def refresh():
            enabled = active.isChecked()
            restore_bottom = enabled and bottom.isChecked()
            valid = not restore_bottom or lower.value() < height.value()
            height.setEnabled(enabled)
            bottom.setEnabled(enabled)
            lower.setEnabled(restore_bottom)
            radius.setEnabled(restore_bottom)
            error.setVisible(not valid)
            buttons.button(QDialogButtonBox.Ok).setEnabled(valid)

        active.toggled.connect(refresh)
        bottom.toggled.connect(refresh)
        height.valueChanged.connect(refresh)
        lower.valueChanged.connect(refresh)
        refresh()
        if dialog.exec() != QDialog.Accepted:
            return
        if active.isChecked():
            settings = dict(clearance_mm=height.value())
            if bottom.isChecked():
                settings.update(bottom_height_mm=lower.value(), radius_mm=radius.value())
            self.plane_filters[mode] = settings
        else:
            self.plane_filters.pop(mode, None)
        button = bridge.shell._industrial_ribbon.commands[(mode, 'plane_filter')]
        button.setText('平面过滤 · 开' if active.isChecked() else '平面过滤')

    def selected_raw(self, mode):
        browser = self.bridge.frame_db.browsers.get(mode)
        if browser is None:
            return None
        items = browser.tree.selectedItems()
        ids = browser.selected_ids()
        if (not items or len(ids) != 1 or any(not item.data(0, Qt.UserRole) for item in items)):
            return None
        uid = ids[0]
        return uid if browser.database.records[uid].kind == 'raw' else None

    def can_recapture(self, mode):
        bridge = self.bridge
        uid = self.selected_raw(mode)
        if uid is None or not bridge.can_change_workspace() or bridge.offline_preview:
            return False
        record = bridge.frame_db.databases[mode].records[uid]
        return record.camera in bridge.camera_manager.get_connected_ids()

    def recapture_selected(self):
        bridge = self.bridge
        mode = bridge._current_mode
        if mode == 'mobile_chain':
            return self.recapture_mobile()
        if mode not in ('multi_cam', 'turntable') or not self.can_recapture(mode):
            return
        uid = self.selected_raw(mode)
        database = bridge.frame_db.databases[mode]
        row = copy.deepcopy(database.records[uid])
        calibration = '标定' in row.purpose or row.purpose == 'calib'
        frames = bridge.frame_db._frames()
        preview = bridge._pause_2d_preview()
        cards = bridge._pause_card_preview()
        bridge.frame_db._selection += 1
        bridge.shell.show_loading('正在重拍选中帧，成功后覆盖原数据…')
        def work():
            with bridge.frame_db.replacing_capture(mode, uid):
                frame = bridge.camera_manager.capture(row.camera)
            if frame is None:
                raise IOError('相机采集失败，旧帧保持不变')
            if calibration:
                for key, record in list(database.records.items()):
                    if record.kind == 'result':
                        database.set_status(key, STALE_RESULT)
            return database.load_frame(uid)
        def done(result, error):
            bridge.shell.hide_loading()
            bridge._resume_2d_preview(preview)
            bridge._resume_card_preview(cards)
            if error:
                QMessageBox.warning(bridge.shell,'重拍失败',str(error))
                return
            frame, cloud = result
            # Replace owned workflow references too; retaining a cached old cloud
            # would make a later stitch silently use the preceding exposure.
            for previous in frames:
                if previous.database_id == uid:
                    previous.__dict__.update(frame.__dict__)
            if mode == 'turntable':
                ws = bridge.shell.workspace_turntable()
                for index, previous in enumerate(ws.session.sequence):
                    if previous.database_id == uid:
                        ws.session.sequence[index] = frame
                        ws.session.sequence_pcds[index] = cloud
                        ws.session.sequence_markers[index] = []
                if calibration:
                    slot = 0 if 'frame0' in row.purpose else 1
                    setattr(ws,'current_frame'+str(slot),frame)
                    setattr(ws,'current_markers'+str(slot),[])
                    getattr(ws.session,'set_frame'+str(slot))(frame,[],cloud)
                    ws.session.calibrated = False
                    ws.session.calibration_result = None
                    ws.set_state('connected')
                ws.merged = None
            elif calibration:
                workflow = bridge.fixed_workflow
                workflow.frames_calib[row.camera] = frame
                workflow._calibration_locked = False
                workflow._state = workflow.STATE_CALIBRATING
                bridge.calibration_engine.reset()
                bridge.shell.workspace_multi().set_state('captured')
            else:
                bridge.fixed_workflow.frames_scan[row.camera] = frame
            workspace = bridge.shell.workspace_turntable() if mode == 'turntable' else bridge.shell.workspace_multi()
            viewer = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
            viewer.clear_all()
            bridge.frame_db.browsers[mode].refresh()
            bridge.frame_db.display_frame(mode,uid,frame,cloud)
            bridge.shell.set_dirty(True)
            bridge.shell.log('已覆盖选中帧的点云和图像；'+('请重新识别并计算标定，再执行拼接。' if calibration else '请重新执行拼接。'),'success')
        bridge._run_background(work,done,must_finish=True,name='selected_raw_recapture')

    def _mobile_selection(self):
        browser = self.bridge.frame_db.browsers.get('mobile_chain')
        if browser is None:
            return []
        database = self.bridge.frame_db.databases['mobile_chain']
        items = browser.tree.selectedItems()
        # Groups and result records are not physical capture/edit targets.
        if not items or any(not item.data(0, Qt.UserRole) for item in items):
            return []
        identifiers = browser.selected_ids()
        if any(database.records[uid].kind != 'raw' for uid in identifiers):
            return []
        return identifiers

    def update_mobile_actions(self):
        bridge = self.bridge
        if bridge.shell._presentation != 'industrial' or bridge._current_mode != 'mobile_chain':
            return
        ws = bridge.shell.workspace_mobile()
        database = bridge.frame_db.databases['mobile_chain']
        selected = self._mobile_selection()
        busy = not bridge.can_change_workspace() or ws.current_state() in ('capturing', 'evaluating')
        online = bool(bridge.camera_manager.get_connected_ids()) and not (
            bridge.offline_preview or getattr(ws, 'offline_preview', False))
        ws._btn_recapture.setEnabled(not busy and online and len(selected) == 1)
        ws._btn_delete_node.setEnabled(not busy and bool(selected))
        ws._btn_undo.setEnabled(not busy and any(row.kind == 'raw' for row in database.records.values()))
        target = ('DB 原始帧 %03d' % database.records[selected[0]].frame_id) if len(selected) == 1 else 'DB 中单独选中的原始帧'
        ws._btn_recapture.setToolTip('重拍' + target + '，覆盖对应PLY和2D图像；请将相机移到目标位置')
        ws._btn_delete_node.setToolTip('删除DB中选中的原始帧（含PLY和2D图像，可从回收区恢复），需重新执行拼接')
        ws._btn_undo.setToolTip('撤销DB中的最后一帧原始数据（与当前选择无关，可从回收区恢复）')
        ribbon = bridge.shell._industrial_ribbon
        browser = bridge.frame_db.browsers.get('mobile_chain')
        available = browser is not None and browser.export_uid() is not None
        ribbon.commands[('mobile_chain', 'export')].setEnabled(not busy and available)

    def _reset_mobile_registration(self):
        bridge = self.bridge
        bridge.frame_db.restore('mobile_chain')
        bridge.mobile_workflow.reset()
        bridge.mobile_workflow.start_chaining()
        bridge.projects.prepare('mobile_chain')
        bridge.frame_db.synchronize()
        ws = bridge.shell.workspace_mobile()
        ws.set_stations([])
        ws.viewer().clear_all()
        bridge._refresh_mobile_live_view_to_latest()
        ws._industrial.restore_business_image()
        ws.set_state('connected' if bridge.camera_manager.get_connected_ids() else 'idle')
        bridge.shell.set_dirty(True)

    def recapture_mobile(self):
        bridge = self.bridge
        if not bridge.can_change_workspace():
            return
        selected = self._mobile_selection()
        if len(selected) != 1:
            bridge.shell.log('请在DB树中单独选择要重拍的原始帧或其PLY/图像子项。', 'warn')
            return
        cameras = bridge.camera_manager.get_connected_ids()
        if not cameras or bridge.offline_preview or getattr(bridge.shell.workspace_mobile(), 'offline_preview', False):
            bridge.shell.log('重拍需要连接实体相机；离线数据仍可删除或重新拼接。', 'warn')
            return
        uid = selected[0]
        database = bridge.frame_db.databases['mobile_chain']
        number = database.records[uid].frame_id
        revision = database.records[uid].revision
        preview = bridge._pause_2d_preview()
        cards = bridge._pause_card_preview()
        ws = bridge.shell.workspace_mobile()
        ws.set_state('capturing')
        bridge.frame_db._selection += 1
        bridge.shell.show_loading(f'正在重拍 DB 原始帧 {number:03d}...')
        def work():
            with bridge.frame_db.replacing_capture('mobile_chain', uid):
                frame = bridge.camera_manager.capture(cameras[0])
            if frame is None:
                raise IOError('相机采集失败，原始数据已保留')
            # The production capture sink validates and commits the complete pair.
            return database.load_frame(uid)
        def done(result, error):
            bridge.shell.hide_loading()
            bridge._resume_2d_preview(preview)
            bridge._resume_card_preview(cards)
            if error:
                if database.records[uid].revision != revision:
                    self._reset_mobile_registration()
                    bridge.shell.log('重拍数据已保存，但预览失败，请重新选择该原始帧：' + str(error), 'error')
                    return
                ws.set_state('chaining' if ws._station_count else 'connected')
                bridge.shell.log('重拍失败，旧帧保持不变：' + str(error), 'error')
                return
            self._reset_mobile_registration()
            frame, cloud = result
            bridge.frame_db.browsers['mobile_chain'].refresh()
            bridge.frame_db.display_frame('mobile_chain', uid, frame, cloud)
            bridge.shell.log(f'已覆盖 DB 原始帧 {number:03d}（PLY和2D图像）；请重新执行拼接。', 'success')
            bridge.shell._refresh_statusbar()
        bridge._run_background(work, done, must_finish=True, name='project_raw_recapture')

    def undo_mobile(self):
        bridge = self.bridge
        database = bridge.frame_db.databases['mobile_chain']
        raw = [uid for uid, row in database.records.items() if row.kind == 'raw']
        if raw:
            self._remove_mobile([raw[-1]], '撤销末帧')

    def delete_mobile(self):
        selected = self._mobile_selection()
        if not selected:
            self.bridge.shell.log('请在DB树中选择要删除的原始帧。', 'warn')
            return
        self._remove_mobile(selected, '删除机位')

    def _remove_mobile(self, identifiers, title):
        bridge = self.bridge
        if not bridge.can_change_workspace():
            return
        database = bridge.frame_db.databases['mobile_chain']
        labels = '、'.join(f'{database.records[uid].frame_id:03d}' for uid in identifiers)
        answer = QMessageBox.question(bridge.shell, title,
            f'将 DB 原始帧 {labels} 的PLY和2D图像移到回收区？\n'
            '当前配准将清空，相关拼接结果标记为需重新拼接；可通过DB右键恢复原始数据。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        bridge.frame_db._selection += 1
        bridge.shell.show_loading('正在更新DB机位数据...')
        def work():
            return database.remove(identifiers, invalidate_results=True)
        def done(result, error):
            bridge.shell.hide_loading()
            if error:
                bridge.shell.log(title + '失败：' + str(error), 'error')
                return
            self._reset_mobile_registration()
            bridge.frame_db.browsers['mobile_chain'].refresh()
            bridge.shell.log(f'已{title}：DB 原始帧 {labels}；请重新执行拼接。', 'success')
            bridge.shell._refresh_statusbar()
        bridge._run_background(work, done, must_finish=True, name='project_mobile_edit')

    def capture_mobile(self):
        bridge = self.bridge
        mode = 'mobile_chain'
        features = self._uses_features(mode)
        if not (bridge.can_change_workspace(allow_feature=True) if features else bridge.can_change_workspace()):
            return
        cameras = bridge.camera_manager.get_connected_ids()
        if not cameras:
            bridge.shell.log('请先连接相机。', 'warn')
            return
        preview = bridge._pause_2d_preview()
        ws = bridge.shell.workspace_mobile()
        database = bridge.frame_db.databases[mode]
        show_cloud = not features or not any(row.kind == 'raw' for row in database.records.values())
        ws.set_state('capturing')
        bridge.shell.show_loading('正在拍摄原始帧并存入DB...')

        def work():
            frame = bridge.camera_manager.capture(cameras[0])
            if frame is None:
                raise ValueError('拍摄失败，请查看设备日志')
            return frame, frame.load_pointcloud_o3d() if show_cloud else None

        def done(result, error):
            bridge.shell.hide_loading()
            ws.set_state('chaining' if ws._station_count or ws.viewer()._merged is not None else 'connected')
            bridge._resume_2d_preview(preview)
            if error:
                bridge.shell.log('原始帧采集失败：' + str(error), 'error')
                return
            frame, cloud = result
            bridge.frame_db.display_frame(mode, frame.database_id, frame, cloud,
                                          'frame' if show_cloud else 'image', switch_view=False)
            bridge.shell.set_dirty(True)
            if frame.pointcloud_aligned is False:
                bridge.shell.log('原始点云与2D图像已保存；该帧未对齐，已标黄。请开启“点云对应2D”后重拍当前帧，暂不能参与拼接。', 'warn')
            elif features:
                self._enqueue_feature_capture(database, frame.database_id)
            else:
                bridge.shell.log('原始点云与2D图像已入DB；点击“执行拼接”生成结果。', 'success')
            bridge.shell._refresh_statusbar()

        bridge._run_background(work, done, must_finish=True, name='raw_capture')

    def execute(self, prepared=None):
        bridge = self.bridge
        if not bridge.can_change_workspace():
            bridge.shell.log('请等待当前任务完成后再执行拼接。', 'warn')
            return
        mode = bridge._current_mode
        if mode == 'robot_stitch':
            bridge._on_robot_publish()
            return
        database = bridge.frame_db.databases[mode]
        raw_ids = [uid for uid, row in database.records.items() if row.kind == 'raw']
        browser = bridge.frame_db.browsers[mode]
        checked = [uid for uid, _ in browser.checked_components('cloud')]
        explicit = bool(checked)
        plane_filter = self.plane_filters.get(mode)
        selected = browser.selected_ids()
        selected = [uid for uid in selected if uid in raw_ids]
        if mode == 'mobile_chain' and len(selected) >= 2:
            raw_ids = selected
        if checked:
            raw_ids = checked
        if prepared is not None:
            if prepared[0] != mode:
                return
            raw_ids = prepared[1]
            explicit = prepared[2]
            plane_filter = prepared[3]
        if any(uid not in database.records or database.records[uid].kind != 'raw' for uid in raw_ids):
            bridge.shell.log('请仅勾选原始点云执行拼接；拼接结果不能作为原始帧输入。', 'warn')
            return
        unaligned = [database.records[uid] for uid in raw_ids if database.records[uid].pointcloud_aligned is False]
        if unaligned:
            show_stitch_failure(bridge, mode, '帧' + '、'.join(f'{row.frame_id:03d}' for row in unaligned) + '：点云未与2D对齐，无法参与拼接。请将拍摄参数“点云对应2D”设为“是”，然后重拍这些帧。')
            return
        if len(raw_ids) < 2:
            bridge.shell.log('执行拼接至少需要两帧原始数据。', 'warn')
            return
        if self._uses_features(mode):
            selected_ids = set(raw_ids)
            self._execute_features(database, [uid for uid in database.records if uid in selected_ids])
            return
        turn = bridge.shell.workspace_turntable()
        step_indices = None
        if explicit and mode == 'turntable' and turn.session.is_calibrated():
            steps = {frame.database_id: i for i, frame in enumerate(turn.session.sequence)}
            for i, frame in enumerate((turn.session.frame0, turn.session.frame1)):
                if frame is not None:
                    steps[frame.database_id] = i
            for uid in raw_ids:
                purpose = database.records[uid].purpose
                if purpose in ('转台标定 frame0', '转台标定 frame1'):
                    steps[uid] = int(purpose[-1])
            if all(uid in steps for uid in raw_ids):
                raw_ids = sorted(raw_ids, key=steps.get)
                step_indices = [steps[uid] for uid in raw_ids]
        use_chain = mode == 'mobile_chain' or (explicit and mode == 'turntable' and step_indices is None)
        recognition_inputs = raw_ids if explicit else ([frame.database_id for frame in turn.session.get_all_frames()] if mode == 'turntable' else raw_ids)
        # Fixed-camera scans already have calibrated extrinsics; their markers
        # remain useful for inspection but are not an input to this stitch.
        recognize_turntable_dots = (mode == 'turntable' and
            turn.combo_marker_type.currentData() == 'unencoded_circle')
        if mode != 'multi_cam' and (not explicit or use_chain or recognize_turntable_dots or plane_filter) and not bridge.recognition.ensure(mode, recognition_inputs,
                lambda: self.execute((mode, raw_ids, explicit, plane_filter)),
                on_error=lambda error: show_stitch_failure(bridge, mode, error)):
            return
        voxel = turn.spin_voxel.value() or None
        refine = turn.chk_icp_refine.isChecked()
        preview = bridge._pause_2d_preview()
        cards = bridge._pause_card_preview()
        frame_names = {f'station_{number}': f'帧{database.records[uid].frame_id:03d}'
                       for number, uid in enumerate(raw_ids, 1)}
        if use_chain:
            bridge.shell.log('参与拼接的原始点云：' + '、'.join(frame_names.values()), 'info')
        bridge.shell.show_loading('正在执行拼接；原始帧保持独立...')
        stitch_report = []
        def work():
            started = perf_counter()
            workflow = None
            source_transforms = {}
            source_planes = {}
            sources = raw_ids
            import sys
            process_sources = raw_ids if explicit else [frame.database_id for frame in turn.session.get_all_frames()]
            if plane_filter:
                from core.marker_plane import fit_marker_plane
                details = f"主体保留高度 > {plane_filter['clearance_mm']:g} mm"
                if 'bottom_height_mm' in plane_filter:
                    details += (f"，底边最低高度 > {plane_filter['bottom_height_mm']:g} mm"
                                f"，补点半径 {plane_filter['radius_mm']:g} mm")
                stitch_report.append(f'标记物平面过滤：{details}。')
                for uid in raw_ids if use_chain else process_sources:
                    row = database.records.get(uid)
                    if row is None:
                        raise ValueError('转台扫描帧已从DB删除，请重新采集后拼接')
                    try:
                        source_planes[uid] = fit_marker_plane(row.markers, **plane_filter)
                    except ValueError as exc:
                        raise ValueError(f'帧{row.frame_id:03d}：{exc}') from exc
            plane_options = dict(planes=[source_planes[uid] for uid in process_sources]) if source_planes and not use_chain else {}
            isolated = (mode == 'turntable' and not use_chain and not getattr(sys, 'frozen', False)
                        and all(uid in database.records for uid in process_sources)
                        and sum(database.records[uid].points or 0 for uid in process_sources) >= 1_000_000)
            if isolated:
                from core.turntable_stitch_job import run_job
                import numpy as np
                from ui_common.industrial_scene.marker_display import valid_xyz
                sources = process_sources
                calib = turn.session.calib
                config = dict(axis=calib.axis.tolist(), center=calib.center.tolist(),
                    angle_deg=float(np.degrees(calib.angle_rad)), step_count=calib.step_count)
                markers = [[m for m in database.records[uid].markers if valid_xyz(m) is not None] for uid in sources]
                merged, metadata = run_job([database.directory/'frames'/uid/'pointmap.ply' for uid in sources],
                    config, markers, step_indices if explicit else None, voxel, refine, **plane_options)
                source_transforms = {uid: t for uid, t in zip(sources, metadata['transforms']) if t is not None}
                if recognize_turntable_dots or source_planes:
                    stitch_report.append(metadata['message'])
                stitch_report.append('独立进程拼接：' + '、'.join(
                    f'帧{database.records[uid].frame_id:03d} 有效{count:,}点'
                    for uid, count in zip(sources, metadata['counts'])) + f'；输出 {len(merged.points):,} 点。')
            elif use_chain:
                workflow = MobileChainWorkflow(bridge.camera_manager, bridge.marker_detector,
                    CalibrationEngine(display_names=frame_names), bridge.stitch_engine, bridge.processor)
                workflow.start_chaining(defer_cloud=True)
                manager = workflow.station_manager
                manager.managed_frames = True
                for number, uid in enumerate(raw_ids, 1):
                    frame, _ = database.load_frame(uid, 'image')
                    frame.camera_name = sid = f'station_{number}'
                    chain = workflow._chain_stitcher
                    ok, message, edge = chain.add_frame(frame,
                        detect_markers=not bool(frame.recognition_key or frame.markers_all or frame.markers))
                    if not ok:
                        raise ValueError(f'{frame_names[sid]}：{message}；未生成结果，请移除质量不佳的帧后重试')
                    manager._stations[sid] = frame
                    manager._station_seq = number
                    workflow._last_edge = edge
                geometry = chain.nodes[chain._reference_id].unencoded
                if len(chain.nodes) >= 3:
                    ok, message, before_mm, after_mm = workflow.optimize_global()
                    if geometry and not chain.has_cross_frame_constraints():
                        stitch_report.append(message)
                    elif not ok:
                        raise ValueError(message)
                    elif geometry:
                        stitch_report.append(f'{message}，圆心 RMS {before_mm:.3f} → {after_mm:.3f} mm。')
                elif geometry:
                    stitch_report.append('普通圆点链式拼接完成，尚无通过几何验证的闭环共视帧。')
                source_transforms = {node.frame.database_id: node.T_world.tolist()
                    for node in workflow._chain_stitcher.nodes.values()}
                poses_done = perf_counter()
                merged = chain.finish_batch(source_planes)
                stitch_report.append(f'位姿计算 {poses_done - started:.2f} 秒，点云读取与合并 {perf_counter() - poses_done:.2f} 秒。')
                if source_planes:
                    counts = chain.filter_counts.values()
                    before, kept = map(sum, zip(*counts))
                    stitch_report.append(f'标记物平面过滤点数：{before:,} → {kept:,} 点。')
                if mode != 'mobile_chain':
                    workflow = None
            elif explicit and mode == 'multi_cam':
                import open3d as o3d
                from core.point_cloud_processor import PointCloudProcessor
                from core.pcd_utils import merge_pointclouds
                frames = {}
                ok, message = bridge.fixed_workflow._check_calibration_quality()
                if not ok:
                    raise ValueError('请先完成有效外参标定：' + message)
                for uid in raw_ids:
                    frame, cloud = database.load_frame(uid)
                    camera = database.records[uid].camera
                    if camera in frames:
                        raise ValueError('同一相机勾选了多帧，请每台相机仅勾选一帧')
                    cloud, _ = PointCloudProcessor._filter_valid(cloud)
                    if not len(cloud.points):
                        raise ValueError('勾选帧没有有效点云：' + camera)
                    frames[camera] = cloud
                reference = bridge.fixed_workflow.reference_id
                if not reference or not bridge.calibration_engine.pair_results:
                    raise ValueError('请先完成多相机外参标定')
                merged = o3d.geometry.PointCloud()
                for camera, cloud in frames.items():
                    transform = bridge.calibration_engine.get_transform(camera, reference)
                    source_transforms[next(uid for uid in raw_ids if database.records[uid].camera == camera)] = transform.tolist()
                    cloud.transform(transform)
                    merge_pointclouds(merged, cloud)
                merged, _ = bridge.processor.process(merged)
            elif explicit and mode == 'turntable':
                frames_clouds = [database.load_frame(uid) for uid in raw_ids]
                from core.point_cloud_processor import PointCloudProcessor
                clouds = [cloud if source_planes else PointCloudProcessor._filter_valid(cloud)[0]
                          for _, cloud in frames_clouds]
                if any(not len(cloud.points) for cloud in clouds):
                    raise ValueError('勾选帧没有有效点云')
                from ui_common.industrial_scene.marker_display import valid_xyz
                markers = [[m for m in frame.markers if valid_xyz(m) is not None] for frame, _ in frames_clouds]
                color_calib = copy.deepcopy(turn.session.calib)
                merged, message = color_calib.stitch_pointclouds(clouds,
                    downsample_voxel=voxel, icp_refine=refine, markers=markers, step_indices=step_indices,
                    **plane_options)
                if merged is None:
                    raise ValueError(message)
                source_transforms = {uid: t.tolist() for uid, t in zip(raw_ids, color_calib.last_stitch_transforms) if t is not None}
            elif mode == 'multi_cam':
                sources = [frame.database_id for frame in bridge.fixed_workflow.frames_scan.values()]
                if len(sources) < 2:
                    raise ValueError('至少需要两台相机的扫描帧，请先完成外参标定并采集')
                if any(uid not in database.records for uid in sources):
                    raise ValueError('扫描帧已从DB删除，请重新采集后拼接')
                ok, message, merged = bridge.fixed_workflow.stitch()
                if not ok:
                    raise ValueError(message + '；请先完成外参标定并采集扫描帧')
                source_transforms = {uid: bridge.calibration_engine.get_transform(database.records[uid].camera,
                    bridge.fixed_workflow.reference_id).tolist() for uid in sources}
            else:
                sources = [frame.database_id for frame in turn.session.get_all_frames()]
                if any(uid not in database.records for uid in sources):
                    raise ValueError('转台扫描帧已从DB删除，请重新采集后拼接')
                merged, message = turn.session.stitch(downsample_voxel=voxel, icp_refine=refine, **plane_options)
                if merged is None:
                    raise ValueError(message)
                source_transforms = {uid: t.tolist() for uid, t in zip(sources, turn.session.calib.last_stitch_transforms) if t is not None}
            if (recognize_turntable_dots or source_planes) and not (isolated or use_chain):
                stitch_report.append(message)
            publishing = perf_counter()
            uid = database.publish_result(merged, sources, source_transforms=source_transforms, source_planes=source_planes)
            stitch_report.append(f'结果写入 DB {perf_counter() - publishing:.2f} 秒，后台拼接总计 {perf_counter() - started:.2f} 秒。')
            return uid, merged, workflow
        def done(result, error):
            bridge.shell.hide_loading()
            bridge._resume_2d_preview(preview)
            bridge._resume_card_preview(cards)
            if error:
                show_stitch_failure(bridge, mode, error)
                return
            uid, cloud, workflow = result
            for report in stitch_report:
                bridge.shell.log(report, 'info')
            bridge.frame_db.overlay.reset(mode)
            bridge.projects.projects[mode].include_raw = True
            if workflow is not None:
                bridge.mobile_workflow = workflow
                bridge.projects.prepare(mode)
                ws = bridge.shell.workspace_mobile()
                ws.set_stations(workflow.get_station_evaluations())
                ws.set_state('chaining')
                edge = workflow.last_edge
                if edge:
                    rms = workflow.get_error_report().get('global_marker_rms_mm', edge.rms_mm)
                    ws.set_evaluation(edge.common_markers, edge.inlier_ratio, rms, 'ok',
                                      '拼接完成：显示最终位姿的标记拟合误差，不代表整个表面精度',
                                      scope='全局标记')
            else:
                ws = bridge.shell.workspace_multi() if mode == 'multi_cam' else turn
                if mode == 'turntable':
                    turn.merged = cloud
                    turn.set_state('stitched')
                    turn._update_online_ui()
            viewer = ws.viewer() if callable(ws.viewer) else ws.viewer
            viewer.set_pointcloud_merged(cloud)
            bridge.frame_db.browsers[mode].refresh()
            # Results have no corresponding camera exposure; clear the 2D inspector.
            from core.frame_data import FrameData
            frame = FrameData(database.records[uid].frame_id, database.records[uid].logical_name, database_id=uid)
            bridge.frame_db.display_frame(mode, uid, frame, cloud)
            bridge.shell.set_dirty(True)
            bridge.shell.log(f'拼接完成：DB已新增 {database.records[uid].logical_name}，{len(cloud.points):,} 点。', 'success')
            bridge.shell._refresh_statusbar()
        bridge._run_background(work, done, must_finish=True, name='explicit_stitch')

    def export(self, uid=None):
        bridge = self.bridge
        if not bridge.can_change_workspace():
            bridge.shell.log('正在处理数据，请完成后导出点云。', 'warn')
            return
        mode = bridge._current_mode
        database = bridge.frame_db.databases[mode]
        if uid is None:
            uid = bridge.frame_db.browsers[mode].export_uid()
        if uid not in database.records or database.records[uid].status == STALE_RESULT:
            bridge.shell.log('请单独选中或勾选一帧有效DB点云；来源已变化的结果需重新生成。', 'warn')
            return
        path, _ = QFileDialog.getSaveFileName(bridge.shell, '导出单帧点云', database.records[uid].logical_name + '.ply', 'PLY 点云 (*.ply)')
        if not path:
            return
        if not Path(path).suffix:
            path += '.ply'
        def work():
            return database.export_cloud(uid, path)
        def done(result, error):
            bridge.shell.log('导出失败：' + str(error) if error else '点云已导出：' + path, 'error' if error else 'success')
        bridge._run_background(work, done, name='project_export_cloud', must_finish=True)
