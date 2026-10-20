"""New-workspace session lifecycle and portable workflow snapshots."""
from dataclasses import asdict
from pathlib import Path
import json

import numpy as np
import open3d as o3d
from PySide6.QtCore import QObject, QEventLoop, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QInputDialog,
    QLabel, QMessageBox, QVBoxLayout)

from core.session_project import SessionProject, MODE_LABELS
from core.frame_database import _json_value
from core.frame_data import FrameData
from core.chain_stitcher import ChainNode, ChainEdge
from core.mobile_chain_workflow import MobileChainWorkflow
from core.calibration_engine import CalibrationEngine
from core.offline_session import OfflineSession
from core.turntable_calibrator import OnlineTurntableSession


def matrix(value):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (4, 4) or not np.isfinite(result).all() or abs(np.linalg.det(result)) < 1e-12:
        raise ValueError('会话位姿矩阵无效')
    return result


def frame_description(database, frame):
    if frame is None:
        return None
    if frame.database_id not in database.records and frame.database_id not in database.removed:
        database.ingest(frame)
    return _json_value(dict(uid=frame.database_id, frame_id=frame.frame_id, camera=frame.camera_name,
        markers=frame.markers, markers_all=frame.markers_all, kind=frame.kind,
        board_pose=frame.board_pose, board_pattern=frame.board_pattern,
        board_pattern_name=frame.board_pattern_name, board_rms_mm=frame.board_rms_mm))


def read_frame(project, entry):
    if entry is None:
        return None, None
    uid = entry['uid']
    db = project.database
    if uid in db.records:
        folder = db.directory / 'frames' / uid
    elif uid in db.removed:
        folder = db.directory / '.trash' / db.removed[uid]['batch'] / uid
    else:
        raise ValueError('会话引用了缺失的原始帧')
    import cv2
    image = cv2.imdecode(np.fromfile(folder / 'image.png', np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError('会话2D图像读取失败')
    frame = FrameData(int(entry['frame_id']), str(entry['camera']), database_id=uid,
        image_np=image, is_offline=True, offline_image_path=str(folder / 'image.png'),
        offline_pointmap_path=str(folder / 'pointmap.ply'), markers=entry['markers'],
        markers_all=entry.get('markers_all'), kind=entry.get('kind'),
        board_pose=np.asarray(entry['board_pose']) if entry.get('board_pose') is not None else None,
        board_pattern=tuple(entry['board_pattern']) if entry.get('board_pattern') else None,
        board_pattern_name=entry.get('board_pattern_name'), board_rms_mm=entry.get('board_rms_mm', 0))
    cloud = frame.load_pointcloud_o3d()
    points = np.asarray(cloud.points)
    valid = np.isfinite(points).all(axis=1) & np.any(points != 0, axis=1)
    cloud = cloud.select_by_index(np.flatnonzero(valid))
    return frame, cloud


class SessionProjects(QObject):
    def __init__(self, bridge):
        super().__init__(bridge)
        self.bridge = bridge
        self.projects = {}
        self.loading = set()
        self.closed = False
        for mode, database in bridge.frame_db.databases.items():
            project = SessionProject(mode)
            project.database = database
            database.directory = project.directory / 'data'
            database.project_title = project.title
            self.projects[mode] = project

    def mark_changed(self, mode):
        if mode in self.loading or self.closed:
            return
        self.projects[mode].dirty = True
        self.update(mode)

    def update(self, mode):
        project = self.projects[mode]
        project.database.project_title = project.title
        browser = self.bridge.frame_db.browsers.get(mode)
        if browser:
            browser.refresh()
            path = str(project.saved_path) if project.saved_path else '未保存 · 临时工作区'
            browser.setToolTip(project.name + '\n' + path)
        self.bridge.shell._dirty = any(p.dirty for p in self.projects.values())

    def prepare(self, mode):
        if mode == 'mobile_chain':
            manager = self.bridge.mobile_workflow.station_manager
            if manager:
                manager.managed_frames = True
                manager._session_dir = str(self.projects[mode].directory)
                self.bridge.mobile_workflow.set_session_dir(manager._session_dir)
                database = self.projects[mode].database
                for frame in manager.get_frames().values():
                    uid = frame.database_id
                    if uid in database.records:
                        folder = database.directory / 'frames' / uid
                    elif uid in database.removed:
                        folder = database.directory / '.trash' / database.removed[uid]['batch'] / uid
                    else:
                        continue
                    frame.offline_dir = None
                    frame.offline_pointmap_path = str(folder / 'pointmap.ply')
                    frame.offline_image_path = str(folder / 'image.png')

    def _available(self):
        if not self.bridge.can_change_workspace():
            self.bridge.shell.log('请等待当前任务完成，再操作会话。', 'warn')
            return False
        return True

    def guard_switch(self, mode, action):
        if not self._available():
            return
        if not self.projects[mode].dirty:
            action()
            return
        answer = QMessageBox.warning(self.bridge.shell, '会话未保存',
            f'“{self.projects[mode].name}”有未保存内容。保存后继续，或放弃本次修改？',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer == QMessageBox.Discard:
            action()
        elif answer == QMessageBox.Save:
            self.save(mode, lambda ok: action() if ok else None)

    def new_dialog(self):
        if not self._available():
            return
        mode = self.bridge._current_mode
        name, ok = QInputDialog.getText(self.bridge.shell, '新建会话', '项目名称：',
            text=MODE_LABELS[mode])
        if ok and name.strip():
            self.guard_switch(mode, lambda: self.new(mode, name))

    def new(self, mode, name):
        old = self.projects[mode]
        self.loading.add(mode)
        try:
            self.reset_workflow(mode)
            project = SessionProject(mode, name, old.save_root)
            project.dirty = True
            project.database.begin_session('采集数据')
            self.install(mode, project)
            self.prepare(mode)
            old.dispose()
        finally:
            self.loading.discard(mode)
        self.update(mode)
        self.bridge.shell.log(f'已新建{MODE_LABELS[mode]}会话：{project.name}（未保存）', 'success')

    def install(self, mode, project):
        self.projects[mode] = project
        db = project.database
        self.bridge.frame_db.databases[mode] = db
        db.project_title = project.title
        db.on_changed = lambda key=mode: self.bridge.frame_db.changed.emit(key)
        browser = self.bridge.frame_db.browsers.get(mode)
        if browser:
            browser.database = db
        workspace = {'multi_cam': self.bridge.shell.workspace_multi,
            'mobile_chain': self.bridge.shell.workspace_mobile,
            'turntable': self.bridge.shell.workspace_turntable}[mode]()
        workspace.frame_database = db

    def reset_workflow(self, mode):
        bridge = self.bridge
        bridge._pause_2d_preview()
        bridge._pause_card_preview()
        bridge.frame_db.restore(mode)
        if mode == 'mobile_chain':
            bridge.mobile_workflow.reset()
            bridge.mobile_workflow.start_chaining()
            ws = bridge.shell.workspace_mobile()
            ws.reset_session()
            ws.set_state('chaining')
            ws.live_view().set_frame(None)
            ws.live_view().set_detection_overlay([])
            ws.viewer().clear_all()
        elif mode == 'multi_cam':
            bridge.fixed_workflow.reset()
            ws = bridge.shell.workspace_multi()
            ws.clear_calibration_results()
            ws.viewer().clear_all()
            for cid in ws.camera_grid().camera_ids():
                ws.camera_grid().set_frame(cid, None)
            bridge.fixed_workflow.start_calibration(ws.current_reference_id() or 'cam0')
            ws.set_state('connected' if bridge.camera_manager.get_connected_ids() else 'idle')
        else:
            ws = bridge.shell.workspace_turntable()
            ws._reset_online_state()
        if hasattr(ws, '_industrial'):
            ws._industrial.set_marker_image(None, [])

    def describe(self, mode, include_raw):
        bridge = self.bridge
        db = self.projects[mode].database
        desc = lambda frame: frame_description(db, frame) if include_raw else None
        if mode == 'mobile_chain':
            chain = bridge.mobile_workflow._chain_stitcher
            return dict(nodes=[dict(station_id=node.station_id, frame=desc(node.frame),
                T_world=node.T_world, cum_rms_mm=node.cum_rms_mm) for node in chain.nodes.values()] if chain else [],
                edges=[asdict(edge) for edge in chain.edges] if chain else [],
                reference_id=chain._reference_id if chain else None)
        if mode == 'multi_cam':
            return dict(calibration=bridge.calibration_engine.to_dict() if bridge.calibration_engine.pair_results else None,
                frames_calib={cid: desc(f) for cid, f in bridge.fixed_workflow.frames_calib.items()} if include_raw else {},
                frames_scan={cid: desc(f) for cid, f in bridge.fixed_workflow.frames_scan.items()} if include_raw else {},
                devices=[dict(serial=d.serial, model=d.model) for d in bridge.shell._devices])
        ws = bridge.shell.workspace_turntable()
        session = ws.session
        calibration = None
        if session.is_calibrated():
            calibration = dict(axis=session.calib.axis, center=session.calib.center,
                angle_deg=float(np.degrees(session.calib.angle_rad)), step_count=session.step_count())
        return dict(calibration=calibration, frame0=desc(ws.current_frame0), frame1=desc(ws.current_frame1),
            sequence=[desc(f) for f in session.sequence] if include_raw else [], current_step=session.current_step if include_raw else 0)

    def save(self, mode=None, callback=None):
        mode = mode or self.bridge._current_mode
        if not self._available():
            if callback:
                callback(False)
            return
        project = self.projects[mode]
        include_raw = project.include_raw
        if project.saved_path is None:
            dialog = QDialog(self.bridge.shell)
            dialog.setWindowTitle('保存会话')
            layout = QVBoxLayout(dialog)
            label = QLabel(f'{project.name}\n保存到：{project.save_root}\n重复保存更新同一项目。')
            label.setWordWrap(True)
            layout.addWidget(label)
            check = QCheckBox('包含原始点云和2D图像（可离线复核/继续拼接）')
            has_calibration = (bool(self.bridge.calibration_engine.pair_results) if mode == 'multi_cam'
                else self.bridge.shell.workspace_turntable().session.is_calibrated())
            check.setChecked(include_raw or not has_calibration)
            check.setEnabled(mode != 'mobile_chain')
            layout.addWidget(check)
            buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.Accepted:
                if callback:
                    callback(False)
                return
            include_raw = check.isChecked()
        self.bridge.shell.show_loading('正在保存当前会话...')
        def work():
            data = self.describe(mode, include_raw)
            return project.save(data, include_raw=include_raw)
        def done(path, error):
            self.bridge.shell.hide_loading()
            if error:
                self.bridge.shell.log(f'会话保存失败：{error}', 'error')
            else:
                project.dirty = False
                self.update(mode)
                self.bridge.shell.log(f'会话已保存：{path}' + ('（含原始帧）' if include_raw else '（标定信息）'), 'success')
            self.bridge.shell.session_save_finished.emit(error is None, str(error or path))
            if callback:
                callback(error is None)
        self.bridge._run_background(work, done, name='project_save', must_finish=True)

    def open(self, path, mode, legacy=False):
        if not self._available():
            return
        self.bridge.shell.show_loading('正在读取会话...')
        self.loading.add(mode)
        def work():
            if legacy:
                project, data = self.import_legacy(path, mode)
            else:
                project, data = SessionProject.load(path, mode, self.projects[mode].save_root)
            try:
                prepared = self.prepare_loaded(project, data)
                return project, data, prepared
            except Exception:
                project.dispose()
                raise
        def done(result, error):
            self.bridge.shell.hide_loading()
            if error:
                self.loading.discard(mode)
                self.bridge.shell.log(f'会话载入失败：{error}', 'error')
                return
            project, data, prepared = result
            old = self.projects[mode]
            try:
                self.reset_workflow(mode)
                self.install(mode, project)
                self.apply_loaded(mode, data, prepared)
                self.prepare(mode)
                project.dirty = bool(legacy)
                old.dispose()
                self.bridge.shell.log(f'已载入会话：{project.name}', 'success')
            finally:
                self.loading.discard(mode)
                self.update(mode)
        self.bridge._run_background(work, done, name='project_open', must_finish=True)

    def import_legacy(self, path, mode):
        project = SessionProject(mode, Path(path).name, self.projects[mode].save_root)
        project.include_raw = True
        db = project.database
        try:
            if mode == 'multi_cam' and (Path(path) / 'turntable_meta.json').is_file():
                raise ValueError('这是转台会话，请进入转台工作区导入')
            if mode == 'mobile_chain':
                bridge = self.bridge
                workflow = MobileChainWorkflow(bridge.camera_manager, bridge.marker_detector,
                    CalibrationEngine(), bridge.stitch_engine, bridge.processor)
                ok, message = workflow.load_session_dir(str(path))
                if not ok:
                    raise ValueError(message)
                chain = workflow._chain_stitcher
                data = dict(nodes=[dict(station_id=node.station_id, frame=frame_description(db, node.frame),
                    T_world=node.T_world, cum_rms_mm=node.cum_rms_mm) for node in chain.nodes.values()],
                    edges=[asdict(edge) for edge in chain.edges], reference_id=chain._reference_id)
            else:
                session = OfflineSession()
                frames = session.load_session(str(path))
                if mode == 'turntable' and session.get_meta('calibration'):
                    raise ValueError('这是多相机标定会话，请进入多相机工作区导入')
                if mode == 'multi_cam':
                    calib, scan = self.bridge._split_session_frames(frames)
                    data = dict(calibration=session.get_meta('calibration'), devices=[],
                        frames_calib={cid: frame_description(db, f) for cid, f in calib.items()},
                        frames_scan={cid: frame_description(db, f) for cid, f in scan.items()})
                else:
                    calibration = None
                    meta_path = Path(path) / 'turntable_meta.json'
                    if meta_path.is_file():
                        meta = json.loads(meta_path.read_text(encoding='utf-8'))
                        if meta.get('axis') is not None:
                            calibration = {key: meta[key] for key in ('axis', 'center', 'angle_deg', 'step_count')}
                    sequence = sorted([frame for values in frames.values() for frame in values], key=lambda frame: frame.frame_id)
                    data = dict(calibration=calibration, frame0=None, frame1=None,
                        sequence=[frame_description(db, f) for f in sequence], current_step=len(sequence))
                if not db.records and not data.get('calibration'):
                    raise ValueError('目录中没有可导入的会话数据')
            return project, _json_value(data)
        except Exception:
            project.dispose()
            raise

    def prepare_loaded(self, project, data):
        mode = project.mode
        if mode == 'mobile_chain':
            bridge = self.bridge
            workflow = MobileChainWorkflow(bridge.camera_manager, bridge.marker_detector,
                CalibrationEngine(), bridge.stitch_engine, bridge.processor)
            workflow.start_chaining()
            chain = workflow._chain_stitcher
            chain._merged_pcd_cache = o3d.geometry.PointCloud()
            manager = workflow.station_manager
            manager.managed_frames = True
            manager._session_dir = str(project.directory)
            workflow.set_session_dir(manager._session_dir)
            for entry in data['nodes']:
                sid = entry['station_id']
                if sid in chain.nodes or not sid.startswith('station_') or not sid[8:].isdigit():
                    raise ValueError('机位名称无效或重复')
                frame, cloud = read_frame(project, entry['frame'])
                if frame.camera_name != sid:
                    raise ValueError('机位和原始帧不匹配')
                transform = matrix(entry['T_world'])
                node = ChainNode(sid, frame, frame.markers, transform, float(entry['cum_rms_mm']))
                chain.nodes[sid] = node
                chain.pose_graph.add_node(sid, transform)
                manager._stations[sid] = frame
                manager._station_seq = max(manager._station_seq, int(sid[8:]))
                cloud.transform(transform)
                chain._node_pcd_cache[sid] = cloud
                chain._node_T_cache[sid] = transform.copy()
                chain._add_node_to_merged(sid)
            chain._reference_id = data['reference_id']
            if chain.nodes and chain._reference_id not in chain.nodes:
                raise ValueError('参考机位缺失')
            for entry in data['edges']:
                entry = dict(entry, T=matrix(entry['T']))
                edge = ChainEdge(**entry)
                if edge.from_id not in chain.nodes or edge.to_id not in chain.nodes:
                    raise ValueError('位姿关系引用了缺失的机位')
                chain.edges.append(edge)
                chain.pose_graph.add_edge(edge.from_id, edge.to_id, edge.T, edge.rms_mm, edge.inlier_ratio, edge.common_markers)
            for sid in chain.nodes:
                if sid != chain._reference_id:
                    chain.pose_graph.get_transform(sid, chain._reference_id)
            workflow._state = workflow.STATE_READY if len(chain.nodes) >= 3 else workflow.STATE_CHAINING
            return workflow, workflow.get_merged_pointcloud()
        if mode == 'multi_cam':
            engine = CalibrationEngine()
            if data.get('calibration'):
                ok, message = engine.load_from_dict(data['calibration'])
                if not ok:
                    raise ValueError(message)
            frames = {}
            for kind in ('frames_calib', 'frames_scan'):
                for cid, entry in data[kind].items():
                    frame, _ = read_frame(project, entry)
                    frame.kind = 'calib' if kind == 'frames_calib' else 'scan'
                    frames.setdefault(cid, []).append(frame)
            return frames
        session = OnlineTurntableSession()
        if data.get('calibration'):
            calibration = data['calibration']
            axis, center = (np.asarray(calibration[key], dtype=float) for key in ('axis', 'center'))
            if (axis.shape != (3,) or center.shape != (3,) or not np.isfinite(axis).all() or
                    not np.isfinite(center).all() or np.linalg.norm(axis) < 1e-9 or
                    not np.isfinite(float(calibration['angle_deg'])) or int(calibration['step_count']) <= 0):
                raise ValueError('转台标定参数无效')
            session.apply_calibration(**data['calibration'])
        first = [read_frame(project, data.get(key)) for key in ('frame0', 'frame1')]
        if first[0][0]:
            session.set_frame0(first[0][0], first[0][0].markers, first[0][1])
        if first[1][0]:
            session.set_frame1(first[1][0], first[1][0].markers, first[1][1])
        for entry in data['sequence']:
            frame, cloud = read_frame(project, entry)
            session.add_sequence_frame(frame, cloud, frame.markers)
        session.current_step = int(data['current_step'])
        if session.current_step < 0:
            raise ValueError('转台步数无效')
        return session, first

    def apply_loaded(self, mode, data, prepared):
        bridge = self.bridge
        if mode == 'mobile_chain':
            workflow, merged = prepared
            bridge.mobile_workflow = workflow
            ws = bridge.shell.workspace_mobile()
            ws.set_stations(workflow.get_station_evaluations())
            ws.set_state(workflow.get_state())
            ws.viewer().set_pointcloud_merged(merged)
            bridge._refresh_mobile_live_view_to_latest()
        elif mode == 'multi_cam':
            session = OfflineSession()
            session._meta['calibration'] = data.get('calibration')
            bridge._load_fixed_session(session, prepared)
        else:
            session, first = prepared
            ws = bridge.shell.workspace_turntable()
            if data.get('calibration'):
                ws.apply_loaded_calibration(data['calibration'])
            ws.session = session
            ws.calib = session.calib
            ws.current_frame0, ws.current_frame1 = (pair[0] for pair in first)
            ws.current_markers0 = ws.current_frame0.markers if ws.current_frame0 else []
            ws.current_markers1 = ws.current_frame1.markers if ws.current_frame1 else []
            for index, (frame, cloud) in enumerate(first):
                if frame:
                    ws.viewer.set_pointcloud(f'frame{index}', cloud)
            for index, cloud in enumerate(session.sequence_pcds):
                ws.viewer.set_pointcloud(f'step{index+1}', cloud)
            latest = (session.sequence[-1] if session.sequence else ws.current_frame1 or ws.current_frame0)
            if latest:
                ws._display_2d(latest.image_np, latest.markers_all or latest.markers)
            ws.set_state('calibrated' if session.is_calibrated() else 'connected')
            ws._update_online_ui()

    def request_close(self):
        if not self._available():
            return False
        dirty = [mode for mode, project in self.projects.items() if project.dirty]
        if not dirty:
            return True
        names = '\n'.join(self.projects[mode].name for mode in dirty)
        answer = QMessageBox.warning(self.bridge.shell, '会话未保存',
            '以下会话有未保存内容：\n' + names + '\n关闭不会自动保存。放弃后临时数据将被清理。',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer == QMessageBox.Discard:
            return True
        if answer != QMessageBox.Save:
            return False
        loop = QEventLoop(self)
        outcome = [False]
        def step(ok=True):
            if not ok or not dirty:
                outcome[0] = ok
                loop.quit()
                return
            # Completion signals can arrive just before QThread exits; dispatch
            # the next save only once the shared worker gate is free.
            if not self.bridge.can_change_workspace():
                QTimer.singleShot(10, step)
                return
            self.save(dirty.pop(0), step)
        QTimer.singleShot(0, step)
        loop.exec()
        return outcome[0]

    def cleanup(self):
        self.closed = True
        for project in self.projects.values():
            project.dispose()
            project.dirty = False

    def manage(self):
        if self._available():
            from .session_storage_dialog import SessionStorageDialog
            dialog = SessionStorageDialog(self, self.bridge._current_mode, self.bridge.shell)
            dialog.exec()
