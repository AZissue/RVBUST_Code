"""Persistent task store and evaluation-to-task behavior tests."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(self.temp.name)

    def task(self):
        return dict(id='MCC-001', title='修复示例', priority='P1', evidence='已复现',
            scope=['src/example.py'], requirements=['保持现有行为'], acceptance=['python test_example.py'])

    def test_create_persist_and_summary(self):
        created = self.store.create_task(self.task())
        self.assertEqual(created['status'], 'open')
        self.assertEqual(created['history'][0]['action'], 'created')
        self.assertEqual(self.store.summary()['open'], 1)
        self.assertEqual(TaskStore(self.temp.name).get('MCC-001')['title'], '修复示例')
        self.assertFalse(list(Path(self.temp.name).glob('*.tmp')))

    def test_claim_transition_release_and_duplicate_guard(self):
        self.store.create_task(self.task())
        claimed = self.store.claim('MCC-001', 'agent-a')
        self.assertEqual(claimed['status'], 'claimed')
        self.assertEqual(claimed['agent'], 'agent-a')
        with self.assertRaisesRegex(ValueError, '已被'):
            self.store.claim('MCC-001', 'agent-b')
        self.assertEqual(self.store.set_status('MCC-001', 'in_progress', 'agent-a')['status'], 'in_progress')
        self.assertEqual(self.store.set_status('MCC-001', 'review', 'agent-a')['status'], 'review')
        self.assertEqual(self.store.set_status('MCC-001', 'done', 'agent-a')['status'], 'done')
        with self.assertRaises(ValueError):
            self.store.set_status('MCC-001', 'in_progress', 'agent-a')

    def test_release_returns_open(self):
        self.store.create_task(self.task())
        self.store.claim('MCC-001', 'agent-a')
        released = self.store.release('MCC-001', 'agent-a')
        self.assertEqual(released['status'], 'open')
        self.assertIsNone(released['agent'])
        self.store.claim('MCC-001', 'agent-b')

    def test_validation_and_evaluation_tasks_are_deduplicated(self):
        with self.assertRaises(ValueError):
            self.store.create_task(dict(self.task(), id='../bad'))
        self.store.create_task(self.task())
        report = {'results': [{'name': 'test_fail.py', 'command': ['python', 'test_fail.py'],
            'returncode': 1, 'log': 'assertion failed', 'duration_sec': .2}],
            'started_at': '2026-10-26T00:00:00+08:00', 'finished_at': '2026-10-26T00:00:01+08:00'}
        self.store.save_evaluation(report)
        created = self.store.sync_evaluation_tasks()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]['source_key'], 'test_fail.py')
        self.assertEqual(self.store.sync_evaluation_tasks(), [])
        self.assertEqual(len(self.store.all_tasks()), 2)

    def test_concurrent_claim_has_single_winner_across_instances(self):
        import threading
        self.store.create_task(self.task())
        other = TaskStore(self.temp.name)
        successes, failures = [], []
        barrier = threading.Barrier(6)
        def claim(store, name):
            barrier.wait()
            try:
                successes.append(store.claim('MCC-001', name)['agent'])
            except Exception as exc:
                failures.append(type(exc).__name__)
        threads = [threading.Thread(target=claim, args=(self.store if i % 2 else other, f'agent-{i}')) for i in range(6)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 5)
        self.assertEqual(self.store.get('MCC-001')['agent'], successes[0])

    def test_completed_auto_task_reopens_on_regression(self):
        report = {'results': [{'name': 'test_fail.py', 'command': ['python', 'test_fail.py'],
            'returncode': 1, 'log': 'first', 'duration_sec': .1}]}
        self.store.save_evaluation(report)
        task = self.store.sync_evaluation_tasks()[0]
        self.store.claim(task['id'], 'agent-a')
        self.store.set_status(task['id'], 'in_progress', 'agent-a')
        self.store.set_status(task['id'], 'review', 'agent-a')
        self.store.set_status(task['id'], 'done', 'agent-a')
        report['results'][0]['log'] = 'new regression'
        self.store.save_evaluation(report)
        self.store.sync_evaluation_tasks()
        reopened = self.store.get(task['id'])
        self.assertEqual(reopened['status'], 'open')
        self.assertIsNone(reopened['agent'])
        self.assertIn('new regression', reopened['evidence'])

    def test_replace_failure_preserves_old_file_and_cleans_temporary(self):
        from unittest.mock import patch
        self.store.create_task(self.task())
        before = self.store.tasks_path.read_bytes()
        with patch('store.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.create_task(dict(self.task(), id='MCC-002'))
        self.assertEqual(self.store.tasks_path.read_bytes(), before)
        self.assertFalse(list(Path(self.temp.name).glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
