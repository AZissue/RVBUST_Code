# -*- coding: utf-8 -*-
"""
手眼结果加载器（handeye_result）—— A7 加载矩阵时不放行坏数据。

加载流程（方案 v2 §4.2）：
  json.load → success 守卫（K7）→ eye_in_hand 键（K6/K7）→ 按分支取键（K6）
  → A7 矩阵合法性校验 → to_mm(unit)（A2，unit 必填无 auto）→ 平移范数窗口（A2）

关键坑（均经本机实跑钉死）：
  K6  眼在手上键 T_cam2tool/T_tool2cam；眼在手外键 T_cam2base/T_base2cam，两者不同。
  K7  src/core/handeye.py:225 _fail() 失败分支只有 T_cam2tool/T_tool2cam，
      眼在手外失败路径没有 T_cam2base/T_base2cam 键 → 必须先判 success 再取键。
  A7  np.isfinite + 旋转块正交性 ‖RᵀR−I‖∞ < 1e-6 + det(R)≈+1 + 末行 [0,0,0,1]。

本模块为纯 numpy/json 实现，不依赖 src/，便于离线单测。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    from .unit_guard import check_translation_norm, normalize_unit, to_mm
except ImportError:  # 测试以顶层模块方式引入时
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from unit_guard import check_translation_norm, normalize_unit, to_mm

# 眼在手上/外各自的正变换键（K6）
KEY_T = {True: "T_cam2tool", False: "T_cam2base"}

ORTH_TOL = 1e-6      # 旋转块正交性容差（A7）
DET_TOL = 1e-6       # det(R)≈+1 容差（A7）
LAST_ROW_TOL = 1e-9  # 末行 [0,0,0,1] 容差（A7）


@dataclass
class HandEyeResult:
    """规范化后的手眼标定结果。validated 只有戳点验证（A3）通过才允许置 True。"""

    eye_in_hand: bool                      # True: T_handeye = T_cam2tool; False: T_cam2base
    T_handeye_mm: np.ndarray               # 4×4，平移已归一到 mm
    rms_t_mm: float = 0.0                  # 内符合指标，非可用性判据（K8，UI 黄字提示）
    rms_r_deg: float = 0.0
    n_samples: int = 0
    source: str = "manual"
    validated: bool = False                # A3 戳点门禁通过前一律 False（UNVERIFIED）

    def key(self) -> str:
        return KEY_T[self.eye_in_hand]

    # ------------------------------------------------------------------
    # 加载 / 构造
    # ------------------------------------------------------------------
    @staticmethod
    def load(path: str, unit: str,
             eye_in_hand: Optional[bool] = None
             ) -> tuple[bool, str, Optional["HandEyeResult"]]:
        """从 JSON 加载（src/core/handeye.py 的 save 格式或同义格式）。

        Args:
            path: JSON 路径。
            unit: 矩阵平移单位 "mm" | "m"，**必填，无 auto**（D4/F2）。
            eye_in_hand: 显式指定安装方式；None 则取 JSON 内字段；
                给出且与 JSON 不一致时拒绝（防止取错键分支）。

        Returns:
            (ok, message, result|None)
        """
        try:
            unit = normalize_unit(unit)
        except ValueError as e:
            return False, str(e), None

        if not os.path.exists(path):
            return False, f"文件不存在: {path}", None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return False, f"JSON 解析失败: {e}", None
        if not isinstance(data, dict):
            return False, "JSON 顶层必须是对象", None
        return HandEyeResult._from_dict(data, unit, eye_in_hand,
                                        source=os.path.abspath(path))

    @staticmethod
    def from_matrix(T, unit: str, eye_in_hand: bool
                    ) -> tuple[bool, str, Optional["HandEyeResult"]]:
        """手动录入 4×4（A2/R4b：矩阵录入入口是必需项）。

        Args:
            T: 16 个数（行优先，与官方 MAT 口径一致）或 4 行 4 列。
            unit: "mm" | "m"，必填。
            eye_in_hand: 安装方式必填（无 JSON 字段可推断）。
        """
        try:
            unit = normalize_unit(unit)
        except ValueError as e:
            return False, str(e), None

        arr = np.asarray(T, dtype=np.float64)
        if arr.size == 16:
            arr = arr.reshape(4, 4)
        ok, msg = validate_matrix(arr)
        if not ok:
            return False, f"手动录入矩阵非法: {msg}", None
        return HandEyeResult._finish(arr, unit, bool(eye_in_hand),
                                     rms_t_mm=0.0, rms_r_deg=0.0, n_samples=0,
                                     source="manual")

    # ------------------------------------------------------------------
    # 内部流程
    # ------------------------------------------------------------------
    @staticmethod
    def _from_dict(data: dict, unit: str,
                   eye_in_hand: Optional[bool],
                   source: str) -> tuple[bool, str, Optional["HandEyeResult"]]:
        # K7：success 守卫（_fail() 输出 success=False 且缺眼在手外键，先判再放行）
        if "success" not in data:
            return False, "JSON 缺少 'success' 字段，不是手眼标定结果文件", None
        if data["success"] is not True:
            return False, (
                f"标定未成功（success={data['success']!r}，"
                f"message={data.get('message', '无')}），拒绝加载"), None

        # K6/K7：eye_in_hand 键决定取键分支
        if "eye_in_hand" not in data:
            return False, "JSON 缺少 'eye_in_hand' 字段，无法确定矩阵键分支", None
        json_eih = bool(data["eye_in_hand"])
        if eye_in_hand is not None and bool(eye_in_hand) != json_eih:
            return False, (
                f"安装方式不一致：JSON 为 {'眼在手上' if json_eih else '眼在手外'}，"
                f"传入为 {'眼在手上' if eye_in_hand else '眼在手外'}"), None

        key = KEY_T[json_eih]
        if key not in data or data[key] is None:
            return False, f"JSON 缺少矩阵键 '{key}'", None
        T = np.asarray(data[key], dtype=np.float64)

        ok, msg = validate_matrix(T)
        if not ok:
            return False, f"矩阵非法: {msg}", None

        return HandEyeResult._finish(
            T, unit, json_eih,
            rms_t_mm=float(data.get("rms_t_mm", 0.0)),
            rms_r_deg=float(data.get("rms_r_deg", 0.0)),
            n_samples=int(data.get("n_samples", 0)),
            source=source)

    @staticmethod
    def _finish(T, unit: str, eye_in_hand: bool,
                rms_t_mm: float, rms_r_deg: float, n_samples: int,
                source: str) -> tuple[bool, str, Optional["HandEyeResult"]]:
        T_mm = to_mm(T, unit)
        ok, msg = check_translation_norm(T_mm, eye_in_hand)  # A2 范数窗口
        if not ok:
            return False, msg, None
        res = HandEyeResult(
            eye_in_hand=eye_in_hand,
            T_handeye_mm=T_mm,
            rms_t_mm=rms_t_mm, rms_r_deg=rms_r_deg,
            n_samples=n_samples, source=source,
            validated=False)  # 一律 UNVERIFIED，戳点（A3）通过才置 True
        return True, msg, res


def validate_matrix(T: np.ndarray) -> tuple[bool, str]:
    """A7 矩阵合法性校验。"""
    T = np.asarray(T, dtype=np.float64)
    if T.shape != (4, 4):
        return False, f"必须是 4×4 矩阵，实际 shape={T.shape}"
    if not np.all(np.isfinite(T)):
        return False, "含 NaN/Inf 非有限值"
    R = T[:3, :3]
    orth = float(np.max(np.abs(R.T @ R - np.eye(3))))
    if orth >= ORTH_TOL:
        return False, f"旋转块非正交 ‖RᵀR−I‖∞={orth:.3e}（≥{ORTH_TOL:g}）"
    det = float(np.linalg.det(R))
    if abs(det - 1.0) >= DET_TOL:
        return False, f"det(R)={det:.6f} ≠ +1（含镜像/缩放）"
    if not np.allclose(T[3], [0.0, 0.0, 0.0, 1.0], atol=LAST_ROW_TOL):
        return False, f"末行应为 [0,0,0,1]，实际 {T[3].tolist()}"
    return True, "ok"
