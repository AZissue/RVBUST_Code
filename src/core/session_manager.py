# -*- coding: utf-8 -*-
"""
统一会话管理（SessionManager）—— 两种模式统一的可重放会话。

数据层结构：
```
scans/<mode>_session_时间戳/
  meta.json              # mode: fixed_multi | mobile_chain, 相机信息, 参考系
  calibration.json       # 功能一：外参结果；功能二：位姿图全部边+质量
  frames_calib/ frame_0001/ ...   # 功能一标定帧（分区）
  frames_scan/  frame_0001/ ...   # 功能一扫描帧（分区）
  stations/     station_1/ ...    # 功能二机位帧(复用 StationManager 目录格式)
  error_report.json      # 每步重合度评估 + 链累计误差，可回放复盘
```

设计原则：
  - 功能一保存外参后，扫描阶段只需 calibration.json + 扫描帧，不依赖标记物；
  - 功能二的 error_report.json 记录每一步的评估结果，支持事后复盘。
"""

from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from .utils import logger


class SessionManager:
    """两种模式统一的可重放会话管理器。"""

    MODE_FIXED_MULTI = "fixed_multi"
    MODE_MOBILE_CHAIN = "mobile_chain"

    def __init__(self, base_dir: str = "scans"):
        self._base_dir = base_dir
        self._session_dir: Optional[str] = None
        self._mode: Optional[str] = None
        self._meta: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 会话创建与加载
    # ------------------------------------------------------------------
    def create_session(self, mode: str, camera_info: Optional[Dict] = None) -> str:
        """创建新会话目录。

        Args:
            mode: 'fixed_multi' 或 'mobile_chain'
            camera_info: 相机信息（型号/SN/数量等）

        Returns:
            会话目录路径
        """
        if mode not in (self.MODE_FIXED_MULTI, self.MODE_MOBILE_CHAIN):
            raise ValueError(f"未知模式: {mode}")
        self._mode = mode
        now = datetime.now()
        session_dir = os.path.abspath(os.path.join(
            self._base_dir, f"{mode}_session_{now.strftime('%Y%m%d_%H%M%S')}"))
        suffix = 2
        while os.path.exists(session_dir):
            session_dir = os.path.abspath(os.path.join(
                self._base_dir,
                f"{mode}_session_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"))
            suffix += 1
        os.makedirs(session_dir, exist_ok=True)
        self._session_dir = session_dir

        # 创建子目录
        if mode == self.MODE_FIXED_MULTI:
            os.makedirs(os.path.join(session_dir, "frames_calib"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "frames_scan"), exist_ok=True)
        else:
            os.makedirs(os.path.join(session_dir, "stations"), exist_ok=True)

        # 写入 meta.json
        self._meta = {
            "mode": mode,
            "created": now.isoformat(),
            "camera_info": camera_info or {},
            "reference_id": None,
        }
        self._write_json(os.path.join(session_dir, "meta.json"), self._meta)
        logger.info(f"会话已创建: {session_dir}")
        return session_dir

    def load_session(self, session_dir: str) -> Tuple[bool, str]:
        """加载已有会话目录。"""
        meta_path = os.path.join(session_dir, "meta.json")
        if not os.path.exists(meta_path):
            return False, f"找不到 meta.json: {meta_path}"
        with open(meta_path, 'r', encoding='utf-8') as f:
            self._meta = json.load(f)
        self._mode = self._meta.get("mode")
        self._session_dir = session_dir
        logger.info(f"会话已加载: {session_dir} (mode={self._mode})")
        return True, f"会话已加载: {session_dir}"

    # ------------------------------------------------------------------
    # 数据保存
    # ------------------------------------------------------------------
    def save_calibration(self, calibration_data: Dict) -> bool:
        """保存外参/位姿图结果。"""
        if self._session_dir is None:
            return False
        path = os.path.join(self._session_dir, "calibration.json")
        return self._write_json(path, calibration_data)

    def save_error_report(self, report: Dict) -> bool:
        """保存误差报告（功能二）。"""
        if self._session_dir is None:
            return False
        path = os.path.join(self._session_dir, "error_report.json")
        return self._write_json(path, report)

    def save_frame(self, frame, phase: str = "scan"):
        """保存帧数据到对应分区。

        Args:
            frame: FrameData 对象
            phase: 'calib' 或 'scan'（功能一）；'station'（功能二）
        """
        if self._session_dir is None:
            return None
        if self._mode == self.MODE_FIXED_MULTI:
            subdir = "frames_calib" if phase == "calib" else "frames_scan"
        else:
            subdir = "stations"
        frame_dir = os.path.join(self._session_dir, subdir)
        os.makedirs(frame_dir, exist_ok=True)
        return frame.save(frame_dir)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------
    def load_calibration(self) -> Optional[Dict]:
        """加载外参/位姿图结果。"""
        if self._session_dir is None:
            return None
        path = os.path.join(self._session_dir, "calibration.json")
        return self._read_json(path)

    def load_error_report(self) -> Optional[Dict]:
        """加载误差报告。"""
        if self._session_dir is None:
            return None
        path = os.path.join(self._session_dir, "error_report.json")
        return self._read_json(path)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------
    @property
    def session_dir(self) -> Optional[str]:
        return self._session_dir

    @property
    def mode(self) -> Optional[str]:
        return self._mode

    @property
    def meta(self) -> Dict[str, Any]:
        return self._meta

    def set_reference_id(self, ref_id: str):
        """设置参考相机/机位 ID 并持久化到 meta.json。"""
        self._meta["reference_id"] = ref_id
        if self._session_dir:
            self._write_json(os.path.join(self._session_dir, "meta.json"), self._meta)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _write_json(path: str, data: Dict) -> bool:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"写入 JSON 失败 {path}: {e}")
            return False

    @staticmethod
    def _read_json(path: str) -> Optional[Dict]:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取 JSON 失败 {path}: {e}")
            return None
