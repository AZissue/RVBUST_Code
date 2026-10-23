"""Bounded, silent recognition queue, independent of foreground UI workers."""
import copy
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, QTimer
from core import frame_recognition


class BackgroundRecognition(QObject):
    def __init__(self, bridge):
        super().__init__(bridge)
        self.bridge = bridge
        self.enabled = True
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='frame-recognition')
        self.jobs = {}
        self.waiters = []
        self.forced = set()
        self.available = set()
        self.commit_errors = set()
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def config(self, mode):
        bridge = self.bridge
        marker_type = bridge.marker_detector.get_marker_type()
        if mode == 'multi_cam':
            marker_type = bridge._map_detect_method(bridge.shell.workspace_multi().current_detect_method())
        elif mode == 'turntable':
            marker_type = bridge.shell.workspace_turntable().combo_marker_type.currentData()
        return frame_recognition.configuration(bridge.marker_detector, marker_type)

    def configure(self, mode, marker_type, boards, gamma):
        """Apply UI settings between foreground tasks; running jobs own copies."""
        import math
        from core.marker_detector import SUPPORTED_MARKER_TYPES
        bridge = self.bridge
        if mode != bridge._current_mode or not bridge.can_change_workspace():
            raise ValueError('当前任务进行中或工作区已切换，请稍后再试。')
        if marker_type not in SUPPORTED_MARKER_TYPES:
            raise ValueError('不支持的识别类型。')
        if not math.isfinite(gamma) or not .1 <= gamma <= 10:
            raise ValueError('Gamma 必须在 0.1～10 之间。')
        if not boards or any(not isinstance(spec.get('cols'), int) or not isinstance(spec.get('rows'), int)
                             or spec['cols'] < 2 or spec['rows'] < 2
                             or not math.isfinite(spec.get('spacing_mm', 0))
                             or spec.get('spacing_mm', 0) <= 0 for spec in boards):
            raise ValueError('标定板规格或圆心间距无效。')
        if not bridge._detect_lock.acquire(blocking=False):
            raise ValueError('识别器正在使用，请稍后再试。')
        try:
            bridge.marker_detector.set_board_specs(copy.deepcopy(boards))
            bridge.marker_detector.set_board_gamma(gamma)
            bridge.marker_detector.set_marker_type(marker_type)
            if mode == 'multi_cam':
                combo = bridge.shell.workspace_multi()._detect_combo
                combo.setCurrentIndex(combo.findData('calib_board' if marker_type == 'asymmetric_grid' else marker_type))
            elif mode == 'turntable':
                combo = bridge.shell.workspace_turntable().combo_marker_type
                # Its legacy handler mutates the same detector and logs the change.
                from PySide6.QtCore import QSignalBlocker
                with QSignalBlocker(combo):
                    combo.setCurrentIndex(combo.findData(marker_type))
        finally:
            bridge._detect_lock.release()
        bridge.shell.log('识别参数已应用；后台识别将按新参数更新原始帧。', 'info')

    def ensure(self, mode, identifiers, callback):
        """Continue an explicit action once only its input frames are ready."""
        if not self.enabled:
            return True
        db = self.bridge.frame_db.databases[mode]
        key = frame_recognition.fingerprint(self.config(mode))
        if any(uid not in db.records for uid in identifiers):
            self.bridge.shell.log('原始帧已删除或项目已变化，请重新选择输入数据。', 'warn')
            return False
        rows = [db.records[uid] for uid in identifiers]
        if any((mode, db.directory, row.uid, row.revision, key) in self.commit_errors for row in rows):
            self.bridge.shell.log('识别结果未能写入DB，请检查存储后右键重新识别。', 'error')
            return False
        errors = [row for row in rows if row.recognition.get('key') == key and row.recognition.get('state') == 'error']
        if errors:
            self.bridge.shell.log('标记识别失败，请在DB右键重新识别：' + errors[0].recognition.get('error', ''), 'error')
            return False
        if all(row.recognition.get('key') == key and row.recognition.get('state') == 'done' for row in rows):
            return True
        token = (mode, db.directory, tuple((row.uid, row.revision) for row in rows), key)
        if not any(item[0] == token for item in self.waiters):
            self.waiters.append((token, callback))
        self.bridge.shell.show_loading('正在等待所选帧的后台标记识别…')
        return False

    def retry(self, mode, identifiers):
        db = self.bridge.frame_db.databases[mode]
        for uid in identifiers:
            if uid in db.records and db.records[uid].kind == 'raw':
                self.forced.add((mode, db.directory, uid, db.records[uid].revision))
                self.commit_errors = {token for token in self.commit_errors if token[:3] != (mode, db.directory, uid)}

    def tick(self):
        if not self.enabled or getattr(self.bridge, '_cleaned', False):
            return
        bridge = self.bridge
        for token, future in list(self.jobs.items()):
            if not future.done():
                continue
            del self.jobs[token]
            mode, directory, uid, revision, key = token
            db = bridge.frame_db.databases[mode]
            if frame_recognition.fingerprint(self.config(mode)) != key:
                continue
            try:
                result = future.result()
            except Exception as exc:
                result = dict(state='error', key=key, error=str(exc))
            try:
                if db.set_recognition(uid, revision, directory, result):
                    self._publish(mode, uid, result)
            except Exception as exc:
                self.commit_errors.add(token)
                bridge.shell.log('保存帧识别结果失败：' + str(exc), 'error')
        # Preview/capture/DB file reads take priority over starting more work.
        if bridge.shell._presentation == 'industrial':
            mode = bridge._current_mode
            db = bridge.frame_db.databases[mode]
            config = self.config(mode)
            key = frame_recognition.fingerprint(config)
            for frame in bridge.frame_db._frames():
                row = db.records.get(frame.database_id)
                if row and row.recognition.get('state') == 'done' and row.recognition.get('key') == key and frame.recognition_key != key:
                    self._publish(mode, row.uid, row.recognition)
            priority = {uid for token, _ in self.waiters for uid, _ in token[2] if token[0] == mode}
            with db._lock:
                rows = sorted(list(db.records.values()), key=lambda row: row.uid not in priority)
            valid = {(mode, db.directory, row.uid, row.revision) for row in rows}
            self.available = {token for token in self.available if token[0] != mode or token in valid}
            self.forced = {token for token in self.forced if token[0] != mode or token in valid}
            foreground = any(worker.isRunning() for worker in bridge._workers) or bridge.shell.workspace_turntable()._busy
            if not foreground:
                self.available.update((mode, db.directory, row.uid, row.revision) for row in rows)
            for row in rows:
                if len(self.jobs) >= 2:
                    break
                if row.kind != 'raw':
                    continue
                token = (mode, db.directory, row.uid, row.revision, key)
                if token[:4] not in self.available:
                    continue
                force = token[:4] in self.forced
                if token in self.jobs or token in self.commit_errors or (not force and row.recognition.get('key') == key and
                                         row.recognition.get('state') in ('done', 'error')):
                    continue
                self.forced.discard(token[:4])
                try:
                    if not db.set_recognition(row.uid, row.revision, db.directory, dict(state='running', key=key)):
                        continue
                except Exception as exc:
                    self.commit_errors.add(token)
                    bridge.shell.log('无法更新识别状态，请检查DB存储：' + str(exc), 'error')
                    continue
                self._publish(mode, row.uid, dict(state='running', key=key))
                directory = db.directory
                def work(db=db, uid=row.uid, revision=row.revision, directory=directory, config=copy.deepcopy(config)):
                    # Only immutable files/numpy data; never a live SDK frame.
                    with db._lock:
                        if db.directory != directory or uid not in db.records or db.records[uid].revision != revision:
                            raise RuntimeError('原始帧已变化')
                    frame, _ = db.load_frame(uid, 'image')
                    return frame_recognition.detect(frame, config)
                self.jobs[token] = self.pool.submit(work)
        for token, callback in list(self.waiters):
            mode, directory, inputs, key = token
            db = bridge.frame_db.databases[mode]
            stale = (bridge._current_mode != mode or db.directory != directory or
                     frame_recognition.fingerprint(self.config(mode)) != key or
                     any(uid not in db.records or db.records[uid].revision != revision for uid, revision in inputs))
            results = [db.records[uid].recognition for uid, _ in inputs if uid in db.records]
            failed = any(result.get('state') == 'error' and result.get('key') == key for result in results)
            failed = failed or any((mode, directory, uid, revision, key) in self.commit_errors for uid, revision in inputs)
            ready = all(result.get('state') == 'done' and result.get('key') == key for result in results)
            if stale or failed or ready and bridge.can_change_workspace():
                self.waiters.remove((token, callback))
                bridge.shell.hide_loading()
                if not stale and not failed:
                    callback()
                else:
                    bridge.shell.log('识别等待已结束：输入帧/识别参数已变化或识别失败，请检查DB后重试。', 'warn')
        if bridge._current_mode == 'multi_cam' and bridge.can_change_workspace():
            frames = list(bridge.fixed_workflow.frames_calib.values())
            key = frame_recognition.fingerprint(self.config('multi_cam'))
            ws = bridge.shell.workspace_multi()
            if frames and all(frame.recognition_key == key for frame in frames) and ws.current_state() == 'captured':
                ws.set_state('detected')

    def _publish(self, mode, uid, result):
        bridge = self.bridge
        if bridge._current_mode != mode:
            return
        owner = bridge.frame_db
        frames = owner._frames()
        shown = owner._displayed.get(mode)
        if shown and shown[0] == uid:
            frames.append(shown[1])
        for frame in frames:
            if frame.database_id == uid:
                frame_recognition.apply(frame, result)
        if mode == 'multi_cam':
            ws = bridge.shell.workspace_multi()
            if result['state'] != 'done' and ws.current_state() == 'detected' and not bridge.fixed_workflow.is_calibration_locked:
                ws.set_state('captured')
            for cid, frame in ws_frame_items(bridge):
                if frame.database_id == uid:
                    ws.camera_grid().set_frame(cid, frame)
                    ws.camera_grid().set_marker_count(cid, len(frame.markers))
        elif mode == 'turntable':
            ws = bridge.shell.workspace_turntable()
            for index in (0, 1):
                frame = getattr(ws, f'current_frame{index}')
                if frame and frame.database_id == uid:
                    setattr(ws, f'current_markers{index}', frame.markers)
                    setattr(ws.session, f'markers{index}', frame.markers)
            for index, frame in enumerate(ws.session.sequence):
                if frame.database_id == uid:
                    ws.session.sequence_markers[index] = frame.markers
            ws._update_online_ui()
            if not shown:
                latest = ws.session.sequence[-1] if ws.session.sequence else ws.current_frame1 or ws.current_frame0
                if latest and latest.database_id == uid:
                    ws._display_2d(latest.image_np, latest.markers_all, reference_markers=ws.current_markers0)
        if shown and shown[0] == uid:
            _, frame, component = shown
            if component != 'cloud':
                bridge.shell._stack.currentWidget()._industrial.show_database_image(frame)
            if component != 'image' and not owner.overlay.active(mode):
                from ui_common.industrial_scene.marker_display import classify_markers
                viewer = owner.overlay._viewer(mode)
                viewer.set_cloud_markers(classify_markers(frame.markers_all).cloud_points())
        if owner.overlay.active(mode):
            owner.overlay._apply(mode)

    def close(self):
        self.timer.stop()
        self.waiters.clear()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.jobs.clear()
        self.available.clear()
        self.forced.clear()


def ws_frame_items(bridge):
    return list(bridge.fixed_workflow.frames_calib.items()) + list(bridge.fixed_workflow.frames_scan.items())
