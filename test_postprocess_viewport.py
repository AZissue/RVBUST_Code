"""Postprocess-only navigation and viewport segmentation command regression."""
import unittest
import threading
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt, QEvent, QPointF, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import test_postprocess as fixture


class ViewportTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp = fixture.PostprocessTests.setUp
    tearDown = fixture.PostprocessTests.tearDown
    wait = fixture.PostprocessTests.wait
    source = fixture.PostprocessTests.source
    finish = fixture.PostprocessTests.finish
    load_grid = fixture.PostprocessTests.load_grid

    def send_drag(self, target, button=Qt.MiddleButton):
        for kind, pos, pressed, buttons in (
                (QEvent.MouseButtonPress, (100, 150), button, button),
                (QEvent.MouseMove, (145, 180), Qt.NoButton, button),
                (QEvent.MouseButtonRelease, (145, 180), button, Qt.NoButton)):
            point = QPointF(*pos)
            event = QMouseEvent(kind, point, point, pressed, buttons, Qt.NoModifier)
            QApplication.sendEvent(target, event)

    def test_middle_click_uses_native_pivot_in_editor_and_main_without_jump(self):
        self.load_grid()
        from core.postprocess.processing import ortho_project
        main_canvas = self.win.workspace_multi().viewer().viewer().canvas
        for canvas in (self.editor.viewer.canvas, main_canvas):
            with self.subTest(canvas=type(canvas).__name__):
                center, pan, rotation = canvas.center.copy(), canvas.pan.copy(), canvas.rotation.matrix.copy()
                point = center + [1., 2., 3.]
                def projection():
                    return ortho_project(np.array([center, point]), center=canvas.center,
                        rotation_matrix=canvas.rotation.matrix, extent=canvas.extent,
                        zoom=canvas.zoom, pan=canvas.pan, width=canvas.width(), height=canvas.height())[0]
                before = projection()
                with patch.object(canvas, 'pick_pivot', return_value=point) as pick, \
                        patch.object(canvas, 'set_pivot', wraps=canvas.set_pivot) as pivot:
                    QTest.mouseClick(canvas, Qt.MiddleButton, pos=QPoint(200, 220))
                    pick.assert_called_once()
                    pivot.assert_called_once()
                np.testing.assert_array_equal(canvas.center, point)
                np.testing.assert_allclose(projection(), before)
                np.testing.assert_array_equal(canvas.rotation.matrix, rotation)
                self.assertEqual(canvas._drag_button, Qt.NoButton)
                center, pan = canvas.center.copy(), canvas.pan.copy()
                with patch.object(canvas, 'pick_pivot', return_value=None), \
                        patch.object(canvas, 'set_pivot', wraps=canvas.set_pivot) as pivot:
                    self.send_drag(canvas)
                    pivot.assert_not_called()
                np.testing.assert_array_equal(canvas.center, center)
                np.testing.assert_array_equal(canvas.pan, pan)
                np.testing.assert_array_equal(canvas.rotation.matrix, rotation)

    def test_drawing_forwards_middle_pick_and_discards_stale_polygon(self):
        self.load_grid()
        self.editor.start_polygon()
        overlay = self.editor.overlay
        QTest.mouseClick(overlay, Qt.LeftButton, pos=QPoint(100, 100))
        self.assertEqual(overlay.vertex_count, 1)
        canvas = self.editor.viewer.canvas
        point = canvas.center + [1, 1, 1]
        with patch.object(canvas, 'pick_pivot', return_value=point) as pick:
            QTest.mouseClick(overlay, Qt.MiddleButton, pos=QPoint(200, 200))
            pick.assert_called_once()
        np.testing.assert_array_equal(canvas.center, point)
        self.assertFalse(overlay.active)
        self.assertIsNone(self.editor._segment)
        self.assertFalse(self.editor.segment_tools.buttons['delete'].isEnabled())
        self.assertFalse(self.editor._closed)

    def test_top_parameters_and_pure_properties_at_both_sizes(self):
        from PySide6.QtWidgets import QDialog, QGroupBox
        from PySide6.QtCore import QSignalBlocker
        raw, source, _ = self.load_grid()
        editor = self.editor
        self.assertIs(editor.properties, editor.source_browser.properties)
        self.assertEqual([editor.properties.tabs.tabText(i) for i in range(editor.properties.tabs.count())],
                         ['数据属性', '3D 显示'])
        self.assertFalse(hasattr(editor, 'params'))
        self.assertFalse(any(group.title() in ('下采样', '外部文件')
                             for group in editor.findChildren(QGroupBox)))
        self.assertNotIn('voxel', editor.actions)
        self.assertNotIn('random', editor.actions)
        self.assertIsNone(editor.actions['downsample'].menu())
        self.assertEqual(editor.actions['downsample'].text(), '下采样')
        self.assertFalse(hasattr(editor, 'processing_menus'))
        self.assertFalse(hasattr(editor, 'processing_panels'))
        for key in ('open', 'color', 'downsample'):
            self.assertIsNone(editor.actions[key].menu())
        for width, height in ((1440, 900), (1050, 650)):
            editor.resize(width, height); self.app.processEvents()
            positions = []
            for button in editor.actions.values():
                self.assertTrue(button.isVisible())
                rect = button.geometry()
                self.assertTrue(editor.operation_bar.rect().contains(rect))
                positions.append(rect)
            for i, rect in enumerate(positions):
                for other in positions[i+1:]:
                    self.assertFalse(rect.intersects(other))
            from PySide6.QtCore import QTimer
            observed = []
            def cancel():
                dialog = self.app.activeModalWidget()
                observed.append((dialog.file_unit.isVisible(), dialog.execute_button.isVisible()))
                dialog.reject()
            QTimer.singleShot(0, cancel)
            editor.actions['open'].click()
            self.assertEqual(observed, [(True, True)])
            dialog = editor.create_downsample_dialog()
            self.assertIsInstance(dialog, QDialog)
            self.assertFalse(dialog.isVisible())
            self.assertEqual(dialog.voxel.value(), 2)
            self.assertEqual(dialog.ratio.value(), 50)
            self.assertEqual(dialog.execute_button.text(), '执行下采样')
            self.assertEqual(dialog.cancel_button.text(), '取消')
            dialog.close()
        editor.downsample('voxel', 3); self.finish()
        result = editor._display_ids[0]
        self.assertEqual(self.db.records[result].points, 16)
        self.assertEqual(editor.properties.values['有效点数'], '16')
        editor.downsample('random', 25); self.finish()
        result = editor._display_ids[0]
        self.assertEqual(self.db.records[result].points, 4)
        browser = editor.source_browser
        for item, expected_type in ((browser._items[raw], '原始帧'),
                (browser._items[source], '拼接结果'),
                (browser._component_items[result, 'cloud'], '后处理点云'),
                (browser._items[result].parent(), '数据分组')):
            with QSignalBlocker(browser.tree):
                browser.tree.setCurrentItem(item)
            browser._selection_changed()
            self.assertEqual(editor.properties.values['类型'], expected_type)
        browser.clear_highlight()
        self.assertIn('提示', editor.properties.values)
        gate = threading.Event()
        editor._run(lambda: gate.wait(3), lambda _: None)
        try:
            self.assertFalse(editor.actions['open'].isEnabled())
            self.assertFalse(editor.actions['downsample'].isEnabled())
        finally:
            gate.set()
        self.finish()
        self.assertTrue(editor.actions['open'].isEnabled())
        self.assertIn(raw, self.db.records)
        editor.load_selected([]); self.finish()
        self.assertFalse(editor.actions['downsample'].isEnabled())

    def test_all_parameter_dialogs_cancel_escape_close_without_leaks_or_work(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog, QToolButton
        from shiboken6 import isValid
        self.load_grid()
        editor = self.editor
        index = (self.db.directory/'index.json').read_bytes()
        display, undo = list(editor._display_ids), list(editor._undo)
        for key in ('open', 'color', 'downsample'):
            self.assertIsNone(editor.actions[key].menu())
            self.assertEqual(editor.actions[key].popupMode(), QToolButton.DelayedPopup)
            for exit_kind in ('cancel', 'escape', 'close', 'cancel'):
                seen = []
                def cancel():
                    dialog = self.app.activeModalWidget()
                    seen.append(dialog)
                    self.assertIsInstance(dialog, QDialog)
                    self.assertTrue(dialog.cancel_button.isDefault())
                    if key == 'open':
                        dialog.file_unit.setCurrentIndex(1)
                    elif key == 'color':
                        dialog.color_strength.setValue(70)
                    if exit_kind == 'escape':
                        QTest.keyClick(dialog, Qt.Key_Escape)
                    elif exit_kind == 'close':
                        dialog.close()
                    else:
                        dialog.cancel_button.click()
                QTimer.singleShot(0, cancel)
                editor.actions[key].click()
                self.app.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()
                self.assertEqual(len(seen), 1)
                self.assertFalse(isValid(seen[0]))
                self.assertIs(self.app.activeModalWidget(), editor)
                self.assertIsNone(editor._worker)
                self.assertEqual(editor._display_ids, display)
                self.assertEqual(editor._undo, undo)
                self.assertEqual((self.db.directory/'index.json').read_bytes(), index)
        self.assertEqual(editor._import_unit, 'm')
        self.assertEqual(editor._color_state['strength'], .7)
        # Accepting parameters still does nothing if the file chooser is cancelled.
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().execute_button.click())
        with patch('ui_v2.postprocess.window.QFileDialog.getOpenFileName', return_value=('', '')):
            editor.actions['open'].click()
        self.assertIsNone(editor._worker)
        self.assertEqual((self.db.directory/'index.json').read_bytes(), index)

    def test_import_snapshot_rechecks_after_parameters_and_file_chooser(self):
        from PySide6.QtCore import QTimer
        self.load_grid()
        editor = self.editor
        index = (self.db.directory/'index.json').read_bytes()
        def changed():
            dialog = self.app.activeModalWidget()
            editor._active_uid = None
            dialog.execute_button.click()
        QTimer.singleShot(0, changed)
        with patch('ui_v2.postprocess.window.QFileDialog.getOpenFileName') as chooser:
            editor.actions['open'].click()
            chooser.assert_not_called()
        self.assertIn('变化', editor.status.text())
        def choose_changed(*args):
            editor._display_ids.clear()
            return ('will-not-read.ply', '')
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().execute_button.click())
        with patch('ui_v2.postprocess.window.QFileDialog.getOpenFileName', side_effect=choose_changed):
            editor.actions['open'].click()
        self.assertIn('变化', editor.status.text())
        self.assertIsNone(editor._worker)
        self.assertEqual((self.db.directory/'index.json').read_bytes(), index)

    def test_downsample_modal_accept_cancel_memory_and_default_direct_call(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog
        _, source, _ = self.load_grid()
        editor = self.editor
        observed = []
        def execute():
            dialog = self.app.activeModalWidget()
            observed.append((isinstance(dialog, QDialog), dialog.inputs.text(), dialog.summary.text()))
            dialog.voxel.setValue(3)
            dialog.execute_button.click()
        QTimer.singleShot(0, execute)
        editor.actions['downsample'].click()
        self.finish()
        result = editor._display_ids[0]
        self.assertTrue(observed[0][0])
        self.assertIn('100 点', observed[0][1])
        self.assertIn('结果点数以下采样计算为准', observed[0][2])
        self.assertEqual(self.db.records[result].points, 16)
        self.assertEqual(self.db.records[result].source_ids, [source])
        self.assertIn(source, self.db.records)
        self.assertIn('已自动新增', editor.status.text())
        editor.undo(); self.finish()
        self.assertEqual(editor._display_ids, [source])

        before_records = set(self.db.records)
        before_display = list(editor._display_ids)
        before_undo = len(editor._undo)
        before_status = editor.status.text()
        cancelled = []
        def cancel():
            dialog = self.app.activeModalWidget()
            cancelled.append(dialog)
            dialog.voxel.setValue(3)
            dialog.method.setCurrentIndex(dialog.method.findData('random'))
            dialog.ratio.setValue(25)
            dialog.cancel_button.click()
        QTimer.singleShot(0, cancel)
        editor.actions['downsample'].click()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        from shiboken6 import isValid
        self.assertFalse(isValid(cancelled[0]))
        self.assertEqual(set(self.db.records), before_records)
        self.assertEqual(editor._display_ids, before_display)
        self.assertEqual(len(editor._undo), before_undo)
        self.assertEqual(editor.status.text(), before_status)
        self.assertIsNone(editor._worker)
        remembered = editor.create_downsample_dialog()
        self.assertEqual(remembered.method.currentData(), 'random')
        self.assertEqual(remembered.voxel.value(), 3)
        self.assertEqual(remembered.ratio.value(), 25)
        remembered.deleteLater()
        editor.downsample('random'); self.finish()
        self.assertEqual(self.db.records[editor._display_ids[0]].points, 50)

    def test_downsample_dialog_validation_and_numeric_input_guards(self):
        from PySide6.QtGui import QWheelEvent
        self.load_grid()
        editor = self.editor
        dialog = editor.create_downsample_dialog()
        dialog.show(); self.app.processEvents()
        before_records = set(self.db.records)
        before_undo = len(editor._undo)
        dialog.method.setCurrentIndex(dialog.method.findData('random'))
        self.assertFalse(dialog.voxel.isEnabled())
        self.assertTrue(dialog.ratio.isEnabled())
        dialog.ratio.setValue(.1)
        self.assertIn('预计输出：0 点', dialog.summary.text())
        self.assertIn('请提高随机保留比例', dialog.validation.text())
        self.assertFalse(dialog.execute_button.isEnabled())
        self.assertIsNone(editor._worker)
        self.assertEqual(set(self.db.records), before_records)
        self.assertEqual(len(editor._undo), before_undo)
        dialog.ratio.setValue(25)
        self.assertTrue(dialog.execute_button.isEnabled())
        self.assertIn('预计输出：25 点', dialog.summary.text())
        dialog.method.setFocus()
        original = dialog.ratio.value()
        event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, -120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        self.app.sendEvent(dialog.ratio, event)
        QTest.keyClick(dialog.ratio, Qt.Key_Down)
        self.assertEqual(dialog.ratio.value(), original)
        dialog.ratio.setFocus()
        QTest.keyClick(dialog.ratio, Qt.Key_Up)
        self.assertEqual(dialog.ratio.value(), original + 1)
        self.assertIn('预计输出：26 点', dialog.summary.text())
        dialog.method.setCurrentIndex(dialog.method.findData('voxel'))
        self.assertTrue(dialog.voxel.isEnabled())
        self.assertFalse(dialog.ratio.isEnabled())
        dialog.method.setFocus()
        original = dialog.voxel.value()
        self.app.sendEvent(dialog.voxel, event)
        QTest.keyClick(dialog.voxel, Qt.Key_Up)
        self.assertEqual(dialog.voxel.value(), original)
        dialog.voxel.setFocus()
        QTest.keyClick(dialog.voxel, Qt.Key_Up)
        self.assertAlmostEqual(dialog.voxel.value(), original + .1)
        self.assertIn(f'{original + .1:.1f} mm', dialog.summary.text())
        dialog.cancel_button.click()
        self.assertIsNone(editor._worker)
        self.assertEqual(set(self.db.records), before_records)

    def test_renderer_fallback_keeps_native_navigation_and_scoped_display_options(self):
        self.load_grid()
        viewer = self.editor.viewer
        old = viewer.canvas
        # Exercise the production fallback path with a software source canvas;
        # no GPU context or physical device is claimed by this offline test.
        with patch.object(old, 'render_failed', object(), create=True):
            viewer._fallback('offline forced fallback')
        self.app.processEvents()
        canvas = viewer.canvas
        self.assertIsNot(old, canvas)
        self.assertIs(self.editor.properties._renderer, viewer)
        self.assertTrue(self.editor.properties.options['marker_centers'].isHidden())
        main = self.browser.properties
        self.assertFalse(main.options['marker_centers'].isHidden())
        for properties in (main, self.editor.properties):
            for name in ('grid', 'axes'):
                option = properties.options[name]
                option.setChecked(not option.isChecked())
                self.assertEqual(properties._renderer.display_actions[name].isChecked(), option.isChecked())
        option = main.options['marker_centers']
        option.setChecked(not option.isChecked())
        self.assertEqual(main._renderer.display_actions['marker_centers'].isChecked(), option.isChecked())
        before = canvas.center.copy()
        with patch.object(canvas, 'pick_pivot', return_value=before + 1) as pick:
            QTest.mouseClick(canvas, Qt.MiddleButton, pos=QPoint(200, 200))
            pick.assert_called_once()
        np.testing.assert_allclose(canvas.center, before + 1)
        pan, rotation = canvas.pan.copy(), canvas.rotation.matrix.copy()
        self.send_drag(canvas, Qt.RightButton)
        np.testing.assert_allclose(canvas.pan-pan, [45, 30])
        np.testing.assert_array_equal(canvas.rotation.matrix, rotation)
        self.send_drag(canvas, Qt.LeftButton)
        self.assertFalse(np.allclose(canvas.rotation.matrix, rotation))
        self.assertIn('中键设旋转中心', self.editor.segment_tools.toolTip())
        self.assertNotIn('中键平移', self.editor.segment_tools.toolTip())

    def test_toolbar_close_keep_inside_and_undo_updates_db(self):
        _, source, _ = self.load_grid()
        tools = self.editor.segment_tools
        self.assertNotIn('draw', tools.buttons)
        self.assertEqual(self.editor.actions['select'].text(), '多边形框选')
        self.editor.actions['select'].click()
        self.assertTrue(self.editor.actions['select'].isChecked())
        self.assertFalse(tools.buttons['close'].isEnabled())
        overlay = self.editor.overlay
        w, h = overlay.width(), overlay.height()
        for point in (QPoint(1, 90), QPoint(w-2, 90), QPoint(w-2, h-2), QPoint(1, h-2)):
            QTest.mouseClick(overlay, Qt.LeftButton, pos=point)
        self.assertTrue(tools.buttons['back'].isEnabled())
        tools.buttons['back'].click()
        self.assertEqual(overlay.vertex_count, 3)
        QTest.mouseClick(overlay, Qt.LeftButton, pos=QPoint(1, h-2))
        tools.buttons['close'].click()
        self.finish()
        self.assertTrue(tools.buttons['inside'].isEnabled())
        self.assertTrue(tools.buttons['outside'].isEnabled())
        tools.buttons['inside'].click()
        self.assertTrue(tools.buttons['inside'].isChecked())
        tools.buttons['delete'].click()
        self.finish()
        result = self.editor._display_ids[0]
        self.assertNotEqual(source, result)
        self.assertIn(source, self.db.records)
        self.editor.undo(); self.finish()
        self.assertEqual(self.editor._display_ids, [source])

    def test_quick_delete_directions_preserve_points_colors_and_source(self):
        _, source, _ = self.load_grid()
        original = self.editor._clouds[source]
        path = self.db.directory / 'frames' / source / 'pointmap.ply'
        before = path.read_bytes()
        mask = np.arange(100) < 40
        for inside, count in ((True, 40), (False, 60)):
            with self.subTest(inside=inside):
                original = self.editor._clouds[source]
                self.editor._segment = (source, original, mask, self.editor._view())
                self.editor._refresh_controls()
                tools = self.editor.segment_tools
                tools.buttons['inside' if inside else 'outside'].click()
                self.assertEqual(tools.buttons['inside'].isChecked(), inside)
                self.assertEqual(tools.buttons['outside'].isChecked(), not inside)
                self.assertEqual(len(self.db.records), 2)  # Direction alone never applies.
                tools.buttons['delete'].click()
                self.finish()
                outputs = self.editor._undo[-1][0]
                layers = self.editor._read_records(self.editor.directory, outputs)
                self.assertEqual([len(p.points) for p in layers], [count, 100-count])
                keep = mask if inside else ~mask
                np.testing.assert_array_equal(layers[0].points, original.points[keep])
                np.testing.assert_array_equal(layers[0].colors, original.colors[keep])
                np.testing.assert_array_equal(layers[1].points, original.points[~keep])
                np.testing.assert_array_equal(layers[1].colors, original.colors[~keep])
                self.assertEqual(self.editor._display_ids, [outputs[0][0]])
                self.assertEqual(path.read_bytes(), before)
                self.assertIn('原始数据保留', self.editor.status.text())
                self.editor.undo()
                self.finish()
                self.assertEqual(self.editor._display_ids, [source])

    def test_quick_delete_empty_branches_and_derived_undo_gate(self):
        _, source, _ = self.load_grid()
        layer = self.editor._clouds[source]
        self.editor._segment = (source, layer, np.zeros(100, bool), self.editor._view())
        self.editor.apply_segment(True)
        self.assertIn('为空', self.editor.status.text())
        self.assertEqual(len(self.db.records), 2)
        self.editor._segment = (source, layer, np.ones(100, bool), self.editor._view())
        self.editor._refresh_controls()
        self.editor.segment_tools.buttons['delete'].click()
        self.finish()
        self.assertEqual(len(self.editor._undo[-1][0]), 1)
        output = self.editor._display_ids[0]
        self.db.publish_result(fixture.cloud([[0, 0, 1]]), [output], postprocess=True)
        before = set(self.db.records)
        self.editor.undo()
        self.wait(lambda: self.editor._worker is None)
        self.assertIn('已有派生数据', self.editor.status.text())
        self.assertEqual(set(self.db.records), before)

    def test_quick_delete_busy_source_and_project_guards(self):
        _, source, _ = self.load_grid()
        layer = self.editor._clouds[source]
        self.assertFalse(self.editor.segment_tools.buttons['delete'].isEnabled())
        self.editor._segment = (source, layer, np.arange(100) < 40, self.editor._view())
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            self.editor._refresh_controls()
            self.assertFalse(self.editor.segment_tools.buttons['delete'].isEnabled())
            self.editor.apply_segment(True)
        self.assertEqual(len(self.db.records), 2)
        self.db.records[source].revision += 1
        self.editor._refresh_controls()
        self.assertFalse(self.editor.segment_tools.buttons['delete'].isEnabled())
        self.editor.apply_segment(True)
        self.wait(lambda: self.editor._worker is None)
        self.assertIn('来源', self.editor.status.text())
        self.assertEqual(len(self.db.records), 2)

    def test_renderer_tools_reinstall_keeps_top_entry_and_callbacks(self):
        self.load_grid()
        button = self.editor.actions['select']
        # Reinstall on the current canvas, as the renderer-switch callback does.
        self.editor.segment_tools.deleteLater()
        self.editor._renderer_changed()
        self.assertIs(self.editor.actions['select'], button)
        self.assertNotIn('draw', self.editor.segment_tools.buttons)
        button.click()
        self.assertTrue(self.editor.overlay.active)
        self.editor.segment_tools.buttons['cancel'].click()
        self.assertFalse(self.editor.overlay.active)

    def test_tools_anchor_resize_and_escape_cancels_without_closing(self):
        self.load_grid()
        for width, height in ((1440, 900), (1050, 650)):
            self.editor.resize(width, height); self.app.processEvents()
            tools = self.editor.segment_tools
            canvas = self.editor.viewer.canvas
            self.assertEqual(tools.y(), 12)
            self.assertLessEqual(tools.geometry().right(), canvas.width()-8)
            self.assertIs(canvas.childAt(tools.geometry().center()), tools.childAt(tools.rect().center()) or tools)
        self.editor.actions['select'].click()
        QTest.keyClick(self.editor, Qt.Key_Escape)
        self.assertFalse(self.editor.overlay.active)
        self.assertFalse(self.editor._closed)

    def test_confirmed_mask_calculation_locks_middle_pick_until_cancel(self):
        self.load_grid()
        entered, release = threading.Event(), threading.Event()
        def delayed(points, polygon, **view):
            entered.set()
            release.wait(4)
            return np.ones(len(points), dtype=bool)
        with patch('ui_v2.postprocess.window.polygon_crop_mask', delayed):
            self.editor.stage_polygon([(10, 10), (500, 10), (500, 500)])
            self.assertTrue(entered.wait(2))
            try:
                canvas = self.editor.viewer.canvas
                before = canvas.center.copy()
                with patch.object(canvas, 'pick_pivot', return_value=before + 1) as pick:
                    for target in (canvas, self.editor.overlay):
                        QTest.mouseClick(target, Qt.MiddleButton, pos=QPoint(200, 200))
                    pick.assert_not_called()
                np.testing.assert_array_equal(canvas.center, before)
                self.assertTrue(self.editor.segment_tools.buttons['cancel'].isEnabled())
                self.editor.segment_tools.buttons['cancel'].click()
            finally:
                release.set()
            self.finish()
        self.assertIsNone(self.editor._segment)
        self.assertFalse(self.editor.overlay.active)
        self.assertFalse(self.editor.segment_tools.buttons['delete'].isEnabled())
        with patch.object(canvas, 'pick_pivot', return_value=before + 1) as pick:
            QTest.mouseClick(canvas, Qt.MiddleButton, pos=QPoint(200, 200))
            pick.assert_called_once()
        np.testing.assert_allclose(canvas.center, before + 1)


if __name__ == '__main__':
    unittest.main()
