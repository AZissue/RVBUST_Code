"""Production top-bar colour operation, provenance, transactions and busy gates."""
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import test_postprocess as fixture
from test_color_correction import scene, overlapping
from core.session_project import SessionProject
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, QEvent
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest


class ColorPostprocessTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp = fixture.PostprocessTests.setUp
    tearDown = fixture.PostprocessTests.tearDown
    wait = fixture.PostprocessTests.wait
    source = fixture.PostprocessTests.source
    finish = fixture.PostprocessTests.finish

    def inputs(self, single=False, uncolored=False):
        raw = self.db.ingest(self.source())
        if single:
            xyz, _, rgb = scene()
            pairs = [(xyz, rgb)]
        else:
            xyz, rgb, target, _ = overlapping()
            pairs = [(xyz, rgb), (xyz, None if uncolored else target)]
        ids = [self.db.publish_result(fixture.cloud(xyz, color), [raw]) for xyz, color in pairs]
        self.editor.source_browser.refresh()
        self.editor.load_selected(ids); self.finish()
        self.editor._color_state.update(aligned=True, strength=1., max_gain=2., scale=15.)
        return raw, ids

    def execute(self):
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().execute_button.click())
        self.editor.actions['color'].click()
        self.finish()

    def test_multi_outputs_show_all_keep_xyz_sources_export_undo_recover_session(self):
        raw, sources = self.inputs()
        layers = [self.editor._clouds[uid] for uid in sources]
        before = {uid: (self.db.directory/'frames'/uid/'pointmap.ply').read_bytes() for uid in [raw, *sources]}
        self.execute()
        outputs = list(self.editor._display_ids)
        self.assertEqual(len(outputs), 2)
        self.assertEqual(self.editor.source_browser.checked_components('cloud'), [(uid, 'cloud') for uid in outputs])
        self.assertEqual([self.db.records[uid].source_ids for uid in outputs], [[uid] for uid in sources])
        self.assertEqual(len({self.db.records[uid].operation_id for uid in outputs}), 1)
        for uid, layer in zip(outputs, layers):
            np.testing.assert_array_equal(self.editor._clouds[uid].points, layer.points)
            path = Path(self.temp.name)/(uid+'.ply')
            self.db.export_cloud(uid, path)
            self.assertEqual(path.read_bytes(), (self.db.directory/'frames'/uid/'pointmap.ply').read_bytes())
        np.testing.assert_array_equal(self.editor._clouds[outputs[0]].colors, layers[0].colors)
        error = np.median(abs(self.editor._clouds[outputs[1]].colors-layers[0].colors))
        self.assertLess(error, .004)
        self.assertIn('重叠', self.editor.status.text())
        self.assertEqual(self.editor._last_color_report[0]['status'], '参考不变')
        project = SessionProject('multi_cam', save_root=Path(self.temp.name)/'saved-color')
        self.addCleanup(project.dispose)
        project.database = self.db
        restored, _ = SessionProject.load(project.save({}), 'multi_cam')
        self.addCleanup(restored.dispose)
        for uid in outputs:
            _, cloud = restored.database.load_frame(uid, 'cloud')
            np.testing.assert_allclose(np.asarray(cloud.colors), self.editor._clouds[uid].colors, atol=1/255)
            self.assertEqual(restored.database.records[uid].operation_id, self.db.records[uid].operation_id)
        self.editor.undo(); self.finish()
        self.assertEqual(self.editor._display_ids, sources)
        self.assertTrue(all(uid in self.db.removed for uid in outputs))
        self.db.restore_last_removal()
        self.assertTrue(all(uid in self.db.records for uid in outputs))
        for uid, data in before.items():
            self.assertEqual((self.db.directory/'frames'/uid/'pointmap.ply').read_bytes(), data)

    def test_zero_parameters_guard_noop_and_lazy_original_comparison(self):
        _, sources = self.inputs(single=True)
        editor = self.editor
        before = set(self.db.records)
        for key, value in (('strength', 0), ('max_gain', 1), ('scale', 0), ('overlap_distance', 0)):
            original = editor._color_state[key]
            editor._color_state[key] = value
            editor.correct_colors()
            self.assertIsNone(editor._worker)
            self.assertEqual(set(self.db.records), before)
            self.assertIn('强度=', editor.status.text())
            editor._color_state[key] = original
        dialog = editor.create_color_dialog()
        dialog.show(); self.app.processEvents()
        dialog.color_reference.setFocus()
        for control in (dialog.color_scale, dialog.color_distance, dialog.color_strength,
                        dialog.color_gain, dialog.color_samples):
            original = control.value()
            control.clearFocus()
            event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, -120),
                                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            self.app.sendEvent(control, event)
            QTest.keyClick(control, Qt.Key_Down)
            self.assertEqual(control.value(), original)
        dialog.reject()
        original_colors = editor._clouds[sources[0]].colors.copy()
        self.execute()
        outputs = list(editor._display_ids)
        corrected_colors = editor._clouds[outputs[0]].colors.copy()
        self.assertIn('分布保留', editor.status.text())
        self.assertIn('实际强度', editor.status.text())
        editor.actions['compare'].click(); self.finish()
        self.assertEqual(editor._display_ids, sources)
        np.testing.assert_array_equal(editor._clouds[sources[0]].colors, original_colors)
        self.assertEqual(editor.actions['compare'].text(), '返回校正结果')
        editor.actions['compare'].click(); self.finish()
        self.assertEqual(editor._display_ids, outputs)
        np.testing.assert_allclose(editor._clouds[outputs[0]].colors, corrected_colors, atol=1/255)
        # Exercise the real estimator on a constant-colour DB result; an
        # effectively identical result must never reach publish_results.
        _, stored_cloud = self.db.load_frame(sources[0], 'cloud')
        points = np.asarray(stored_cloud.points).copy()
        unchanged = self.db.publish_result(fixture.cloud(points, np.full_like(points, .3)),
                                           [sources[0]], postprocess=True)
        editor.load_selected([unchanged]); self.finish()
        before = set(self.db.records)
        undo_count = len(editor._undo)
        editor.correct_colors(); self.wait(lambda: editor._worker is None)
        self.assertEqual(set(self.db.records), before)
        self.assertEqual(editor._display_ids, [unchanged])
        self.assertEqual(len(editor._undo), undo_count)
        self.assertIn('无可应用校正', editor.status.text())
        self.assertEqual(editor._last_color_report[0]['changed_fraction'], 0)

    def test_single_top_menu_scales_and_two_sizes(self):
        _, sources = self.inputs(single=True)
        editor = self.editor
        before = editor._clouds[sources[0]]
        for size in ((1440, 900), (1050, 650)):
            editor.resize(*size); self.app.processEvents()
            for button in editor.actions.values():
                self.assertTrue(editor.operation_bar.rect().contains(button.geometry()))
            observed = []
            def cancel():
                dialog = self.app.activeModalWidget()
                observed.append((dialog.color_scale.isVisible(), dialog.execute_button.isVisible(), dialog.color_inputs.text()))
                dialog.reject()
            QTimer.singleShot(0, cancel)
            editor.actions['color'].click()
            self.assertTrue(observed[0][0])
            self.assertTrue(observed[0][1])
            self.assertIn('1 层', observed[0][2])
        self.execute()
        output = editor._clouds[editor._display_ids[0]]
        np.testing.assert_array_equal(output.points, before.points)
        self.assertFalse(np.allclose(output.colors, before.colors))
        self.assertEqual(editor._last_color_report[0]['mode'], '空间低频')
        self.assertEqual(editor.properties.values['有效点数'], f'{len(before.points):,}')

    def test_color_modal_snapshot_reference_and_deleted_controls(self):
        from shiboken6 import isValid
        _, sources = self.inputs()
        editor = self.editor
        # Modal parameters must choose the actual second UID, rather than an index.
        dialogs = []
        def accept():
            dialog = self.app.activeModalWidget()
            dialogs.append(dialog)
            self.assertTrue(dialog.color_reference.isEnabled())
            self.assertFalse(dialog.color_scale.isEnabled())
            self.assertTrue(dialog.color_distance.isEnabled())
            dialog.color_reference.setCurrentIndex(1)
            dialog.execute_button.click()
        QTimer.singleShot(0, accept)
        editor.actions['color'].click()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(dialogs[0]))
        self.finish()
        outputs = list(editor._display_ids)
        np.testing.assert_array_equal(editor._clouds[outputs[1]].colors,
                                      self.db.load_frame(sources[1], 'cloud')[1].colors)
        self.assertEqual(self.db.records[outputs[1]].source_ids, [sources[1]])
        editor.undo(); self.finish()
        index = (self.db.directory/'index.json').read_bytes()
        for mutation in ('inputs', 'revision', 'project'):
            original_directory = editor.directory
            def change_then_accept():
                dialog = self.app.activeModalWidget()
                if mutation == 'inputs':
                    editor._display_ids.reverse()
                elif mutation == 'revision':
                    self.db.records[sources[0]].revision += 1
                else:
                    editor.directory = Path(self.temp.name)/'changed'
                dialog.execute_button.click()
            QTimer.singleShot(0, change_then_accept)
            editor.actions['color'].click()
            self.assertIsNone(editor._worker)
            self.assertIn('变化' if mutation != 'project' else '项目', editor.status.text())
            self.assertEqual((self.db.directory/'index.json').read_bytes(), index)
            editor.directory = original_directory
            if mutation == 'inputs':
                editor._display_ids.reverse()
            elif mutation == 'revision':
                self.db.records[sources[0]].revision -= 1

    def test_color_dialog_validation_blocks_accept_and_remembers_cancelled_values(self):
        self.inputs(single=True)
        editor = self.editor
        seen = []
        def validate():
            dialog = self.app.activeModalWidget()
            seen.append(dialog)
            for control, value in ((dialog.color_strength, 0), (dialog.color_gain, 1)):
                old = control.value()
                control.setValue(value)
                self.assertFalse(dialog.execute_button.isEnabled())
                self.assertTrue(dialog.validation.text())
                dialog.accept()
                self.assertTrue(dialog.isVisible())
                control.setValue(old)
            dialog.color_strength.setValue(65)
            dialog.reject()
        QTimer.singleShot(0, validate)
        before = set(self.db.records)
        editor.actions['color'].click()
        self.assertEqual(set(self.db.records), before)
        self.assertIsNone(editor._worker)
        self.assertEqual(editor._color_state['strength'], .65)

    def test_second_write_failure_rolls_back_whole_color_batch(self):
        _, sources = self.inputs()
        before = set(self.db.records)
        index = (self.db.directory/'index.json').read_bytes()
        from core.utils import write_point_cloud_atomic
        calls = []
        def write(path, data):
            calls.append(path)
            return write_point_cloud_atomic(path, data) if len(calls) == 1 else False
        with patch('core.utils.write_point_cloud_atomic', side_effect=write):
            self.editor.correct_colors()
            self.wait(lambda: self.editor._worker is None)
        self.assertIn('失败', self.editor.status.text())
        self.assertEqual(set(self.db.records), before)
        self.assertEqual((self.db.directory/'index.json').read_bytes(), index)
        self.assertEqual(self.editor._display_ids, sources)
        self.assertFalse(self.editor._undo)

    def test_mixed_no_color_and_unconfirmed_or_raw_multi_reject_without_write(self):
        _, sources = self.inputs(uncolored=True)
        before = set(self.db.records)
        self.editor.correct_colors()
        self.assertIn('无色', self.editor.status.text())
        self.assertIsNone(self.editor._worker)
        self.editor._color_state['aligned'] = False
        self.editor.correct_colors()
        self.assertIn('坐标系', self.editor.status.text())
        self.editor._color_state['aligned'] = True
        self.db.records[sources[0]].kind = 'raw'
        self.editor.correct_colors()
        self.assertIn('先拼接', self.editor.status.text())
        self.db.records[sources[0]].kind = 'result'
        self.assertEqual(set(self.db.records), before)

    def test_busy_close_and_source_revision_gate(self):
        _, sources = self.inputs()
        before = set(self.db.records)
        entered, release = threading.Event(), threading.Event()
        from core.postprocess.color_correction import unify_colors
        def delayed(*args, **kwargs):
            entered.set(); release.wait(5)
            return unify_colors(*args, **kwargs)
        with patch('ui_v2.postprocess.window.unify_colors', delayed):
            self.editor.correct_colors()
            self.assertTrue(entered.wait(2))
            try:
                self.assertFalse(self.editor.actions['color'].isEnabled())
                with patch.object(self.editor, 'create_color_dialog') as create:
                    self.editor.open_color_dialog()
                    create.assert_not_called()
                self.editor.reject()
                self.assertFalse(self.editor._closed)
                self.db.records[sources[1]].revision += 1
            finally:
                release.set()
            self.wait(lambda: self.editor._worker is None)
        self.assertEqual(set(self.db.records), before)
        self.assertIn('来源', self.editor.status.text())
        directory = self.editor.directory
        self.editor.directory = Path(self.temp.name)/'other'
        self.editor.correct_colors()
        self.assertIn('项目', self.editor.status.text())
        self.editor.directory = directory


if __name__ == '__main__':
    unittest.main()
