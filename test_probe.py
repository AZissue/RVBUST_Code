"""Probe numerical and production read-only lifecycle regressions."""
import unittest
from unittest.mock import patch
import threading
import numpy as np
import test_postprocess as fixture
from core.postprocess.probe import spacing, coverage, source_reason
from core.frame_database import STALE_RESULT


class ProbeMathTests(unittest.TestCase):
    def test_grid_and_determinism(self):
        xyz = np.array([[x, y, 0] for x in range(10) for y in range(10)])*2
        s = spacing(xyz)
        for k in ('p50', 'mean', 'p90', 'p95'):
            self.assertEqual(s[k], 2)
        self.assertEqual(spacing(xyz, 10)['p50'], spacing(xyz, 10)['p50'])
        self.assertTrue(spacing(xyz, 10)['estimated'])

    def test_degenerate(self):
        for points in ([], [[0, 0, 0]], [[np.nan, 0, 0]]):
            self.assertIn('reason', spacing(points))
        self.assertEqual(spacing([[0, 0, 0]]*3)['p50'], 0)
        s = spacing([[0, 0, 0], [1, 0, 0], [100, 0, 0]])
        self.assertEqual(s['p50'], 1)
        self.assertGreater(s['mean'], s['p50'])
        self.assertGreater(s['p90'], s['p50'])

    def test_translation(self):
        a = np.array([[0, 0, 0], [10, 0, 0], [20, 0, 0]])
        b = a+[0, 0, 2]
        for x, y in ((a,b), (b,a)):
            self.assertEqual(coverage(x, y, 3)['coverage'], 1)
            self.assertEqual(coverage(x, y, 3)['rms'], 2)
            self.assertEqual(coverage(x, y, 1)['coverage'], 0)
            self.assertIsNone(coverage(x, y, 1)['rms'])


class ProbeUiTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp = fixture.PostprocessTests.setUp
    tearDown = fixture.PostprocessTests.tearDown
    wait = fixture.PostprocessTests.wait
    source = fixture.PostprocessTests.source
    finish = fixture.PostprocessTests.finish

    def inputs(self):
        uid = self.db.ingest(self.source())
        self.editor.source_browser.refresh()
        self.editor.load_selected([uid]); self.finish()
        return uid

    def test_toolbar_dialog_is_manual_reusable_and_busy_gated(self):
        self.assertFalse(self.editor.actions['probe'].isEnabled())
        self.inputs()
        with patch.object(self.editor, 'analyze_probe') as analyze:
            self.editor.actions['probe'].click()
            self.app.processEvents()
            self.assertTrue(self.editor.probe_dialog.isVisible())
            self.assertFalse(self.editor.properties.isAncestorOf(self.editor.probe))
            analyze.assert_not_called()
            self.editor.probe_dialog.close()
            self.editor.actions['probe'].click()
            self.assertTrue(self.editor.probe_dialog.isVisible())
        self.editor.analyze_probe()
        self.assertFalse(self.editor.actions['probe'].isEnabled())
        self.assertFalse(self.editor.probe.isEnabled())
        self.editor.probe_dialog.close()
        self.finish()
        self.editor.actions['probe'].click()
        self.assertTrue(self.editor.probe.apply.isEnabled())
        self.assertTrue(self.editor.probe.isEnabled())

    def test_reasons(self):
        uid = self.inputs()
        row = self.db.records[uid]
        self.assertTrue(source_reason([], True))
        self.assertTrue(source_reason([row], True))
        self.assertTrue(source_reason([row, row], True))
        self.assertTrue(source_reason([None, row], True))
        row.kind = 'result'
        self.assertTrue(source_reason([row, row], False))
        self.assertFalse(source_reason([row, row], True))
        row.status = STALE_RESULT
        self.assertTrue(source_reason([row, row], True))

    def test_readonly_and_adopt(self):
        self.inputs()
        before = (self.db.directory/'index.json').read_bytes()
        with patch.object(self.db, 'publish_results', side_effect=AssertionError('DB write')), patch.object(self.bridge.shell, 'set_dirty', side_effect=AssertionError('dirty')), patch('core.frame_data._import_rvc', side_effect=AssertionError('SDK')):
            self.editor.analyze_probe(); self.finish()
        self.assertEqual(before, (self.db.directory/'index.json').read_bytes())
        self.assertIsNotNone(self.editor._probe_report)
        with patch.object(self.editor, 'open_downsample_dialog') as opened, patch.object(self.editor, 'downsample') as execute:
            self.editor.adopt_probe_voxel(1.234)
            opened.assert_called_once()
            execute.assert_not_called()
            self.assertEqual(self.editor.create_downsample_dialog().parameters()['voxel'], 1.23)
        self.editor.properties.show_values({'test': 'metadata'})
        self.assertIsNotNone(self.editor.probe.parent())

    def test_stale_selection_and_project(self):
        uid = self.inputs()
        original = spacing
        for project in (False, True):
            entered, release = threading.Event(), threading.Event()
            def slow(points):
                entered.set(); release.wait(5)
                return original(points)
            old = self.db.directory
            with patch('core.postprocess.probe.spacing', side_effect=slow):
                self.editor.analyze_probe()
                self.wait(entered.is_set)
                if project:
                    self.db.directory = old/'other'
                else:
                    self.editor.load_selected([])
                release.set()
                self.wait(lambda: self.editor._worker is None)
                self.assertIsNone(self.editor._probe_report)
            self.db.directory = old
            self.editor.load_selected([uid]); self.finish()


if __name__ == '__main__':
    unittest.main()
