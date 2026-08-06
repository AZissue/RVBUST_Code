# -*- coding: utf-8 -*-
"""
链式拼接编排器（ChainStitcher）—— 功能二：单相机移动链式拼接。

核心职责：
  - 每拍一帧 → 自动检测标记 → 与已有位姿图匹配共有标记 → 求解相对位姿；
  - 评估配准质量（共视标记数 / 内点率 / RMS），通过则加入位姿图；
  - 实时更新拼接点云（增量合并到参考坐标系）；
  - 支持闭环检测与全局优化。

设计原则：
  - 复用现有模块：MarkerDetector（检测）、CalibrationEngine（pair 标定）、
    PoseGraph（位姿图）、StitchEngine（合并）；
  - 只做"编排"，不重复实现算法；
  - 每步结果可回放（误差报告），支持事后复盘。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

from .marker_detector import MarkerDetector
from .calibration_engine import CalibrationEngine
from .stitch_engine import StitchEngine
from .pose_graph import PoseGraph
from .frame_data import FrameData
from .utils import logger


@dataclass
class ChainEdge:
    """位姿图边（相邻机位间的相对位姿）。"""
    from_id: str
    to_id: str
    T: np.ndarray                # from→to 的 4x4 变换
    rms_mm: float                # 配准 RMS
    inlier_ratio: float          # 内点率
    common_markers: int          # 共视标记数
    quality: str = "unknown"     # 质量评级：good / ok / poor


@dataclass
class ChainNode:
    """位姿图节点（机位）。"""
    station_id: str
    frame: FrameData
    markers: List[Dict] = field(default_factory=list)
    T_world: Optional[np.ndarray] = None  # 机位到世界参考系的 4x4 变换
    cum_rms_mm: float = 0.0      # 累计误差


class ChainStitcher:
    """单相机移动链式拼接编排器。"""

    def __init__(self,
                 marker_detector: MarkerDetector,
                 calibration_engine: CalibrationEngine,
                 stitch_engine: StitchEngine,
                 min_common_markers: int = 6,
                 min_inlier_ratio: float = 0.7,
                 max_rms_mm: float = 2.0):
        self.marker_detector = marker_detector
        self.calibration_engine = calibration_engine
        self.stitch_engine = stitch_engine
        self.min_common_markers = min_common_markers
        self.min_inlier_ratio = min_inlier_ratio
        self.max_rms_mm = max_rms_mm

        self.pose_graph = PoseGraph()
        self.nodes: Dict[str, ChainNode] = {}
        self.edges: List[ChainEdge] = []
        self._reference_id: Optional[str] = None
        self._merged_pcd = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def add_frame(self, frame: FrameData) -> Tuple[bool, str, Optional[ChainEdge]]:
        """添加新机位帧：检测标记 → 匹配共有标记 → 配准 → 评估 → 入图。

        Returns:
            (success, message, edge)
            success: 是否成功加入位姿图
            message: 结果描述（含评估详情）
            edge: 成功时返回新边，失败返回 None
        """
        # 1. 检测标记
        markers = self.marker_detector.detect_3d(
            frame.image_np,
            pointmap=frame.pointmap,
            rvc_image=frame.rvc_image,
            offline_ply_path=frame.offline_pointmap_path,
        )
        if not markers:
            return False, "未检测到标记物，请调整机位或光照", None
        frame.markers = markers

        station_id = frame.camera_name
        node = ChainNode(station_id=station_id, frame=frame, markers=markers)
        self.nodes[station_id] = node

        # 2. 首个机位：设为参考系
        if self._reference_id is None:
            self._reference_id = station_id
            node.T_world = np.eye(4, dtype=np.float64)
            self.pose_graph.add_node(station_id, T=np.eye(4, dtype=np.float64))
            logger.info(f"链式拼接：机位 {station_id} 设为参考系")
            return True, f"机位 {station_id} 设为参考系，{len(markers)} 个标记", None

        # 3. 与已有节点匹配共有标记（最近 N 个 + 参考节点）
        best_edge = None
        best_score = -1
        for prev_id, prev_node in self.nodes.items():
            if prev_id == station_id:
                continue
            edge = self._try_register(node, prev_node)
            if edge is not None and edge.common_markers > best_score:
                best_score = edge.common_markers
                best_edge = edge

        if best_edge is None:
            return False, f"未找到足够共有标记（需 ≥{self.min_common_markers}），请减小移动距离", None

        # 4. 评估质量
        ok, quality_msg = self._evaluate_edge(best_edge)
        if not ok:
            return False, quality_msg, None

        # 5. 加入位姿图
        self.edges.append(best_edge)
        self.pose_graph.add_edge(best_edge.from_id, best_edge.to_id,
                                 best_edge.T, rms_mm=best_edge.rms_mm,
                                 inlier_ratio=best_edge.inlier_ratio,
                                 common_markers=best_edge.common_markers)
        node.T_world = self.pose_graph.get_transform(station_id, self._reference_id)

        # 6. 更新累计误差
        node.cum_rms_mm = self._compute_cumulative_rms(station_id)

        msg = (f"机位 {station_id} 配准成功: {best_edge.common_markers} 个共有标记, "
               f"RMS {best_edge.rms_mm:.3f}mm, 内点率 {best_edge.inlier_ratio:.1%}, "
               f"累计误差 {node.cum_rms_mm:.3f}mm")
        logger.info(msg)
        return True, msg, best_edge

    def get_merged_pointcloud(self, processor=None):
        """获取当前拼接点云（增量合并到参考坐标系）。"""
        if not self.nodes:
            return None
        frames = {sid: node.frame for sid, node in self.nodes.items()}
        merged, msg = self.stitch_engine.stitch(
            frames, self.calibration_engine, self._reference_id, processor=processor)
        return merged

    def get_error_report(self) -> Dict[str, Any]:
        """生成误差报告（可回放复盘）。"""
        return {
            'reference_id': self._reference_id,
            'n_nodes': len(self.nodes),
            'n_edges': len(self.edges),
            'edges': [
                {
                    'from': e.from_id,
                    'to': e.to_id,
                    'rms_mm': e.rms_mm,
                    'inlier_ratio': e.inlier_ratio,
                    'common_markers': e.common_markers,
                    'quality': e.quality,
                }
                for e in self.edges
            ],
            'cumulative_rms_mm': {
                sid: node.cum_rms_mm for sid, node in self.nodes.items()
            },
        }

    def detect_loop_closure(self, new_station_id: str) -> List[str]:
        """检测闭环：新帧与早期机位（非最近 3 个）共有标记 ≥6 时提示。"""
        if len(self.nodes) < 4:
            return []
        new_node = self.nodes.get(new_station_id)
        if new_node is None or not new_node.markers:
            return []
        new_codes = {m['code'] for m in new_node.markers}
        recent_ids = list(self.nodes.keys())[-3:]
        loops = []
        for sid, node in self.nodes.items():
            if sid in recent_ids or sid == new_station_id:
                continue
            old_codes = {m['code'] for m in node.markers}
            if len(new_codes & old_codes) >= 6:
                loops.append(sid)
        return loops

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _try_register(self, new_node: ChainNode, prev_node: ChainNode) -> Optional[ChainEdge]:
        """尝试把新机位配准到已有位姿图。"""
        result = self.calibration_engine.calibrate_pair(
            prev_node.station_id, new_node.station_id,
            prev_node.markers, new_node.markers,
            ransac_threshold=2.0)
        if not result.get('success'):
            return None
        return ChainEdge(
            from_id=new_node.station_id,
            to_id=prev_node.station_id,
            T=result['T'],
            rms_mm=result['rms_mm'],
            inlier_ratio=result['inlier_ratio'],
            common_markers=result['inlier_count'],
        )

    def _evaluate_edge(self, edge: ChainEdge) -> Tuple[bool, str]:
        """评估配准质量，返回 (ok, message)。"""
        if edge.common_markers < self.min_common_markers:
            return False, f"共有标记不足: {edge.common_markers} < {self.min_common_markers}"
        if edge.inlier_ratio < self.min_inlier_ratio:
            return False, f"内点率过低: {edge.inlier_ratio:.1%} < {self.min_inlier_ratio:.1%}"
        if edge.rms_mm > self.max_rms_mm:
            return False, f"RMS 过高: {edge.rms_mm:.3f}mm > {self.max_rms_mm}mm"
        edge.quality = "good" if edge.rms_mm < 0.5 else "ok"
        return True, "配准质量良好"

    def _compute_cumulative_rms(self, station_id: str) -> float:
        """计算机位到参考系的累计误差（沿最短路径的 RMS 均方根）。"""
        path_rms = []
        current = station_id
        visited = set()
        while current != self._reference_id and current not in visited:
            visited.add(current)
            edge = next((e for e in self.edges if e.from_id == current), None)
            if edge is None:
                break
            path_rms.append(edge.rms_mm)
            current = edge.to_id
        if not path_rms:
            return 0.0
        return float(np.sqrt(np.mean(np.square(path_rms))))
