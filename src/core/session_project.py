"""Explicit project snapshots; acquisition writes only to an owned draft.

Saved projects are changed exclusively by save(). No startup/exit autosave.
"""
from datetime import datetime
from pathlib import Path
import json
import os
import re
import shutil
import sys
import tempfile
import uuid

from .utils import write_json_atomic
from .frame_database import FrameDatabase, _json_value

PROJECT_ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
DEFAULT_SESSIONS = PROJECT_ROOT / 'sessions'
MODE_LABELS = dict(multi_cam='多相机标定', mobile_chain='移动拼接', turntable='转台拼接')


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name.strip()).strip('. ')
    if not name or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        name = '未命名项目'
    return name[:60]


def disk_usage(path):
    size = trash = files = 0
    path = Path(path)
    if path.exists():
        for base, folders, names in os.walk(path, followlinks=False):
            folders[:] = [f for f in folders if not (Path(base) / f).is_symlink()]
            for name in names:
                item = Path(base) / name
                if item.is_symlink():
                    continue
                n = item.stat().st_size
                size += n
                files += 1
                if '.trash' in item.relative_to(path).parts:
                    trash += n
    return dict(bytes=size, trash_bytes=trash, files=files)


class SessionProject:
    def __init__(self, mode, name=None, save_root=None):
        if mode not in MODE_LABELS:
            raise ValueError('未知会话类型')
        self.mode = mode
        self.uid = uuid.uuid4().hex
        self.name = safe_name(name or ('未命名' + MODE_LABELS[mode]))
        self.created = datetime.now().isoformat(timespec='seconds')
        self.directory = Path(tempfile.gettempdir()) / 'MCC_workspaces' / self.uid
        self.save_root = Path(save_root or DEFAULT_SESSIONS).resolve()
        self.saved_path = None
        self.dirty = False
        self.include_raw = True
        self.database = FrameDatabase(mode)
        self.database.directory = self.directory / 'data'

    @property
    def title(self):
        return self.name + (' *' if self.dirty else '')

    def save(self, workflow, *, include_raw=None):
        include_raw = True if include_raw is None else include_raw
        self.save_root.mkdir(parents=True, exist_ok=True)
        destination = self.saved_path or self.save_root / (
            MODE_LABELS[self.mode] + '_' + safe_name(self.name) + '_' +
            datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + self.uid[:8])
        if destination.exists():
            old = json.loads((destination / 'session.json').read_text(encoding='utf-8'))
            if old.get('id') != self.uid:
                raise ValueError('目标目录不属于当前会话')
        staging = self.save_root / ('.saving_' + uuid.uuid4().hex)
        backup = self.save_root / ('.backup_' + uuid.uuid4().hex)
        staging.mkdir()
        try:
            # Keep explicit exports and user notes placed in the project folder.
            # Re-saving session state must not erase these independent outputs.
            if destination.exists():
                for item in destination.iterdir():
                    if item.name in ('data', 'session.json'):
                        continue
                    if item.is_symlink():
                        raise ValueError('会话附加文件不能是符号链接')
                    if item.is_dir():
                        if any(p.is_symlink() for p in item.rglob('*')):
                            raise ValueError('会话附加目录不能包含符号链接')
                        shutil.copytree(item, staging / item.name)
                    else:
                        shutil.copy2(item, staging / item.name)
            if include_raw:
                self.database._save_index()
                def copy_asset(source, target):
                    source = Path(source)
                    previous = destination / 'data' / source.relative_to(self.database.directory)
                    # Immutable assets keep their UUID. Reuse the saved inode
                    # inside the new snapshot, never link to the mutable draft.
                    # Filesystems without hard-link support use ordinary copies.
                    if source.suffix.lower() in ('.ply', '.png') and previous.is_file() and previous.stat().st_size == source.stat().st_size:
                        try:
                            os.link(previous, target)
                            return str(target)
                        except OSError:
                            pass
                    return shutil.copy2(source, target)
                shutil.copytree(self.database.directory, staging / 'data', copy_function=copy_asset)
            manifest = dict(format='MCC_SESSION', schema=1, id=self.uid, mode=self.mode,
                name=self.name, created=self.created, saved=datetime.now().isoformat(timespec='seconds'),
                units='mm', include_raw=bool(include_raw), workflow=workflow)
            write_json_atomic(str(staging / 'session.json'), _json_value(manifest), ensure_ascii=False, indent=2)
            if destination.exists():
                destination.rename(backup)
            try:
                staging.rename(destination)
            except Exception:
                if backup.exists():
                    backup.rename(destination)
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        if backup.exists():
            shutil.rmtree(backup)
        self.saved_path = destination
        self.include_raw = bool(include_raw)
        return destination

    @classmethod
    def load(cls, path, mode, save_root=None):
        path = Path(path).resolve()
        data = json.loads((path / 'session.json').read_text(encoding='utf-8'))
        if (data.get('format') != 'MCC_SESSION' or data.get('schema') != 1 or
                data.get('mode') != mode or data.get('units') != 'mm'):
            raise ValueError('会话格式或功能类型不匹配，请进入对应工作区')
        uid = data['id']
        if not isinstance(uid, str) or len(uid) != 32 or any(c not in '0123456789abcdef' for c in uid):
            raise ValueError('会话ID无效')
        project = cls(mode, data['name'], save_root)
        try:
            project.directory.mkdir(parents=True)
            project.include_raw = bool(data['include_raw'])
            if project.include_raw:
                if (path / 'data').is_symlink() or any(item.is_symlink() for item in (path / 'data').rglob('*')):
                    raise ValueError('会话数据目录不能包含符号链接')
                shutil.copytree(path / 'data', project.database.directory)
                project.database.open_project(project.database.directory / 'index.json')
            project.uid = uid
            project.created = data['created']
            project.saved_path = path
            # Updating an imported project updates its own directory, explicitly
            # on Save; drafts remain isolated from that directory until then.
            project.save_root = path.parent
            return project, data['workflow']
        except Exception:
            project.dispose()
            raise

    def dispose(self):
        # Only remove this instance's private draft, never a user project path.
        owned = self.directory.resolve()
        parent = (Path(tempfile.gettempdir()) / 'MCC_workspaces').resolve()
        if owned.parent != parent or not re.fullmatch('[0-9a-f]{32}', owned.name):
            raise ValueError('临时工作区路径无效')
        if owned.exists():
            shutil.rmtree(owned)
