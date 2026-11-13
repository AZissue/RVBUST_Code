import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from app import Workbench


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    # The Windows offscreen backend does not enumerate system fonts itself.
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    win = Workbench()
    win.show()
    app.processEvents()
    yield win
    win.timer.stop()
    win.flow.active = None
    win.close()


def prepare(win):
    win.tree.topLevelItem(0).setCheckState(1, Qt.Checked)
    win.tree.topLevelItem(1).setCheckState(1, Qt.Checked)
    win.pages.setCurrentIndex(1)


def test_complete_ui_cycle_and_independent_visibility(window):
    prepare(window)
    window.tree.topLevelItem(0).setCheckState(2, Qt.Unchecked)
    assert len(window.flow.inputs) == 2
    window.primary.click()
    assert window.flow.busy
    for _ in range(8):
        window.tick()
    assert window.flow.can_publish
    assert not window.primary.isEnabled()
    window.review.setChecked(True)
    window.primary.click()
    assert len(window.flow.results) == 1
    assert window.tree.topLevelItemCount() == 4
    assert window.flow.selected == '演练结果 001'


def test_back_keeps_draft_and_candidate_invalidation(window):
    prepare(window)
    window.parameter.setValue(2.5)
    window.back_button.click()
    window.pages.setCurrentIndex(1)
    assert window.parameter.value() == 2.5
    window.primary.click()
    for _ in range(8):
        window.tick()
    window.review.setChecked(True)
    window.parameter.setValue(3)
    assert not window.review.isChecked()
    assert not window.flow.can_publish


def test_focus_keeps_stop_and_close_waits(window):
    prepare(window)
    window.primary.click()
    window.toggle_focus()
    QApplication.processEvents()
    assert not window.right.isVisible()
    assert window.stop_button.isVisible()
    assert not window.close()
    window.stop_button.click()
    assert window.flow.busy
    window.tick()
    assert not window.flow.busy


@pytest.mark.parametrize('size', [(1366, 768), (1600, 1000), (1920, 1080)])
def test_layout(size, window):
    window.resize(*size)
    prepare(window)
    QApplication.processEvents()
    assert window.primary.isVisible()
    assert window.primary.width() >= 200
    assert window.right.rect().contains(window.primary.geometry().bottomRight())
    assert window.centralWidget().width() <= size[0]
    if size == (1366, 768):
        dest = Path(__file__).resolve().parents[1] / 'artifacts'
        dest.mkdir(exist_ok=True)
        assert window.grab().save(str(dest / 'workbench-1366.png'))
