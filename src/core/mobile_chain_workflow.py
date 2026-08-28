# -*- coding: utf-8 -*-
"""
功能二：单相机移动链式拼接工作流（MobileChainWorkflow）。

工作流程（状态机）：
  连接相机 → 拍摄机位1(自动检测) → 移动 → 拍摄机位2
          → 自动匹配共有标记 → 求相对位姿 → 评估(重合度/误差)
                │ 通过(绿)            │ 不通过(红/黄)
                ▼                     ▼
          加入位姿图 → 实时拼接刷新    提示重拍/调整移动距离
                │
                ▼
        拍摄机位3 → ... → 完成 → 保存(会话+点云)
                │
                └→ 检测到与早期机位共有标记 → 提示「可闭环」→ 全局优化

设计原则：
  - 无预标定：每拍一帧即配准，配准成功才入图，失败帧直接拒绝并提示；
  - 自动候选匹配：新帧与「最近 N 个机位 + 参考机位」逐一匹配，取最优；
  - 评估门限：共有标记 ≥6、内点率 ≥0.7、RMS ≤ 阈值，三条件同时满足才接受；
  - 实时性：每帧配准 + 位姿图更新 + 拼接刷新应在 1~2 秒内完成。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple, Any

import cv2
import numpy as np

from .workflow_base import WorkflowBase
from .chain_stitcher import ChainStitcher, ChainEdge
from .frame_data import FrameData
from .station_manager import StationManager
from .utils import logger


class MobileChainWorkflow(WorkflowBase):
    """单相机移动链式拼接工作流。"""

    # 状态定义
    STATE_IDLE = "idle"
    STATE_CHAINING = "chaining"
    STATE_READY = "ready"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state = self.STATE_IDLE
        self._chain_stitcher: Optional[ChainStitcher] = None
        self._station_manager: Optional[StationManager] = None
        self._last_edge: Optional[ChainEdge] = None
        self._loop_candidates: List[str] = []

    # ------------------------------------------------------------------
    # 抽象接口实现
    # ------------------------------------------------------------------
    def get_mode_name(self) -> str:
        return "mobile_chain"

    def get_state(self) -> str:
        return self._state

    def can_proceed(self) -> Tuple[bool, str]:
        """检查当前状态是否允许进入下一步。"""
        if self._state == self.STATE_IDLE:
            return True, "可以开始连接相机"
        if self._state == self.STATE_CHAINING:
            if self._chain_stitcher is None or not self._chain_stitcher.nodes:
                return False, "请先拍摄首个机位"
            return True, "可以继续拍摄下一机位"
        if self._state == self.STATE_READY:
            return True, "可以保存结果或继续拍摄"
        return False, f"未知状态: {self._state}"

    def reset(self):
        """重置工作流到初始状态。"""
        self._state = self.STATE_IDLE
        self._chain_stitcher = None
        self._station_manager = None
        self._last_edge = None
        self._loop_candidates = []
        logger.info("功能二工作流已重置")

    # ------------------------------------------------------------------
    # 链式拼接流程
    # ------------------------------------------------------------------
    def start_chaining(self) -> Tuple[bool, str]:
        """开始链式拼接：初始化 ChainStitcher 和 StationManager。

        注意：会话目录不再在启动时创建，而是延迟到首次拍摄机位时，
        避免测试阶段反复进入模式 B 产生大量空会话目录。
        """
        if self._state not in (self.STATE_IDLE, self.STATE_READY):
            return False, f"当前状态 {self._state} 不允许重新开始"
        self._chain_stitcher = ChainStitcher(
            marker_detector=self.marker_detector,
            calibration_engine=self.calibration_engine,
            stitch_engine=self.stitch_engine,
            min_common_markers=3,
            min_inlier_ratio=0.7,
            max_rms_mm=2.0,
        )
        self._station_manager = StationManager(self.camera_manager)
        # 延迟创建会话目录，首次拍摄时 StationManager.capture_station 会自动创建
        self.set_session_dir(None)
        self._state = self.STATE_CHAINING
        logger.info("链式拼接已就绪，等待拍摄首个机位")
        return True, "链式拼接已就绪，等待拍摄首个机位"

    def load_session_dir(self, session_dir: str) -> Tuple[bool, str]:
        """从已有会话目录离线加载所有站位并自动拼接。

        目录结构要求：
            session_*/station_1/station_1.png + station_1.ply + meta.json
            session_*/station_2/...
        """
        if not os.path.isdir(session_dir):
            return False, f"目录不存在: {session_dir}"

        # 初始化链式拼接器
        self._chain_stitcher = ChainStitcher(
            marker_detector=self.marker_detector,
            calibration_engine=self.calibration_engine,
            stitch_engine=self.stitch_engine,
            min_common_markers=3,
            min_inlier_ratio=0.7,
            max_rms_mm=2.0,
        )
        self._station_manager = StationManager(self.camera_manager)
        self._station_manager.attach_session(session_dir)
        self.set_session_dir(session_dir)
        self._state = self.STATE_CHAINING

        station_names = [
            name for name in sorted(os.listdir(session_dir))
            if name.startswith(self._station_manager.STATION_PREFIX)
            and os.path.isdir(os.path.join(session_dir, name))
        ]
        if not station_names:
            return False, "未找到站位数据（station_N 子目录）"

        loaded = 0
        for station_name in station_names:
            station_dir = os.path.join(session_dir, station_name)
            img_path = os.path.join(station_dir, f"{station_name}.png")
            ply_path = os.path.join(station_dir, f"{station_name}.ply")
            if not os.path.exists(img_path) or not os.path.exists(ply_path):
                logger.warning(f"{station_name} 缺少 png/ply，跳过")
                continue

            image = cv2.imread(img_path)
            if image is None:
                logger.warning(f"{station_name} 图像读取失败，跳过")
                continue

            markers = self.marker_detector.detect_3d(
                image, offline_ply_path=ply_path)
            if not markers:
                logger.warning(f"{station_name} 未检测到标记物，跳过")
                continue

            # 统一字段名
            for m in markers:
                if "x_2d" in m and "u" not in m:
                    m["u"] = m["x_2d"]
                if "y_2d" in m and "v" not in m:
                    m["v"] = m["y_2d"]

            try:
                seq = int(station_name.split("_")[1])
            except ValueError:
                seq = loaded + 1

            frame = FrameData(
                frame_id=seq,
                camera_name=station_name,
                image_np=image,
                pointmap=None,
                rvc_image=None,
                is_offline=True,
                offline_dir=session_dir,
                offline_image_path=img_path,
                offline_pointmap_path=ply_path,
                markers=markers,
            )

            ok, msg, _edge = self._chain_stitcher.add_frame(frame)
            if not ok:
                logger.warning(f"{station_name} 配准失败: {msg}，跳过")
                continue

            self._station_manager._stations[station_name] = frame
            self._station_manager._station_times[station_name] = ""
            self._station_manager._station_seq = max(
                self._station_manager._station_seq, seq)
            loaded += 1

        if loaded == 0:
            return False, "没有成功加载任何站位"
        if len(self._chain_stitcher.nodes) < 2:
            return True, f"仅成功加载 {loaded} 个有效站位，无法形成拼接链"

        self._state = self.STATE_READY if len(self._chain_stitcher.nodes) >= 3 else self.STATE_CHAINING
        logger.info(f"离线加载会话完成: {session_dir}，共 {loaded} 个站位入链")
        return True, f"离线加载完成: {loaded} 个站位入链"

    def capture_station(self) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """拍摄当前机位并自动配准。

        Returns:
            (success, message, evaluation)
            evaluation: 配准评估结果（共视标记数/内点率/RMS/建议动作）
        """
        if self._state not in (self.STATE_CHAINING, self.STATE_READY):
            return False, "当前不在链式拼接状态", None

        # 拍摄并存盘（模式 B 只有一台物理相机）
        connected = self.camera_manager.get_connected_ids()
        if not connected:
            return False, "没有已连接相机", None
        camera_id = connected[0]
        station_id, msg = self._station_manager.capture_station(camera_id)
        if station_id is None:
            return False, f"拍摄失败: {msg}", None

        # 首次拍摄后同步会话目录到工作流
        if self.session_dir is None:
            self.set_session_dir(self._station_manager.session_dir)

        # 获取帧数据
        frame = self._station_manager.get_frame(station_id)
        if frame is None:
            return False, "获取帧数据失败", None

        # 自动配准
        ok, msg, edge = self._chain_stitcher.add_frame(frame)
        if not ok:
            # 配准失败，删除刚拍的机位（磁盘/内存注册表）
            self._station_manager.remove_station(station_id)
            evaluation = {
                'station_id': station_id,
                'success': False,
                'message': msg,
                'suggestion': '请减小移动距离或调整视角后重拍',
                # 失败帧仍返回给 UI，让用户能看到当前 2D/3D 数据
                'frame': frame,
            }
            return False, msg, evaluation

        # 配准成功
        self._last_edge = edge
        evaluation = {
            'station_id': station_id,
            'success': True,
            'common_markers': edge.common_markers if edge else 0,
            'rms_mm': edge.rms_mm if edge else 0.0,
            'inlier_ratio': edge.inlier_ratio if edge else 0.0,
            'cum_rms_mm': self._chain_stitcher.nodes[station_id].cum_rms_mm,
            'message': msg,
            'suggestion': '重合度充足，可继续移动',
        }

        # 闭环检测
        loops = self._chain_stitcher.detect_loop_closure(station_id)
        if loops:
            self._loop_candidates = loops
            evaluation['loop_closure'] = loops
            evaluation['suggestion'] = f"发现闭环候选 {loops}，可执行全局优化"

        # 状态更新
        if len(self._chain_stitcher.nodes) >= 3:
            self._state = self.STATE_READY

        logger.info(f"机位 {station_id} 配准成功: {msg}")
        return True, msg, evaluation

    def _remove_station_from_chain(self, station_id: str) -> Tuple[bool, str]:
        """从链中删除指定机位及其关联边（内部工具方法）。

        返回：
            (success, message)
            success=False 且 message 含 "参考机位已固定" 时，
            表示需要 UI 层二次确认后调用 ``reset_chain`` 重置整条链。
        """
        if self._chain_stitcher is None or station_id not in self._chain_stitcher.nodes:
            return False, "指定机位不存在"

        is_reference = station_id == self._chain_stitcher._reference_id
        n_nodes = len(self._chain_stitcher.nodes)

        if is_reference and n_nodes > 1:
            return False, "参考机位已固定，删除将重置整条链"

        # 移除节点（含位姿图）；返回列表可能包含级联删除的后续机位
        removed_ids = self._chain_stitcher.remove_node(station_id)
        for sid in removed_ids:
            self._station_manager.remove_station(sid)

        # 若删除了唯一参考机位，清空参考 ID
        if is_reference and n_nodes == 1:
            self._chain_stitcher._reference_id = None

        # 机位少于 3 个时回到 chaining 状态
        if len(self._chain_stitcher.nodes) < 3:
            self._state = self.STATE_CHAINING
        return True, f"已删除机位 {station_id}"

    def reset_chain(self) -> Tuple[bool, str]:
        """重置整条链（删除所有机位），用于删除已固定的参考机位。"""
        if self._chain_stitcher is None:
            return False, "链未初始化"
        while self._chain_stitcher.nodes:
            sid = next(iter(self._chain_stitcher.nodes))
            removed_ids = self._chain_stitcher.remove_node(sid)
            for rid in removed_ids:
                self._station_manager.remove_station(rid)
        self._chain_stitcher._reference_id = None
        self._state = self.STATE_CHAINING
        self._last_edge = None
        self._loop_candidates = []
        logger.info("整条链已重置")
        return True, "整条链已重置"

    def undo_last_station(self) -> Tuple[bool, str]:
        """撤销上一机位（删除并重新配准）。"""
        if self._chain_stitcher is None or not self._chain_stitcher.nodes:
            return False, "无机位可撤销"
        last_id = list(self._chain_stitcher.nodes.keys())[-1]
        ok, msg = self._remove_station_from_chain(last_id)
        if ok:
            logger.info(f"已撤销机位 {last_id}")
            return True, f"已撤销机位 {last_id}"
        return False, msg

    def delete_station(self, station_id: str) -> Tuple[bool, str]:
        """删除指定机位（后续链自动重算）。

        删除已固定的参考机位会返回 ``(False, "参考机位已固定...")``，
        需要调用方二次确认后调用 ``reset_chain`` 重置整条链。
        """
        if self._chain_stitcher is None or station_id not in self._chain_stitcher.nodes:
            return False, "指定机位不存在"
        return self._remove_station_from_chain(station_id)

    def recapture_station(self, station_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """重拍指定机位：用当前相机位置替换该机位数据并重新配准。

        流程：删除旧机位 → 拍摄新机位（生成新 station_id）→ 配准入链。
        调用方需确保相机已移动到该机位对应位置。

        参考机位仅在它是唯一机位时允许重拍；已固定（存在后续机位）时
        需先重置整条链。
        """
        if self._state != self.STATE_CHAINING and self._state != self.STATE_READY:
            return False, "当前不在链式拼接状态", None
        if self._chain_stitcher is None or station_id not in self._chain_stitcher.nodes:
            return False, "指定机位不存在", None
        if (station_id == self._chain_stitcher._reference_id and
                len(self._chain_stitcher.nodes) > 1):
            return False, "参考机位已固定，请先删除整条链后重拍", None
        # 删除旧机位
        ok, msg = self._remove_station_from_chain(station_id)
        if not ok:
            return False, msg, None
        # 拍摄并配准新机位
        return self.capture_station()

    def optimize_global(self) -> Tuple[bool, str, float, float]:
        """执行全局 BA 优化（消除累积漂移）。

        Returns:
            (success, message, before_mm, after_mm)
            before_mm / after_mm: 优化前后位姿图边平均平移残差（mm）。
        """
        if self._chain_stitcher is None or len(self._chain_stitcher.nodes) < 3:
            return False, "机位不足，无法全局优化", 0.0, 0.0
        ref_id = self._chain_stitcher._reference_id

        # 优化前：用当前 BFS/树状位姿计算边平移残差
        initial_poses = {sid: node.T_world for sid, node in
                         self._chain_stitcher.nodes.items()}
        before_mm = self._mean_translation_residual(initial_poses)

        optimized = self._chain_stitcher.pose_graph.optimize_global_ba(ref_id)
        # 更新所有节点的世界变换
        for sid, T in optimized.items():
            if sid in self._chain_stitcher.nodes:
                self._chain_stitcher.nodes[sid].T_world = T

        # 清空拼接缓存，确保 get_merged_pointcloud 使用优化后的新位姿
        self._chain_stitcher.invalidate_cache()

        after_mm = self._mean_translation_residual(optimized)
        logger.info(f"全局 BA 优化完成，锚点 {ref_id}, "
                    f"残差 {before_mm:.3f}mm -> {after_mm:.3f}mm")
        return True, f"全局优化完成，锚点 {ref_id}", before_mm, after_mm

    def _mean_translation_residual(self, poses: Dict[str, np.ndarray]) -> float:
        """计算当前位姿下所有边的平均平移残差（mm）。"""
        if self._chain_stitcher is None or not self._chain_stitcher.edges:
            return 0.0
        total = 0.0
        count = 0
        for edge in self._chain_stitcher.edges:
            T_from = poses.get(edge.from_id)
            T_to = poses.get(edge.to_id)
            if T_from is None or T_to is None:
                continue
            T_pred = np.linalg.inv(T_to) @ T_from
            T_err = np.linalg.inv(edge.T) @ T_pred
            total += float(np.linalg.norm(T_err[:3, 3]))
            count += 1
        return total / count if count > 0 else 0.0

    def get_merged_pointcloud(self, processor=None):
        """获取当前拼接点云。"""
        if self._chain_stitcher is None:
            return None
        return self._chain_stitcher.get_merged_pointcloud(processor or self.processor)

    def get_error_report(self) -> Dict[str, Any]:
        """生成误差报告。"""
        if self._chain_stitcher is None:
            return {}
        report = self._chain_stitcher.get_error_report()
        if self._station_manager is not None:
            report['session_dir'] = self._station_manager.session_dir
        return report

    def get_station_evaluations(self) -> List[Dict[str, Any]]:
        """获取当前机位列表的评估信息（供 UI 重建时间线）。"""
        if self._chain_stitcher is None:
            return []
        return self._chain_stitcher.get_station_evaluations()

    def get_station_list(self) -> List[Dict[str, Any]]:
        """获取机位列表（时间线显示用）。"""
        if self._chain_stitcher is None:
            return []
        stations = []
        for sid, node in self._chain_stitcher.nodes.items():
            stations.append({
                'station_id': sid,
                'n_markers': len(node.markers),
                'cum_rms_mm': node.cum_rms_mm,
                'is_reference': sid == self._chain_stitcher._reference_id,
            })
        return stations

    @property
    def last_edge(self) -> Optional[ChainEdge]:
        return self._last_edge

    @property
    def loop_candidates(self) -> List[str]:
        return self._loop_candidates

    @property
    def station_manager(self) -> Optional[StationManager]:
        return self._station_manager
