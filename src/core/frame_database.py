"""Raw capture archive. Geometry is owned on disk, not by UI rows.

Published records contain no SDK handles or large numpy arrays. A frame is
published only after its organized PLY and matching PNG have both been saved.
Workflow deletion, re-registration and display sampling never alter this store.
Explicit retakes replace a complete pair under the same record identity/revision.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
import copy
import json
import shutil
import threading
import uuid
import os
import tempfile

import cv2
import numpy as np

from .frame_data import FrameData, _import_rvc
from .utils import rvc_sdk_lock, write_json_atomic


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'offline_data' / 'frame_db'
STALE_RESULT = '来源数据已变更，请重新拼接'


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def ply_count(path):
    with Path(path).open('rb') as stream:
        for _ in range(100):
            line = stream.readline(1024).decode('ascii', errors='ignore').strip()
            if line.startswith('element vertex '):
                return int(line.split()[-1])
            if line == 'end_header':
                break
    return None


@dataclass
class FrameRecord:
    uid: str
    session_id: str
    camera: str
    frame_id: int
    purpose: str
    logical_name: str
    created: str
    points: int | None
    image_size: list
    markers: list = field(default_factory=list)
    status: str = '已入库'
    kind: str = 'raw'
    source_ids: list = field(default_factory=list)
    revision: int = 0
    recognition: dict = field(default_factory=dict)


class FrameDatabase:
    def __init__(self, mode, base_dir=None, on_changed=None):
        self.mode = mode
        self.directory = Path(base_dir or DEFAULT_ROOT) / (mode + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
        self.records = {}
        self.removed = {}
        self.sessions = {}
        self.session_id = None
        self._lock = threading.RLock()
        self.on_changed = on_changed

    def begin_session(self, title='采集会话'):
        with self._lock:
            self.session_id = uuid.uuid4().hex
            self.sessions[self.session_id] = dict(title=title, created=datetime.now().isoformat(timespec='seconds'))
        return self.session_id

    def _save_index(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        # Keep the schema-1 record shape readable by older MCC versions. The
        # optional top-level cache can be ignored without losing raw assets.
        records = [{key: value for key, value in vars(row).items() if key != 'recognition'}
                   for row in self.records.values()]
        removed = {uid: {**entry, 'record': {key: value for key, value in entry['record'].items()
                                            if key != 'recognition'}} for uid, entry in self.removed.items()}
        recognition = {uid: row.recognition for uid, row in self.records.items() if row.recognition}
        recognition.update({uid: entry['record']['recognition'] for uid, entry in self.removed.items()
                            if entry['record'].get('recognition')})
        write_json_atomic(str(self.directory / 'index.json'), _json_value(dict(
            schema=1, mode=self.mode, sessions=self.sessions,
            records=records, removed=removed, recognition=recognition)), ensure_ascii=False, indent=2)

    def _notify(self):
        if self.on_changed:
            self.on_changed()

    def ingest(self, frame, *, purpose=None, camera=None, logical_name=None):
        """Freeze a capture before reuse; return its stable record id.

        Lock order: SDK lock before store lock, also for offline imports. This
        keeps parallel multi-camera capture and archive writes deadlock-free.
        """
        with rvc_sdk_lock:
            with self._lock:
                old = getattr(frame, 'database_id', None)
                if old in self.removed:
                    raise ValueError('该帧已从DB移除，请先恢复删除')
                if old in self.records:
                    return old
                if self.session_id is None:
                    self.begin_session()
                directory, session_id = self.directory, self.session_id
            uid = uuid.uuid4().hex
            folder = directory / 'frames' / uid
            folder.mkdir(parents=True)
            try:
                image = frame.image_np
                if image is None and frame.offline_image_path:
                    image = cv2.imdecode(np.fromfile(frame.offline_image_path, np.uint8), cv2.IMREAD_UNCHANGED)
                if image is None:
                    raise ValueError('缺少对应2D图像')
                ok, encoded = cv2.imencode('.png', image)
                if not ok:
                    raise IOError('2D图像编码失败')
                encoded.tofile(folder / 'image.png')
                target = folder / 'pointmap.ply'
                if frame.pointmap is not None and frame.rvc_image is not None:
                    sdk = _import_rvc()
                    if sdk is None or not frame.pointmap.SaveWithImage(str(target), frame.rvc_image,
                            sdk.PointMapUnitEnum.Millimeter, True):
                        raise IOError('原始点云保存失败')
                elif frame.offline_pointmap_path:
                    shutil.copyfile(frame.offline_pointmap_path, target)
                else:
                    raise ValueError('缺少原始点云')
                if not target.is_file() or not target.stat().st_size:
                    raise IOError('原始点云文件为空')
                count = ply_count(target)
                if count is None or count <= 0:
                    raise IOError('原始点云PLY头无效或无点')
                record = FrameRecord(uid, session_id, camera or frame.camera_name,
                    frame.frame_id, purpose or frame.kind or '采集帧', logical_name or frame.camera_name,
                    datetime.now().isoformat(timespec='seconds'), count,
                    list(image.shape[:2][::-1]), _json_value(frame.markers_all if frame.markers_all is not None else frame.markers))
                # Large PLY/PNG writes above do not hold the metadata lock, so
                # Qt can read the existing tree while another camera is saving.
                with self._lock:
                    if self.directory != directory:
                        raise RuntimeError('入库期间DB项目发生变化')
                    self.records[uid] = record
                    try:
                        self._save_index()
                    except Exception:
                        self.records.pop(uid)
                        raise
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            frame.database_id = uid
        self._notify()
        return uid

    def replace_capture(self, uid, frame):
        """Stage a complete exposure, then replace one owned pair and its index.

        Keep the record identity/order; failed capture/validation/index writes
        leave the old pair and every result status unchanged.
        """
        with rvc_sdk_lock:
            with self._lock:
                original = copy.deepcopy(self.records[uid])
                if original.kind != 'raw':
                    raise ValueError('只能重拍原始帧')
                directory = self.directory
            staging = FrameDatabase(self.mode)
            staging.directory = directory / ('.replacing_' + uuid.uuid4().hex)
            backup = staging.directory / 'previous'
            committed = False
            candidate = replace(frame, database_id=None, recognition_key=None, markers=[], markers_all=None,
                                board_pose=None, board_pattern=None, board_pattern_name=None, board_rms_mm=0)
            try:
                staged_uid = staging.ingest(candidate)
                # Validate readable geometry before any existing files change.
                staging.load_frame(staged_uid)
                incoming = staging.directory / 'frames' / staged_uid
                target = directory / 'frames' / uid
                with self._lock:
                    if self.directory != directory or self.records.get(uid) != original:
                        raise RuntimeError('重拍期间DB帧已变化，请重试')
                    before = copy.deepcopy(self.records)
                    new = staging.records[staged_uid]
                    new = replace(new, uid=uid, session_id=original.session_id,
                        camera=original.camera, frame_id=original.frame_id,
                        purpose=original.purpose, logical_name=original.logical_name,
                        revision=original.revision + 1, status='已重拍，待拼接')
                    target.rename(backup)
                    try:
                        incoming.rename(target)
                        self.records[uid] = new
                        self._invalidate_results([uid])
                        self._save_index()
                        committed = True
                    except Exception:
                        self.records = before
                        if target.exists():
                            target.rename(incoming)
                        backup.rename(target)
                        raise
                frame.database_id = uid
                frame.frame_id = original.frame_id
                frame.markers = []
                frame.markers_all = None
                frame.recognition_key = None
                frame.board_pose = None
                frame.board_pattern = None
                frame.board_pattern_name = None
                frame.board_rms_mm = 0
            finally:
                # If an OS error also prevents rollback, keep the old pair for
                # recovery instead of deleting its only remaining directory.
                if committed or not backup.exists():
                    shutil.rmtree(staging.directory, ignore_errors=True)
        self._notify()
        return uid

    def _invalidate_results(self, identifiers):
        changed = set(identifiers)
        # Propagate to derived postprocess branches as well as direct stitches.
        while True:
            descendants = {row.uid for row in self.records.values()
                           if row.kind == 'result' and row.uid not in changed
                           and changed.intersection(row.source_ids)}
            if not descendants:
                break
            for uid in descendants:
                self.records[uid].status = STALE_RESULT
            changed.update(descendants)

    def annotate(self, frame, *, purpose=None, status=None, logical_name=None):
        with self._lock:
            record = self.records.get(getattr(frame, 'database_id', None))
            if record is None:
                return
            before = copy.deepcopy(vars(record))
            if not record.recognition or frame.recognition_key == record.recognition.get('key'):
                record.markers = _json_value(frame.markers_all if frame.markers_all is not None else frame.markers)
            record.logical_name = logical_name or frame.camera_name
            if purpose:
                record.purpose = purpose
            if status:
                record.status = status
            if before == vars(record):
                return
            try:
                self._save_index()
            except Exception:
                record.__dict__.update(before)
                raise
        self._notify()

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self.sessions), copy.deepcopy(list(self.records.values()))

    def set_recognition(self, uid, revision, directory, result):
        """Commit metadata only if the exact captured data still exists."""
        with self._lock:
            row = self.records.get(uid)
            if self.directory != directory or row is None or row.kind != 'raw' or row.revision != revision:
                return False
            before = copy.deepcopy(vars(row))
            row.recognition = _json_value(result)
            row.markers = copy.deepcopy(row.recognition.get('markers', []))
            try:
                self._save_index()
            except Exception:
                row.__dict__.update(before)
                raise
        self._notify()
        return True

    def set_status(self, uid, status):
        with self._lock:
            record = self.records[uid]
            if record.status == status:
                return
            before = record.status
            record.status = status
            try:
                self._save_index()
            except Exception:
                record.status = before
                raise
        self._notify()

    def load_frame(self, uid, component='frame'):
        if component not in ('frame', 'cloud', 'image'):
            raise ValueError('未知DB预览类型')
        with self._lock:
            record = copy.deepcopy(self.records[uid])
            folder = self.directory / 'frames' / uid
        if record.kind == 'result':
            if component == 'image':
                raise ValueError('拼接结果没有对应2D图像')
            frame = FrameData(record.frame_id, record.logical_name, is_offline=True,
                offline_pointmap_path=str(folder / 'pointmap.ply'), database_id=uid)
            cloud = frame.load_pointcloud_o3d()
            if cloud is None or not len(cloud.points):
                raise IOError('DB拼接点云读取失败')
            return frame, cloud
        image = None
        if component != 'cloud':
            image = cv2.imdecode(np.fromfile(folder / 'image.png', np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise IOError('DB中对应2D图像读取失败')
        frame = FrameData(record.frame_id, record.camera, image_np=image,
            markers=[m for m in record.markers if m.get('valid_3d', True)], markers_all=record.markers,
            is_offline=True, offline_image_path=str(folder / 'image.png'),
            offline_pointmap_path=str(folder / 'pointmap.ply'), database_id=uid)
        if record.recognition.get('state') == 'done':
            from .frame_recognition import apply
            apply(frame, record.recognition)
        if component == 'image':
            return frame, None
        cloud = frame.load_pointcloud_o3d()
        if cloud is None or not len(cloud.points):
            raise IOError('DB中原始点云读取失败')
        return frame, cloud

    def export_cloud(self, uid, destination):
        """Atomically export one complete stored PLY, including derived records.

        Copy the file rather than the rendered/filtered Open3D geometry, keeping
        organized slots, colors and additional PLY fields exactly as stored.
        """
        target = Path(destination).expanduser().resolve()
        if target.suffix.lower() != '.ply':
            raise ValueError('单帧点云请导出为 PLY 文件')
        if target.is_relative_to(self.directory.resolve()):
            raise ValueError('不能导出到当前 DB 内部，请选择其他目录')
        temporary = None
        with self._lock:
            record = self.records[uid]
            if record.status == STALE_RESULT:
                raise ValueError('所选点云来源已变化，请重新生成后导出')
            source = self.directory / 'frames' / uid / 'pointmap.ply'
            try:
                with source.open('rb') as incoming:
                    with tempfile.NamedTemporaryFile(dir=target.parent,
                            prefix='.'+target.name+'.', suffix='.tmp', delete=False) as output:
                        temporary = Path(output.name)
                        shutil.copyfileobj(incoming, output)
                os.replace(temporary, target)
                temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return str(target)

    def publish_result(self, cloud, source_ids, *, postprocess=False, name=None):
        """Commit a separate immutable result; never change raw frame geometry."""
        return self.publish_results([(cloud, source_ids, name)], postprocess=postprocess)[0]

    def publish_results(self, results, *, postprocess=False):
        """Atomically commit related (cloud, source_ids, name) result branches.

        In particular, polygon keep/discard branches must both succeed or neither
        may appear in the DB. Notify observers only after the whole index commits.
        """
        from .utils import write_point_cloud_atomic
        results = [(cloud, list(sources), name) for cloud, sources, name in results]
        if not results:
            raise ValueError('没有结果可写入')
        role = '后处理' if postprocess else '拼接'
        identifiers, folders, staged = [], [], {}
        with self._lock:
            for cloud, sources, _ in results:
                if (not postprocess and not sources) or any(
                        key not in self.records or (not postprocess and self.records[key].kind != 'raw')
                        or self.records[key].status == STALE_RESULT for key in sources):
                    raise ValueError(role + '来源帧已变化，请重新执行')
                if cloud is None or not len(cloud.points):
                    raise IOError(role + '结果写入失败')
            previous_session, previous_sessions = self.session_id, self.sessions.copy()
            if self.session_id is None:
                self.begin_session()
            number = 1 + sum(row.kind == 'result' for row in self.records.values())
            try:
                for cloud, sources, name in results:
                    uid = uuid.uuid4().hex
                    folder = self.directory / 'frames' / uid
                    folders.append(folder)
                    folder.mkdir(parents=True)
                    if not write_point_cloud_atomic(str(folder / 'pointmap.ply'), cloud):
                        raise IOError(role + '结果写入失败')
                    title = name or (f'后处理点云 {number:03d}' if postprocess else f'拼接帧 {number:03d}')
                    staged[uid] = FrameRecord(uid, self.session_id, '', number, role + '结果',
                        title, datetime.now().isoformat(timespec='seconds'), len(cloud.points), [0, 0],
                        status='已处理' if postprocess else '已拼接', kind='result', source_ids=sources)
                    identifiers.append(uid)
                    number += 1
                self.records.update(staged)
                self._save_index()
            except Exception:
                for uid in identifiers:
                    self.records.pop(uid, None)
                for folder in folders:
                    shutil.rmtree(folder, ignore_errors=True)
                self.session_id, self.sessions = previous_session, previous_sessions
                raise
        self._notify()
        return identifiers

    def remove(self, identifiers, *, invalidate_results=False):
        """Move owned pairs into a recoverable batch, committing the index last.

        Returns {uid: (old_folder, new_folder)} so workflow references can follow
        the move without deleting an already accepted station or calibration.
        """
        with rvc_sdk_lock, self._lock:
            identifiers = list(dict.fromkeys(identifiers))
            if not identifiers or any(uid not in self.records for uid in identifiers):
                raise ValueError('请选择有效的DB帧')
            batch = uuid.uuid4().hex
            moves = {}
            before = copy.deepcopy(self.records)
            try:
                for uid in identifiers:
                    old = self.directory / 'frames' / uid
                    new = self.directory / '.trash' / batch / uid
                    new.parent.mkdir(parents=True, exist_ok=True)
                    old.rename(new)
                    moves[uid] = (old, new)
                    self.removed[uid] = dict(batch=batch, record=vars(self.records.pop(uid)).copy())
                if invalidate_results:
                    self._invalidate_results(identifiers)
                self._save_index()
            except Exception:
                self.records = before
                for uid, (old, new) in reversed(list(moves.items())):
                    new.rename(old)
                    self.removed.pop(uid, None)
                raise
        self._notify()
        return moves

    def restore_last_removal(self):
        with rvc_sdk_lock, self._lock:
            if not self.removed:
                raise ValueError('没有可恢复的删除')
            batch = next(reversed(self.removed.values()))['batch']
            entries = {uid: entry for uid, entry in self.removed.items() if entry['batch'] == batch}
            moves = {}
            before = self.removed.copy()
            try:
                for uid, entry in entries.items():
                    old = self.directory / '.trash' / batch / uid
                    new = self.directory / 'frames' / uid
                    names = ('pointmap.ply',) if entry['record'].get('kind') == 'result' else ('image.png', 'pointmap.ply')
                    if not all((old / name).is_file() for name in names):
                        raise IOError('回收区原始数据不完整')
                    new.parent.mkdir(parents=True, exist_ok=True)
                    old.rename(new)
                    moves[uid] = (old, new)
                    self.records[uid] = FrameRecord(**entry['record'])
                    self.removed.pop(uid)
                self._save_index()
            except Exception:
                self.removed = before
                for uid, (old, new) in reversed(list(moves.items())):
                    new.rename(old)
                    self.records.pop(uid, None)
                raise
        self._notify()
        return moves

    def purge_removed(self, protected=()):
        """Permanently clear only unreferenced recycle entries after UI approval."""
        protected = set(protected)
        with rvc_sdk_lock, self._lock:
            eligible = {uid: entry for uid, entry in self.removed.items() if uid not in protected}
            if not eligible:
                return 0
            staging = self.directory / '.purge' / uuid.uuid4().hex
            moves = []
            before = self.removed.copy()
            try:
                for uid, entry in eligible.items():
                    old = self.directory / '.trash' / entry['batch'] / uid
                    new = staging / uid
                    staging.mkdir(parents=True, exist_ok=True)
                    old.rename(new)
                    moves.append((old, new))
                    self.removed.pop(uid)
                self._save_index()
            except Exception:
                self.removed = before
                for old, new in reversed(moves):
                    new.rename(old)
                raise
        shutil.rmtree(staging)
        self._notify()
        return len(eligible)

    def open_project(self, index):
        directory = Path(index).resolve().parent
        data = json.loads((directory / 'index.json').read_text(encoding='utf-8'))
        if data.get('schema') != 1 or data.get('mode') != self.mode:
            raise ValueError('DB项目版本或工作区类型不匹配')
        records = {}
        removed = data.get('removed', {})
        recognition = data.get('recognition', {})
        if not isinstance(recognition, dict) or not all(isinstance(value, dict) for value in recognition.values()):
            raise ValueError('DB识别缓存格式无效')
        for uid, entry in removed.items():
            entry['record']['recognition'] = recognition.get(uid, entry['record'].get('recognition', {}))
            batch = entry['batch']
            if (len(uid) != 32 or len(batch) != 32 or
                    any(c not in '0123456789abcdef' for c in uid + batch) or
                    FrameRecord(**entry['record']).uid != uid):
                raise ValueError('DB回收区索引无效')
        for values in data['records']:
            row = FrameRecord(**values)
            row.recognition = recognition.get(row.uid, row.recognition)
            if len(row.uid) != 32 or any(c not in '0123456789abcdef' for c in row.uid):
                raise ValueError('DB帧标识无效')
            if row.uid in records or row.session_id not in data['sessions']:
                raise ValueError('DB索引重复或会话缺失')
            session = data['sessions'][row.session_id]
            if (not isinstance(row.frame_id, int) or row.frame_id < 0 or
                    not isinstance(row.revision, int) or row.revision < 0 or
                    not isinstance(row.points, int) or row.points <= 0 or
                    row.kind not in ('raw', 'result') or len(row.image_size) != 2 or
                    not all(isinstance(v, int) and v >= (1 if row.kind == 'raw' else 0) for v in row.image_size) or
                    not isinstance(row.source_ids, list) or any(not isinstance(v, str) or len(v) != 32 or
                        any(c not in '0123456789abcdef' for c in v) for v in row.source_ids) or
                    not isinstance(row.markers, list) or not all(isinstance(v, dict) for v in row.markers) or
                    not isinstance(row.recognition, dict) or
                    not all(isinstance(v, str) for v in (row.camera, row.purpose, row.logical_name, row.status, session['title'], session['created']))):
                raise ValueError('DB帧元数据无效')
            for name in (('image.png', 'pointmap.ply') if row.kind == 'raw' else ('pointmap.ply',)):
                if not (directory / 'frames' / row.uid / name).is_file():
                    raise ValueError(f'DB帧缺少文件: {row.uid}/{name}')
            records[row.uid] = row
        if set(records) & set(removed):
            raise ValueError('DB帧同时存在于回收区')
        with self._lock:
            self.directory, self.records, self.sessions = directory, records, data['sessions']
            self.removed = removed
            self.session_id = None
        self._notify()
