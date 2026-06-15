"""
右侧辅助面板组件。
包含三个卡片：当前操作提示、标定注意事项、数据文件预览。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QTextEdit, QPushButton,
    QSizePolicy,
)

import resources as res


class SidePanel(QWidget):
    """右侧辅助面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 24, 0)
        layout.setSpacing(12)

        self._tips_card = TipsCard()
        self._notes_card = NotesCard()
        self._preview_card = FilePreviewCard()

        layout.addWidget(self._tips_card)
        layout.addWidget(self._notes_card)
        layout.addWidget(self._preview_card, 1)

    def set_tip(self, text, is_error=False):
        self._tips_card.set_tip(text, is_error)

    def update_file_preview(self, eye_in_hand, marker_type, records):
        self._preview_card.refresh(eye_in_hand, marker_type, records)


class TipsCard(QFrame):
    """当前操作提示卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            TipsCard {{
                background-color: {res.BG_MAIN};
                border: 1px solid {res.BORDER_DEFAULT};
                border-radius: {res.BORDER_RADIUS}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(36)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_label = QLabel("\U0001f4a1 当前操作提示")
        header_label.setStyleSheet(
            f"font-size: {res.FONT_H2}px; font-weight: 600; "
            f"color: {res.PRIMARY}; border: none;"
        )
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        layout.addWidget(header)

        self._content = QLabel("请先连接相机，然后选择标定模式")
        self._content.setWordWrap(True)
        self._content.setAlignment(Qt.AlignVCenter)
        self._content.setMinimumHeight(48)
        self._content.setStyleSheet(
            f"font-size: {res.FONT_BODY}px; color: {res.TEXT_BODY}; "
            f"border: none; padding: 0 16px 12px 16px;"
        )
        layout.addWidget(self._content)

    def set_tip(self, text, is_error=False):
        self._content.setText(text)
        if is_error:
            self._content.setStyleSheet(
                f"font-size: {res.FONT_BODY}px; color: {res.ERROR}; "
                f"border: none; padding: 0 16px 12px 16px;"
            )
            self.setStyleSheet(f"""
                TipsCard {{
                    background-color: {res.ERROR_BG};
                    border: 1px solid {res.ERROR};
                    border-radius: {res.BORDER_RADIUS}px;
                }}
            """)
        else:
            self._content.setStyleSheet(
                f"font-size: {res.FONT_BODY}px; color: {res.TEXT_BODY}; "
                f"border: none; padding: 0 16px 12px 16px;"
            )
            self.setStyleSheet(f"""
                TipsCard {{
                    background-color: {res.BG_MAIN};
                    border: 1px solid {res.BORDER_DEFAULT};
                    border-radius: {res.BORDER_RADIUS}px;
                }}
            """)


class NotesCard(QFrame):
    """标定注意事项卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            NotesCard {{
                background-color: {res.BG_MAIN};
                border: 1px solid {res.BORDER_DEFAULT};
                border-radius: {res.BORDER_RADIUS}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setStyleSheet(f"""
            background-color: {res.PRIMARY};
            border-top-left-radius: {res.BORDER_RADIUS}px;
            border-top-right-radius: {res.BORDER_RADIUS}px;
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_label = QLabel("\U0001f4cb 标定注意事项")
        title_label.setStyleSheet(
            f"font-size: {res.FONT_H2}px; font-weight: 600; "
            f"color: #FFFFFF; border: none;"
        )
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addWidget(title_bar)

        content = QTextEdit()
        content.setReadOnly(True)
        content.setStyleSheet(f"""
            QTextEdit {{
                border: none;
                font-size: {res.FONT_BODY}px;
                color: {res.TEXT_BODY};
                padding: 16px;
                background-color: {res.BG_MAIN};
                border-bottom-left-radius: {res.BORDER_RADIUS}px;
                border-bottom-right-radius: {res.BORDER_RADIUS}px;
            }}
        """)
        content.setHtml("""
            <p style='line-height: 22px;'>
            <b style='color: #FAAD14;'>⚠️ 标定过程中严禁移动相机和机器人基座</b><br><br>
            • 标定板应尽量充满相机视野的不同区域<br>
            • 建议采集 15-20 组不同位姿的数据<br>
            • 位姿应包含不同的角度和距离<br>
            • 机器人动作幅度越大，标定结果越稳定<br>
            • 确保每次拍照时标定板清晰可见
            </p>
        """)
        layout.addWidget(content)


class FilePreviewCard(QFrame):
    """数据文件预览卡片 — 实时展示已保存的 txt 文件内容"""

    _FILE_SPECS = [
        ("camera_target", "cameraCapturePointXyz.txt", "相机目标点"),
        ("robot_pose", "cameraCaptureRobotPose.txt", "机器人位姿"),
        ("robot_target", "tcp.txt", "机器人目标点"),
    ]

    _MARKER_FILE = ("pose.txt", "机器人拍照位姿")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._eye_in_hand = True
        self._marker_type = True
        self._records = []
        self._active_key = None
        self._tab_btns = {}  # key → QPushButton

        self.setStyleSheet(f"""
            FilePreviewCard {{
                background-color: {res.BG_MAIN};
                border: 1px solid {res.BORDER_DEFAULT};
                border-radius: {res.BORDER_RADIUS}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏（小号字体）
        header = QWidget()
        header.setFixedHeight(30)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 8, 0)

        title = QLabel("\U0001f4c2 数据文件预览")
        title.setStyleSheet(
            f"font-size: {res.FONT_BODY}px; font-weight: 600; "
            f"color: {res.TEXT_TITLE}; border: none;"
        )
        header_layout.addWidget(title)
        header_layout.addStretch()

        # marker 模式：静态标签
        self._marker_label = QLabel("pose.txt")
        self._marker_label.setStyleSheet(
            f"font-size: {res.FONT_HINT}px; color: {res.TEXT_HINT}; border: none;"
        )
        header_layout.addWidget(self._marker_label)

        layout.addWidget(header)

        # TCP 模式：文件切换标签栏（独立一行，有足够空间）
        self._tab_bar = QWidget()
        tab_bar_layout = QHBoxLayout(self._tab_bar)
        tab_bar_layout.setContentsMargins(12, 2, 12, 4)
        tab_bar_layout.setSpacing(6)

        tab_style = f"""
            QPushButton {{
                background-color: {res.BG_CARD};
                color: {res.TEXT_BODY};
                border: 1px solid {res.BORDER_DEFAULT};
                border-radius: 4px;
                font-size: {res.FONT_HINT}px;
                padding: 4px 10px;
            }}
            QPushButton:checked {{
                background-color: {res.PRIMARY};
                color: #FFFFFF;
                border-color: {res.PRIMARY_CLICK};
                border-bottom: 2px solid {res.PRIMARY_CLICK};
            }}
            QPushButton:hover:!checked {{
                background-color: {res.PRIMARY_LIGHT};
                border-color: {res.PRIMARY};
            }}
        """
        for key, filename, label in self._FILE_SPECS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(tab_style)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._on_tab_changed)
            self._tab_btns[key] = btn
            tab_bar_layout.addWidget(btn)
        tab_bar_layout.addStretch()
        layout.addWidget(self._tab_bar)

        # 文本预览区
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(f"""
            QTextEdit {{
                border: none;
                font-size: {res.FONT_HINT}px;
                font-family: Consolas, "Courier New", monospace;
                color: {res.TEXT_BODY};
                padding: 8px 12px;
                background-color: {res.BG_MAIN};
                border-bottom-left-radius: {res.BORDER_RADIUS}px;
                border-bottom-right-radius: {res.BORDER_RADIUS}px;
            }}
        """)
        layout.addWidget(self._text)

    def refresh(self, eye_in_hand, marker_type, records):
        self._eye_in_hand = eye_in_hand
        self._marker_type = marker_type
        self._records = records

        if marker_type:
            self._tab_bar.setVisible(False)
            self._marker_label.setVisible(True)
            self._show_marker_content()
        else:
            self._marker_label.setVisible(False)
            self._tab_bar.setVisible(True)
            self._update_tab_visibility()
            # 默认选中第一个可用标签
            available = self._available_keys()
            if self._active_key not in available:
                self._select_tab(available[0] if available else None)

    def _available_keys(self):
        keys = ["camera_target", "robot_target"]
        if self._eye_in_hand:
            keys.insert(1, "robot_pose")
        return keys

    def _update_tab_visibility(self):
        available = set(self._available_keys())
        for key, btn in self._tab_btns.items():
            btn.setVisible(key in available)

    def _select_tab(self, key):
        if key is None:
            return
        self._active_key = key
        for k, btn in self._tab_btns.items():
            btn.setChecked(k == key)
        self._show_tcp_content(key)

    def _on_tab_changed(self, checked):
        # 找出是哪个按钮发出的信号，通过 sender 或遍历
        for key, btn in self._tab_btns.items():
            if btn.isChecked() and key != self._active_key:
                self._active_key = key
                # 取消其他按钮的选中态
                for k2, b2 in self._tab_btns.items():
                    if k2 != key:
                        b2.setChecked(False)
                self._show_tcp_content(key)
                return
        # 如果所有按钮都未选中（用户点击了已选中的按钮），保持当前选中
        if not any(btn.isChecked() for btn in self._tab_btns.values()):
            # 恢复当前选中按钮的状态
            if self._active_key and self._active_key in self._tab_btns:
                self._tab_btns[self._active_key].setChecked(True)

    def _show_marker_content(self):
        filename, _ = self._MARKER_FILE
        lines = [r.robot_capture_pose for r in self._records]
        self._text.setPlainText(self._format_content(filename, lines))

    def _show_tcp_content(self, key):
        field_map = {
            "camera_target": "camera_target_xyz",
            "robot_pose": "robot_capture_pose",
            "robot_target": "robot_target_xyz",
        }
        field = field_map.get(key, "")
        filename = next((f for k, f, _ in self._FILE_SPECS if k == key), "")
        lines = [getattr(r, field, "") for r in self._records]
        self._text.setPlainText(self._format_content(filename, lines))

    @staticmethod
    def _format_content(filename, lines):
        if not lines or all(not s.strip() for s in lines):
            return f"# {filename}\n(暂无数据)"
        return f"# {filename}\n" + "\n".join(str(s) for s in lines)
