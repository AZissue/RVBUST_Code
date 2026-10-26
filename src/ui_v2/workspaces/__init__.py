# -*- coding: utf-8 -*-
"""Production workspaces for the v2 shell."""

from .multi_cam_workspace import MultiCamWorkspace
from .mobile_chain_workspace import MobileChainWorkspace
from .turntable_workspace import TurntableWorkspace
from .robot_workspace import RobotWorkspace

__all__ = ["MultiCamWorkspace", "MobileChainWorkspace", "TurntableWorkspace", "RobotWorkspace"]
