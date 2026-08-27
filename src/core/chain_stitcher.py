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

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

import open3d as o3d

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
    common_markers: int          # 共视标记总数（原始 code 交集）
    quality: str = "unknown"     # 质量评级：good / ok / poor
    inlier_count: int = 0        # RANSAC 内点数
    total_common: int = 0        # 与 common_markers 同义，保留以便显式区分


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

        # 增量合并缓存：机位 ID → 变换到参考系的点云；删除节点或位姿图变化时清空
        self._node_pcd_cache: Dict[str, o3d.geometry.PointCloud] = {}
        self._node_T_cache: Dict[str, np.ndarray] = {}
        self._merged_pcd_cache: Optional[o3d.geometry.PointCloud] = None

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
            self._cache_node_pcd(node)
            self._add_node_to_merged(station_id)
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
            # 配准失败：清理已加入的当前节点，避免残留影响后续匹配
            self.nodes.pop(station_id, None)
            return False, f"未找到足够共有标记（需 ≥{self.min_common_markers}），请减小移动距离", None

        # 4. 评估质量
        ok, quality_msg = self._evaluate_edge(best_edge)
        if not ok:
            # 评估失败：清理已加入的当前节点
            self.nodes.pop(station_id, None)
            return False, quality_msg, None

        # 5. 加入位姿图
        self.edges.append(best_edge)
        self.pose_graph.add_edge(best_edge.from_id, best_edge.to_id,
                                 best_edge.T, rms_mm=best_edge.rms_mm,
                                 inlier_ratio=best_edge.inlier_ratio,
                                 common_markers=best_edge.common_markers)
        try:
            node.T_world = self.pose_graph.get_transform(station_id, self._reference_id)
        except ValueError as e:
            # 防御性处理：加入边后仍无法到达参考系，说明图已不连通
            logger.error(f"add_frame: 机位 {station_id} 无法到达参考系: {e}")
            self.remove_node(station_id)
            return False, "位姿图不连通，请检查链式结构", None

        # 6. 缓存新机位变换后的点云并增量合并
        self._cache_node_pcd(node)
        self._add_node_to_merged(station_id)

        # 7. 更新累计误差
        node.cum_rms_mm = self._compute_cumulative_rms(station_id)

        msg = (f"机位 {station_id} 配准成功: {best_edge.common_markers} 个共有标记, "
               f"RMS {best_edge.rms_mm:.3f}mm, 内点率 {best_edge.inlier_ratio:.1%}, "
               f"累计误差 {node.cum_rms_mm:.3f}mm")
        logger.info(msg)
        return True, msg, best_edge

    def get_merged_pointcloud(self, processor=None):
        """获取当前拼接点云（优先使用增量缓存，缺失时回退全量重算）。"""
        if not self.nodes:
            return None

        # 若缓存缺失或不完整（例如位姿图变化后），回退到全量重算
        missing = [sid for sid in self.nodes if sid not in self._node_pcd_cache]
        if missing or self._merged_pcd_cache is None:
            self._rebuild_merged_cache()

        if self._merged_pcd_cache is None or len(self._merged_pcd_cache.points) == 0:
            return None

        merged = self._merged_pcd_cache
        if processor is not None:
            merged, _ = processor.process(merged)
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

    def get_station_evaluations(self) -> List[Dict[str, Any]]:
        """按节点顺序返回每个机位的评估信息（用于 UI 时间线重建）。"""
        result = []
        for sid, node in self.nodes.items():
            if sid == self._reference_id:
                result.append({
                    'station_id': sid,
                    'shared_markers': len(node.markers),
                    'inlier_ratio': 0.0,
                    'rms_mm': 0.0,
                    'status': 'ok',
                })
                continue
            # 取该机位关联的边（链中每个非参考节点应至少有一条出边）
            outgoing = [e for e in self.edges if e.from_id == sid]
            if not outgoing:
                result.append({
                    'station_id': sid,
                    'shared_markers': len(node.markers),
                    'inlier_ratio': 0.0,
                    'rms_mm': None,
                    'status': 'fail',
                })
                continue
            edge = min(outgoing, key=lambda e: e.rms_mm)
            result.append({
                'station_id': sid,
                'shared_markers': edge.common_markers,
                'inlier_ratio': edge.inlier_ratio,
                'rms_mm': edge.rms_mm,
                'status': edge.quality if edge.quality in ('ok', 'good') else 'ok',
            })
        return result

    def detect_loop_closure(self, new_station_id: str) -> List[str]:
        """检测闭环：新帧与早期机位（非最近 3 个）共有标记足够时提示。"""
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
            if len(new_codes & old_codes) >= self.min_common_markers:
                loops.append(sid)
        return loops

    def invalidate_cache(self):
        """清空增量合并缓存，强制下次 get_merged_pointcloud 全量重算。"""
        self._node_pcd_cache.clear()
        self._node_T_cache.clear()
        self._merged_pcd_cache = None

    def remove_node(self, station_id: str) -> List[str]:
        """从位姿图中移除指定机位及其关联边。

        若删除中间机位导致后续机位与参考系断开，会尝试用剩余机位重新配准
        （"后续链自动重算"）；重配准失败的机位才会被级联删除。最后重新计算
        所有剩余机位的 T_world，保证位姿图连通、无幻影点云。

        Returns:
            实际被移除的机位 ID 列表（含级联删除的机位）。
        """
        removed_ids: List[str] = []

        # 参考机位被删除时：直接清空整条链
        if station_id == self._reference_id:
            removed_ids.extend(list(self.nodes.keys()))
            self.nodes.clear()
            self.edges.clear()
            self.pose_graph = PoseGraph()
            self._reference_id = None
            self.invalidate_cache()
            return removed_ids

        # 常规删除
        if station_id in self.nodes:
            self.nodes.pop(station_id, None)
            removed_ids.append(station_id)
        self.edges = [e for e in self.edges
                      if e.from_id != station_id and e.to_id != station_id]
        self.pose_graph.remove_node(station_id)

        def _compute_reachable() -> set:
            """从参考系出发计算可达节点集合。"""
            reachable: set = set()
            if self._reference_id is None or self._reference_id not in self.nodes:
                return reachable
            queue = deque([self._reference_id])
            reachable.add(self._reference_id)
            while queue:
                cur = queue.popleft()
                for nxt, _ in self.pose_graph._adjacency.get(cur, []):
                    if nxt not in reachable:
                        reachable.add(nxt)
                        queue.append(nxt)
            return reachable

        reachable = _compute_reachable()

        # 尝试重新配准不可达机位（按原拍摄顺序）
        still_unreachable = []
        for sid in list(self.nodes.keys()):
            if sid in reachable:
                continue
            node = self.nodes.get(sid)
            if node is None:
                continue
            # 依次尝试与所有可达机位配准
            reregistered = False
            for prev_id in list(reachable):
                prev_node = self.nodes.get(prev_id)
                if prev_node is None:
                    continue
                edge = self._try_register(node, prev_node)
                if edge is None:
                    continue
                ok, _ = self._evaluate_edge(edge)
                if not ok:
                    continue
                # 重配准成功：加入位姿图并扩展可达集合
                self.edges.append(edge)
                self.pose_graph.add_edge(edge.from_id, edge.to_id,
                                         edge.T, rms_mm=edge.rms_mm,
                                         inlier_ratio=edge.inlier_ratio,
                                         common_markers=edge.common_markers)
                # 重配准成功后必须重算可达闭包，否则下游节点经新边已连通，
                # 仍会被判为不可达而重复注册，导致 edges 与邻接表出现重复边。
                reachable = _compute_reachable()
                reregistered = True
                break
            if not reregistered:
                still_unreachable.append(sid)

        # 删除无法重新配准的机位
        for sid in still_unreachable:
            self.nodes.pop(sid, None)
            self.pose_graph.remove_node(sid)
            removed_ids.append(sid)
        if still_unreachable:
            self.edges = [e for e in self.edges
                          if e.from_id not in still_unreachable
                          and e.to_id not in still_unreachable]

        # 重新计算所有剩余机位的世界变换（避免残留旧 T_world 导致幻影点云）
        for sid, node in self.nodes.items():
            if sid == self._reference_id:
                node.T_world = np.eye(4, dtype=np.float64)
            else:
                try:
                    node.T_world = self.pose_graph.get_transform(sid, self._reference_id)
                except ValueError as e:
                    logger.warning(f"remove_node: 机位 {sid} 变换重算失败: {e}")
                    node.T_world = None

        # 位姿图结构变化，清空缓存
        self.invalidate_cache()
        return removed_ids

    # ------------------------------------------------------------------
    # 增量合并缓存（内部）
    # ------------------------------------------------------------------
    def _cache_node_pcd(self, node: ChainNode) -> Optional[o3d.geometry.PointCloud]:
        """加载机位点云并按 node.T_world 变换到参考系后缓存。"""
        sid = node.station_id
        T = node.T_world
        try:
            pcd = node.frame.load_pointcloud_o3d()
        except Exception as e:
            logger.warning(f"链式拼接: 机位 '{sid}' 点云加载失败，跳过缓存: {e}")
            return None
        if pcd is None or len(pcd.points) == 0:
            self._node_pcd_cache.pop(sid, None)
            self._node_T_cache.pop(sid, None)
            return None
        # 复制一份避免污染原始 FrameData 中的点云数据
        pcd = o3d.geometry.PointCloud(pcd)
        if T is not None:
            pcd.transform(T.astype(np.float64))
        self._node_pcd_cache[sid] = pcd
        self._node_T_cache[sid] = T.copy() if T is not None else np.eye(4, dtype=np.float64)
        return pcd

    def _add_node_to_merged(self, station_id: str):
        """将指定机位的缓存点云增量合并到总点云。"""
        pcd = self._node_pcd_cache.get(station_id)
        if pcd is None:
            return
        if self._merged_pcd_cache is None:
            self._merged_pcd_cache = o3d.geometry.PointCloud()
        self._merged_pcd_cache += pcd

    def _rebuild_merged_cache(self):
        """根据当前所有节点重建缓存（回退路径）。"""
        self._node_pcd_cache.clear()
        self._node_T_cache.clear()
        self._merged_pcd_cache = o3d.geometry.PointCloud()
        for sid, node in self.nodes.items():
            self._cache_node_pcd(node)
            self._add_node_to_merged(sid)

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
        # 原始共有标记数（与 RANSAC 内点数区分）
        codes_prev = {m['code'] for m in prev_node.markers}
        codes_new = {m['code'] for m in new_node.markers}
        total_common = len(codes_prev & codes_new)
        return ChainEdge(
            from_id=new_node.station_id,
            to_id=prev_node.station_id,
            T=result['T'],
            rms_mm=result['rms_mm'],
            inlier_ratio=result['inlier_ratio'],
            common_markers=total_common,
            inlier_count=int(result.get('inlier_count', 0)),
            total_common=total_common,
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
