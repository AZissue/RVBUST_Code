from PySide6.QtGui import QColor, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QProxyStyle, QStyle

from .icons import icon
from .window_frame import WindowsFrameTheme


class MetrixStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect and isinstance(widget, QAbstractButton):
            return
        if widget is not None and widget.objectName() == "objectTree":
            state = QStyle.StateFlag
            if element == QStyle.PrimitiveElement.PE_IndicatorBranch:
                if option.state & state.State_Children:
                    glyph = "expand" if option.state & state.State_Open else "collapse"
                    icon(glyph, 12).paint(painter, option.rect.adjusted(0, 0, -2, 0))
                return
            if element == QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck:
                checked = bool(option.state & state.State_On)
                painter.save()
                painter.setBrush(QColor("#973840" if checked else "#242629"))
                painter.setPen(QPen(QColor("#ce6c74" if checked else "#777e85")))
                rect = option.rect.adjusted(1, 1, -1, -1)
                painter.drawRoundedRect(rect, 3, 3)
                if checked:
                    icon("check", 11).paint(painter, rect.adjusted(1, 1, -1, -1))
                painter.restore()
                return
        super().drawPrimitive(element, option, painter, widget)


def configure_ui(app: QApplication) -> None:
    app.setStyle(MetrixStyle("Fusion"))
    palette = app.palette()
    role = QPalette.ColorRole
    for entry, color in (
        (role.Window, "#242424"), (role.WindowText, "#ece9e7"),
        (role.Base, "#1b1b1b"), (role.AlternateBase, "#292929"),
        (role.Text, "#e5e5e5"), (role.Button, "#303030"),
        (role.ButtonText, "#ece9e7"), (role.Highlight, "#67343b"),
        (role.HighlightedText, "#ffffff"), (role.PlaceholderText, "#a9a29e"),
        (role.ToolTipBase, "#28282a"), (role.ToolTipText, "#ece9e7"),
    ):
        palette.setColor(entry, QColor(color))
    for entry in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, entry, QColor("#828286"))
    app.setPalette(palette)
    app.setStyleSheet("QAbstractButton { outline: none; }")
    if app.platformName() == "windows" and app.findChild(WindowsFrameTheme) is None:
        app.installEventFilter(WindowsFrameTheme(app))
