# -*- coding: utf-8 -*-
"""
功能一：多相机外参标定拼接工作流（FixedMultiCamWorkflow）。

工作流程（状态机）：
  [标定阶段] 连接多相机 → 同步/异步拍摄(标定板全共视)
          → 检测标记/标定板 → 标定外参 → 保存外参JSON
                │（外参锁定, 相机不可移动）
                ▼
  [扫描阶段] 撤掉标定板 → 重新拍摄被测场景 → 一键拼接 → 保存PLY
                │
                ▼
        （可反复扫描多次，外参复用；或回到标定阶段重新标定）

设计原则：
  - 标定阶段与扫描阶段帧数据分区存放（frames_calib / frames_scan），互不覆盖；
  - 扫描阶段外参只读（锁定），拼接不要求检测到标记物；
  - 标定质量不达标（RMS 过高 / 内点率过低）时，禁止进入扫描阶段。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any

import numpy as np

from .workflow_base import WorkflowBase
from .frame_data import FrameData
from .utils import logger


class FixedMultiCamWorkflow(WorkflowBase):
    """多相机外参标定拼接工作流。"""

    # 状态定义
    STATE_IDLE = "idle"
    STATE_CALIBRATING = "calibrating"
    STATE_CALIBRATED = "calibrated"
    STATE_SCANNING = "scanning"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state = self.STATE_IDLE
        self._reference_id: Optional[str] = None
        self._frames_calib: Dict[str, FrameData] = {}   # 标定阶段帧
        self._frames_scan: Dict[str, FrameData] = {}    # 扫描阶段帧
        self._calibration_locked = False

    # ------------------------------------------------------------------
    # 抽象接口实现
    # ------------------------------------------------------------------
    def get_mode_name(self) -> str:
        return "fixed_multi"

    def get_state(self) -> str:
        return self._state

    def can_proceed(self) -> Tuple[bool, str]:
        """检查当前状态是否允许进入下一步。"""
        if self._state == self.STATE_IDLE:
            return True, "可以开始连接相机"
        if self._state == self.STATE_CALIBRATING:
            if not self._frames_calib:
                return False, "请先拍摄标定帧"
            if not self.calibration_engine.pair_results:
                return False, "请先执行标定"
            ok, msg = self._check_calibration_quality()
            if not ok:
                return False, f"标定质量不达标: {msg}"
            return True, "标定完成，可以进入扫描阶段"
        if self._state == self.STATE_CALIBRATED:
            return True, "可以开始扫描"
        if self._state == self.STATE_SCANNING:
            if not self._frames_scan:
                return False, "请先拍摄扫描帧"
            return True, "可以执行拼接"
        return False, f"未知状态: {self._state}"

    def reset(self):
        """重置工作流到初始状态。"""
        self._state = self.STATE_IDLE
        self._reference_id = None
        self._frames_calib.clear()
        self._frames_scan.clear()
        self._calibration_locked = False
        self.calibration_engine.pair_results.clear()
        logger.info("功能一工作流已重置")

    # ------------------------------------------------------------------
    # 标定阶段
    # ------------------------------------------------------------------
    def start_calibration(self, reference_id: str) -> Tuple[bool, str]:
        """开始标定阶段：设置参考相机，进入标定状态。

        支持从扫描阶段回到标定阶段重新标定（相机移动后需要重新标定）。
        """
        if self._state == self.STATE_SCANNING:
            # 扫描阶段重新标定：清空历史标定/扫描数据，但保持相机连接
            self._frames_calib.clear()
            self._frames_scan.clear()
            self._calibration_locked = False
            self.calibration_engine.pair_results.clear()
            logger.info("从扫描阶段回到标定阶段，已清空历史标定/扫描数据")
        elif self._state not in (self.STATE_IDLE, self.STATE_CALIBRATED):
            return False, f"当前状态 {self._state} 不允许重新标定"
        self._reference_id = reference_id
        self._state = self.STATE_CALIBRATING
        self._calibration_locked = False
        logger.info(f"进入标定阶段，参考相机: {reference_id}")
        return True, f"标定阶段已开始，参考相机 {reference_id}"

    def add_calibration_frame(self, frame: FrameData) -> Tuple[bool, str]:
        """添加标定帧（标定阶段）。"""
        if self._state != self.STATE_CALIBRATING:
            return False, "当前不在标定阶段"
        self._frames_calib[frame.camera_name] = frame
        logger.info(f"标定帧已添加: {frame.camera_name}")
        return True, f"标定帧 {frame.camera_name} 已添加"

    def detect_markers(self) -> Tuple[bool, str]:
        """对所有标定帧检测标记。"""
        if self._state != self.STATE_CALIBRATING:
            return False, "当前不在标定阶段"
        if not self._frames_calib:
            return False, "无标定帧，请先拍摄"
        total = 0
        for cid, frame in self._frames_calib.items():
            markers = self.marker_detector.detect_3d(
                frame.image_np,
                pointmap=frame.pointmap,
                rvc_image=frame.rvc_image,
                offline_ply_path=frame.offline_pointmap_path,
            )
            frame.markers = markers
            # 标定板模式：缓存位姿与规格，供位姿法标定使用
            if self.marker_detector.is_board_mode():
                br = self.marker_detector.last_board_result
                if br is not None and br.get('success'):
                    frame.board_pose = br.get('T_board_in_cam')
                    frame.board_pattern = br.get('pattern_size')
                    frame.board_pattern_name = br.get('pattern_name')
                    frame.board_rms_mm = float(br.get('rms_mm', 0.0))
                else:
                    frame.board_pose = None
                    frame.board_pattern = None
                    frame.board_pattern_name = None
                    frame.board_rms_mm = 0.0
            total += len(markers)
            logger.info(f"相机 {cid}: 检测到 {len(markers)} 个标记")
        return True, f"标记检测完成，共 {total} 个"

    def calibrate(self) -> Tuple[bool, str]:
        """执行外参标定（所有非参考相机对标参考相机）。"""
        if self._state != self.STATE_CALIBRATING:
            return False, "当前不在标定阶段"
        if not self._reference_id:
            return False, "未设置参考相机"
        ref_frame = self._frames_calib.get(self._reference_id)
        if ref_frame is None or not ref_frame.markers:
            return False, "参考相机缺少标记数据，请先检测标记"

        results = []
        for cid, frame in self._frames_calib.items():
            if cid == self._reference_id:
                continue
            if not frame.markers:
                results.append(f"{cid}: 缺少标记，跳过")
                continue
            result = self.calibration_engine.calibrate_pair(
                self._reference_id, cid,
                ref_frame.markers, frame.markers,
                ransac_threshold=2.0)
            if result.get('success'):
                results.append(
                    f"{cid}→{self._reference_id}: RMS {result['rms_mm']:.4f}mm, "
                    f"内点率 {result['inlier_ratio']:.1%}")
            else:
                results.append(f"{cid}→{self._reference_id}: 失败 ({result.get('message')})")

        ok, quality_msg = self._check_calibration_quality()
        if ok:
            self._state = self.STATE_CALIBRATED
            self._calibration_locked = True
            msg = f"标定完成: {quality_msg}"
        else:
            msg = f"标定质量不达标: {quality_msg}"
        logger.info(msg + " | " + "; ".join(results))
        return ok, msg

    def save_calibration(self, path: str) -> Tuple[bool, str]:
        """保存外参 JSON。"""
        if not self.calibration_engine.pair_results:
            return False, "无标定结果可保存"
        if self.calibration_engine.save_calibration(path):
            return True, f"外参已保存: {path}"
        return False, f"保存失败: {path}"

    def load_calibration(self, path: str) -> Tuple[bool, str]:
        """加载外参 JSON。"""
        if self.calibration_engine.load_calibration(path):
            self._reference_id = self.calibration_engine.reference_id
            self._state = self.STATE_CALIBRATED
            self._calibration_locked = True
            return True, f"外参已加载: {path}"
        return False, f"加载失败: {path}"

    # ------------------------------------------------------------------
    # 扫描阶段
    # ------------------------------------------------------------------
    def start_scanning(self) -> Tuple[bool, str]:
        """进入扫描阶段（外参锁定）。"""
        ok, msg = self.can_proceed()
        if not ok:
            return False, msg
        self._state = self.STATE_SCANNING
        logger.info("进入扫描阶段，外参已锁定")
        return True, "扫描阶段已开始，请勿移动相机"

    def add_scan_frame(self, frame: FrameData) -> Tuple[bool, str]:
        """添加扫描帧（扫描阶段）。"""
        if self._state != self.STATE_SCANNING:
            return False, "当前不在扫描阶段"
        self._frames_scan[frame.camera_name] = frame
        logger.info(f"扫描帧已添加: {frame.camera_name}")
        return True, f"扫描帧 {frame.camera_name} 已添加"

    def stitch(self, save_path: Optional[str] = None) -> Tuple[bool, str, Any]:
        """执行拼接（扫描阶段）。"""
        if self._state != self.STATE_SCANNING:
            return False, "当前不在扫描阶段", None
        if not self._frames_scan:
            return False, "无扫描帧，请先拍摄", None

        merged, msg = self.stitch_engine.stitch(
            self._frames_scan, self.calibration_engine,
            self._reference_id, processor=self.processor)
        if merged is None:
            return False, f"拼接失败: {msg}", None

        if save_path:
            import open3d as o3d
            o3d.io.write_point_cloud(save_path, merged)
            msg += f"\n已保存: {save_path}"
        logger.info(f"拼接完成: {len(merged.points)} 点")
        return True, msg, merged

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _check_calibration_quality(self) -> Tuple[bool, str]:
        """检查标定质量（RMS / 内点率）。"""
        if not self.calibration_engine.pair_results:
            return False, "无标定结果"
        max_rms = 0.0
        min_inlier = 1.0
        for (ref, cam), res in self.calibration_engine.pair_results.items():
            if not res.get('success'):
                return False, f"{cam}→{ref} 标定失败"
            max_rms = max(max_rms, res['rms_mm'])
            min_inlier = min(min_inlier, res['inlier_ratio'])
        if max_rms > 2.0:
            return False, f"最大 RMS {max_rms:.3f}mm 超过 2.0mm"
        if min_inlier < 0.5:
            return False, f"最小内点率 {min_inlier:.1%} 低于 50%"
        return True, f"最大 RMS {max_rms:.3f}mm, 最小内点率 {min_inlier:.1%}"

    # ------------------------------------------------------------------
    # 帧数据访问（UI 层使用）
    # ------------------------------------------------------------------
    @property
    def frames_calib(self) -> Dict[str, FrameData]:
        return self._frames_calib

    @property
    def frames_scan(self) -> Dict[str, FrameData]:
        return self._frames_scan

    @property
    def reference_id(self) -> Optional[str]:
        return self._reference_id

    @property
    def is_calibration_locked(self) -> bool:
        return self._calibration_locked
