# -*- coding: utf-8 -*-
"""
会话落盘与恢复（session）—— A6 可复盘。

会话目录结构（方案 §1 A6，固定四项）：
    handeye.json        手眼矩阵与元数据（eye_in_hand / T_handeye_mm / rms / n_samples /
                        source / validated），重新加载后 validated 状态不丢
    poses.json          采集用过的全部位姿（毫米，行优先 16 数 + unit/pose_type 元数据）
    frames/frame_*.ply  每帧基座系点云（ASCII PLY，含颜色；无颜色则只写 xyz）
    error_report.json   戳点门禁等验证报告（TipTouchValidator.check() 的字典）

验收口径（A6）：重新打开能还原——点数一致、位姿一致。
PLY 读写为纯 numpy 实现（ASCII），不依赖 open3d / src/，便于离线单测；
帧入参可以是 open3d 点云、N×3 数组或 (xyz, colors) 元组。

内部统一毫米（§4.1）。fail-closed：任一必需文件缺失/损坏 → 拒绝恢复，
不返回半截会话。
"""

from __future__ import annotations

import json
import os
from typing import List, Optional, Sequence

import numpy as np

HANDEYE_FILE = "handeye.json"
POSES_FILE = "poses.json"
FRAMES_DIR = "frames"
ERROR_REPORT_FILE = "error_report.json"


class SessionError(ValueError):
    """会话落盘/恢复失败（文件缺失、格式损坏、内容不一致）。"""


# ----------------------------------------------------------------------
# 帧 → (xyz, colors)
# ----------------------------------------------------------------------
def _frame_to_arrays(frame) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """把帧规整成 (xyz N×3 mm, colors N×3∈[0,1] | None)。

    接受：open3d 点云（有 .points）、(xyz, colors) 元组、N×3 数组（无色）。
    """
    colors: Optional[np.ndarray] = None
    if isinstance(frame, tuple) and len(frame) == 2:
        xyz_raw, col_raw = frame
        if col_raw is not None:
            colors = np.asarray(col_raw, dtype=np.float64)
    else:
        xyz_raw = getattr(frame, "points", frame)
        col_attr = getattr(frame, "colors", None)
        if col_attr is not None and len(col_attr) > 0:
            colors = np.asarray(col_attr, dtype=np.float64)
    xyz = np.asarray(xyz_raw, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) == 0:
        raise SessionError(f"帧必须是 N×3 点集（毫米，非空），实际 shape={xyz.shape}")
    if not np.all(np.isfinite(xyz)):
        raise SessionError("帧点云含 NaN/Inf 非有限值：拒绝落盘")
    if colors is not None:
        if colors.shape != xyz.shape:
            raise SessionError(
                f"帧颜色必须与点同形 ({xyz.shape})，实际 {colors.shape}")
        if not np.all(np.isfinite(colors)):
            raise SessionError("帧颜色含 NaN/Inf 非有限值：拒绝落盘")
        colors = np.clip(colors, 0.0, 1.0)
    return xyz, colors


# ----------------------------------------------------------------------
# 极简 ASCII PLY（纯 numpy，xyz + 可选 uchar rgb）
# ----------------------------------------------------------------------
def write_ply(path: str, xyz: np.ndarray,
              colors: Optional[np.ndarray] = None) -> None:
    """写 ASCII PLY（毫米 xyz；colors ∈ [0,1] 时写 uchar rgb）。"""
    n = len(xyz)
    has_color = colors is not None
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write("comment MultiCameraCalibration robot_handeye_transform session\n")
        f.write(f"element vertex {n}\n")
        f.write("property double x\nproperty double y\nproperty double z\n")
        if has_color:
            f.write("property uchar red\nproperty uchar green\n"
                    "property uchar blue\n")
        f.write("end_header\n")
        if has_color:
            rgb = np.rint(colors * 255.0).astype(np.uint8)
            for p, c in zip(xyz, rgb):
                f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f} "
                        f"{int(c[0])} {int(c[1])} {int(c[2])}\n")
        else:
            for p in xyz:
                f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")


def read_ply(path: str) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """读回 write_ply 写出的 ASCII PLY → (xyz N×3, colors N×3∈[0,1] | None)。"""
    with open(path, "r", encoding="utf-8") as f:
        first = f.readline().strip()
        if first != "ply":
            raise SessionError(f"不是 PLY 文件: {path}")
        n = None
        has_color = False
        for line in f:
            line = line.strip()
            if line.startswith("element vertex"):
                n = int(line.split()[-1])
            elif line.startswith("property uchar"):
                has_color = True
            elif line == "end_header":
                break
        else:
            raise SessionError(f"PLY 头不完整（缺 end_header）: {path}")
        if n is None:
            raise SessionError(f"PLY 头缺 element vertex: {path}")
        rows = []
        for _ in range(n):
            line = f.readline()
            if not line:
                raise SessionError(f"PLY 顶点数不足：声明 {n}，实际 {len(rows)}: {path}")
            rows.append([float(v) for v in line.split()])
    arr = np.asarray(rows, dtype=np.float64)
    xyz = arr[:, :3]
    # 盘上存的是 0~255 整数字节，读回除 255 归一（不要再 rint：会把 0~1 值取整成 0/1）
    colors = (arr[:, 3:6] / 255.0).clip(0.0, 1.0) if has_color else None
    return xyz, colors


# ----------------------------------------------------------------------
# 手眼结果序列化（与 core/handeye_result.py 的 HandEyeResult 字段一致）
# ----------------------------------------------------------------------
def handeye_to_dict(handeye) -> dict:
    """HandEyeResult（或同字段对象/字典）→ 可 JSON 化字典。"""
    if isinstance(handeye, dict):
        data = dict(handeye)
    elif hasattr(handeye, "T_handeye_mm"):
        data = {k: getattr(handeye, k) for k in
                ("eye_in_hand", "T_handeye_mm", "rms_t_mm", "rms_r_deg",
                 "n_samples", "source", "validated")}
    else:
        raise SessionError(
            "handeye 必须是 HandEyeResult 或同字段字典（含 T_handeye_mm）")
    try:
        T = np.asarray(data["T_handeye_mm"], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as e:
        raise SessionError(
            f"handeye 缺/坏 T_handeye_mm 字段（须为 4×4 数值矩阵）: {e}") from None
    if T.shape != (4, 4) or not np.all(np.isfinite(T)):
        raise SessionError("手眼矩阵必须是有限 4×4 才能落盘")
    return {
        "eye_in_hand": bool(data["eye_in_hand"]),
        "T_handeye_mm": T.tolist(),
        "rms_t_mm": float(data.get("rms_t_mm", 0.0)),
        "rms_r_deg": float(data.get("rms_r_deg", 0.0)),
        "n_samples": int(data.get("n_samples", 0)),
        "source": str(data.get("source", "manual")),
        "validated": bool(data.get("validated", False)),
    }


def handeye_from_dict(data: dict) -> dict:
    """字典 → 还原（T 转回 np.ndarray，毫米域）。"""
    required = ("eye_in_hand", "T_handeye_mm", "validated")
    missing = [k for k in required if k not in data]
    if missing:
        raise SessionError(f"handeye.json 缺字段 {missing}，不是本原型的会话文件")
    T = np.asarray(data["T_handeye_mm"], dtype=np.float64)
    if T.shape != (4, 4) or not np.all(np.isfinite(T)):
        raise SessionError("handeye.json 矩阵非法：必须是有限 4×4")
    return {
        "eye_in_hand": bool(data["eye_in_hand"]),
        "T_handeye_mm": T,
        "rms_t_mm": float(data.get("rms_t_mm", 0.0)),
        "rms_r_deg": float(data.get("rms_r_deg", 0.0)),
        "n_samples": int(data.get("n_samples", 0)),
        "source": str(data.get("source", "manual")),
        "validated": bool(data["validated"]),
    }


# ----------------------------------------------------------------------
# 会话落盘 / 恢复
# ----------------------------------------------------------------------
def save_session(session_dir: str, handeye,
                 poses: Sequence[np.ndarray],
                 frames: Sequence,
                 error_report: Optional[dict] = None
                 ) -> tuple[bool, str]:
    """把一次采集会话完整落盘（A6 四项）。

    Args:
        session_dir: 会话目录（不存在则创建；已存在则覆盖同名文件）。
        handeye: HandEyeResult 或同字段字典（validated 状态随盘保存）。
        poses: 采集用过的 T_base2tool（绝对位姿，毫米，4×4 或 16 数）。
        frames: 每帧基座系点云（open3d / N×3 / (xyz, colors) 元组）。
        error_report: 验证报告字典（TipTouchValidator.check() 输出等），
            默认 {} 也会落盘（A6 目录结构固定含 error_report.json）。

    Returns:
        (ok, message)。任一输入非法 → 不写盘（不留下半截会话），返回 False。
    """
    try:
        he = handeye_to_dict(handeye)
        pose_mats: List[List[float]] = []
        for i, p in enumerate(poses):
            arr = np.asarray(p, dtype=np.float64)
            if arr.size == 16:
                arr = arr.reshape(4, 4)
            if arr.shape != (4, 4) or not np.all(np.isfinite(arr)):
                raise SessionError(f"位姿 #{i + 1} 必须是有限 4×4，实际 shape={arr.shape}")
            pose_mats.append(arr.reshape(-1).tolist())
        frame_arrays = [_frame_to_arrays(fr) for fr in frames]
    except SessionError as e:
        return False, str(e)

    os.makedirs(session_dir, exist_ok=True)
    frames_dir = os.path.join(session_dir, FRAMES_DIR)
    os.makedirs(frames_dir, exist_ok=True)

    with open(os.path.join(session_dir, HANDEYE_FILE), "w",
              encoding="utf-8") as f:
        json.dump(he, f, ensure_ascii=False, indent=2)
    with open(os.path.join(session_dir, POSES_FILE), "w",
              encoding="utf-8") as f:
        json.dump({"unit": "mm", "pose_type": "absolute", "poses": pose_mats},
                  f, ensure_ascii=False, indent=2)
    # 旧帧清理：防止上次会话残留的 frame_*.ply 混入本次恢复
    for old in os.listdir(frames_dir):
        if old.endswith(".ply"):
            os.remove(os.path.join(frames_dir, old))
    for i, (xyz, colors) in enumerate(frame_arrays):
        write_ply(os.path.join(frames_dir, f"frame_{i:03d}.ply"), xyz, colors)
    with open(os.path.join(session_dir, ERROR_REPORT_FILE), "w",
              encoding="utf-8") as f:
        json.dump(error_report if error_report is not None else {},
                  f, ensure_ascii=False, indent=2, default=str)
    return True, (f"会话已保存：{os.path.abspath(session_dir)}"
                  f"（位姿 {len(pose_mats)}、帧 {len(frame_arrays)}）")


def load_session(session_dir: str) -> tuple[bool, str, Optional[dict]]:
    """恢复会话（A6：点数一致、位姿一致、validated 状态还原）。

    Returns:
        (ok, message, session|None)。session = {
            "handeye": {..., "T_handeye_mm": np.ndarray},
            "poses": [np.ndarray(4,4), ...],
            "frames": [{"xyz": np.ndarray, "colors": np.ndarray|None}, ...],
            "error_report": dict,
        }
        必需文件缺失/损坏 → (False, msg, None)，fail-closed 不返回半截。
    """
    if not os.path.isdir(session_dir):
        return False, f"会话目录不存在: {session_dir}", None
    try:
        with open(os.path.join(session_dir, HANDEYE_FILE), "r",
                  encoding="utf-8") as f:
            handeye = handeye_from_dict(json.load(f))
        with open(os.path.join(session_dir, POSES_FILE), "r",
                  encoding="utf-8") as f:
            poses_data = json.load(f)
        if not isinstance(poses_data, dict) or "poses" not in poses_data:
            raise SessionError("poses.json 格式非法：缺 'poses' 键")
        poses = []
        for i, row in enumerate(poses_data["poses"]):
            arr = np.asarray(row, dtype=np.float64)
            if arr.size != 16 or not np.all(np.isfinite(arr)):
                raise SessionError(f"poses.json 第 {i + 1} 个位姿非法（须 16 个有限数）")
            poses.append(arr.reshape(4, 4))
        frames_dir = os.path.join(session_dir, FRAMES_DIR)
        frames = []
        if os.path.isdir(frames_dir):
            for name in sorted(os.listdir(frames_dir)):
                if name.endswith(".ply"):
                    xyz, colors = read_ply(os.path.join(frames_dir, name))
                    frames.append({"xyz": xyz, "colors": colors})
        err_path = os.path.join(session_dir, ERROR_REPORT_FILE)
        with open(err_path, "r", encoding="utf-8") as f:
            error_report = json.load(f)
    except (OSError, json.JSONDecodeError, SessionError) as e:
        return False, f"会话恢复失败: {e}", None
    return True, (f"会话已恢复：位姿 {len(poses)}、帧 {len(frames)}"
                  f"（validated={handeye['validated']}）"), {
        "handeye": handeye,
        "poses": poses,
        "frames": frames,
        "error_report": error_report,
    }
