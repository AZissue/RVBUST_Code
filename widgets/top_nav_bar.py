"""
顶部导航栏组件。
显示应用标题、相机连接状态、采集进度条、和设置/帮助/连接相机按钮。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QProgressBar, QSizePolicy,
)

import resources as res


class TopNavBar(QWidget):
    """顶部导航栏，包含标题、进度、相机状态和功能按钮"""

    # 信号定义
    settings_clicked = pyqtSignal()          # 设置按钮被点击
    help_clicked = pyqtSignal()              # 帮助按钮被点击
    connect_camera_clicked = pyqtSignal()    # 连接相机按钮被点击（断开状态时）
    disconnect_camera_clicked = pyqtSignal() # 断开相机按钮被点击（连接状态时）

    def __init__(self, parent=None):
        super().__init__(parent)
        # 固定高度 48px，宽度自适应
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 顶栏背景色 + 底部分割线
        self.setStyleSheet(f"""
            TopNavBar {{
                background-color: {res.BG_MAIN};
                border-bottom: 1px solid {res.BORDER_DEFAULT};
            }}
        """)

        # 水平布局：左侧标题 | 中部进度 | 右侧按钮
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(12)

        # ── 左侧：机器人图标 + 应用标题 ──
        # 使用 Unicode 字符作为图标占位（避免外部图片依赖）
        icon_label = QLabel("\U0001f916")  # 机器人 emoji
        icon_label.setStyleSheet(f"font-size: 20px; color: {res.PRIMARY}; border: none;")
        layout.addWidget(icon_label)

        # 应用标题：H1 字号，深色粗体
        title = QLabel("手眼标定数据收集助手 V1.0")
        title.setStyleSheet(f"""
            font-size: {res.FONT_H1}px;
            font-weight: 600;
            color: {res.TEXT_TITLE};
            border: none;
        """)
        layout.addWidget(title)

        layout.addStretch()  # 弹性空间，将后续组件推到中间和右侧

        # ── 中部：相机连接状态 ──
        self._camera_status_label = QLabel("⚪ 未连接")  # ⚪ 未连接
        self._camera_status_label.setStyleSheet(
            f"font-size: {res.FONT_HINT}px; color: {res.TEXT_HINT}; border: none;"
        )
        layout.addWidget(self._camera_status_label)

        # 连接相机按钮
        self._connected = False  # 跟踪当前连接状态
        self._btn_connect = QPushButton("连接相机")  # 连接相机
        self._btn_connect.setFixedHeight(28)
        self._btn_connect.setStyleSheet(f"""
            QPushButton {{
                background-color: {res.PRIMARY};
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                font-size: {res.FONT_HINT}px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {res.PRIMARY_HOVER};
            }}
        """)
        # 根据当前连接状态分发不同的信号
        self._btn_connect.clicked.connect(self._on_connect_btn_clicked)
        layout.addWidget(self._btn_connect)

        layout.addSpacing(24)

        # ── 中部：采集进度标签 + 进度条 ──
        self._progress_label = QLabel("已采集 0 组数据")  # 已采集 0 组数据
        self._progress_label.setStyleSheet(
            f"font-size: {res.FONT_BODY}px; color: {res.TEXT_BODY}; border: none;"
        )
        layout.addWidget(self._progress_label)

        # 进度条：天蓝色填充，6px 高度，固定宽度 120px
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(120)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)

        layout.addStretch()

        # ── 右侧：设置按钮 + 帮助按钮 ──
        for text, signal, tip in [
            ("⚙", self.settings_clicked, "设置"),   # ⚙ 设置
            ("?", self.help_clicked, "帮助"),            # ? 帮助
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(24, 24)
            btn.setToolTip(tip)
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    font-size: 18px;
                    color: {res.TEXT_HINT};
                }}
                QPushButton:hover {{
                    color: {res.PRIMARY};
                }}
            """)
            btn.clicked.connect(signal.emit)
            layout.addWidget(btn)

    def update_progress(self, current, total=None):
        """
        更新采集进度显示。
        current: 当前已采集组数
        total: 目标组数（None 时取 current 和 15 的较大值）
        """
        if total is None or total <= 0:
            total = max(current, res.RECOMMENDED_COUNT)
        self._progress_label.setText(f"已采集 {current}/{total} 组数据")
        # 计算百分比进度
        pct = min(int(current / max(total, 1) * 100), 100)
        self._progress_bar.setValue(pct)

    def set_camera_status(self, connected, device_name=""):
        """
        更新相机连接状态显示。
        connected=True 时显示绿色圆点 + 设备名，按钮变为"断开相机"；
        connected=False 时显示灰色圆点 + "未连接"，按钮变为"连接相机"。
        """
        self._connected = connected
        if connected:
            self._camera_status_label.setText(
                f"\U0001f7e2 {device_name}"  # 🟢 设备名
            )
            self._camera_status_label.setStyleSheet(
                f"font-size: {res.FONT_HINT}px; color: {res.SUCCESS}; border: none;"
            )
            self._btn_connect.setText("断开相机")  # 断开相机
            self._btn_connect.setStyleSheet(f"""
                QPushButton {{
                    background-color: {res.BG_MAIN};
                    color: {res.ERROR};
                    border: 1px solid {res.ERROR};
                    border-radius: 4px;
                    font-size: {res.FONT_HINT}px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background-color: {res.ERROR_BG};
                }}
            """)
        else:
            self._camera_status_label.setText("⚪ 未连接")  # ⚪ 未连接
            self._camera_status_label.setStyleSheet(
                f"font-size: {res.FONT_HINT}px; color: {res.TEXT_HINT}; border: none;"
            )
            self._btn_connect.setText("连接相机")  # 连接相机
            self._btn_connect.setStyleSheet(f"""
                QPushButton {{
                    background-color: {res.PRIMARY};
                    color: #FFFFFF;
                    border: none;
                    border-radius: 4px;
                    font-size: {res.FONT_HINT}px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background-color: {res.PRIMARY_HOVER};
                }}
            """)

    def _on_connect_btn_clicked(self):
        """
        连接/断开按钮点击处理。
        根据当前连接状态分发不同的信号。
        """
        if self._connected:
            self.disconnect_camera_clicked.emit()
        else:
            self.connect_camera_clicked.emit()
