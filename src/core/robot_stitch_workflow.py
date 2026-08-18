# -*- coding: utf-8 -*-
"""
机器人手眼配合拼接工作流（RobotStitchWorkflow）。

模式 D 核心：相机配合机器人做多视角扫描拼接。
  - 利用手眼标定结果，把相机坐标系点云变换到机器人基座系；
  - 不依赖标记物，适合无纹理工件 / 自动化产线；
  - 支持 Eye-in-Hand（相机在末端）和 Eye-to-Hand（相机固定）。

坐标链：
  Eye-in-Hand: T_base2cam = T_base2tool @ T_tool2cam
               其中 T_tool2cam = inv(T_cam2tool)（手眼标定结果）
  Eye-to-Hand: T_base2cam = T_cam2base^{-1} = T_base2cam（手眼标定结果）
               此时相机固定在基座系，与机器人位姿无关。

每帧拼接：p_base = T_base2cam @ p_cam
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import open3d as o3d

from .workflow_base import WorkflowBase
from .robot_interface import RobotInterface
from .frame_data import FrameData
from .utils import logger


class RobotStitchWorkflow(WorkflowBase):
    """机器人手眼配合拼接工作流。"""

    STATE_IDLE = "idle"
    STATE_CONNECTED = "connected"
    STATE_READY = "ready"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state = self.STATE_IDLE
        self._robot: Optional[RobotInterface] = None
        self._eye_in_hand: bool = True
        self._T_handeye: Optional[np.ndarray] = None  # Eye-in-Hand: T_cam2tool; Eye-to-Hand: T_cam2base
        self._frames: List[FrameData] = []
        self._T_base2cam_list: List[np.ndarray] = []
        self._merged_pcd: Optional[o3d.geometry.PointCloud] = None

    # ------------------------------------------------------------------
    # 抽象接口实现
    # ------------------------------------------------------------------
    def get_mode_name(self) -> str:
        return "robot_stitch"

    def get_state(self) -> str:
        return self._state

    def can_proceed(self) -> Tuple[bool, str]:
        if self._state == self.STATE_IDLE:
            return True, "可以连接相机和机器人"
        if self._state == self.STATE_CONNECTED:
            return bool(self._T_handeye is not None), "请先加载或标定手眼结果"
        if self._state == self.STATE_READY:
            return True, "可以开始扫描拼接"
        return False, f"未知状态: {self._state}"

    def reset(self):
        """重置工作流。"""
        self._state = self.STATE_IDLE
        self._robot = None
        self._T_handeye = None
        self._frames.clear()
        self._T_base2cam_list.clear()
        self._merged_pcd = None
        logger.info("机器人拼接工作流已重置")

    # ------------------------------------------------------------------
    # 机器人 / 手眼配置
    # ------------------------------------------------------------------
    def set_robot(self, robot: RobotInterface) -> Tuple[bool, str]:
        """设置并连接机器人接口。"""
        if self._robot is not None and self._robot.is_connected():
            self._robot.disconnect()
        self._robot = robot
        ok, msg = robot.connect()
        if not ok:
            return False, msg
        self._state = self.STATE_CONNECTED
        return True, msg

    def set_handeye_result(self, eye_in_hand: bool, T_handeye: np.ndarray) -> Tuple[bool, str]:
        """加载手眼标定结果。

        Args:
            eye_in_hand: True 为 Eye-in-Hand（T_handeye = T_cam2tool）；
                         False 为 Eye-to-Hand（T_handeye = T_cam2base）。
            T_handeye: 4×4 齐次矩阵。
        """
        T = np.asarray(T_handeye, dtype=np.float64)
        if T.shape != (4, 4):
            return False, "手眼结果必须是 4×4 齐次矩阵"
        self._eye_in_hand = eye_in_hand
        self._T_handeye = T
        if self._state == self.STATE_CONNECTED:
            self._state = self.STATE_READY
        logger.info(f"手眼结果已加载: {'Eye-in-Hand' if eye_in_hand else 'Eye-to-Hand'}")
        return True, "手眼结果已加载"

    def compute_cam2base(self, T_base2tool: np.ndarray) -> Optional[np.ndarray]:
        """由当前机器人位姿和手眼结果求 T_cam2base（把相机坐标变换到基座系）。"""
        if self._T_handeye is None:
            return None
        T_base2tool = np.asarray(T_base2tool, dtype=np.float64)
        if self._eye_in_hand:
            # Eye-in-Hand: p_base = T_base2tool @ p_tool
            #              p_tool = T_cam2tool @ p_cam
            #              => T_cam2base = T_base2tool @ T_cam2tool
            return T_base2tool @ self._T_handeye
        # Eye-to-Hand: 相机固定在基座系，T_handeye 即为 T_cam2base
        return self._T_handeye

    # ------------------------------------------------------------------
    # 扫描拼接
    # ------------------------------------------------------------------
    def capture_frame(self, camera_id: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """在当前机器人位姿下触发相机拍摄，并记录变换。

        Returns:
            (success, message, info)
        """
        if self._state != self.STATE_READY:
            return False, "工作流未就绪，请先连接机器人并加载手眼结果", None
        if self._robot is None or not self._robot.is_connected():
            return False, "机器人未连接", None

        T_base2tool = self._robot.get_current_pose()
        if T_base2tool is None:
            return False, "无法读取机器人当前位姿", None

        T_cam2base = self.compute_cam2base(T_base2tool)
        if T_cam2base is None:
            return False, "手眼结果无效", None

        connected = self.camera_manager.get_connected_ids()
        if not connected:
            return False, "没有已连接相机", None
        cam_id = camera_id or connected[0]
        frame = self.camera_manager.capture(cam_id)
        if frame is None:
            return False, "相机拍摄失败", None

        self._frames.append(frame)
        self._T_base2cam_list.append(T_cam2base)

        # 增量合并：把相机系点云变换到基座系
        pcd = frame.load_pointcloud_o3d()
        if pcd is not None and len(pcd.points) > 0:
            pcd_t = pcd.transform(T_cam2base.astype(np.float64))
            if self._merged_pcd is None:
                self._merged_pcd = o3d.geometry.PointCloud(pcd_t)
            else:
                self._merged_pcd += pcd_t

        info = {
            'frame_id': frame.frame_id,
            'camera_id': cam_id,
            'n_frames': len(self._frames),
            'T_cam2base': T_cam2base,
        }
        logger.info(f"机器人拼接：第 {len(self._frames)} 帧拍摄完成，相机 {cam_id}")
        return True, f"第 {len(self._frames)} 帧拍摄并合并完成", info

    def get_merged_pointcloud(self, processor=None):
        """获取当前拼接点云。"""
        if self._merged_pcd is None:
            return None
        if processor is not None:
            pcd, _ = processor.process(self._merged_pcd)
            return pcd
        return self._merged_pcd

    def get_frame_count(self) -> int:
        return len(self._frames)

    def save_merged_ply(self, path: str) -> Tuple[bool, str]:
        """保存合并点云到 PLY。"""
        if self._merged_pcd is None:
            return False, "无合并点云可保存"
        try:
            o3d.io.write_point_cloud(path, self._merged_pcd)
            return True, f"已保存 {path}"
        except Exception as e:
            logger.error(f"保存合并点云失败: {e}")
            return False, f"保存失败: {e}"
