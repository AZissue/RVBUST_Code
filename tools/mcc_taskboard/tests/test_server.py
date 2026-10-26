"""Local task-board HTTP API tests using an ephemeral loopback port."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation import EvaluationRunner
from server import create_server
from store import TaskStore


class TaskBoardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        store = TaskStore(self.temp.name)
        store.create_task(dict(id='MCC-001', title='示例任务', priority='P1', evidence='证据',
            scope=['src/example.py'], requirements=['要求'], acceptance=['python test_example.py']))
        self.store = store
        self.runner = EvaluationRunner(store, commands=[('dummy_fail', [sys.executable, '-c', 'raise SystemExit(1)'])])
        self.server = create_server(store, self.runner, host='127.0.0.1', port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, method='GET', data=None, headers=None):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(self.base + path, data=body, method=method,
            headers=headers or {'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_summary_and_task_claim_lifecycle(self):
        code, summary = self.request('/api/summary')
        self.assertEqual(code, 200)
        self.assertEqual(summary['open'], 1)
        code, task = self.request('/api/tasks/MCC-001/claim', 'POST', {'agent': 'agent-a'})
        self.assertEqual(code, 200)
        self.assertEqual(task['status'], 'claimed')
        code, _ = self.request('/api/tasks/MCC-001/claim', 'POST', {'agent': 'agent-b'})
        self.assertEqual(code, 409)
        code, task = self.request('/api/tasks/MCC-001/status', 'POST',
            {'status': 'in_progress', 'agent': 'agent-a', 'note': '开始修复'})
        self.assertEqual(code, 200)
        self.assertEqual(task['history'][-1]['note'], '开始修复')
        code, task = self.request('/api/tasks/MCC-001/release', 'POST', {'agent': 'agent-a'})
        self.assertEqual(code, 200)
        self.assertEqual(task['status'], 'open')

    def test_invalid_input_and_missing_task(self):
        code, _ = self.request('/api/tasks/MCC-001/status', 'POST',
            {'status': 'done', 'agent': 'agent-a'})
        self.assertEqual(code, 409)
        code, _ = self.request('/api/tasks/UNKNOWN')
        self.assertEqual(code, 404)

    def test_evaluation_failure_creates_task_once(self):
        code, response = self.request('/api/evaluate', 'POST', {})
        self.assertEqual(code, 202)
        code, response = self.request('/api/evaluate', 'POST', {})
        self.assertEqual(code, 409)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            _, evaluation = self.request('/api/evaluation')
            if evaluation.get('state') == 'complete':
                break
            time.sleep(.05)
        self.assertEqual(evaluation['results'][0]['returncode'], 1)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            code, task = self.request('/api/tasks/AUTO-DUMMY-FAIL')
            if code == 200:
                break
            time.sleep(.05)
        self.assertEqual(code, 200)
        self.assertEqual(task['source'], 'evaluation')

    def test_non_owner_origin_and_content_type_are_rejected(self):
        self.request('/api/tasks/MCC-001/claim', 'POST', {'agent': 'agent-a'})
        code, _ = self.request('/api/tasks/MCC-001/status', 'POST',
            {'status': 'in_progress', 'agent': 'agent-b'})
        self.assertEqual(code, 403)
        code, _ = self.request('/api/tasks/MCC-001/release', 'POST', {'agent': 'agent-a'},
            headers={'Content-Type': 'application/json', 'Origin': 'https://evil.example'})
        self.assertEqual(code, 403)
        code, _ = self.request('/api/tasks/MCC-001/release', 'POST', {'agent': 'agent-a'},
            headers={'Content-Type': 'text/plain'})
        self.assertEqual(code, 415)

    def test_oversize_and_invalid_json(self):
        code, _ = self.request('/api/tasks/MCC-001/claim', 'POST', {'agent': 'x' * 70000})
        self.assertEqual(code, 413)
        request = Request(self.base + '/api/tasks/MCC-001/claim', data=b'{bad',
            headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_sync_failure_is_failed_not_running_and_restart_recovers(self):
        from unittest.mock import patch
        with patch.object(self.store, 'sync_evaluation_tasks', side_effect=RuntimeError('sync failed')):
            self.assertTrue(self.runner.start())
            self.runner._thread.join(5)
            self.assertFalse(self.runner._thread.is_alive())
            evaluation = self.store.evaluation()
            self.assertEqual(evaluation['state'], 'failed')
            self.assertIn('sync failed', evaluation['error'])
        self.store.save_evaluation({'state': 'running', 'results': []})
        self.runner.recover_interrupted()
        self.assertEqual(self.store.evaluation()['state'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
