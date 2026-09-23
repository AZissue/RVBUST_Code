# -*- coding: utf-8 -*-
"""
位姿来源抽象（pose_source）—— D3：没有真机也必须能跑完整闭环。

PoseSource.get_pose() 统一返回 T_base2tool（基座→工具法兰，**毫米**）：
  (ok, message, T|None)

元数据三件套 **全部必填、无任何默认**（方案 v4 §4.2 / R11）：
  unit       "mm" | "m"                      —— 米制示教器数值不声明就静默错 1000×
  pose_type  "absolute" | "delta"            —— 绑定不同范数窗口（R11）
  order      欧拉顺序（仅六自由度入口需要）   —— 删除旧 "ZYX" 静默默认

三入口流程钉死：normalize_unit/pose_type → check_rigid_4x4 → to_mm → check_pose_norm，
实现全部走 `unit_guard` 共用层（禁两份副本，K4 型漂移）。
错误一律自家可读报错（不抛 numpy 原生异常），入口返回 (ok, message[, T_mm])。

实测背景（@qa）：旧版 set_pose_xyz_rpy([0.4,0.1,0.2], [0,0,0]) 米制数值被当毫米，
端到端单点偏差 457.799 mm 且全程零报错；NaN 位姿透传成 [nan 40. 520.] 点云。

实现：
  MockPoseSource   位姿序列回放（测试/演示；get_pose 取当前帧，step_next 步进）
  ManualPoseSource 手动六自由度录入（XYZ + RxRyRz + 欧拉顺序 + unit + pose_type）
  CsvPoseSource    CSV 位姿离线回放（产线复盘；6 列格式拒收，文件须带 pose_type 声明）
  TcpRobot         空实现——真实协议待 @user §8 现场信息，按 PoseSource 接口重做
                   （不要照抄 docs/机器人配合拼接方案_手眼标定与点云融合_20260827.md
                   §5.5 的 UR 示例，未经本机验证，方案 §9）

欧拉角口径：order 字符串直接传给 scipy.spatial.transform.Rotation
（小写 = 外旋/固定轴，大写 = 内旋/绕动轴）。
"""

from __future__ import annotations

import csv
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence

import numpy as np

try:
    from .unit_guard import (PoseError, check_pose_norm, check_rigid_4x4,
                             normalize_pose_type, normalize_unit, to_mm)
except ImportError:  # 测试以顶层模块方式引入时
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from unit_guard import (PoseError, check_pose_norm, check_rigid_4x4,
                            normalize_pose_type, normalize_unit, to_mm)

EULER_ORDERS = ("ZYX", "ZXY", "YZX", "YXZ", "XZY", "XYZ",
                "zyx", "zxy", "yzx", "yxz", "xzy", "xyz")

CSV_POSE_TYPE_HEADER = "pose_type:"   # 形如 `# pose_type: absolute`


# ----------------------------------------------------------------------
# 共用录入流程（三入口唯一实现）
# ----------------------------------------------------------------------
def _as_4x4(pose) -> Optional[np.ndarray]:
    """把 4×4 / 16 个数（行优先）统一成 (4,4) 数组；尺寸或类型不对返回 None。"""
    try:
        arr = np.asarray(pose, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if arr.ndim == 1 and arr.size == 16:
        arr = arr.reshape(4, 4)
    if arr.shape != (4, 4):
        return None
    return arr


def admit_pose(pose, unit, pose_type, label: str = "位姿"
               ) -> tuple[bool, str, Optional[np.ndarray]]:
    """位姿录入统一流程：单位/类型校验 → 刚性校验 → 换算 mm → 范数窗口。

    Returns:
        (ok, message, T_mm|None)。T_mm 为毫米域 4×4；失败时 message 可读、T_mm=None。
    """
    try:
        unit = normalize_unit(unit)
        pt = normalize_pose_type(pose_type)
    except (ValueError, PoseError) as e:
        return False, str(e), None

    arr = _as_4x4(pose)
    if arr is None:
        shape = np.shape(pose)
        return False, (f"{label} 必须是 4×4 矩阵或 16 个数（行优先），"
                       f"实际 shape={shape}"), None
    ok, msg = check_rigid_4x4(arr)
    if not ok:
        return False, f"{label} 非法: {msg}", None
    T_mm = to_mm(arr, unit)
    ok, msg = check_pose_norm(T_mm, pt)
    if not ok:
        return False, msg, None
    return True, f"{msg}；unit={unit} pose_type={pt}", T_mm


def euler_to_matrix(xyz: Sequence[float], rpy_deg: Sequence[float],
                    order: str) -> np.ndarray:
    """六自由度 → 4×4 T_base2tool。order **必填**（无 "ZYX" 默认，静默默认=静默错姿态）。

    Args:
        xyz: 平移 3 分量（单位由调用方在 admit_pose 里声明换算）。
        rpy_deg: 旋转 3 分量（度）。
        order: 欧拉顺序，见 EULER_ORDERS。

    Raises:
        PoseError: order 非法/缺失，或 xyz/rpy 不是 3 分量。
    """
    if order is None:
        raise PoseError(
            "欧拉顺序 order 必填（无默认）：静默默认 ZYX 会在非 ZYX 机器人上"
            "静默错姿态，请显式指定，可选 " + str(EULER_ORDERS))
    if order not in EULER_ORDERS:
        raise PoseError(f"不支持的欧拉顺序 {order!r}，可选 {EULER_ORDERS}")
    for name, v in (("XYZ", xyz), ("RPY", rpy_deg)):
        arr = np.asarray(v, dtype=np.float64).reshape(-1)
        if arr.size != 3:
            raise PoseError(f"{name} 必须是 3 个分量，实际 {np.shape(v)}")
    from scipy.spatial.transform import Rotation
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = Rotation.from_euler(order, np.asarray(rpy_deg, dtype=np.float64),
                                    degrees=True).as_matrix()
    T[:3, 3] = np.asarray(xyz, dtype=np.float64).reshape(3)
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

    def __init__(self, poses: Optional[List[np.ndarray]] = None,
                 unit: Optional[str] = None,
                 pose_type: Optional[str] = None):
        self._poses: List[np.ndarray] = []
        self._index = 0
        self._unit: Optional[str] = None
        self._pose_type: Optional[str] = None
        if poses:
            ok, msg = self.set_poses(poses, unit, pose_type)
            if not ok:
                raise PoseError(f"MockPoseSource 初始化失败: {msg}")

    def _check_type_lock(self, pose_type: str) -> Optional[str]:
        """同一位姿源不允许中途改 pose_type（窗口语义会变）。"""
        try:
            pt = normalize_pose_type(pose_type)
        except PoseError as e:
            return str(e)
        if self._pose_type is not None and pt != self._pose_type:
            return (f"同一位姿源不允许混用 pose_type（已锁定 {self._pose_type}，"
                    f"收到 {pt}）")
        return None

    def set_poses(self, poses, unit, pose_type) -> tuple[bool, str]:
        """批量录入。unit / pose_type **必填无默认**。

        任一位姿失败则整体不生效（不留半截序列）。
        """
        err = self._check_type_lock(pose_type)
        if err:
            return False, err
        admitted: List[np.ndarray] = []
        for i, p in enumerate(poses):
            ok, msg, T_mm = admit_pose(p, unit, pose_type, f"位姿 #{i + 1}")
            if not ok:
                return False, f"set_poses 第 {i + 1} 个位姿被拒: {msg}"
            assert T_mm is not None
            admitted.append(T_mm)
        if not admitted:
            return False, "set_poses 收到空位姿列表"
        self._poses = admitted
        self._index = 0
        self._unit = normalize_unit(unit)
        self._pose_type = normalize_pose_type(pose_type)
        return True, (f"已载入 {len(admitted)} 个位姿"
                      f"（unit={self._unit} pose_type={self._pose_type}）")

    def append_pose(self, pose, unit, pose_type) -> tuple[bool, str]:
        """追加单个位姿。unit / pose_type **必填无默认**。"""
        err = self._check_type_lock(pose_type)
        if err:
            return False, err
        ok, msg, T_mm = admit_pose(pose, unit, pose_type,
                                   f"位姿 #{len(self._poses) + 1}")
        if not ok:
            return False, msg
        assert T_mm is not None
        self._poses.append(T_mm)
        self._unit = normalize_unit(unit)
        self._pose_type = normalize_pose_type(pose_type)
        return True, msg

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
        self._unit: Optional[str] = None
        self._pose_type: Optional[str] = None

    def set_pose_matrix(self, T_base2tool, unit, pose_type) -> tuple[bool, str]:
        """直接录入 4×4（或 16 个数，行优先）。unit / pose_type 必填无默认。"""
        ok, msg, T_mm = admit_pose(T_base2tool, unit, pose_type, "手动位姿")
        if not ok:
            return False, msg
        self._pose = T_mm
        self._unit = normalize_unit(unit)
        self._pose_type = normalize_pose_type(pose_type)
        return True, msg

    def set_pose_xyz_rpy(self, xyz, rpy_deg, order, unit, pose_type
                         ) -> tuple[bool, str]:
        """六自由度录入。order / unit / pose_type **全部必填无默认**。

        Args:
            xyz: 平移 3 分量，单位由 unit 显式声明（米制示教器数值必须 unit="m"，
                 否则会被 pose 范数窗口拦下——@qa 实测旧版静默错 457.799 mm）。
            rpy_deg: 旋转 3 分量（度）。
            order: 欧拉顺序（无默认）。
            unit: "mm" | "m"（无默认）。
            pose_type: "absolute" | "delta"（无默认）。
        """
        try:
            T = euler_to_matrix(xyz, rpy_deg, order)
        except PoseError as e:
            return False, str(e)
        ok, msg, T_mm = admit_pose(T, unit, pose_type, "手动位姿")
        if not ok:
            return False, msg
        self._pose = T_mm
        self._unit = normalize_unit(unit)
        self._pose_type = normalize_pose_type(pose_type)
        return True, (f"位姿已录入 XYZ={list(xyz)} RPY={list(rpy_deg)}° "
                      f"({order}, unit={self._unit}, {self._pose_type})")

    def get_pose(self) -> tuple[bool, str, Optional[np.ndarray]]:
        if self._pose is None:
            return False, "尚未录入位姿（XYZ + RPY 或 4×4 矩阵）", None
        return True, "手动位姿", self._pose.copy()


class CsvPoseSource(PoseSource):
    """CSV 位姿离线回放。

    文件要求：
      - 必须带一行注释声明位姿类型（其余 `#` 行任意）：
            # pose_type: absolute        （或 delta，须与构造参数一致）
        理由：absolute 与 delta 的范数窗口不同（R11），无声明只能静默猜 → 拒收。
      - 数据行两种格式（忽略空行与 # 注释行）：
            16 列   —— 行优先 4×4 T_base2tool
            7 列    —— x y z rx ry rz order
        **6 列拒收**（无 order 字段，必然静默猜欧拉顺序）。

    构造时即完成全部校验，失败抛 PoseError（可读）；UI 侧可用 `load()` 拿元组。
    """

    def __init__(self, path: str, unit, pose_type, loop: bool = False):
        self._path = path
        self._loop = loop
        try:
            pt = normalize_pose_type(pose_type)
            unit = normalize_unit(unit)
        except (PoseError, ValueError) as e:
            raise PoseError(str(e)) from None
        poses, declared = self._parse(path, unit, pt)
        if declared is None:
            raise PoseError(
                f"位姿 CSV 缺少 '{CSV_POSE_TYPE_HEADER} absolute|delta' 声明行: {path}"
                f"（absolute/delta 窗口不同，无声明只能静默猜，故拒收）")
        if declared != pt:
            raise PoseError(
                f"CSV 声明的 pose_type={declared} 与入参 pose_type={pt} 不一致: {path}")
        self._poses = poses
        self._index = 0
        self._unit = unit
        self._pose_type = pt

    @classmethod
    def load(cls, path: str, unit, pose_type, loop: bool = False
             ) -> tuple[bool, str, Optional["CsvPoseSource"]]:
        """构造的元组形式（UI 用，不抛异常）。"""
        try:
            src = cls(path, unit, pose_type, loop=loop)
        except (PoseError, OSError) as e:
            return False, str(e), None
        return True, (f"已载入 {src.count()} 个位姿"
                      f"（unit={src._unit} pose_type={src._pose_type}, {path}）"), src

    @staticmethod
    def _parse(path: str, unit: str, pose_type: str
               ) -> tuple[List[np.ndarray], Optional[str]]:
        if not os.path.exists(path):
            raise PoseError(f"位姿 CSV 不存在: {path}")
        poses: List[np.ndarray] = []
        declared: Optional[str] = None
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                cells = [c.strip() for c in next(csv.reader([line])) if c.strip()]
                if len(cells) < 2:
                    # 制表符/空格分隔的示教器导出文件也收（逗号才是标准 CSV）
                    cells = line.split()
                if not cells:
                    continue
                if line.startswith("#"):
                    if CSV_POSE_TYPE_HEADER in line:
                        declared = line.split(CSV_POSE_TYPE_HEADER, 1)[1].strip().lower()
                        if declared not in ("absolute", "delta"):
                            raise PoseError(
                                f"CSV 第 {lineno} 行 pose_type 声明非法: {declared!r}"
                                f"（可选 absolute / delta）")
                    continue
                n = len(cells)
                if n == 16:
                    try:
                        vals = [float(c) for c in cells]
                    except ValueError as e:
                        raise PoseError(f"CSV 第 {lineno} 行含非数值: {e}") from None
                    pose = np.asarray(vals, dtype=np.float64).reshape(4, 4)
                elif n == 7:
                    # order 列是字符串，先按列数分流再转数值（旧版先 float 全行会崩）
                    try:
                        nums = [float(c) for c in cells[:6]]
                    except ValueError as e:
                        raise PoseError(
                            f"CSV 第 {lineno} 行前 6 列含非数值: {e}") from None
                    try:
                        pose = euler_to_matrix(nums[0:3], nums[3:6], cells[6])
                    except PoseError as e:
                        raise PoseError(f"CSV 第 {lineno} 行: {e}") from None
                elif n == 6:
                    raise PoseError(
                        f"CSV 第 {lineno} 行为 6 列格式（xyz+rpy 无 order 列）："
                        f"已拒收——欧拉顺序无声明只能静默猜，请补第 7 列 order "
                        f"或改用 16 列矩阵")
                else:
                    raise PoseError(
                        f"CSV 第 {lineno} 行格式无法识别（{n} 列）：{cells}")
                ok, msg, T_mm = admit_pose(pose, unit, pose_type,
                                           f"CSV 第 {lineno} 行位姿")
                if not ok:
                    raise PoseError(msg)
                assert T_mm is not None
                poses.append(T_mm)
        if not poses:
            raise PoseError(f"位姿 CSV 无有效数据行: {path}")
        return poses, declared

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
    PoseSource 接口实现；实现时 unit / pose_type 同为必填参数（R11），
    不要照抄 20260827 版 §5.5 的未验证示例。
    """

    def __init__(self, *args, **kwargs):
        self._config = (args, kwargs)

    def get_pose(self) -> tuple[bool, str, Optional[np.ndarray]]:
        return False, ("TcpRobot 未实现：真实协议待现场信息"
                       "（方案 §8-② 机器人品牌/位姿单位/旋转表示）"), None
