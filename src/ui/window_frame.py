from ctypes import byref, sizeof, wintypes
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget


class WindowsFrameTheme(QObject):
    def __init__(self, app):
        super().__init__(app)
        from ctypes import WinDLL

        self.set_attribute = WinDLL("dwmapi").DwmSetWindowAttribute
        self.set_attribute.argtypes = (
            wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD,
        )
        self.set_attribute.restype = wintypes.LONG
        self.supports_frame_colors = sys.getwindowsversion().build >= 22000

    def eventFilter(self, widget, event):
        if (
            event.type() == QEvent.Type.Show
            and isinstance(widget, QWidget)
            and widget.isWindow()
            and widget.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog)
        ):
            self.apply(int(widget.winId()))
        return False

    def apply(self, hwnd):
        # Windows 10 supports the dark frame, while Windows 11 also exposes its colors.
        dark = wintypes.BOOL(True)
        self.set_attribute(hwnd, 20, byref(dark), sizeof(dark))
        if self.supports_frame_colors:
            for attribute, color in (
                (34, 0x44403D),  # Border, COLORREF (BGR)
                (35, 0x242424),  # Caption
                (36, 0xF0ECE9),  # Title text
            ):
                value = wintypes.DWORD(color)
                self.set_attribute(hwnd, attribute, byref(value), sizeof(value))
