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

from typing import Dict, List, Optional, Tuple, Any

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
        """开始链式拼接：初始化 ChainStitcher 和 StationManager。"""
        if self._state not in (self.STATE_IDLE, self.STATE_READY):
            return False, f"当前状态 {self._state} 不允许重新开始"
        self._chain_stitcher = ChainStitcher(
            marker_detector=self.marker_detector,
            calibration_engine=self.calibration_engine,
            stitch_engine=self.stitch_engine,
            min_common_markers=6,
            min_inlier_ratio=0.7,
            max_rms_mm=2.0,
        )
        self._station_manager = StationManager(self.camera_manager)
        session_dir = self._station_manager.new_session()
        self.set_session_dir(session_dir)
        self._state = self.STATE_CHAINING
        logger.info(f"链式拼接已开始，会话目录: {session_dir}")
        return True, f"链式拼接已开始，会话目录: {session_dir}"

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

        # 获取帧数据
        frame = self._station_manager.get_frame(station_id)
        if frame is None:
            return False, "获取帧数据失败", None

        # 自动配准
        ok, msg, edge = self._chain_stitcher.add_frame(frame)
        if not ok:
            # 配准失败，删除刚拍的机位
            self._station_manager.remove_station(station_id)
            evaluation = {
                'station_id': station_id,
                'success': False,
                'message': msg,
                'suggestion': '请减小移动距离或调整视角后重拍',
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

    def _remove_station_from_chain(self, station_id: str) -> bool:
        """从链中删除指定机位及其关联边（内部工具方法）。"""
        if self._chain_stitcher is None or station_id not in self._chain_stitcher.nodes:
            return False
        if station_id == self._chain_stitcher._reference_id:
            return False
        self._chain_stitcher.nodes.pop(station_id, None)
        self._chain_stitcher.edges = [
            e for e in self._chain_stitcher.edges
            if e.from_id != station_id and e.to_id != station_id
        ]
        self._station_manager.remove_station(station_id)
        # 机位少于 3 个时回到 chaining 状态
        if len(self._chain_stitcher.nodes) < 3:
            self._state = self.STATE_CHAINING
        return True

    def undo_last_station(self) -> Tuple[bool, str]:
        """撤销上一机位（删除并重新配准）。"""
        if self._chain_stitcher is None or not self._chain_stitcher.nodes:
            return False, "无机位可撤销"
        last_id = list(self._chain_stitcher.nodes.keys())[-1]
        if last_id == self._chain_stitcher._reference_id:
            return False, "不能撤销参考机位"
        if self._remove_station_from_chain(last_id):
            logger.info(f"已撤销机位 {last_id}")
            return True, f"已撤销机位 {last_id}"
        return False, f"撤销机位 {last_id} 失败"

    def delete_station(self, station_id: str) -> Tuple[bool, str]:
        """删除指定机位（后续链自动重算）。"""
        if self._chain_stitcher is None or station_id not in self._chain_stitcher.nodes:
            return False, "指定机位不存在"
        if station_id == self._chain_stitcher._reference_id:
            return False, "不能删除参考机位"
        if self._remove_station_from_chain(station_id):
            logger.info(f"已删除机位 {station_id}")
            return True, f"已删除机位 {station_id}"
        return False, f"删除机位 {station_id} 失败"

    def recapture_station(self, station_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """重拍指定机位：用当前相机位置替换该机位数据并重新配准。

        流程：删除旧机位 → 拍摄新机位（生成新 station_id）→ 配准入链。
        调用方需确保相机已移动到该机位对应位置。
        """
        if self._state != self.STATE_CHAINING and self._state != self.STATE_READY:
            return False, "当前不在链式拼接状态", None
        if self._chain_stitcher is None or station_id not in self._chain_stitcher.nodes:
            return False, "指定机位不存在", None
        if station_id == self._chain_stitcher._reference_id:
            return False, "不能重拍参考机位", None
        # 删除旧机位
        self._remove_station_from_chain(station_id)
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
