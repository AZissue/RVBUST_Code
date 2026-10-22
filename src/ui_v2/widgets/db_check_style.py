"""DB component checkbox visuals, independent of preview and selection behavior."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle


DB_CHECK_QSS = '''
QWidget#frameDatabaseBrowser QTreeWidget::item { min-height:26px; }
QWidget#frameDatabaseBrowser QTreeWidget::indicator {
    width:18px; height:18px; margin-left:2px; margin-right:6px;
    border:0; background:transparent; image:none;
}
'''


def paint_component_check(painter, option, index, rect):
    if index.data(Qt.CheckStateRole) is None:
        return
    enabled = bool(option.state & QStyle.State_Enabled)
    checked = index.data(Qt.CheckStateRole) == Qt.Checked.value
    hovered = bool(option.state & QStyle.State_MouseOver)
    fill = '#C93E42' if checked else '#202124'
    border = '#E66A6D' if checked or hovered else '#777B84'
    if not enabled:
        fill, border = '#393B40', '#55585F'
    box = QRectF(rect.center().x() - 7.5, rect.center().y() - 7.5, 16, 16)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(fill))
    painter.setPen(QPen(QColor(border), 1.2))
    painter.drawRoundedRect(box, 3.5, 3.5)
    if checked:
        tick = QPainterPath()
        tick.moveTo(box.left() + 3.5, box.top() + 8)
        tick.lineTo(box.left() + 6.5, box.top() + 11)
        tick.lineTo(box.left() + 12.5, box.top() + 4.8)
        pen = QPen(QColor('#FFFFFF' if enabled else '#9A9DA3'), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(tick)
    painter.restore()
