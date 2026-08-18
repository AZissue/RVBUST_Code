# -*- coding: utf-8 -*-
"""
机器人手眼标定封装（HandEyeCalibrator）。

本模块对 OpenCV cv2.calibrateHandEye 的参数约定进行了合成实验标定，
实际使用方式与 OpenCV 官方文档的符号命名相反，总结如下：

Eye-in-Hand（相机装在机器人末端）：
  输入：
    R_gripper2base / t_gripper2base -> T_base2tool（基座→工具法兰）
    R_target2cam     / t_target2cam     -> T_board2cam（标定板→相机）
  输出：
    R_cam2gripper / t_cam2gripper -> T_cam2tool（相机→工具法兰）
  变换链：
    T_base2board = T_base2tool @ T_cam2tool @ T_board2cam

Eye-to-Hand（相机固定在基座，标定板在工具上）：
  输入：
    R_base2gripper / t_base2gripper -> T_base2tool（基座→工具法兰）
    R_target2cam   / t_target2cam   -> T_board2cam（标定板→相机）
  输出：
    R_cam2base / t_cam2base -> T_cam2base（相机→基座）
  变换链：
    T_board2cam = T_base2cam @ T_base2board
                = T_base2cam @ inv(T_base2tool) @ T_board2tool

一致性误差：利用标定结果反推固定的位姿（Eye-in-Hand 为 T_base2board，
Eye-to-Hand 为 T_board2tool），计算多组样本反推结果的平移/旋转分散程度。
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import cv2

from .utils import logger


class HandEyeCalibrator:
    """手眼标定器（当前优先支持 Eye-in-Hand）。"""

    def __init__(self, eye_in_hand: bool = True,
                 method: int = cv2.CALIB_HAND_EYE_TSAI):
        """
        Args:
            eye_in_hand: True 为 Eye-in-Hand（相机在末端）；
                         False 为 Eye-to-Hand（相机固定）。
            method: OpenCV 手眼求解算法（TSAI / PARK / HORAUD / ANDREFF / DANIILIDIS）。
        """
        self.eye_in_hand = eye_in_hand
        self.method = method
        self.T_base2tool_list: List[np.ndarray] = []
        self.T_board2cam_list: List[np.ndarray] = []

    # ------------------------------------------------------------------
    # 样本采集
    # ------------------------------------------------------------------
    def add_sample(self, T_base2tool: np.ndarray, T_board2cam: np.ndarray):
        """添加一组样本。

        Args:
            T_base2tool: 4×4 齐次矩阵，机器人基座→工具法兰。
            T_board2cam: 4×4 齐次矩阵，标定板→相机。
        """
        self.T_base2tool_list.append(np.asarray(T_base2tool, dtype=np.float64))
        self.T_board2cam_list.append(np.asarray(T_board2cam, dtype=np.float64))

    def sample_count(self) -> int:
        return len(self.T_base2tool_list)

    def clear(self):
        """清空所有样本。"""
        self.T_base2tool_list.clear()
        self.T_board2cam_list.clear()

    # ------------------------------------------------------------------
    # 标定求解
    # ------------------------------------------------------------------
    def calibrate(self) -> Dict:
        """执行手眼标定。

        Returns:
            {
                'success': bool,
                'message': str,
                'T_cam2tool': np.ndarray | None,   # 相机→工具法兰（Eye-in-Hand 结果）
                'T_tool2cam': np.ndarray | None,   # 工具法兰→相机
                'rms_t_mm': float,                 # 标定板在基座系下平移一致性误差（mm）
                'rms_r_deg': float,                # 旋转一致性误差（度）
                'n_samples': int,
            }
        """
        n = self.sample_count()
        if n < 3:
            return self._fail("手眼标定至少需要 3 组样本")

        if self.eye_in_hand:
            return self._calibrate_eye_in_hand()
        return self._calibrate_eye_to_hand()

    def _calibrate_eye_in_hand(self) -> Dict:
        """Eye-in-Hand：求解 T_cam2tool。"""
        # 经最小合成实验验证的 OpenCV 实际约定：
        #   R_gripper2base / t_gripper2base 为 T_base2tool（基座→工具法兰）
        #   R_target2cam / t_target2cam 为 T_board2cam（标定板→相机）
        #   返回值 R_cam2gripper / t_cam2gripper 实际为 T_cam2tool（相机→工具法兰）
        R_gripper2base = [T[:3, :3] for T in self.T_base2tool_list]
        t_gripper2base = [T[:3, 3] for T in self.T_base2tool_list]
        R_target2cam = [T[:3, :3] for T in self.T_board2cam_list]
        t_target2cam = [T[:3, 3] for T in self.T_board2cam_list]

        try:
            R_cam2tool, t_cam2tool = cv2.calibrateHandEye(
                R_gripper2base, t_gripper2base,
                R_target2cam, t_target2cam,
                method=self.method)
        except cv2.error as e:
            return self._fail(f"OpenCV 手眼求解失败: {e}")

        T_cam2tool = np.eye(4, dtype=np.float64)
        T_cam2tool[:3, :3] = R_cam2tool
        T_cam2tool[:3, 3] = t_cam2tool.flatten()

        # 一致性：固定标定板在基座系下位姿应恒定
        # T_base2board = T_base2tool @ T_cam2tool @ T_board2cam
        T_base2boards = [
            self.T_base2tool_list[i] @ T_cam2tool @ self.T_board2cam_list[i]
            for i in range(self.sample_count())
        ]
        rms_t, rms_r = self._compute_consistency_error(T_base2boards)

        return {
            'success': True,
            'message': f"手眼标定完成，样本 {self.sample_count()}，"
                       f"平移一致性 {rms_t:.3f} mm，旋转一致性 {rms_r:.2f}°",
            'T_cam2tool': T_cam2tool,
            'T_tool2cam': np.linalg.inv(T_cam2tool),
            'rms_t_mm': float(rms_t),
            'rms_r_deg': float(rms_r),
            'n_samples': self.sample_count(),
        }

    def _calibrate_eye_to_hand(self) -> Dict:
        """Eye-to-Hand：求解 T_cam2base（相机在基座系下固定位姿）。

        经最小合成实验验证的 OpenCV 实际约定：
          R_base2gripper / t_base2gripper 为 T_base2tool（基座→工具法兰）
          R_target2cam / t_target2cam 为 T_board2cam（标定板→相机）
          返回值 R_cam2base / t_cam2base 为 T_cam2base（相机→基座）
        """
        R_base2gripper = [T[:3, :3] for T in self.T_base2tool_list]
        t_base2gripper = [T[:3, 3] for T in self.T_base2tool_list]
        R_target2cam = [T[:3, :3] for T in self.T_board2cam_list]
        t_target2cam = [T[:3, 3] for T in self.T_board2cam_list]

        try:
            R_cam2base, t_cam2base = cv2.calibrateHandEye(
                R_base2gripper, t_base2gripper,
                R_target2cam, t_target2cam,
                method=self.method)
        except cv2.error as e:
            return self._fail(f"OpenCV 手眼求解失败: {e}")

        T_cam2base = np.eye(4, dtype=np.float64)
        T_cam2base[:3, :3] = R_cam2base
        T_cam2base[:3, 3] = t_cam2base.flatten()

        # 一致性：相机在基座系下位姿固定，反推板在工具上的位姿应恒定
        # T_board2cam = T_base2cam @ T_base2board = T_base2cam @ inv(T_base2tool) @ T_board2tool
        # => T_board2tool = T_base2tool @ inv(T_base2cam) @ T_board2cam
        #    = T_base2tool @ T_cam2base @ T_board2cam
        T_board2tools = [
            self.T_base2tool_list[i] @ T_cam2base @ self.T_board2cam_list[i]
            for i in range(self.sample_count())
        ]
        rms_t, rms_r = self._compute_consistency_error(T_board2tools)

        return {
            'success': True,
            'message': f"手眼标定完成（Eye-to-Hand），样本 {self.sample_count()}，"
                       f"平移一致性 {rms_t:.3f} mm，旋转一致性 {rms_r:.2f}°",
            'T_cam2base': T_cam2base,
            'T_base2cam': np.linalg.inv(T_cam2base),
            'rms_t_mm': float(rms_t),
            'rms_r_deg': float(rms_r),
            'n_samples': self.sample_count(),
        }

    @staticmethod
    def _compute_consistency_error(poses: List[np.ndarray]) -> Tuple[float, float]:
        """计算多组位姿的一致性误差（平移 mm / 旋转 deg）。"""
        ts = np.array([T[:3, 3] for T in poses])
        mean_t = ts.mean(axis=0)
        rms_t = float(np.sqrt(np.mean(np.sum((ts - mean_t) ** 2, axis=1))))

        Rs = [T[:3, :3] for T in poses]
        R_mean = HandEyeCalibrator._average_rotations(Rs)
        angles = []
        for R in Rs:
            cos_val = (np.trace(R.T @ R_mean) - 1.0) / 2.0
            cos_val = np.clip(cos_val, -1.0, 1.0)
            angles.append(np.arccos(cos_val))
        rms_r = float(np.degrees(np.sqrt(np.mean(np.array(angles) ** 2))))
        return rms_t, rms_r

    @staticmethod
    def _average_rotations(Rs: List[np.ndarray]) -> np.ndarray:
        """四元数平均（处理 q/-q 歧义）。"""
        from scipy.spatial.transform import Rotation
        quats = Rotation.from_matrix(Rs).as_quat()
        q_ref = quats[0]
        fixed = []
        for q in quats:
            if np.dot(q, q_ref) < 0:
                q = -q
            fixed.append(q)
        q_avg = np.mean(fixed, axis=0)
        q_avg /= np.linalg.norm(q_avg)
        return Rotation.from_quat(q_avg).as_matrix()

    def _fail(self, message: str) -> Dict:
        logger.warning(f"HandEyeCalibrator: {message}")
        return {
            'success': False,
            'message': message,
            'T_cam2tool': None,
            'T_tool2cam': None,
            'rms_t_mm': 0.0,
            'rms_r_deg': 0.0,
            'n_samples': self.sample_count(),
        }

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def save(self, path: str) -> bool:
        """保存标定结果到 JSON。"""
        res = self.calibrate()
        if not res.get('success'):
            logger.warning(f"手眼结果保存失败: {res.get('message')}")
            return False
        data = {
            'eye_in_hand': self.eye_in_hand,
            'method': int(self.method),
            'n_samples': res['n_samples'],
            'rms_t_mm': res['rms_t_mm'],
            'rms_r_deg': res['rms_r_deg'],
        }
        if 'T_cam2tool' in res and res['T_cam2tool'] is not None:
            data['T_cam2tool'] = res['T_cam2tool'].tolist()
            data['T_tool2cam'] = res['T_tool2cam'].tolist()
        if 'T_cam2base' in res and res['T_cam2base'] is not None:
            data['T_cam2base'] = res['T_cam2base'].tolist()
            data['T_base2cam'] = res['T_base2cam'].tolist()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存手眼结果失败: {e}")
            return False

    @staticmethod
    def load_result(path: str) -> Optional[Dict]:
        """加载已保存的手眼结果 JSON。"""
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for key in ('T_cam2tool', 'T_tool2cam', 'T_cam2base', 'T_base2cam'):
                if key in data and data[key] is not None:
                    data[key] = np.asarray(data[key], dtype=np.float64)
            return data
        except Exception as e:
            logger.error(f"加载手眼结果失败: {e}")
            return None
