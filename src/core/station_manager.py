# -*- coding: utf-8 -*-
"""
单相机多站位管理（StationManager）—— Phase 5。

应用场景：只有 1 台物理相机时，把相机移动到不同站位各拍一帧，
每个站位视为一台"虚拟相机"（station_1、station_2 ...）参与标定与拼接。
核心算法零改动：CalibrationEngine / StitchEngine 只认帧 ID，
站位 ID 与相机 ID 在框架中完全等价。

核心设计：
  - 拍摄站位后**立即把帧存盘**（FrameData.save）：物理相机拍下一帧后，
    上一帧的 RVC PointMap / Image 句柄可能被驱动覆盖或释放，只有落盘
    才能保证站位帧长期有效；
  - 存盘后帧切换为离线模式（文件路径引用），并主动销毁 RVC 句柄
    （保留内存图像用于预览 / 2D 检测），在框架中表现得与普通相机帧
    完全一致（检测 / 标定 / 拼接零改动）；
  - 站位帧目录结构：
        offline_data/stations/session_YYYYMMDD_HHMMSS/
            meta.json                      # 会话级：created / stations / updated
            station_1/
                station_1.png  station_1.ply  meta.json
            station_2/ ...

删除策略：
  - remove_station / clear：删除站位并清理其磁盘目录（工作数据随删随清）；
  - new_session：归档旧会话目录（不删历史数据），另建时间戳新目录。
"""

from __future__ import annotations

import os
import json
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .frame_data import FrameData, _import_rvc
from .utils import logger, safe_destroy

if TYPE_CHECKING:
    from .camera_manager import CameraManager


class StationManager:
    """单相机多站位管理：1 台物理相机 → N 个虚拟站位。"""

    STATION_PREFIX = "station_"  # 站位 ID 前缀（station_1、station_2 ...）

    def __init__(self, camera_manager: 'CameraManager',
                 base_dir: str = "offline_data/stations"):
        self._cam_mgr = camera_manager
        self._base_dir = base_dir
        self._stations: Dict[str, FrameData] = {}   # station_id → 离线模式帧
        self._station_times: Dict[str, str] = {}    # station_id → 拍摄时刻 "HH:MM:SS"
        self._session_dir: Optional[str] = None     # 当前会话目录
        self._created: str = ""                     # 会话创建时间（ISO）
        self._station_seq = 0                       # 站位序号（会话内递增）

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------
    @property
    def session_dir(self) -> Optional[str]:
        return self._session_dir

    def new_session(self) -> str:
        """清空站位，创建新会话目录（旧会话目录归档保留，不删历史数据）。"""
        self._stations = {}
        self._station_times = {}
        self._station_seq = 0
        now = datetime.now()
        session_dir = os.path.abspath(os.path.join(
            self._base_dir, f"session_{now.strftime('%Y%m%d_%H%M%S')}"))
        suffix = 2
        while os.path.exists(session_dir):
            session_dir = os.path.abspath(os.path.join(
                self._base_dir,
                f"session_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"))
            suffix += 1
        os.makedirs(session_dir, exist_ok=True)
        self._session_dir = session_dir
        self._created = now.isoformat(timespec="seconds")
        self._write_meta()
        logger.info(
            f"站位会话已创建: {session_dir}。\n"
            "  存储结构: session_*/station_N/station_N.png + station_N.ply + meta.json\n"
            "  - png: 2D 图像（含编码圆标注）\n"
            "  - ply: 对应站位点云\n"
            "  - meta.json: 会话元数据（创建时间、站位列表）")
        return session_dir

    def attach_session(self, session_dir: str) -> bool:
        """关联一个已存在的会话目录，不创建新目录（用于离线加载）。"""
        if not os.path.isdir(session_dir):
            return False
        self._stations = {}
        self._station_times = {}
        self._station_seq = 0
        self._session_dir = os.path.abspath(session_dir)
        # 尝试读取原 meta.json 的创建时间
        meta_path = os.path.join(self._session_dir, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._created = meta.get("created", "")
            except Exception:
                self._created = ""
        else:
            self._created = ""
        return True

    def _write_meta(self):
        """重写会话级 meta.json（站位列表 + 创建 / 更新时间）。"""
        if not self._session_dir:
            return
        meta = {
            "type": "single_camera_stations",
            "created": self._created,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "stations": list(self._stations.keys()),
        }
        try:
            with open(os.path.join(self._session_dir, "meta.json"),
                      'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"站位会话 meta 写入失败: {e}")

    # ------------------------------------------------------------------
    # 站位拍摄（拍后立即存盘 + 释放 RVC 句柄）
    # ------------------------------------------------------------------
    def capture_station(self, camera_id: str) -> Tuple[Optional[str], str]:
        """从物理相机拍摄一帧，立即存盘，注册为 station_N。

        Returns:
            (station_id 或 None, 日志消息)；失败时 station_id 为 None。
        """
        if self._session_dir is None:
            self.new_session()  # 首次拍摄自动建会话

        frame = self._cam_mgr.capture(camera_id)
        if frame is None:
            return None, f"相机 {camera_id} 拍摄失败（未连接？）"

        self._station_seq += 1
        station_id = f"{self.STATION_PREFIX}{self._station_seq}"

        # 立即存盘：物理相机下一拍会覆盖 / 释放本次的 RVC 句柄，
        # 只有落盘才能保证站位帧长期有效
        frame.camera_name = station_id
        frame.frame_id = self._station_seq
        frame_dir = os.path.join(self._session_dir, station_id)
        try:
            frame.save(self._session_dir, frame_dir=frame_dir)
        except Exception as e:
            self._station_seq -= 1
            logger.error(f"站位帧存盘失败: {e}")
            return None, f"站位帧存盘失败: {e}"

        # 存盘后主动销毁 RVC 句柄（帧已切离线模式，保留内存图像用于预览/检测）
        RVC = _import_rvc()
        if RVC is not None:
            safe_destroy(frame.pointmap, RVC.PointMap.Destroy, "PointMap")
            safe_destroy(frame.rvc_image, RVC.Image.Destroy, "Image")
        frame.pointmap = None
        frame.rvc_image = None

        self._stations[station_id] = frame
        self._station_times[station_id] = datetime.now().strftime("%H:%M:%S")
        self._write_meta()
        logger.info(f"站位 {station_id} 已拍摄并存盘: {frame_dir}")
        return station_id, f"站位 {self._station_seq} 已拍摄并存盘"

    # ------------------------------------------------------------------
    # 站位增删
    # ------------------------------------------------------------------
    def remove_station(self, station_id: str) -> bool:
        """删除站位（同时清理其磁盘目录）。不存在返回 False。"""
        frame = self._stations.pop(station_id, None)
        if frame is None:
            return False
        self._station_times.pop(station_id, None)
        if frame.offline_dir and os.path.isdir(frame.offline_dir):
            shutil.rmtree(frame.offline_dir, ignore_errors=True)
        self._write_meta()
        logger.info(f"站位 {station_id} 已删除")
        return True

    def clear(self):
        """清空所有站位（保留当前会话目录，站位磁盘目录随删随清）。"""
        for station_id in list(self._stations.keys()):
            self.remove_station(station_id)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_station_ids(self) -> List[str]:
        """站位 ID 列表（按拍摄顺序）。"""
        return list(self._stations.keys())

    def get_frames(self) -> Dict[str, FrameData]:
        """站位帧集合（离线模式），喂给检测 / 标定 / 拼接。"""
        return dict(self._stations)

    def get_frame(self, station_id: str) -> Optional[FrameData]:
        return self._stations.get(station_id)

    def capture_time(self, station_id: str) -> str:
        """站位拍摄时刻 "HH:MM:SS"（UI 列表显示用）。"""
        return self._station_times.get(station_id, "")

    def station_count(self) -> int:
        return len(self._stations)
