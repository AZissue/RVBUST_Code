# -*- coding: utf-8 -*-
"""
N 相机离线会话（OfflineSession）。

参考 DualCameraFusion/src/app.py:440-577 的 OfflineSession 泛化而来：
  - 原实现仅支持 A/B 双相机、单帧目录；
  - 本实现支持任意 N 台相机：同一次拍摄的所有相机帧存入同一个
    frame_XXXX/ 共享目录（文件名带相机 ID 前缀），会话级 meta.json
    记录相机列表、帧数、创建时间。

会话目录结构：
    offline_data/session_YYYYMMDD_HHMMSS/
        meta.json                     # 会话级元数据（created / camera_ids / frame_count）
        frame_0001/
            cam0.png  cam0.ply        # 各相机图像 + 点云
            cam1.png  cam1.ply
            meta.json                 # 帧级元数据（{"frame_id", "cameras": {...}}）
        frame_0002/ ...

功能：
  - create_new / add_frame / save_all / load_session：会话创建与帧落盘/恢复；
  - detect_all：批量编码圆 2D+3D 检测（结果回写帧 meta.json）；
  - calibrate_multi：批量多帧标定（逐帧累积 + 四元数平均）；
  - stitch_all：批量拼接（按 frame_id 分组逐对拼接后整体合并）。
"""

from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import cv2
import numpy as np

from .frame_data import FrameData
from .utils import logger

if TYPE_CHECKING:
    from .marker_detector import MarkerDetector
    from .calibration_engine import CalibrationEngine
    from .stitch_engine import StitchEngine
    from .point_cloud_processor import PointCloudProcessor


class OfflineSession:
    """N 相机离线会话：保存/加载/批量检测/批量标定/批量拼接。"""

    def __init__(self, session_dir: Optional[str] = None):
        self.session_dir: Optional[str] = session_dir
        # {camera_id: [FrameData, ...]}，按 frame_id 升序
        self.frames: Dict[str, List[FrameData]] = {}
        self._meta: dict = {}

    # ------------------------------------------------------------------
    # 会话创建与元数据
    # ------------------------------------------------------------------
    def create_new(self, base_dir: str = "offline_data") -> str:
        """创建新的离线会话目录（时间戳命名，同一秒冲突时追加序号），
        写入会话级 meta.json，返回会话目录绝对路径。"""
        now = datetime.now()
        session_dir = os.path.abspath(
            os.path.join(base_dir, f"session_{now.strftime('%Y%m%d_%H%M%S')}"))
        suffix = 2
        while os.path.exists(session_dir):
            session_dir = os.path.abspath(os.path.join(
                base_dir, f"session_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"))
            suffix += 1
        os.makedirs(session_dir, exist_ok=True)
        self.session_dir = session_dir
        self.frames = {}
        self._meta = {"created": now.isoformat(timespec="seconds")}
        self._write_session_meta()
        logger.info(f"离线会话已创建: {session_dir}")
        return session_dir

    def _write_session_meta(self):
        """重写会话级 meta.json（相机列表 + 帧数 + 创建时间）。"""
        if not self.session_dir:
            return
        meta = dict(self._meta)
        if self.frames:
            meta["camera_ids"] = sorted(self.frames.keys())
        else:
            meta.setdefault("camera_ids", [])
        meta["frame_count"] = len(self._list_frame_dirs())
        with open(os.path.join(self.session_dir, "meta.json"), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _list_frame_dirs(self) -> List[str]:
        if not self.session_dir or not os.path.isdir(self.session_dir):
            return []
        return sorted(
            os.path.join(self.session_dir, d)
            for d in os.listdir(self.session_dir)
            if d.startswith("frame_") and os.path.isdir(os.path.join(self.session_dir, d))
        )

    # ------------------------------------------------------------------
    # 帧保存 / 加载
    # ------------------------------------------------------------------
    def add_frame(self, camera_id: str, frame_data: FrameData) -> str:
        """添加一帧到会话（委托 FrameData.save 落盘），返回帧目录路径。

        同一 frame_id 的所有相机帧共享 frame_XXXX/ 目录。
        内存中保存的是脱离在线资源的离线引用副本（图像/点云按路径引用），
        原帧后续被 release() 也不影响会话数据。
        """
        if not self.session_dir:
            raise RuntimeError("离线会话未创建，请先调用 create_new()")
        frame_data.camera_name = camera_id
        frame_dir = os.path.join(self.session_dir, f"frame_{frame_data.frame_id:04d}")
        frame_data.save(self.session_dir, frame_dir=frame_dir)

        # 内存副本：只持有离线路径与标记，不持有 RVC 对象 / 大图
        saved = FrameData(
            frame_id=frame_data.frame_id,
            camera_name=camera_id,
            image_np=frame_data.image_np,  # 在线会话期间复用内存图像（release 后为 None，检测时从磁盘读）
            markers=list(frame_data.markers),
            is_offline=True,
            offline_dir=frame_data.offline_dir,
            offline_image_path=frame_data.offline_image_path,
            offline_pointmap_path=frame_data.offline_pointmap_path,
        )
        frames = self.frames.setdefault(camera_id, [])
        # 同 camera_id + frame_id 去重（重复保存同一拍则替换）
        for i, f in enumerate(frames):
            if f.frame_id == saved.frame_id:
                frames[i] = saved
                break
        else:
            frames.append(saved)
        frames.sort(key=lambda f: f.frame_id)
        self._write_session_meta()
        return frame_dir

    def save_all(self) -> str:
        """把内存中的所有帧（重新）保存到磁盘并更新会话 meta，返回会话目录。

        FrameData.save 幂等：图像/点云已落盘时仅刷新 meta.json
        （含最新检测结果 markers）。
        """
        if not self.session_dir:
            raise RuntimeError("离线会话未创建，请先调用 create_new() 或 load_session()")
        for camera_id, frames in self.frames.items():
            for frame in frames:
                frame_dir = os.path.join(self.session_dir, f"frame_{frame.frame_id:04d}")
                frame.camera_name = camera_id
                frame.save(self.session_dir, frame_dir=frame_dir)
        self._write_session_meta()
        logger.info(f"离线会话已保存: {self.session_dir}")
        return self.session_dir

    def load_session(self, session_dir: str) -> Dict[str, List[FrameData]]:
        """加载会话目录中的所有帧，返回 {camera_id: [FrameData, ...]}。

        兼容两种帧目录格式：
          - 会话格式（frame_XXXX/meta.json 含 "cameras" 键）；
          - 旧版独立目录（frame_XXXX_cam/meta.json 含 "camera_name" 键，
            直接委托 FrameData.load）。
        """
        self.session_dir = session_dir
        self.frames = {}
        self._meta = {}
        meta_path = os.path.join(session_dir, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    self._meta = json.load(f)
            except Exception as e:
                logger.warning(f"会话 meta.json 读取失败: {e}")

        for frame_dir in self._list_frame_dirs():
            fmeta_path = os.path.join(frame_dir, "meta.json")
            if not os.path.exists(fmeta_path):
                continue
            try:
                with open(fmeta_path, 'r', encoding='utf-8') as f:
                    fmeta = json.load(f)
            except Exception as e:
                logger.error(f"帧 meta 读取失败 {frame_dir}: {e}")
                continue

            if "cameras" in fmeta:
                # 会话格式：一个目录多台相机
                fid = fmeta.get("frame_id", 0)
                for cam_id, entry in fmeta["cameras"].items():
                    bp_list = entry.get("board_pose")
                    bp_tuple = entry.get("board_pattern")
                    frame = FrameData(
                        frame_id=entry.get("frame_id", fid),
                        camera_name=cam_id,
                        is_offline=True,
                        offline_dir=frame_dir,
                        markers=entry.get("markers", []),
                        board_pose=np.asarray(bp_list, dtype=np.float64) if bp_list is not None else None,
                        board_pattern=tuple(bp_tuple) if bp_tuple is not None else None,
                        board_pattern_name=entry.get("board_pattern_name"),
                    )
                    img_path = os.path.join(frame_dir, f"{cam_id}.png")
                    if os.path.exists(img_path):
                        frame.image_np = cv2.imread(img_path)
                        frame.offline_image_path = img_path
                    ply_path = os.path.join(frame_dir, f"{cam_id}.ply")
                    if os.path.exists(ply_path):
                        frame.offline_pointmap_path = ply_path
                    self.frames.setdefault(cam_id, []).append(frame)
            else:
                # 旧版独立目录格式
                try:
                    frame = FrameData.load(frame_dir)
                    self.frames.setdefault(frame.camera_name, []).append(frame)
                except Exception as e:
                    logger.error(f"加载离线帧失败 {frame_dir}: {e}")

        for frames in self.frames.values():
            frames.sort(key=lambda f: f.frame_id)
        n_frames = sum(len(v) for v in self.frames.values())
        logger.info(f"离线会话已加载: {session_dir} "
                    f"({len(self.frames)} 台相机, {n_frames} 帧)")
        return self.frames

    def latest_frames(self) -> Dict[str, FrameData]:
        """每台相机最新一帧（用于加载会话后同步 UI 预览）。"""
        return {cid: frames[-1] for cid, frames in self.frames.items() if frames}

    # ------------------------------------------------------------------
    # 批量检测
    # ------------------------------------------------------------------
    def detect_all(self, detector: 'MarkerDetector') -> Dict[str, List[List[Dict]]]:
        """批量检测所有帧的编码圆（2D+3D），结果回写帧 meta.json。

        返回 {camera_id: [markers_per_frame, ...]}。
        """
        results: Dict[str, List[List[Dict]]] = {}
        for cam_id, frames in self.frames.items():
            cam_results: List[List[Dict]] = []
            for frame in frames:
                # 图像不在内存时从磁盘读（release 后的在线帧）
                if frame.image_np is None and frame.offline_image_path \
                        and os.path.exists(frame.offline_image_path):
                    frame.image_np = cv2.imread(frame.offline_image_path)
                markers = detector.detect_3d(
                    frame.image_np,
                    pointmap=frame.pointmap,
                    rvc_image=frame.rvc_image,
                    offline_ply_path=frame.offline_pointmap_path,
                )
                frame.markers = markers
                # 标定板模式：缓存位姿与规格
                if getattr(detector, 'is_board_mode', lambda: False)():
                    br = detector.last_board_result
                    if br is not None and br.get('success'):
                        frame.board_pose = br.get('T_board_in_cam')
                        frame.board_pattern = br.get('pattern_size')
                        frame.board_pattern_name = br.get('pattern_name')
                    else:
                        frame.board_pose = None
                        frame.board_pattern = None
                        frame.board_pattern_name = None
                cam_results.append(markers)
                self._write_back_markers(frame)
            results[cam_id] = cam_results
            logger.info(f"批量检测 {cam_id}: "
                        f"{[len(m) for m in cam_results]} 个/帧")
        return results

    def _write_back_markers(self, frame: FrameData):
        """把检测结果回写到帧目录 meta.json（兼容两种格式）。"""
        if not frame.offline_dir:
            return
        meta_path = os.path.join(frame.offline_dir, "meta.json")
        try:
            meta = {}
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            board_pose_entry = frame.board_pose.tolist() if frame.board_pose is not None else None
            board_pattern_entry = list(frame.board_pattern) if frame.board_pattern is not None else None
            if "cameras" in meta:
                entry = meta["cameras"].setdefault(frame.camera_name, {})
                entry["markers"] = frame.markers
                entry["board_pose"] = board_pose_entry
                entry["board_pattern"] = board_pattern_entry
                entry["board_pattern_name"] = frame.board_pattern_name
            else:
                meta["markers"] = frame.markers
                meta["board_pose"] = board_pose_entry
                meta["board_pattern"] = board_pattern_entry
                meta["board_pattern_name"] = frame.board_pattern_name
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"回写检测结果失败 {meta_path}: {e}")

    # ------------------------------------------------------------------
    # 批量标定（多帧累积 + 平均）
    # ------------------------------------------------------------------
    def calibrate_multi(
        self,
        engine: 'CalibrationEngine',
        ref_id: str,
        ransac_threshold: float = 2.0,
        min_pairs: int = 3,
    ) -> Dict[str, dict]:
        """批量标定：所有非参考相机对参考相机做多帧平均标定。

        按 frame_id 对齐各相机帧（同一次拍摄），逐对累积到引擎多帧缓存，
        再走 calibrate_multi_frame（四元数平均）。
        注意：3D 坐标来自 SaveWithImage(Millimeter)，阈值默认 2.0 mm。

        返回 {cam_id: result}。
        """
        if ref_id not in self.frames:
            logger.error(f"批量标定: 参考相机 '{ref_id}' 不在会话中")
            return {}
        ref_frames = {f.frame_id: f for f in self.frames[ref_id]}
        results: Dict[str, dict] = {}

        for cam_id, frames in self.frames.items():
            if cam_id == ref_id:
                continue
            engine.clear_frame_data(ref_id, cam_id)
            n_paired = 0
            for frame in frames:
                ref_frame = ref_frames.get(frame.frame_id)
                if ref_frame is None or not ref_frame.markers or not frame.markers:
                    continue
                engine.add_frame_data(ref_id, cam_id, ref_frame.markers, frame.markers)
                n_paired += 1
            if n_paired == 0:
                results[cam_id] = {'success': False,
                                   'message': "无有效配对帧（缺标记或帧号不对齐）"}
                logger.warning(f"批量标定 {cam_id}→{ref_id}: 无有效配对帧")
                continue
            res = engine.calibrate_multi_frame(
                ref_id, cam_id,
                ransac_threshold=ransac_threshold, min_pairs=min_pairs)
            results[cam_id] = res
        return results

    # ------------------------------------------------------------------
    # 批量拼接
    # ------------------------------------------------------------------
    def stitch_all(
        self,
        stitch_engine: 'StitchEngine',
        engine: 'CalibrationEngine',
        ref_id: str,
        processor: Optional['PointCloudProcessor'] = None,
    ):
        """批量拼接：按 frame_id 分组，逐对拼接后整体合并到参考坐标系。

        返回 (merged_open3d_pointcloud 或 None, 日志消息)。
        """
        groups: Dict[int, Dict[str, FrameData]] = {}
        for cam_id, frames in self.frames.items():
            for frame in frames:
                groups.setdefault(frame.frame_id, {})[cam_id] = frame
        session_frames = [groups[k] for k in sorted(groups.keys())]
        if not session_frames:
            return None, "会话无帧数据"
        return stitch_engine.stitch_offline(
            session_frames, engine, ref_id, processor=processor)
