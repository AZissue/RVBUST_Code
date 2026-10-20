"""Industrial raw acquisition and explicit, independently archived stitching."""
from pathlib import Path

from PySide6.QtWidgets import QFileDialog
from core.calibration_engine import CalibrationEngine
from core.mobile_chain_workflow import MobileChainWorkflow
from core.utils import write_point_cloud_atomic


class ExplicitStitching:
    def __init__(self, bridge):
        self.bridge = bridge

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
                    ws.set_evaluation(edge.common_markers, edge.inlier_ratio, edge.rms_mm, 'ok', '拼接完成')
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

    def export(self):
        bridge = self.bridge
        if not bridge.can_change_workspace():
            return
        mode = bridge._current_mode
        database = bridge.frame_db.databases[mode]
        results = [uid for uid, row in database.records.items() if row.kind == 'result']
        selected = [uid for uid in bridge.frame_db.browsers[mode].selected_ids() if uid in results]
        if not results:
            bridge.shell.log('请先执行拼接，再导出DB中的拼接结果。', 'warn')
            return
        uid = selected[-1] if selected else results[-1]
        path, _ = QFileDialog.getSaveFileName(bridge.shell, '导出拼接结果', database.records[uid].logical_name + '.ply', 'PLY 点云 (*.ply)')
        if not path:
            return
        def work():
            _, cloud = database.load_frame(uid)
            if not write_point_cloud_atomic(str(Path(path)), cloud):
                raise IOError('点云导出失败')
        def done(result, error):
            bridge.shell.log('导出失败：' + str(error) if error else '点云已导出：' + path, 'error' if error else 'success')
        bridge._run_background(work, done, name='project_export_result', must_finish=True)
