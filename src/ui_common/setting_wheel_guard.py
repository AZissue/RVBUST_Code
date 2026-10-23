"""Keep scrolling over settings from changing combo/spin box values."""
from PySide6.QtCore import QObject, QEvent, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget, QComboBox, QAbstractSpinBox, QAbstractScrollArea, QSlider


def install_setting_wheel_guard(root):
    """Mark one widget subtree; share one filter across all window lifetimes."""
    root.setProperty('mccSettingWheelGuard', True)
    app = QApplication.instance()
    guard = getattr(app, '_mcc_setting_wheel_guard', None)
    if guard is None:
        guard = _SettingWheelGuard(app)
        app._mcc_setting_wheel_guard = guard
        app.installEventFilter(guard)
    return guard


class _SettingWheelGuard(QObject):
    """Protect existing and dynamically created controls under one window.

    Closed controls never step on wheel input, even when focused. Popup lists
    keep normal scrolling; otherwise the nearest enclosing panel scrolls.
    """
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel or not isinstance(watched, QWidget):
            return False
        control, protected = None, False
        ancestor = watched
        while ancestor is not None:
            if control is None and (isinstance(ancestor, (QComboBox, QAbstractSpinBox)) or
                                    isinstance(ancestor, QSlider) and ancestor.property('mccSettingSlider')):
                control = ancestor
            if ancestor.property('mccSettingWheelGuard'):
                protected = True
                break
            ancestor = ancestor.parentWidget()
        if not protected or control is None:
            return False
        if isinstance(control, QComboBox) and control.view().isVisible():
            return False
        container = control.parentWidget()
        while container is not None and not isinstance(container, QAbstractScrollArea):
            container = container.parentWidget()
        if container is not None:
            viewport = container.viewport()
            forwarded = QWheelEvent(
                QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                event.buttons(), event.modifiers(), event.phase(), event.inverted(),
                event.source(), event.pointingDevice())
            QApplication.sendEvent(viewport, forwarded)
        event.accept()
        return True
