"""Offline entrance orchestration; uses production workflows, not fake cameras."""
from pathlib import Path
import shutil
import tempfile

from core.offline_fixture import load_stool
from core.mobile_chain_workflow import MobileChainWorkflow
from core.offline_session import OfflineSession
from core.calibration_engine import CalibrationEngine
from core.point_cloud_processor import PointCloudProcessor
from core.marker_detector import MarkerDetector, MARKER_TYPE_CODED_CIRCLE
from core.session_project import SessionProject


def open_preview(bridge, mode, on_finished=None):
    if mode not in ('multi_cam', 'mobile_chain', 'turntable'):
        raise ValueError(mode)
    if not bridge.can_change_workspace():
        if on_finished:
            on_finished(False, '请先完成当前任务')
        return False
    shell = bridge.shell
    bridge._pause_2d_preview()
    bridge._pause_card_preview()
    shell.show_loading('正在加载凳子第 1、2 帧离线数据...')

    def work():
        project = SessionProject(mode, '凳子离线预览', bridge.projects.projects[mode].save_root)
        try:
            return build(project)
        except Exception:
            project.dispose()
            raise

    def build(project):
        records = load_stool()
        database = project.database
        database.begin_session('凳子离线数据')
        for index, (frame, _) in enumerate(records):
            purpose = '标定数据' if mode == 'multi_cam' else '移动机位' if mode == 'mobile_chain' else f'转台标定 frame{index}'
            if mode == 'turntable':
                frame.kind = purpose
            database.ingest(frame, purpose=purpose, camera=frame.camera_name if mode == 'multi_cam' else 'cam0',
                            logical_name=f'station_{index+1}' if mode == 'mobile_chain' else frame.camera_name)
        mobile = None
        merged = None
        if mode == 'mobile_chain':
            # Existing station deletion removes directories. Give it disposable
            # copies, never point StationManager at the immutable fixture/cache.
            runtime = project.directory / 'preview_work'
            runtime.mkdir(parents=True, exist_ok=True)
            session = Path(tempfile.mkdtemp(prefix='stool_', dir=runtime))
            try:
                for index, (frame, _) in enumerate(records, 1):
                    name = f'station_{index}'
                    folder = session / name
                    folder.mkdir()
                    shutil.copy2(frame.offline_image_path, folder / f'{name}.png')
                    shutil.copy2(frame.offline_pointmap_path, folder / f'{name}.ply')
                preview_processor = PointCloudProcessor()
                preview_processor.enable_outlier_removal = False
                mobile = MobileChainWorkflow(bridge.camera_manager, MarkerDetector(),
                    CalibrationEngine(), bridge.stitch_engine, preview_processor)
                saved_markers = {f'station_{index}': frame.markers_all
                                 for index, (frame, _) in enumerate(records, 1)}
                ok, message = mobile.load_session_dir(str(session), saved_markers=saved_markers)
                manager = mobile.station_manager
                for index, (source, _) in enumerate(records, 1):
                    loaded = manager.get_frame(f'station_{index}') if manager else None
                    if loaded:
                        loaded.database_id = source.database_id
                        folder = database.directory / 'frames' / source.database_id
                        loaded.offline_dir = None
                        loaded.offline_image_path = str(folder / 'image.png')
                        loaded.offline_pointmap_path = str(folder / 'pointmap.ply')
                manager.managed_frames = True
                if not ok or len(mobile.get_station_evaluations()) != len(records):
                    raise ValueError('离线链式拼接未完整加载两帧：' + message)
                merged = mobile.get_merged_pointcloud()
                shutil.rmtree(session)
            except Exception:
                shutil.rmtree(session)
                raise
        return records, mobile, merged, project

    def done(result, error):
        shell.hide_loading()
        if error:
            message = f'离线数据加载失败：{error}'
            shell.log(message, 'error')
            if on_finished:
                on_finished(False, message)
            return
        records, mobile, merged, project = result
        old = bridge.projects.projects[mode]
        bridge.projects.reset_workflow(mode)
        bridge.projects.install(mode, project)
        project.dirty = True
        old.dispose()
        bridge.camera_manager.clear()
        bridge.offline_preview = True
        bridge._offline_clouds = {frame.camera_name: cloud for frame, cloud in records} if mode == 'multi_cam' else {}
        bridge._current_mode = mode
        shell._offline_preview = True
        for workspace in (shell.workspace_multi(), shell.workspace_mobile(), shell.workspace_turntable()):
            workspace.offline_preview = True
        shell.set_presentation('industrial')
        shell.set_mode(mode, [])
        if mode == 'multi_cam':
            frames = {frame.camera_name: [frame] for frame, _ in records}
            bridge._load_fixed_session(OfflineSession(), frames)
            ws = shell.workspace_multi()
            ws._detect_combo.setCurrentIndex(ws._detect_combo.findData('coded_circle'))
            ws.viewer().clear_all()
            ws._ref_combo.blockSignals(True)
            ws._ref_combo.clear()
            ws._device_list.clear()
            for frame, cloud in records:
                ws._ref_combo.addItem(f'离线视角 {frame.frame_id}', frame.camera_name)
                ws._device_list.addItem(f'离线视角 {frame.frame_id} · 未连接相机')
                ws.viewer().set_pointcloud(frame.camera_name, cloud)
            ws._ref_combo.blockSignals(False)
            ws.refresh_marker_pair()
            message = '已加载凳子 1、2 帧作为两路离线标定数据，可重新检测及计算外参；当前点云尚未对齐。'
        elif mode == 'mobile_chain':
            bridge.mobile_workflow = mobile
            ws = shell.workspace_mobile()
            ws.reset_session()
            ws.set_stations(mobile.get_station_evaluations())
            ws.set_state('chaining')
            ws.viewer().clear_all()
            ws.viewer().set_pointcloud_merged(merged)
            bridge._refresh_mobile_live_view_to_latest()
            message = '已加载凳子 1、2 帧并完成离线链式拼接，可选择机位查看对应图像、识别和配准结果。'
        else:
            ws = shell.workspace_turntable()
            ws.combo_marker_type.setCurrentIndex(ws.combo_marker_type.findData(MARKER_TYPE_CODED_CIRCLE))
            for index, (frame, cloud) in enumerate(records[:2]):
                setattr(ws, f'current_frame{index}', frame)
                setattr(ws, f'current_markers{index}', frame.markers)
                getattr(ws.session, f'set_frame{index}')(frame, frame.markers, cloud)
                ws.viewer.set_pointcloud(f'frame{index}', cloud)
            ws._display_2d(records[1][0].image_np, records[1][0].markers_all,
                           reference_markers=records[0][0].markers)
            ws._update_online_ui()
            ws.lbl_cam_status.setText('离线数据 · 未连接相机')
            message = '已加载离线 frame0 / frame1；凳子数据没有已知转台角度，仅用于界面和标定算法测试。'
        viewer = ws.viewer() if callable(ws.viewer) else ws.viewer
        viewer.reset_view()
        from version import get_version
        from .launcher_dialog import LauncherDialog
        shell.setWindowTitle(f'MCC 拼接工作站 — {LauncherDialog.MODE_NAMES[mode]} {get_version()} · 新版 · 离线预览')
        shell.set_dirty(False)
        bridge.projects.prepare(mode)
        bridge.projects.update(mode)
        shell._refresh_statusbar()
        shell.log(message, 'success')
        bridge.frame_db.synchronize()
        if on_finished:
            on_finished(True, message)

    bridge._run_background(work, done, name='offline_preview')
    return True
