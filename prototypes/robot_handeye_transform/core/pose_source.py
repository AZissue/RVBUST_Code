# -*- coding: utf-8 -*-
"""
位姿来源抽象（pose_source）—— D3：没有真机也必须能跑完整闭环。

PoseSource.get_pose() 统一返回 T_base2tool（基座→工具法兰，**毫米**）：
  (ok, message, T|None)

实现：
  MockPoseSource   位姿序列回放（测试/演示；get_pose 取当前帧，step_next 步进）
  ManualPoseSource 手动六自由度录入（XYZ mm + RxRyRz deg + 欧拉顺序）
  CsvPoseSource    CSV 位姿离线回放（产线复盘）
  TcpRobot         空实现——真实协议待 @user §8 现场信息，按 PoseSource 接口重做
                   （不要照抄 docs/机器人配合拼接方案_手眼标定与点云融合_20260827.md
                   §5.5 的 UR 示例，未经本机验证，方案 §9）

欧拉角口径：order 字符串直接传给 scipy.spatial.transform.Rotation
（小写 = 外旋/固定轴，大写 = 内旋/绕动轴），默认 "ZYX"（机器人 RPY 常用）。
"""

from __future__ import annotations

import csv
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence

import numpy as np

# 内部统一毫米；米制位姿文件在录入处显式换算（K1：单位由产出者决定）
EULER_ORDERS = ("ZYX", "ZXY", "YZX", "YXZ", "XZY", "XYZ",
                "zyx", "zxy", "yzx", "yxz", "xzy", "xyz")


def euler_to_matrix(xyz_mm: Sequence[float], rpy_deg: Sequence[float],
                    order: str = "ZYX") -> np.ndarray:
    """六自由度 → 4×4 T_base2tool（毫米）。order 见模块 docstring。"""
    if order not in EULER_ORDERS:
        raise ValueError(f"不支持的欧拉顺序 {order!r}，可选 {EULER_ORDERS}")
    from scipy.spatial.transform import Rotation
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = Rotation.from_euler(order, np.asarray(rpy_deg, dtype=np.float64),
                                    degrees=True).as_matrix()
    T[:3, 3] = np.asarray(xyz_mm, dtype=np.float64)
    return T


class PoseSource(ABC):
    """机器人位姿来源抽象基类。"""

    @abstractmethod
    def get_pose(self) -> tuple[bool, str, Optional[np.ndarray]]:
        """读取当前位姿，返回 (ok, message, T_base2tool_mm|None)。"""

    def source_name(self) -> str:
        return self.__class__.__name__


class MockPoseSource(PoseSource):
    """位姿序列回放（无硬件闭环测试/演示）。不控制任何硬件。"""

    def __init__(self, poses_mm: Optional[List[np.ndarray]] = None):
        self._poses: List[np.ndarray] = []
        self._index = 0
        for p in (poses_mm or []):
            self.append_pose(p)

    def set_poses(self, poses_mm: List[np.ndarray]):
        self._poses = [np.asarray(p, dtype=np.float64).reshape(4, 4) for p in poses_mm]
        self._index = 0

    def append_pose(self, pose_mm: np.ndarray):
        self._poses.append(np.asarray(pose_mm, dtype=np.float64).reshape(4, 4))

    def get_pose(self) -> tuple[bool, str, Optional[np.ndarray]]:
        if not self._poses:
            return False, "MockPoseSource 无位姿（请先录入/加载位姿序列）", None
        return True, f"Mock 位姿 #{self._index + 1}/{len(self._poses)}", \
            self._poses[self._index].copy()

    def step_next(self) -> tuple[bool, str, Optional[np.ndarray]]:
        """步进到序列下一帧（循环）。首帧问题（R6）：初始停在 #1。"""
        if not self._poses:
            return False, "MockPoseSource 无位姿", None
        self._index = (self._index + 1) % len(self._poses)
        return self.get_pose()

    def current_index(self) -> int:
        return self._index

    def count(self) -> int:
        return len(self._poses)


class ManualPoseSource(PoseSource):
    """手动六自由度录入（无机器人时的真实闭环入口）。"""

    def __init__(self):
        self._pose: Optional[np.ndarray] = None

    def set_pose_matrix(self, T_base2tool_mm: np.ndarray):
        self._pose = np.asarray(T_base2tool_mm, dtype=np.float64).reshape(4, 4).copy()

    def set_pose_xyz_rpy(self, xyz_mm: Sequence[float], rpy_deg: Sequence[float],
                         order: str = "ZYX") -> tuple[bool, str]:
        try:
            self._pose = euler_to_matrix(xyz_mm, rpy_deg, order)
        except ValueError as e:
            return False, str(e)
        return True, f"位姿已录入 XYZ={list(xyz_mm)} RPY={list(rpy_deg)}° ({order})"

    def get_pose(self) -> tuple[bool, str, Optional[np.ndarray]]:
        if self._pose is None:
            return False, "尚未录入位姿（XYZ + RPY）", None
        return True, "手动位姿", self._pose.copy()


class CsvPoseSource(PoseSource):
    """CSV 位姿离线回放。

    每行两种格式（自动识别，忽略空行与 # 注释行）：
      16 列        —— 行优先 4×4 T_base2tool（毫米）
      6/7 列       —— x y z rx ry rz [order]，平移毫米、角度度
    回放完毕默认停在最后一帧并报可读提示；loop=True 循环。
    """

    def __init__(self, path: str, loop: bool = False):
        self._path = path
        self._loop = loop
        self._poses = self._parse(path)
        self._index = 0

    @staticmethod
    def _parse(path: str) -> List[np.ndarray]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"位姿 CSV 不存在: {path}")
        poses: List[np.ndarray] = []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                cells = [c.strip() for c in row if c.strip()]
                if not cells or cells[0].startswith("#"):
                    continue
                vals = [float(c) for c in cells]
                if len(vals) == 16:
                    poses.append(np.asarray(vals, dtype=np.float64).reshape(4, 4))
                elif len(vals) in (6, 7):
                    order = cells[6] if len(vals) == 7 else "ZYX"
                    poses.append(euler_to_matrix(vals[0:3], vals[3:6], order))
                else:
                    raise ValueError(
                        f"位姿 CSV 行格式无法识别（{len(vals)} 列）：{cells}")
        if not poses:
            raise ValueError(f"位姿 CSV 无有效行: {path}")
        return poses

    def get_pose(self) -> tuple[bool, str, Optional[np.ndarray]]:
        if not self._poses:
            return False, "CSV 无位姿", None
        return True, f"CSV 位姿 #{self._index + 1}/{len(self._poses)}", \
            self._poses[self._index].copy()

    def step_next(self) -> tuple[bool, str, Optional[np.ndarray]]:
        if not self._poses:
            return False, "CSV 无位姿", None
        nxt = self._index + 1
        if nxt >= len(self._poses):
            if not self._loop:
                return False, f"位姿序列已回放完毕（共 {len(self._poses)} 帧）", \
                    self._poses[self._index].copy()
            nxt = 0
        self._index = nxt
        return self.get_pose()

    def count(self) -> int:
        return len(self._poses)


class TcpRobot(PoseSource):
    """真实机器人 TCP 接口（空实现）。

    待 @user 提供现场机器人品牌与位姿输出格式（方案 §8-②）后按
    PoseSource 接口实现；不要照抄 20260827 版 §5.5 的未验证示例。
    """

    def __init__(self, *args, **kwargs):
        self._config = (args, kwargs)

    def get_pose(self) -> tuple[bool, str, Optional[np.ndarray]]:
        return False, ("TcpRobot 未实现：真实协议待现场信息"
                       "（方案 §8-② 机器人品牌/位姿单位/旋转表示）"), None
