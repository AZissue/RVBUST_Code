from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle


DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1
PREVIEW_ROLE = Qt.ItemDataRole.UserRole + 2


class ProjectCardDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = option.rect.adjusted(2, 3, -10, -9)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        surface = "#3f2c35" if selected else "#292f39" if hovered else "#252a33"
        outline = "#f38e99" if focused else "#aa616d" if selected else "#414955"
        painter.setBrush(QColor(surface))
        painter.setPen(QPen(QColor(outline)))
        painter.drawRoundedRect(card, 9, 9)

        preview_area = card.adjusted(9, 9, -9, -53)
        clip = QPainterPath()
        clip.addRoundedRect(preview_area.toRectF(), 5, 5)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(preview_area, QColor("#1b1e25"))
        preview = index.data(PREVIEW_ROLE)
        if preview is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(preview_area, preview, preview.rect())
        else:
            glyph = index.data(Qt.ItemDataRole.DecorationRole)
            if isinstance(glyph, QIcon):
                icon_rect = QRect(0, 0, 40, 40)
                icon_rect.moveCenter(preview_area.center())
                glyph.paint(painter, icon_rect)
        painter.restore()

        title = card.adjusted(10, card.height() - 47, -10, -24)
        detail = card.adjusted(10, card.height() - 24, -10, -5)
        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        text = painter.fontMetrics().elidedText(
            index.data(Qt.ItemDataRole.DisplayRole), Qt.TextElideMode.ElideRight, title.width()
        )
        painter.setPen(QColor("#eef0f4"))
        painter.drawText(title, alignment, text)
        font.setBold(False)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#abb4c1"))
        painter.drawText(detail, alignment, index.data(DETAIL_ROLE))
        painter.restore()
