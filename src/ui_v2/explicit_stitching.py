"""Industrial raw acquisition and explicit, independently archived stitching."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from .dialogs import ChineseMessageBox as QMessageBox
from core.frame_database import STALE_RESULT
from core.calibration_engine import CalibrationEngine
from core.mobile_chain_workflow import MobileChainWorkflow


class ExplicitStitching:
    def __init__(self, bridge):
        self.bridge = bridge

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
        if not bridge.can_change_workspace():
            return
        cameras = bridge.camera_manager.get_connected_ids()
        if not cameras:
            bridge.shell.log('请先连接相机。', 'warn')
            return
        preview = bridge._pause_2d_preview()
        ws = bridge.shell.workspace_mobile()
        ws.set_state('capturing')
        bridge.shell.show_loading('正在拍摄原始帧并存入DB...')
        def work():
            frame = bridge.camera_manager.capture(cameras[0])
            if frame is None:
                raise ValueError('拍摄失败，请查看设备日志')
            return frame, frame.load_pointcloud_o3d()
        def done(result, error):
            bridge.shell.hide_loading()
            ws.set_state('chaining' if ws._station_count else 'connected')
            bridge._resume_2d_preview(preview)
            if error:
                bridge.shell.log('原始帧采集失败：' + str(error), 'error')
                return
            frame, cloud = result
            bridge.frame_db.display_frame('mobile_chain', frame.database_id, frame, cloud)
            bridge.shell.set_dirty(True)
            bridge.shell.log('原始点云与2D图像已入DB；点击“执行拼接”生成结果。', 'success')
            bridge.shell._refresh_statusbar()
        bridge._run_background(work, done, must_finish=True, name='raw_capture')

    def execute(self):
        bridge = self.bridge
        if not bridge.can_change_workspace():
            bridge.shell.log('请等待当前任务完成后再执行拼接。', 'warn')
            return
        mode = bridge._current_mode
        database = bridge.frame_db.databases[mode]
        raw_ids = [uid for uid, row in database.records.items() if row.kind == 'raw']
        selected = bridge.frame_db.browsers[mode].selected_ids()
        selected = [uid for uid in selected if uid in raw_ids]
        if mode == 'mobile_chain' and len(selected) >= 2:
            raw_ids = selected
        if len(raw_ids) < 2:
            bridge.shell.log('执行拼接至少需要两帧原始数据。', 'warn')
            return
        turn = bridge.shell.workspace_turntable()
        voxel = turn.spin_voxel.value() or None
        refine = turn.chk_icp_refine.isChecked()
        preview = bridge._pause_2d_preview()
        cards = bridge._pause_card_preview()
        bridge.shell.show_loading('正在执行拼接；原始帧保持独立...')
        def work():
            workflow = None
            sources = raw_ids
            if mode == 'mobile_chain':
                workflow = MobileChainWorkflow(bridge.camera_manager, bridge.marker_detector,
                    CalibrationEngine(), bridge.stitch_engine, bridge.processor)
                workflow.start_chaining()
                manager = workflow.station_manager
                manager.managed_frames = True
                for number, uid in enumerate(raw_ids, 1):
                    frame, _ = database.load_frame(uid)
                    frame.camera_name = sid = f'station_{number}'
                    chain = workflow._chain_stitcher
                    ok, message, edge = chain.add_frame(frame,
                        detect_markers=not bool(frame.markers_all or frame.markers))
                    if not ok:
                        raise ValueError(f'原始帧 {number}：{message}；未生成结果，请移除质量不佳的帧后重试')
                    cached = chain._node_pcd_cache.get(sid)
                    if cached is None or not len(cached.points):
                        raise ValueError(f'原始帧 {number} 没有有效3D点，未生成拼接结果')
                    manager._stations[sid] = frame
                    manager._station_seq = number
                    workflow._last_edge = edge
                if len(chain.nodes) >= 3:
                    ok, message, before_mm, after_mm = workflow.optimize_global()
                    if not ok:
                        raise ValueError(message)
                merged = workflow._chain_stitcher.get_merged_pointcloud()
            elif mode == 'multi_cam':
                sources = [frame.database_id for frame in bridge.fixed_workflow.frames_scan.values()]
                if len(sources) < 2:
                    raise ValueError('至少需要两台相机的扫描帧，请先完成外参标定并采集')
                if any(uid not in database.records for uid in sources):
                    raise ValueError('扫描帧已从DB删除，请重新采集后拼接')
                ok, message, merged = bridge.fixed_workflow.stitch()
                if not ok:
                    raise ValueError(message + '；请先完成外参标定并采集扫描帧')
            else:
                sources = [frame.database_id for frame in turn.session.get_all_frames()]
                if any(uid not in database.records for uid in sources):
                    raise ValueError('转台扫描帧已从DB删除，请重新采集后拼接')
                merged, message = turn.session.stitch(downsample_voxel=voxel, icp_refine=refine)
                if merged is None:
                    raise ValueError(message)
            uid = database.publish_result(merged, sources)
            return uid, merged, workflow
        def done(result, error):
            bridge.shell.hide_loading()
            bridge._resume_2d_preview(preview)
            bridge._resume_card_preview(cards)
            if error:
                bridge.shell.log('拼接失败：' + str(error), 'error')
                return
            uid, cloud, workflow = result
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
