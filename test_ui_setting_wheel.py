"""Wheel input scrolls panels instead of silently changing settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea, QComboBox, QSpinBox, QDoubleSpinBox
from ui_common.setting_wheel_guard import install_setting_wheel_guard
from ui_v2 import MainWindowShell


def wheel(widget, delta=-120):
    position = widget.rect().center()
    event = QWheelEvent(QPointF(position), QPointF(widget.mapToGlobal(position)),
                        QPoint(), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


class SettingWheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = QWidget()
        self.guard = install_setting_wheel_guard(self.root)
        root_layout = QVBoxLayout(self.root)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        root_layout.addWidget(self.scroll)
        body = QWidget()
        body.setMinimumHeight(1000)
        layout = QVBoxLayout(body)
        self.combo = QComboBox()
        self.combo.addItems([str(i) for i in range(60)])
        self.combo.setCurrentIndex(20)
        self.combo.setMaxVisibleItems(6)
        self.spin = QSpinBox()
        self.spin.setValue(50)
        self.double = QDoubleSpinBox()
        self.double.setValue(50)
        for control in (self.combo, self.spin, self.double):
            layout.addWidget(control)
        layout.addStretch(1)
        self.scroll.setWidget(body)
        self.root.resize(420, 260)
        self.root.show()
        self.app.processEvents()

    def tearDown(self):
        self.combo.hidePopup()
        self.root.close()
        self.root.deleteLater()
        self.app.processEvents()

    def test_closed_controls_and_spin_editors_keep_values_even_when_focused(self):
        combo_changed = QSignalSpy(self.combo.currentIndexChanged)
        spin_changed = QSignalSpy(self.spin.valueChanged)
        for target in (self.combo, self.spin, self.spin.lineEdit(), self.double, self.double.lineEdit()):
            for focused in (False, True):
                if focused:
                    target.setFocus()
                else:
                    target.clearFocus()
                self.scroll.verticalScrollBar().setValue(0)
                wheel(target)
                self.assertEqual(self.combo.currentIndex(), 20)
                self.assertEqual(self.spin.value(), 50)
                self.assertEqual(self.double.value(), 50)
                self.assertGreater(self.scroll.verticalScrollBar().value(), 0)
        self.assertEqual(combo_changed.count()+spin_changed.count(), 0)

    def test_popup_list_scroll_and_explicit_selection_still_work(self):
        self.combo.showPopup()
        self.app.processEvents()
        view = self.combo.view()
        bar = view.verticalScrollBar()
        bar.setValue(0)
        wheel(view.viewport(), -240)
        self.app.processEvents()
        self.assertGreater(bar.value(), 0)
        index = view.indexAt(QPoint(10, 12))
        self.assertTrue(index.isValid())
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.visualRect(index).center())
        self.assertEqual(self.combo.currentIndex(), index.row())
        self.combo.hidePopup()
        before = self.combo.currentIndex()
        QTest.keyClick(self.combo, Qt.Key_Down)
        self.assertEqual(self.combo.currentIndex(), before+1)
        QTest.keyClick(self.spin, Qt.Key_Up)
        self.assertEqual(self.spin.value(), 51)

    def test_unrelated_windows_are_not_intercepted(self):
        outside = QSpinBox()
        outside.setValue(50)
        wheel(outside)
        self.assertEqual(outside.value(), 49)
        outside.deleteLater()

    def test_main_window_protects_all_modes_and_keeps_canvas_zoom(self):
        win = MainWindowShell()
        try:
            self.assertIs(win._setting_wheel_guard, self.guard)
            win.show()
            for mode in ('multi_cam', 'mobile_chain', 'turntable'):
                win.set_mode(mode, [])
                win.set_presentation('industrial')
                workspace = win._stack.currentWidget()
                props = workspace._industrial.frame_browser.properties
                props.tabs.setCurrentIndex(1)
                self.app.processEvents()
                values = [props.view_preset.currentText(), props.quality.currentText(),
                          props.color_mode.currentText(), props.point_size.value()]
                for control in (props.view_preset, props.quality, props.color_mode, props.point_size):
                    control.setFocus()
                    wheel(control)
                self.assertEqual(values, [props.view_preset.currentText(), props.quality.currentText(),
                                          props.color_mode.currentText(), props.point_size.value()])
                panel = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
                canvas = panel.viewer().canvas
                before = canvas.zoom
                wheel(canvas)
                self.assertNotEqual(canvas.zoom, before)
        finally:
            win._dirty = False
            win.close()
            win.deleteLater()
            self.app.processEvents()
