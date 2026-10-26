"""Atomic persistent task and evaluation store for the local MCC board."""
from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading

STATUSES = ('open', 'claimed', 'in_progress', 'review', 'done')
TRANSITIONS = {
    'open': {'claimed'},
    'claimed': {'in_progress', 'open'},
    'in_progress': {'review', 'open'},
    'review': {'done', 'in_progress', 'open'},
    'done': set(),
}
ID_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9-]{1,63}$')


class ConflictError(ValueError):
    pass


class PermissionError(ValueError):
    pass


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


_LOCK_STATE = threading.local()


@contextmanager
def file_lock(data_dir):
    key = str(Path(data_dir).resolve())
    depths = getattr(_LOCK_STATE, 'depths', None)
    if depths is None:
        depths = _LOCK_STATE.depths = {}
    if key in depths:
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return
    lock_path = Path(data_dir) / '.board.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open('a+b')
    try:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        depths[key] = 1
        yield
    finally:
        depths.pop(key, None)
        try:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
            dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path, default):
    path = Path(path)
    if not path.is_file():
        return copy.deepcopy(default)
    with path.open('r', encoding='utf-8') as stream:
        return json.load(stream)


def validate_agent(agent):
    agent = str(agent or '').strip()
    if not agent or len(agent) > 60 or any(ord(char) < 32 for char in agent):
        raise ValueError('Agent 名称必须为 1～60 个有效字符')
    return agent


class TaskStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.tasks_path = self.data_dir / 'tasks.json'
        self.evaluation_path = self.data_dir / 'evaluation.json'
        self._lock = threading.RLock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _tasks(self):
        return read_json(self.tasks_path, [])

    def _write_tasks(self, tasks):
        atomic_write(self.tasks_path, tasks)

    def all_tasks(self):
        with self._lock:
            return copy.deepcopy(self._tasks())

    def get(self, task_id):
        for task in self._tasks():
            if task['id'] == task_id:
                return copy.deepcopy(task)
        raise KeyError(f'任务不存在: {task_id}')

    def create_task(self, data):
        data = dict(data)
        task_id = str(data.get('id', ''))
        if not ID_PATTERN.fullmatch(task_id):
            raise ValueError('任务 ID 只能包含大写字母、数字和连字符，且不能以连字符开头')
        for field in ('title', 'priority', 'evidence'):
            if not str(data.get(field, '')).strip():
                raise ValueError(f'缺少任务字段: {field}')
        task = {
            'id': task_id,
            'title': str(data['title']).strip(),
            'priority': str(data['priority']).upper(),
            'evidence': str(data['evidence']).strip(),
            'scope': list(data.get('scope', [])),
            'requirements': list(data.get('requirements', [])),
            'acceptance': list(data.get('acceptance', [])),
            'dependencies': list(data.get('dependencies', [])),
            'status': 'open',
            'agent': None,
            'source': data.get('source', 'manual'),
            'source_key': data.get('source_key'),
            'created_at': now_iso(),
            'updated_at': now_iso(),
            'history': [{'at': now_iso(), 'action': 'created', 'agent': 'mcc-board',
                'note': '正式任务已发布'}],
        }
        with self._lock, file_lock(self.data_dir):
            tasks = self._tasks()
            if any(item['id'] == task_id for item in tasks):
                raise ConflictError(f'任务 ID 已存在: {task_id}')
            tasks.append(task)
            self._write_tasks(tasks)
        return copy.deepcopy(task)

    def _change(self, task_id, action, agent=None, note='', *,
                expected_statuses=None, expected_agent=None, evidence=None):
        with self._lock, file_lock(self.data_dir):
            tasks = self._tasks()
            for index, task in enumerate(tasks):
                if task['id'] != task_id:
                    continue
                if expected_statuses is not None and task['status'] not in expected_statuses:
                    raise ConflictError(f'任务当前状态不允许该操作: {task["status"]}')
                if expected_agent is not None and task['agent'] != expected_agent:
                    raise PermissionError('只有接取该任务的 Agent 可以执行该操作')
                previous = task['status']
                if evidence is not None:
                    task['evidence'] = evidence
                task['status'] = action
                task['updated_at'] = now_iso()
                if action == 'open':
                    task['agent'] = None
                elif agent is not None:
                    task['agent'] = agent
                task['history'].append({'at': task['updated_at'], 'action': action,
                    'agent': agent, 'note': note or f'{previous} → {action}'})
                tasks[index] = task
                self._write_tasks(tasks)
                return copy.deepcopy(task)
        raise KeyError(f'任务不存在: {task_id}')

    def claim(self, task_id, agent):
        agent = validate_agent(agent)
        task = self.get(task_id)
        if task['status'] != 'open':
            raise ConflictError(f'任务 {task_id} 已被接取或当前不可接取')
        return self._change(task_id, 'claimed', agent, 'Agent 已接取任务',
            expected_statuses=['open'])

    def release(self, task_id, agent):
        agent = validate_agent(agent)
        task = self.get(task_id)
        if task['status'] == 'open':
            raise ConflictError('任务尚未接取')
        if task['status'] == 'done':
            raise ConflictError('已完成任务不能释放')
        return self._change(task_id, 'open', agent, 'Agent 释放任务',
            expected_statuses=['claimed', 'in_progress', 'review'], expected_agent=agent)

    def set_status(self, task_id, status, agent, note=''):
        if status not in STATUSES:
            raise ValueError(f'未知任务状态: {status}')
        agent = validate_agent(agent)
        task = self.get(task_id)
        if status not in TRANSITIONS[task['status']]:
            raise ConflictError(f'不允许从 {task["status"]} 转为 {status}')
        return self._change(task_id, status, agent, note,
            expected_statuses=[task['status']], expected_agent=agent)

    def reopen(self, task_id, evidence):
        return self._change(task_id, 'open', 'evaluation', '新一次评估失败，任务重新开放',
            expected_statuses=['done'], evidence=evidence)

    def save_evaluation(self, report):
        with self._lock, file_lock(self.data_dir):
            atomic_write(self.evaluation_path, report)
        return copy.deepcopy(report)

    def evaluation(self):
        return read_json(self.evaluation_path, {'state': 'idle', 'results': []})

    def project_info(self):
        root = Path(__file__).resolve().parents[2]
        version = 'unknown'
        try:
            match = re.search(r'__VERSION__\s*=\s*["\']([^"\']+)["\']',
                (root / 'src' / 'version.py').read_text(encoding='utf-8'))
            version = match.group(1) if match else version
        except OSError:
            pass
        try:
            head = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=root,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=2, check=False).stdout.strip()
            branch = subprocess.run(['git', 'branch', '--show-current'], cwd=root,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=2, check=False).stdout.strip()
        except OSError:
            head, branch = '', ''
        return {'version': version, 'head': head, 'branch': branch}

    def summary(self):
        tasks = self._tasks()
        counts = {status: sum(task['status'] == status for task in tasks) for status in STATUSES}
        evaluation = self.evaluation()
        results = evaluation.get('results', [])
        passed = sum(result.get('returncode') == 0 for result in results)
        counts.update(total=len(tasks), evaluation=evaluation,
            passed=passed, failed=len(results) - passed,
            pass_rate=round(passed * 100 / len(results), 1) if results else None,
            project=self.project_info())
        return counts

    def sync_evaluation_tasks(self):
        with self._lock, file_lock(self.data_dir):
            evaluation = self.evaluation()
            existing = {task.get('source_key'): task for task in self._tasks()}
            created = []
            for result in evaluation.get('results', []):
                if result.get('returncode') == 0:
                    continue
                name = result['name']
                evidence = f"实跑退出码 {result.get('returncode')}。{result.get('log', '')[-1500:]}"
                previous = existing.get(name)
                if previous is not None:
                    if previous['status'] == 'done':
                        self.reopen(previous['id'], evidence)
                    continue
                slug = re.sub(r'[^A-Za-z0-9]+', '-', Path(name).stem).strip('-').upper() or 'FAILURE'
                command = result.get('command', [])
                command_text = ' '.join(command) if isinstance(command, list) else str(command)
                created.append(self.create_task({
                    'id': f'AUTO-{slug}',
                    'title': f'修复失败测试：{name}',
                    'priority': 'P1',
                    'evidence': evidence,
                    'scope': [name],
                    'requirements': ['先复现失败并定位根因，修复后运行相关回归；不得初始化实体设备。'],
                    'acceptance': [command_text],
                    'source': 'evaluation',
                    'source_key': name,
                }))
                existing[name] = created[-1]
            return created
