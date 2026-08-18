# -*- coding: utf-8 -*-
"""
机器人接口抽象层（RobotInterface）。

用于模式 D「机器人手眼配合拼接」：
  - 统一不同机器人品牌/协议的位姿获取与运动控制接口；
  - 提供 MockRobot 用于无硬件时的合成数据测试。

坐标约定：
  - get_current_pose() 返回 4×4 齐次矩阵 T_base2tool（基座→工具法兰）；
  - move_to(pose) 的 pose 同样为 T_base2tool。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import numpy as np


class RobotInterface(ABC):
    """机器人接口抽象基类。"""

    @abstractmethod
    def connect(self) -> Tuple[bool, str]:
        """连接机器人控制器。返回 (success, message)。"""
        pass

    @abstractmethod
    def disconnect(self) -> Tuple[bool, str]:
        """断开连接。"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接。"""
        pass

    @abstractmethod
    def get_current_pose(self) -> Optional[np.ndarray]:
        """读取机器人当前 TCP 位姿，返回 4×4 T_base2tool 或 None。"""
        pass

    @abstractmethod
    def move_to(self, pose: np.ndarray, blocking: bool = True,
                timeout_sec: float = 60.0) -> Tuple[bool, str]:
        """移动到目标位姿。pose 为 4×4 T_base2tool。

        Args:
            pose: 4×4 齐次矩阵
            blocking: 是否阻塞等待到位
            timeout_sec: 阻塞超时

        Returns:
            (success, message)
        """
        pass

    @abstractmethod
    def is_moving(self) -> bool:
        """机器人是否仍在运动中。"""
        pass


class MockRobot(RobotInterface):
    """模拟机器人：按预设位姿序列返回 T_base2tool，不实际控制硬件。"""

    def __init__(self, poses: Optional[List[np.ndarray]] = None):
        self._poses = poses or []
        self._index = 0
        self._connected = False
        self._moving = False
        self._current_pose: Optional[np.ndarray] = None

    def connect(self) -> Tuple[bool, str]:
        self._connected = True
        if self._poses:
            self._current_pose = self._poses[0].copy()
        return True, "MockRobot 已连接"

    def disconnect(self) -> Tuple[bool, str]:
        self._connected = False
        return True, "MockRobot 已断开"

    def is_connected(self) -> bool:
        return self._connected

    def get_current_pose(self) -> Optional[np.ndarray]:
        return self._current_pose.copy() if self._current_pose is not None else None

    def move_to(self, pose: np.ndarray, blocking: bool = True,
                timeout_sec: float = 60.0) -> Tuple[bool, str]:
        if not self._connected:
            return False, "机器人未连接"
        self._moving = True
        self._current_pose = np.asarray(pose, dtype=np.float64).copy()
        self._moving = False
        return True, "MockRobot 已移动到位"

    def is_moving(self) -> bool:
        return self._moving

    def set_poses(self, poses: List[np.ndarray]):
        """重新设置预设位姿序列。"""
        self._poses = [np.asarray(p, dtype=np.float64) for p in poses]
        self._index = 0
        if self._connected and self._poses:
            self._current_pose = self._poses[0].copy()

    def append_pose(self, pose: np.ndarray):
        """追加一个预设位姿。"""
        self._poses.append(np.asarray(pose, dtype=np.float64))

    def step_next(self) -> Optional[np.ndarray]:
        """按预设序列步进到下一个位姿并返回。"""
        if not self._poses:
            return None
        self._index = (self._index + 1) % len(self._poses)
        self._current_pose = self._poses[self._index].copy()
        return self._current_pose.copy()
