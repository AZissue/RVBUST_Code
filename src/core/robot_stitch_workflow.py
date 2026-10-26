# -*- coding: utf-8 -*-
"""Robot hand-eye scanning in the robot base coordinate system.

Eye-in-Hand: T_cam2base = T_base2tool @ T_cam2tool.
Eye-to-Hand: T_handeye is already the fixed T_cam2base.
All transforms and point coordinates use millimetres.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import open3d as o3d

from .workflow_base import WorkflowBase
from .robot_interface import RobotInterface
from .frame_data import FrameData
from .pcd_utils import merge_pointclouds
from .utils import logger, write_point_cloud_atomic
from .robot_handeye import (
    CsvPoseSource, HandEyeResult, ManualPoseSource, PoseSource, TipTouchValidator,
)
from .robot_handeye.pose_source import admit_pose
from .robot_handeye.unit_guard import check_rigid_4x4
from .robot_handeye.transform_chain import compute_cam2base, transform_pcd


class _RobotPoseSource(PoseSource):
    def __init__(self, robot: RobotInterface):
        self.robot = robot

    def get_pose(self):
        if not self.robot.is_connected():
            return False, '机器人未连接', None
        pose = self.robot.get_current_pose()
        if pose is None:
            return False, '无法读取机器人当前位姿', None
        return admit_pose(pose, 'mm', 'absolute', '机器人位姿')

    def source_name(self):
        return type(self.robot).__name__


class RobotStitchWorkflow(WorkflowBase):
    STATE_IDLE = 'idle'
    STATE_CONNECTED = 'connected'
    STATE_READY = 'ready'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state = self.STATE_IDLE
        self._robot: Optional[RobotInterface] = None
        self._pose_source: Optional[PoseSource] = None
        self._csv_exhausted = False
        self._frame_provider = None
        self._handeye: Optional[HandEyeResult] = None
        self._eye_in_hand = True
        self._T_handeye: Optional[np.ndarray] = None
        self._frames: List[FrameData] = []
        self._poses: List[np.ndarray] = []
        self._T_base2cam_list: List[np.ndarray] = []
        self._merged_pcd: Optional[o3d.geometry.PointCloud] = None
        self.validator: Optional[TipTouchValidator] = None
        self.tip_report: Optional[dict] = None

    @property
    def handeye(self):
        return self._handeye

    @property
    def pose_source(self):
        return self._pose_source

    @property
    def frames(self):
        return self._frames

    @property
    def poses(self):
        return self._poses

    @property
    def transforms(self):
        return self._T_base2cam_list

    def get_mode_name(self) -> str:
        return 'robot_stitch'

    def get_state(self) -> str:
        return self._state

    def can_proceed(self) -> Tuple[bool, str]:
        if self._state == self.STATE_IDLE:
            return True, '可以设置位姿来源并加载手眼结果'
        if self._state == self.STATE_CONNECTED:
            return self._handeye is not None, '请先加载手眼结果'
        if self._state == self.STATE_READY:
            return True, '可以开始扫描拼接'
        return False, f'未知状态: {self._state}'

    def reset(self):
        self._state = self.STATE_IDLE
        self._robot = None
        self._pose_source = None
        self._frame_provider = None
        self._handeye = None
        self._T_handeye = None
        self.validator = None
        self.tip_report = None
        self.clear_frames()
        logger.info('机器人拼接工作流已重置')

    def clear_frames(self):
        self._frames.clear()
        self._poses.clear()
        self._T_base2cam_list.clear()
        self._merged_pcd = None

    def set_frame_provider(self, provider):
        self._frame_provider = provider

    def clear_pose_source(self):
        self._pose_source = None
        self._csv_exhausted = False
        self._state = self.STATE_CONNECTED if self._handeye is not None else self.STATE_IDLE

    def set_pose_source(self, source: PoseSource) -> Tuple[bool, str]:
        if source is None or not callable(getattr(source, 'get_pose', None)):
            return False, '位姿来源必须实现 get_pose()'
        self._pose_source = source
        self._csv_exhausted = False
        self._state = self.STATE_READY if self._handeye is not None else self.STATE_CONNECTED
        return True, f'位姿来源已设置: {source.source_name()}'

    def set_robot(self, robot: RobotInterface) -> Tuple[bool, str]:
        if self._robot is not None and self._robot.is_connected():
            self._robot.disconnect()
        ok, msg = robot.connect()
        if not ok:
            return False, msg
        self._robot = robot
        return self.set_pose_source(_RobotPoseSource(robot))

    def set_handeye(self, result: HandEyeResult) -> Tuple[bool, str]:
        if result is None:
            return False, '手眼结果不能为空'
        ok, msg, normalized = HandEyeResult.from_matrix(
            result.T_handeye_mm, 'mm', result.eye_in_hand)
        if not ok:
            return False, msg
        for name in ('rms_t_mm', 'rms_r_deg', 'n_samples', 'source', 'rms_unknown',
                     'verification', 'file_meta'):
            if hasattr(result, name):
                setattr(normalized, name, getattr(result, name))
        self._handeye = normalized
        self._eye_in_hand = normalized.eye_in_hand
        self._T_handeye = normalized.T_handeye_mm.copy()
        self.validator = TipTouchValidator(normalized.eye_in_hand, normalized.T_handeye_mm)
        self.tip_report = None
        self.clear_frames()
        if self._pose_source is not None:
            self._state = self.STATE_READY
        logger.info(f"手眼结果已加载: {'Eye-in-Hand' if normalized.eye_in_hand else 'Eye-to-Hand'}")
        return True, '手眼结果已加载，状态 UNVERIFIED'

    def set_handeye_result(self, eye_in_hand: bool, T_handeye: np.ndarray) -> Tuple[bool, str]:
        ok, msg, result = HandEyeResult.from_matrix(T_handeye, 'mm', eye_in_hand)
        if not ok:
            return False, msg
        return self.set_handeye(result)

    def compute_cam2base(self, T_base2tool: np.ndarray) -> Optional[np.ndarray]:
        if self._T_handeye is None:
            return None
        return compute_cam2base(self._eye_in_hand, self._T_handeye, T_base2tool)

    @staticmethod
    def _valid_cloud(frame):
        cloud = frame.load_pointcloud_o3d()
        if cloud is None or not len(cloud.points):
            raise ValueError('原始帧点云为空')
        points = np.asarray(cloud.points)
        valid = np.isfinite(points).all(axis=1) & np.any(points != 0, axis=1)
        if not np.any(valid):
            raise ValueError('原始帧没有有效点云')
        return cloud.select_by_index(np.flatnonzero(valid))

    def capture_frame(self, camera_id: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        if self._state != self.STATE_READY or self._handeye is None:
            return False, '工作流未就绪，请先设置位姿来源并加载手眼结果', None
        if self._pose_source is None:
            return False, '未设置机器人位姿来源', None
        if isinstance(self._pose_source, CsvPoseSource) and self._csv_exhausted:
            return False, 'CSV 位姿序列已耗尽，请重新加载后再采集', None
        ok, pose_message, T_base2tool = self._pose_source.get_pose()
        if not ok or T_base2tool is None:
            return False, f'无法读取位姿: {pose_message}', None
        T_cam2base = self.compute_cam2base(T_base2tool)
        try:
            if self._frame_provider is not None:
                frame = self._frame_provider()
                cam_id = camera_id or 'cam0'
            else:
                connected = self.camera_manager.get_connected_ids()
                if not connected:
                    return False, '没有已连接相机', None
                cam_id = camera_id or connected[0]
                frame = self.camera_manager.capture(cam_id)
            if frame is None:
                return False, '相机拍摄失败或离线帧已耗尽', None
            pcd = self._valid_cloud(frame)
            pcd_t = transform_pcd(pcd, T_cam2base)
        except Exception as exc:
            return False, f'采集点云失败: {exc}', None
        merged = self._merged_pcd
        try:
            if merged is None:
                merged = o3d.geometry.PointCloud(pcd_t)
            else:
                merged = merge_pointclouds(o3d.geometry.PointCloud(merged), pcd_t)
        except Exception as exc:
            return False, f'合并点云失败: {exc}', None
        self._frames.append(frame)
        self._poses.append(T_base2tool.copy())
        self._T_base2cam_list.append(T_cam2base.copy())
        self._merged_pcd = merged
        if isinstance(self._pose_source, CsvPoseSource):
            advanced, _, _ = self._pose_source.step_next()
            self._csv_exhausted = not advanced
        info = {
            'frame_id': frame.frame_id,
            'database_id': frame.database_id,
            'camera_id': cam_id,
            'n_frames': len(self._frames),
            'frame': frame,
            'pcd_cam': pcd,
            'pcd_base': pcd_t,
            'T_base2tool': T_base2tool.copy(),
            'T_cam2base': T_cam2base.copy(),
        }
        logger.info(f'机器人拼接：第 {len(self._frames)} 帧拍摄完成，相机 {cam_id}；{pose_message}')
        return True, f'第 {len(self._frames)} 帧拍摄并合并完成', info

    def add_tip_sample(self, pose, tip):
        if self.validator is None or self._handeye is None:
            return False, '尚未加载手眼矩阵'
        ok, message = self.validator.add_sample(pose, tip)
        if ok:
            self._handeye.validated = False
            self.tip_report = None
        return ok, message

    def run_tip_check(self):
        if self.validator is None or self._handeye is None:
            return {'verdict': 'FAIL', 'reasons': ['尚未加载手眼矩阵']}
        self.tip_report = self.validator.check()
        self._handeye.validated = self.tip_report['verdict'] == 'PASS'
        return self.tip_report

    def get_merged_pointcloud(self, processor=None):
        if self._merged_pcd is None:
            return None
        if processor is not None:
            pcd, _ = processor.process(self._merged_pcd)
            return pcd
        return self._merged_pcd

    def get_frame_count(self) -> int:
        return len(self._frames)

    def _pose_source_snapshot(self):
        source = self._pose_source
        if isinstance(source, ManualPoseSource):
            ok, _, pose = source.get_pose()
            return {'kind': 'manual', 'pose': pose.tolist() if ok else None}
        if isinstance(source, CsvPoseSource):
            return {'kind': 'csv', 'poses': [pose.tolist() for pose in source._poses],
                'index': source.current_index(), 'exhausted': self._csv_exhausted}
        return None

    def snapshot(self):
        handeye = None
        if self._handeye is not None:
            handeye = {
                'eye_in_hand': self._handeye.eye_in_hand,
                'T_handeye_mm': self._handeye.T_handeye_mm.tolist(),
                'rms_t_mm': self._handeye.rms_t_mm,
                'rms_r_deg': self._handeye.rms_r_deg,
                'n_samples': self._handeye.n_samples,
                'source': self._handeye.source,
                'validated': self._handeye.validated,
                'rms_unknown': bool(getattr(self._handeye, 'rms_unknown', False)),
            }
        return {
            'handeye': handeye,
            'pose_source': self._pose_source_snapshot(),
            'tip_samples': [dict(T_base2tool=pose.tolist(), p_tip_in_cam=tip.tolist())
                for pose, tip in self.validator.samples()] if self.validator else [],
            'tip_report': self.tip_report,
            'captures': [dict(frame_id=frame.frame_id, database_id=frame.database_id,
                T_base2tool=pose.tolist(), T_cam2base=transform.tolist())
                for frame, pose, transform in zip(
                    self._frames, self._poses, self._T_base2cam_list)],
        }

    @staticmethod
    def _restore_pose_source(data):
        if not data:
            return None
        kind = data.get('kind')
        if kind == 'manual':
            source = ManualPoseSource()
            if data.get('pose') is not None:
                ok, message = source.set_pose_matrix(data['pose'], 'mm', 'absolute')
                if not ok:
                    raise ValueError(message)
            return source
        if kind == 'csv':
            return CsvPoseSource.from_poses(data['poses'], int(data.get('index', 0)))
        raise ValueError(f'未知机器人位姿来源: {kind}')

    def restore_snapshot(self, data, frames):
        handeye_data = data.get('handeye')
        if not handeye_data:
            raise ValueError('机器人会话缺少手眼矩阵')
        ok, message, handeye = HandEyeResult.from_matrix(
            handeye_data['T_handeye_mm'], 'mm', handeye_data['eye_in_hand'])
        if not ok:
            raise ValueError(message)
        pose_source = self._restore_pose_source(data.get('pose_source'))
        captures = data.get('captures', [])
        frames = list(frames)
        if len(frames) != len(captures):
            raise ValueError('机器人会话引用了缺失的原始帧')
        restored_frames, poses, transforms = [], [], []
        merged = None
        for entry, frame in zip(captures, frames):
            if entry.get('database_id') != frame.database_id:
                raise ValueError('机器人会话原始帧身份不匹配')
            pose = np.asarray(entry['T_base2tool'], dtype=np.float64)
            transform = np.asarray(entry['T_cam2base'], dtype=np.float64)
            if pose.shape != (4, 4) or transform.shape != (4, 4):
                raise ValueError('机器人会话位姿或变换尺寸不一致')
            ok, message, pose = admit_pose(pose, 'mm', 'absolute', '会话位姿')
            if not ok:
                raise ValueError(message)
            rigid_ok, rigid_message = check_rigid_4x4(transform)
            if not rigid_ok:
                raise ValueError('机器人会话变换非刚性：' + rigid_message)
            expected = compute_cam2base(handeye.eye_in_hand, handeye.T_handeye_mm, pose)
            if not np.allclose(expected, transform):
                raise ValueError('机器人会话位姿或变换不一致')
            cloud = transform_pcd(self._valid_cloud(frame), transform)
            merged = o3d.geometry.PointCloud(cloud) if merged is None else merge_pointclouds(merged, cloud)
            restored_frames.append(frame)
            poses.append(pose.copy())
            transforms.append(transform.copy())
        for name in ('rms_t_mm', 'rms_r_deg', 'n_samples', 'source', 'rms_unknown'):
            if name in handeye_data:
                setattr(handeye, name, handeye_data[name])
        validator = TipTouchValidator(handeye.eye_in_hand, handeye.T_handeye_mm)
        for sample in data.get('tip_samples', []):
            ok, message = validator.add_sample(sample['T_base2tool'], sample['p_tip_in_cam'])
            if not ok:
                raise ValueError('机器人会话戳点样本无效：' + message)
        recalculated = validator.check()
        handeye.validated = bool(handeye_data.get('validated')) and recalculated['verdict'] == 'PASS'
        self._handeye = handeye
        self._eye_in_hand = handeye.eye_in_hand
        self._T_handeye = handeye.T_handeye_mm.copy()
        self._pose_source = pose_source
        self._csv_exhausted = bool((data.get('pose_source') or {}).get('exhausted', False))
        self.validator = validator
        self.tip_report = recalculated if len(validator) else data.get('tip_report')
        self._frames = restored_frames
        self._poses = poses
        self._T_base2cam_list = transforms
        self._merged_pcd = merged
        self._state = self.STATE_READY

    def save_merged_ply(self, path: str) -> Tuple[bool, str]:
        if self._handeye is None or not self._handeye.validated:
            return False, '合并点云导出被戳点门禁拦住：未 VERIFIED'
        if self._merged_pcd is None:
            return False, '无合并点云可保存'
        try:
            if write_point_cloud_atomic(path, self._merged_pcd):
                return True, f'已保存 {path}'
            return False, '点云保存失败（open3d 返回 False，详见日志）'
        except Exception as exc:
            logger.error(f'保存合并点云失败: {exc}')
            return False, f'保存失败: {exc}'
