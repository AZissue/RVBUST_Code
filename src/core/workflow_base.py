# -*- coding: utf-8 -*-
"""
工作流抽象基类（WorkflowBase）—— 双模式工作流架构。

两种主体功能：
  - FixedMultiCamWorkflow：多相机外参标定拼接（固定安装，先标后扫）
  - MobileChainWorkflow：单相机移动链式拼接（边走边拼）

设计原则：
  - 工作流只负责"状态机编排 + 业务逻辑调用"，不直接操作 UI；
  - UI 通过信号/回调与工作流交互，保持 core 与 UI 完全解耦；
  - 每种工作流管理自己的帧数据、标定/位姿图结果、会话目录。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any

from .camera_manager import CameraManager
from .marker_detector import MarkerDetector
from .calibration_engine import CalibrationEngine
from .stitch_engine import StitchEngine
from .point_cloud_processor import PointCloudProcessor
from .utils import logger


class WorkflowBase(ABC):
    """工作流抽象基类。"""

    def __init__(self,
                 camera_manager: CameraManager,
                 marker_detector: MarkerDetector,
                 calibration_engine: CalibrationEngine,
                 stitch_engine: StitchEngine,
                 processor: Optional[PointCloudProcessor] = None):
        self.camera_manager = camera_manager
        self.marker_detector = marker_detector
        self.calibration_engine = calibration_engine
        self.stitch_engine = stitch_engine
        self.processor = processor or PointCloudProcessor()

        # 工作流状态（子类维护）
        self._state = "idle"
        self._session_dir: Optional[str] = None

    # ------------------------------------------------------------------
    # 抽象接口（子类必须实现）
    # ------------------------------------------------------------------
    @abstractmethod
    def get_mode_name(self) -> str:
        """返回模式名称（如 'fixed_multi' / 'mobile_chain'）。"""
        pass

    @abstractmethod
    def get_state(self) -> str:
        """返回当前状态（如 'idle' / 'calibrating' / 'scanning' / 'chaining'）。"""
        pass

    @abstractmethod
    def can_proceed(self) -> Tuple[bool, str]:
        """检查当前状态是否允许进入下一步，返回 (ok, reason)。"""
        pass

    @abstractmethod
    def reset(self):
        """重置工作流到初始状态。"""
        pass

    # ------------------------------------------------------------------
    # 公共工具方法
    # ------------------------------------------------------------------
    def _log(self, text: str):
        """统一日志输出（子类可覆盖为 UI 信号）。"""
        logger.info(text)

    def _warn(self, text: str):
        """统一警告输出。"""
        logger.warning(text)

    def _error(self, text: str):
        """统一错误输出。"""
        logger.error(text)

    @property
    def session_dir(self) -> Optional[str]:
        return self._session_dir

    def set_session_dir(self, path: str):
        self._session_dir = path
