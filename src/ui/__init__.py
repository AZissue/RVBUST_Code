# -*- coding: utf-8 -*-
"""
MultiCameraCalibration UI 包（Phase 3）。

三栏布局（参考 DualCameraFusion，泛化为 N 相机）：
  - 左：CameraPanel      —— 相机管理 + 采集控制
  - 中：相机预览卡片网格 + 嵌入式 3D 查看器（可折叠）
  - 右：QTabWidget       —— CalibrationPanel / StitchPanel
  - 底：可折叠日志面板
"""

from .camera_card import CameraPreviewCard, AspectRatioLabel
from .viewer_3d import EmbeddedPointCloudViewer
from .panels.camera_panel import CameraPanel
from .panels.calibration_panel import CalibrationPanel
from .panels.stitch_panel import StitchPanel
from .main_window import MainWindow

__all__ = [
    "CameraPreviewCard", "AspectRatioLabel",
    "EmbeddedPointCloudViewer",
    "CameraPanel", "CalibrationPanel", "StitchPanel",
    "MainWindow",
]
