"""Numeric setting with synchronized progress slider and precise input."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSlider, QSpinBox, QDoubleSpinBox


class ParameterSlider(QWidget):
    """Numeric editor; owns range, placeholder and slider/input synchronization.

    Consumers use value(), set_value(), set_range() and set_unloaded().
    The child widgets remain available for Qt signal wiring and focus handling.
    """
    def __init__(self, *, decimals=0, suffix='', parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setProperty('mccSettingSlider', True)
        self.slider.setMinimumWidth(45)
        self.spin = QDoubleSpinBox() if decimals else QSpinBox()
        if decimals:
            self.spin.setDecimals(decimals)
            self.spin.setSingleStep(.1)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(91)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self._decimals = decimals
        self.slider.valueChanged.connect(self._slide)
        self.spin.valueChanged.connect(self._sync)

    def set_range(self, low, high):
        self.spin.setRange(low, high)
        self.slider.setRange(0, min(100000, max(0, round((high-low)*10**self._decimals))))
        self._sync(self.spin.value())

    def value(self):
        return self.spin.value()

    def set_value(self, value):
        self.spin.setSpecialValueText('')
        self.spin.setValue(value)

    def set_unloaded(self):
        """Show an unknown value; the page controls whether editing is enabled."""
        self.set_range(0, 0)
        self.spin.setSpecialValueText('—')
        self.spin.setValue(0)

    def _sync(self, value):
        span = self.spin.maximum()-self.spin.minimum()
        with QSignalBlocker(self.slider):
            self.slider.setValue(round((value-self.spin.minimum()) / span * self.slider.maximum()) if span else 0)

    def _slide(self, value):
        steps = self.slider.maximum()
        number = self.spin.minimum() + (value / steps if steps else 0) * (self.spin.maximum()-self.spin.minimum())
        self.spin.setValue(number if self._decimals else round(number))
