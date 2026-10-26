"""Compact viewport segmentation tools and postprocess-only middle pan."""
from PySide6.QtCore import QObject, QEvent, Qt, QSize
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton
from ui_common.symbols import icon


class MiddlePan(QObject):
    """Reuse the renderer's right-drag pan without changing other workspaces."""
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        canvas.setProperty('postprocessMiddlePan', True)
        canvas.installEventFilter(self)

    def eventFilter(self, watched, event):
        kinds = (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease)
        if event.type() not in kinds or not (event.button() == Qt.MiddleButton or
                                             event.buttons() & Qt.MiddleButton):
            return False
        buttons = event.buttons() & ~Qt.MiddleButton
        if event.buttons() & Qt.MiddleButton:
            buttons |= Qt.RightButton
        button = Qt.RightButton if event.button() == Qt.MiddleButton else event.button()
        translated = QMouseEvent(event.type(), event.position(), event.globalPosition(),
                                 button, buttons, event.modifiers())
        handler = {QEvent.MouseButtonPress: self.canvas.mousePressEvent,
                   QEvent.MouseMove: self.canvas.mouseMoveEvent,
                   QEvent.MouseButtonRelease: self.canvas.mouseReleaseEvent}[event.type()]
        handler(translated)
        event.accept()
        return True


class SegmentationToolbar(QFrame):
    def __init__(self, canvas, callbacks):
        super().__init__(canvas)
        self.setObjectName('segmentationToolbar')
        self.setStyleSheet('QFrame#segmentationToolbar {background:#26282b; border:1px solid #555; border-radius:4px;}'
                          'QToolButton {padding:3px; border:1px solid transparent; border-radius:3px;}'
                          'QToolButton:hover {background:#474747; border-color:#777;}'
                          'QToolButton:checked {background:#633134; border-color:#b84444;}')
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(3)
        row.addWidget(QLabel('分割'))
        self.buttons = {}
        for key, title, glyph in (
                ('draw', '多边形框选：左键加顶点，Alt+左键撤点；中键拖动平移并重新框选', 'polygon'),
                ('close', '封闭多边形（至少3个顶点；也可右键或双击）', 'polygon_close'),
                ('back', '撤销最后一个顶点（Alt+左键）', 'undo'),
                ('inside', '保留框内点云；框外另存为DB分支', 'crop_inside'),
                ('outside', '保留框外点云；框内另存为DB分支', 'crop_outside'),
                ('cancel', '取消框选（Esc）', 'close')):
            button = QToolButton()
            button.setIcon(icon(glyph, '#dddddd', 21))
            button.setIconSize(QSize(21, 21))
            button.setFixedSize(30, 30)
            button.setToolTip(title)
            button.setAccessibleName(title.split('：')[0].split('（')[0])
            button.clicked.connect(callbacks[key])
            row.addWidget(button)
            self.buttons[key] = button
        self.buttons['draw'].setCheckable(True)
        self.setToolTip('左键画多边形 · 右键封闭 · 中键平移 · Esc取消；封闭后锁住视图，应用或取消后恢复。分割沿视线投影，不区分深度。')
        canvas.installEventFilter(self)
        self.adjustSize()
        self._position()
        self.show()

    def _position(self):
        self.move(max(4, self.parentWidget().width() - self.width() - 12), 12)
        self.raise_()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self._position()
        return False

    def refresh(self, *, ready, available, overlay, staged):
        self.buttons['draw'].setEnabled(ready and available)
        self.buttons['draw'].setChecked(overlay.active)
        self.buttons['close'].setEnabled(ready and overlay.active and not overlay.has_mask and overlay.vertex_count >= 3)
        self.buttons['back'].setEnabled(ready and overlay.active and not overlay.has_mask and overlay.vertex_count > 0)
        for key in ('inside', 'outside'):
            self.buttons[key].setEnabled(ready and staged)
        self.buttons['cancel'].setEnabled(overlay.active)
        self.raise_()
