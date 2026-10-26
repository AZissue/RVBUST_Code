"""Background, script-based MCC evaluation without device initialization."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from store import now_iso

REPO_ROOT = Path(__file__).resolve().parents[2]


def default_commands():
    python = sys.executable
    scripts = [
        'test_chain_stitcher.py',
        'test_workflows.py',
        'test_station.py',
        'test_handeye.py',
        'test_robot_stitch.py',
        'test_robot_handeye_core.py',
        'test_robot_handeye_file.py',
        'test_robot_workspace.py',
        'test_robot_session.py',
        'src/ui_v2/smoke_test.py',
        'prototypes/industrial_offline_stitch/tests/test_offline_workflow.py',
        'prototypes/industrial_offline_stitch/tests/test_ui_smoke.py',
        'tools/mcc_taskboard/tests/test_store.py',
        'tools/mcc_taskboard/tests/test_server.py',
    ]
    return [(Path(script).name, [python, script]) for script in scripts]


class EvaluationRunner:
    def __init__(self, store, commands=None, timeout_sec=240):
        self.store = store
        self.commands = list(commands or default_commands())
        self.timeout_sec = timeout_sec
        self._lock = threading.Lock()
        self._thread = None
        self.recover_interrupted()

    def recover_interrupted(self):
        evaluation = self.store.evaluation()
        if evaluation.get('state') == 'running':
            evaluation.update(state='interrupted', finished_at=now_iso(),
                error='服务重启，评估中断；可以重新运行')
            self.store.save_evaluation(evaluation)

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self.store.evaluation().get('state') == 'running':
                return False
            started_at = now_iso()
            self.store.save_evaluation({'state': 'running', 'started_at': started_at,
                'finished_at': None, 'results': []})
            self._thread = threading.Thread(target=self._run, args=(started_at,),
                daemon=True, name='mcc-evaluation')
            self._thread.start()
            return True

    def _run(self, started_at):
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        environment['PYTHONUTF8'] = '1'
        environment['QT_QPA_PLATFORM'] = 'offscreen'
        results = []
        try:
            for name, command in self.commands:
                started = time.perf_counter()
                try:
                    completed = subprocess.run(command, cwd=REPO_ROOT, env=environment,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding='utf-8', errors='replace',
                        timeout=self.timeout_sec, check=False)
                    returncode = completed.returncode
                    output = completed.stdout or ''
                except Exception as exc:
                    returncode = -1
                    output = str(exc)
                results.append({'name': name, 'command': list(command),
                    'returncode': returncode,
                    'duration_sec': round(time.perf_counter() - started, 3),
                    'log': output[-5000:]})
                self.store.save_evaluation({'state': 'running', 'started_at': started_at,
                    'finished_at': None, 'results': list(results)})
            self.store.sync_evaluation_tasks()
            self.store.save_evaluation({'state': 'complete', 'started_at': started_at,
                'finished_at': now_iso(), 'results': results})
        except Exception as exc:
            try:
                self.store.save_evaluation({'state': 'failed', 'started_at': started_at,
                    'finished_at': now_iso(), 'results': results, 'error': str(exc)})
            except Exception:
                pass
