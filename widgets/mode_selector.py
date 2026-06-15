"""
模式选择组件。
包含两组互斥切换按钮：标定模式（眼在手外/眼在手上）和标定类型（标记物/戳点）。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QButtonGroup, QSizePolicy,
)

import resources as res


class ModeSelector(QWidget):
    """模式选择器：两组互斥按钮组"""

    # 模式变化信号：eye_in_hand(是否眼在手上), marker_type(是否标记物标定)
    mode_changed = pyqtSignal(bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(f"background-color: {res.BG_MAIN};")

        # 默认状态：眼在手上 + 标记物标定
        self._eye_in_hand = True
        self._marker_type = True

        # 水平布局，元素间距 48px
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(48)

        # ── 第一组：标定模式（眼在手外 / 眼在手上）──
        mode_label = QLabel("标定模式：")
        mode_label.setStyleSheet(
            f"font-size: {res.FONT_BODY}px; color: {res.TEXT_BODY}; "
            f"font-weight: 500; border: none;"
        )
        layout.addWidget(mode_label)

        # QButtonGroup 实现互斥选择（同一时间只能选一个）
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self._btn_eye_to_hand = self._create_toggle("眼在手外", False)
        self._btn_eye_in_hand = self._create_toggle("眼在手上", True)
        self._mode_group.addButton(self._btn_eye_to_hand, 0)
        self._mode_group.addButton(self._btn_eye_in_hand, 1)
        layout.addWidget(self._btn_eye_to_hand)
        layout.addWidget(self._btn_eye_in_hand)

        layout.addSpacing(48)

        # ── 第二组：标定类型（标记物标定 / 戳点标定）──
        type_label = QLabel("标定类型：")
        type_label.setStyleSheet(
            f"font-size: {res.FONT_BODY}px; color: {res.TEXT_BODY}; "
            f"font-weight: 500; border: none;"
        )
        layout.addWidget(type_label)

        self._type_group = QButtonGroup(self)
        self._type_group.setExclusive(True)

        self._btn_marker = self._create_toggle("标记物标定", True)
        self._btn_tcp = self._create_toggle("戳点标定", False)
        self._type_group.addButton(self._btn_marker, 0)
        self._type_group.addButton(self._btn_tcp, 1)
        layout.addWidget(self._btn_marker)
        layout.addWidget(self._btn_tcp)

        layout.addStretch()

        # 连接按钮点击信号
        self._mode_group.buttonClicked[int].connect(self._on_mode_changed)
        self._type_group.buttonClicked[int].connect(self._on_type_changed)

    def _create_toggle(self, text, selected):
        """
        创建一个可切换状态的按钮。
        text: 按钮文字
        selected: 是否为默认选中状态
        """
        btn = QPushButton(text)
        btn.setCheckable(True)       # 可切换选中/未选中
        btn.setChecked(selected)     # 设置默认状态
        btn.setFixedHeight(32)
        btn.setMinimumWidth(80)
        self._update_toggle_style(btn, selected)
        return btn

    def _update_toggle_style(self, btn, selected):
        """
        更新按钮样式。
        选中态：蓝色填充白色文字（天蓝色主题主色）
        未选中态：灰色背景深色文字
        """
        if selected:
            btn.setStyleSheet(res.toggle_selected_style())
        else:
            btn.setStyleSheet(res.toggle_unselected_style())

    def _on_mode_changed(self, id_):
        """标定模式切换回调：id_=0 表示眼在手外，id_=1 表示眼在手上"""
        self._eye_in_hand = (id_ == 1)
        # 更新两个按钮的选中/未选中样式
        self._update_toggle_style(self._btn_eye_to_hand, id_ == 0)
        self._update_toggle_style(self._btn_eye_in_hand, id_ == 1)
        self.mode_changed.emit(self._eye_in_hand, self._marker_type)

    def _on_type_changed(self, id_):
        """标定类型切换回调：id_=0 表示标记物标定，id_=1 表示戳点标定"""
        self._marker_type = (id_ == 0)
        self._update_toggle_style(self._btn_marker, id_ == 0)
        self._update_toggle_style(self._btn_tcp, id_ == 1)
        self.mode_changed.emit(self._eye_in_hand, self._marker_type)

    def current_mode(self):
        """返回当前模式：(eye_in_hand, marker_type)"""
        return self._eye_in_hand, self._marker_type

    def set_mode(self, eye_in_hand, marker_type):
        """程序化设置模式（用于恢复之前的状态）"""
        self._eye_in_hand = eye_in_hand
        self._marker_type = marker_type
        if eye_in_hand:
            self._btn_eye_in_hand.setChecked(True)
        else:
            self._btn_eye_to_hand.setChecked(True)
        if marker_type:
            self._btn_marker.setChecked(True)
        else:
            self._btn_tcp.setChecked(True)
        self._update_toggle_style(self._btn_eye_to_hand, not eye_in_hand)
        self._update_toggle_style(self._btn_eye_in_hand, eye_in_hand)
        self._update_toggle_style(self._btn_marker, marker_type)
        self._update_toggle_style(self._btn_tcp, not marker_type)
