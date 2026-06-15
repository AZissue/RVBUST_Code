"""
数据输入卡片区域容器。
管理三张输入卡片的显示/隐藏，根据标定模式动态调整。
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QScrollArea

from widgets.data_input_card import DataInputCard


class DataInputArea(QWidget):
    """
    数据输入区域，包含 3 张卡片。
    卡片1: 相机目标点坐标 — 仅戳点标定模式可见
    卡片2: 机器人拍照位姿 — 眼在手外+戳点模式隐藏
    卡片3: 机器人目标点坐标 — 仅戳点标定模式可见
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 允许内容随窗口宽度伸缩
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 垂直排列三张卡片，间距 12px
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 卡片1：相机目标点坐标（仅戳点模式需要手动记录）
        self._card1 = DataInputCard(
            "camera_target", "相机目标点坐标",
            "识别到的相机坐标目标点坐标，也可手动输入"
        )
        # 卡片2：机器人拍照位姿（标记物模式 + 眼在手上戳点模式需要）
        self._card2 = DataInputCard(
            "robot_pose", "机器人拍照位姿",
            "支持手动输入或复制粘贴，格式: x y z rx ry rz"
        )
        # 卡片3：机器人目标点坐标（仅戳点模式需要手动记录 TCP 戳点坐标）
        self._card3 = DataInputCard(
            "robot_target", "机器人目标点坐标",
            "TCP 戳点坐标，也可手动输入或复制粘贴"
        )

        layout.addWidget(self._card1)
        layout.addWidget(self._card2)
        layout.addWidget(self._card3)

    def update_visibility(self, eye_in_hand, marker_type):
        """
        根据标定模式更新卡片显示/隐藏。
        显示规则：
        - 卡片1（相机目标点坐标）：仅戳点标定模式可见
        - 卡片2（机器人拍照位姿）：眼在手外+戳点模式隐藏，其余可见
        - 卡片3（机器人目标点坐标）：仅戳点标定模式可见
        """
        # 卡片1 仅在戳点标定模式下显示
        is_tcp = not marker_type
        self._card1.setVisible(is_tcp)

        # 卡片2 在眼在手外+戳点模式下隐藏
        show_card2 = not (not eye_in_hand and not marker_type)
        self._card2.setVisible(show_card2)

        # 卡片3 仅在戳点标定模式下显示
        self._card3.setVisible(is_tcp)

    def get_card(self, card_id):
        """根据 ID 获取对应的卡片对象"""
        return {
            "camera_target": self._card1,
            "robot_pose": self._card2,
            "robot_target": self._card3,
        }[card_id]

    def get_all_values(self):
        """获取三张卡片的当前值（字典格式）"""
        return {
            "camera_target": self._card1.get_value(),
            "robot_pose": self._card2.get_value(),
            "robot_target": self._card3.get_value(),
        }

    # 属性快捷访问
    @property
    def card1(self):
        """卡片1：相机目标点坐标"""
        return self._card1

    @property
    def card2(self):
        """卡片2：机器人拍照位姿"""
        return self._card2

    @property
    def card3(self):
        """卡片3：机器人目标点坐标"""
        return self._card3
