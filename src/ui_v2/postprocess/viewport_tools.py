"""Compact viewport segmentation tools."""
from PySide6.QtCore import QEvent, Qt, QSize
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QButtonGroup
from ui_common.symbols import icon


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
        self.keep_direction = QButtonGroup(self)
        self.keep_direction.setExclusive(True)
        for key, title, glyph in (
                ('close', '封闭多边形（至少3个顶点；也可右键或双击）', 'polygon_close'),
                ('back', '撤销最后一个顶点（Alt+左键）', 'undo'),
                ('inside', '保留框内：快捷删除框外；框外仍保存为DB分支', 'crop_inside'),
                ('outside', '保留框外：快捷删除框内；框内仍保存为DB分支', 'crop_outside'),
                ('delete', '快捷删除：保留框内时删除框外，保留框外时删除框内；原始数据保留', 'trash'),
                ('cancel', '取消框选（Esc）', 'close')):
            button = QToolButton()
            button.setIcon(icon(glyph, '#dddddd', 21))
            button.setIconSize(QSize(21, 21))
            button.setFixedSize(30, 30)
            button.setToolTip(title)
            button.setAccessibleName(title.split('：')[0].split('（')[0])
            if key in ('inside', 'outside', 'delete'):
                button.setText(title.split('：')[0])
                button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                button.setFixedWidth(96)
            if key in ('inside', 'outside'):
                button.setCheckable(True)
                self.keep_direction.addButton(button)
            else:
                button.clicked.connect(callbacks[key])
            row.addWidget(button)
            self.buttons[key] = button
        self.buttons['inside'].setChecked(True)
        self.setToolTip('左键画多边形 · 右键封闭 · 中键设旋转中心 · Esc取消；封闭后锁住视图，应用或取消后恢复。分割沿视线投影，不区分深度。')
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
        self.buttons['close'].setEnabled(ready and overlay.active and not overlay.has_mask and overlay.vertex_count >= 3)
        self.buttons['back'].setEnabled(ready and overlay.active and not overlay.has_mask and overlay.vertex_count > 0)
        for key in ('inside', 'outside'):
            self.buttons[key].setEnabled(ready and available)
        self.buttons['delete'].setEnabled(ready and staged and available)
        self.buttons['cancel'].setEnabled(overlay.active)
        self.raise_()
