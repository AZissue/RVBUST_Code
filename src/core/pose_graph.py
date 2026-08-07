# -*- coding: utf-8 -*-
"""
位姿图模块（pose_graph）—— 链式拓扑 BFS 复合 + 全局优化。

说明：
  - **星型拓扑**（单块标定板全共视）通常不经过本模块：
    CalibrationEngine.get_transform 通过直达 pair 或求逆即可得到任意
    from→to 变换；只有直达失败时才委托 find_path_transform。
  - **链式拓扑**（相邻相机两两共视，如环绕式多相机布局）使用本模块：
    当 from→to 没有直达 pair 时，在 pair 结果构成的无向图上做 BFS
    找一条最短变换链并依次复合（矩阵链乘）。
  - PoseGraph 类提供增量边添加（add_edge）与全局 BA（optimize_global_ba），
    用于功能二（单相机移动链式拼接）的实时位姿图构建与漂移消除。

方向约定与 calibration_engine 一致：
  pair_results[(ref_id, cam_id)]['T'] 是 cam→ref 的 4x4 变换，
  即 p_ref = T @ p_cam（齐次左乘）。pair (a, b) 视为无向边：
    - 沿 b→a 方向（存储方向）取 T；
    - 沿 a→b 方向取 np.linalg.inv(T)。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import least_squares

from .utils import logger


# =========================================================================
# 独立函数（原有，保持兼容）
# =========================================================================

def _build_adjacency(
    pair_results: Dict[Tuple[str, str], dict],
) -> Dict[str, List[Tuple[str, np.ndarray]]]:
    """把 pair_results 构建为无向邻接表。

    pair (a, b) 存的是 b→a 的变换 T（p_a = T @ p_b），因此：
      - a 的邻居列表加 (b, inv(T))：从 a 走一步到 b，p_b = inv(T) @ p_a；
      - b 的邻居列表加 (a, T)：      从 b 走一步到 a，p_a = T @ p_b。

    只收录含有效 T 矩阵的结果。
    """
    adj: Dict[str, List[Tuple[str, np.ndarray]]] = {}
    for (a, b), res in pair_results.items():
        T = res.get('T') if isinstance(res, dict) else None
        if T is None:
            continue
        T = np.asarray(T, dtype=np.float64)
        if T.shape != (4, 4):
            continue
        try:
            T_inv = np.linalg.inv(T)
        except np.linalg.LinAlgError:
            logger.warning(f"pair ({a}, {b}) 变换矩阵不可逆，已跳过")
            continue
        adj.setdefault(a, []).append((b, T_inv))
        adj.setdefault(b, []).append((a, T))
    return adj


def find_path_transform(
    pair_results: Dict[Tuple[str, str], dict],
    from_id: str,
    to_id: str,
) -> np.ndarray:
    """BFS 在 pair 图上搜索 from_id→to_id 的最短变换链并复合。

    图结构：pair (a, b) 视为无向边 a—b，正向（cam→ref，即 b→a）取
    存储的 T，反向取 np.linalg.inv(T)。找到路径后依次左乘复合：
    若路径为 v0=from → v1 → ... → vk=to，则
        T_total = T_step(v_{k-1}→v_k) @ ... @ T_step(v0→v1)
    满足 p_to = T_total @ p_from。

    Args:
        pair_results: CalibrationEngine.pair_results，{(ref_id, cam_id): result}
        from_id / to_id: 起点 / 终点相机 ID

    Returns:
        4x4 齐次变换矩阵，满足 p_to = T @ p_from

    Raises:
        ValueError: 找不到路径（图不连通或端点不在图中）
    """
    if from_id == to_id:
        return np.eye(4)

    adj = _build_adjacency(pair_results)
    if from_id not in adj:
        raise ValueError(f"位姿图中找不到起点 '{from_id}'（无相关 pair 标定）")
    if to_id not in adj:
        raise ValueError(f"位姿图中找不到终点 '{to_id}'（无相关 pair 标定）")

    # BFS 最短路径；prev[node] = (前驱节点, 前驱→node 的单步变换)
    prev: Dict[str, Tuple[Optional[str], Optional[np.ndarray]]] = {from_id: (None, None)}
    queue = deque([from_id])
    while queue:
        cur = queue.popleft()
        if cur == to_id:
            break
        for nxt, T_step in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = (cur, T_step)
                queue.append(nxt)

    if to_id not in prev:
        raise ValueError(
            f"位姿图不连通: 找不到 '{from_id}' → '{to_id}' 的变换路径"
        )

    # 回溯路径并依次左乘复合（从终点往起点收集，再反向相乘）
    steps: List[np.ndarray] = []
    node = to_id
    while prev[node][0] is not None:
        parent, T_step = prev[node]
        steps.append(T_step)
        node = parent

    T_total = np.eye(4)
    for T_step in reversed(steps):
        T_total = T_step @ T_total

    logger.info(
        f"位姿图链式复合 {from_id}→{to_id}: 经过 {len(steps)} 步 "
        f"({' -> '.join([from_id] + [n for n in _path_nodes(prev, from_id, to_id)])})"
    )
    return T_total


def _path_nodes(prev: dict, from_id: str, to_id: str) -> List[str]:
    """从 BFS 前驱表回溯节点路径（不含起点），仅用于日志。"""
    nodes = []
    node = to_id
    while node != from_id:
        nodes.append(node)
        node = prev[node][0]
    return list(reversed(nodes))


def optimize_global(
    pair_results: Dict[Tuple[str, str], dict],
    reference_id: str,
) -> Dict[str, np.ndarray]:
    """全局位姿图优化：以 reference_id 为锚点，联合优化所有相机外参。

    当前实现：简化为 BFS 生成树复合（以 reference_id 为根，沿最短路径
    把每台相机的变换复合到参考坐标系），不做迭代优化。不连通的相机
    记录 warning 并跳过。

    TODO(Phase 2+): 真正的全局 BA —— 以所有 pair 边为约束构建最小二乘
    问题（g2o/Ceres 风格），联合优化所有节点位姿，消除链式复合的
    累积误差；可用 scipy.optimize.least_squares 在李代数 SE(3) 上参数化，
    或引入 g2opy / ceres 绑定。

    Returns:
        {camera_id: T_cam_to_ref}（参考相机自身为 4x4 单位阵）
    """
    result: Dict[str, np.ndarray] = {reference_id: np.eye(4)}

    adj = _build_adjacency(pair_results)
    if reference_id not in adj:
        logger.warning(f"optimize_global: 参考相机 '{reference_id}' 不在位姿图中")
        return result

    # BFS 生成树：accum[node] 为 node→reference_id 的复合变换
    accum: Dict[str, np.ndarray] = {reference_id: np.eye(4)}
    queue = deque([reference_id])
    while queue:
        cur = queue.popleft()
        for nxt, T_step in adj.get(cur, []):
            if nxt in accum:
                continue
            # T_step 是 cur→nxt，故 nxt→cur = inv(T_step)，
            # nxt→ref = (cur→ref) @ (nxt→cur)
            accum[nxt] = accum[cur] @ np.linalg.inv(T_step)
            queue.append(nxt)

    # 收集不连通节点，记 warning
    all_nodes = set(adj.keys())
    unreachable = all_nodes - set(accum.keys())
    for node in sorted(unreachable):
        logger.warning(f"optimize_global: 相机 '{node}' 与 '{reference_id}' 不连通，已跳过")

    result.update(accum)
    logger.info(f"optimize_global(BFS生成树): 锚点 {reference_id}, "
                f"覆盖 {len(accum)} 台相机, 跳过 {len(unreachable)} 台")
    return result


# =========================================================================
# PoseGraph 类（新增，用于链式拼接增量位姿图）
# =========================================================================

@dataclass
class PoseEdge:
    """位姿图边。"""
    from_id: str
    to_id: str
    T: np.ndarray                # from→to 的 4x4 变换
    rms_mm: float = 0.0
    inlier_ratio: float = 0.0
    common_markers: int = 0


class PoseGraph:
    """增量位姿图：支持动态添加节点/边，实时查询变换，全局 BA 优化。"""

    def __init__(self):
        self.nodes: Dict[str, np.ndarray] = {}  # node_id → T_world (4x4)
        self.edges: List[PoseEdge] = []
        self._adjacency: Dict[str, List[Tuple[str, np.ndarray]]] = {}

    # ------------------------------------------------------------------
    # 节点/边管理
    # ------------------------------------------------------------------
    def add_node(self, node_id: str, T: np.ndarray = None):
        """添加节点（若已存在则更新变换）。"""
        if T is None:
            T = np.eye(4, dtype=np.float64)
        self.nodes[node_id] = np.asarray(T, dtype=np.float64)

    def add_edge(self, from_id: str, to_id: str, T: np.ndarray,
                 rms_mm: float = 0.0, inlier_ratio: float = 0.0,
                 common_markers: int = 0):
        """添加边（from→to 的相对位姿），并更新邻接表。"""
        T = np.asarray(T, dtype=np.float64)
        if T.shape != (4, 4):
            raise ValueError(f"边变换矩阵必须是 4x4，实际 {T.shape}")
        edge = PoseEdge(from_id, to_id, T, rms_mm, inlier_ratio, common_markers)
        self.edges.append(edge)
        # 更新邻接表（无向）
        try:
            T_inv = np.linalg.inv(T)
        except np.linalg.LinAlgError:
            logger.warning(f"边 ({from_id}, {to_id}) 变换矩阵不可逆，已跳过")
            return
        # 邻接表语义：从当前节点出发走到邻居节点所需的单步变换。
        # add_edge(from, to, T) 表示 p_to = T @ p_from，因此：
        #   - 从 from 走到 to 取 T
        #   - 从 to 走回 from 取 T_inv
        self._adjacency.setdefault(from_id, []).append((to_id, T))
        self._adjacency.setdefault(to_id, []).append((from_id, T_inv))
        # 如果节点不存在，自动添加
        if from_id not in self.nodes:
            self.add_node(from_id)
        if to_id not in self.nodes:
            self.add_node(to_id)

    def get_transform(self, from_id: str, to_id: str) -> np.ndarray:
        """查询 from_id→to_id 的变换（BFS 最短路径复合）。"""
        if from_id == to_id:
            return np.eye(4, dtype=np.float64)
        if from_id not in self._adjacency:
            raise ValueError(f"位姿图中找不到起点 '{from_id}'")
        if to_id not in self._adjacency:
            raise ValueError(f"位姿图中找不到终点 '{to_id}'")

        # BFS 最短路径
        prev: Dict[str, Tuple[Optional[str], Optional[np.ndarray]]] = {from_id: (None, None)}
        queue = deque([from_id])
        while queue:
            cur = queue.popleft()
            if cur == to_id:
                break
            for nxt, T_step in self._adjacency.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = (cur, T_step)
                    queue.append(nxt)

        if to_id not in prev:
            raise ValueError(f"位姿图不连通: 找不到 '{from_id}' → '{to_id}' 的路径")

        # 回溯并复合
        steps: List[np.ndarray] = []
        node = to_id
        while prev[node][0] is not None:
            parent, T_step = prev[node]
            steps.append(T_step)
            node = parent
        T_total = np.eye(4, dtype=np.float64)
        for T_step in reversed(steps):
            T_total = T_step @ T_total
        return T_total

    def get_edge_quality(self, from_id: str, to_id: str) -> Optional[PoseEdge]:
        """查询指定边的质量信息。"""
        for edge in self.edges:
            if (edge.from_id == from_id and edge.to_id == to_id) or \
               (edge.from_id == to_id and edge.to_id == from_id):
                return edge
        return None

    # ------------------------------------------------------------------
    # 全局优化（BA）
    # ------------------------------------------------------------------
    def optimize_global_ba(self, reference_id: str,
                           max_iterations: int = 50) -> Dict[str, np.ndarray]:
        """全局位姿图 BA：以 reference_id 为锚点，联合优化所有节点位姿。

        使用 scipy.optimize.least_squares 在 SE(3) 李代数上参数化，
        以所有边为约束构建最小二乘问题，消除链式复合的累积误差。

        Returns:
            {node_id: T_node_to_ref}（参考节点自身为 4x4 单位阵）
        """
        if reference_id not in self.nodes:
            logger.warning(f"optimize_global_ba: 参考节点 '{reference_id}' 不在位姿图中")
            return {reference_id: np.eye(4, dtype=np.float64)}

        # 收集所有节点和边
        node_ids = list(self.nodes.keys())
        if len(node_ids) < 2:
            return {nid: self.nodes[nid] for nid in node_ids}

        # 参数化：每个非参考节点用 6 维李代数 (rx, ry, rz, tx, ty, tz)
        non_ref_nodes = [nid for nid in node_ids if nid != reference_id]
        node_to_idx = {nid: i for i, nid in enumerate(non_ref_nodes)}
        n_params = len(node_to_idx) * 6
        if n_params == 0:
            return {reference_id: np.eye(4, dtype=np.float64)}

        # 初始值：用 BFS 生成树计算每个节点到参考系的位姿，避免 eye(4) 初值导致 LM 发散
        initial_poses = self._bfs_spanning_tree(reference_id)
        x0 = np.zeros(n_params, dtype=np.float64)
        for nid, idx in node_to_idx.items():
            T = initial_poses.get(nid, self.nodes.get(nid, np.eye(4, dtype=np.float64)))
            x0[idx*6:(idx+1)*6] = self._se3_log(T)

        # 构建残差函数
        def residuals(x):
            # 恢复所有节点位姿
            T_map = {reference_id: np.eye(4, dtype=np.float64)}
            for nid, idx in node_to_idx.items():
                T_map[nid] = self._se3_exp(x[idx*6:(idx+1)*6])
            res = []
            for edge in self.edges:
                if edge.from_id not in T_map or edge.to_id not in T_map:
                    continue
                T_pred = np.linalg.inv(T_map[edge.to_id]) @ T_map[edge.from_id]
                err = self._se3_log(np.linalg.inv(edge.T) @ T_pred)
                res.extend(err)
            return np.array(res)

        try:
            result = least_squares(residuals, x0, method='lm', max_nfev=max_iterations)
            # 恢复优化后的位姿
            optimized = {reference_id: np.eye(4, dtype=np.float64)}
            for nid, idx in node_to_idx.items():
                optimized[nid] = self._se3_exp(result.x[idx*6:(idx+1)*6])
            logger.info(f"optimize_global_ba: 锚点 {reference_id}, "
                        f"优化 {len(node_to_idx)} 节点, 残差 {result.cost:.6f}")
            return optimized
        except Exception as e:
            logger.error(f"optimize_global_ba 失败: {e}，回退到 BFS 生成树")
            return self._bfs_spanning_tree(reference_id)

    def _bfs_spanning_tree(self, reference_id: str) -> Dict[str, np.ndarray]:
        """BFS 生成树复合（BA 失败时的回退方案）。"""
        accum: Dict[str, np.ndarray] = {reference_id: np.eye(4, dtype=np.float64)}
        queue = deque([reference_id])
        while queue:
            cur = queue.popleft()
            for nxt, T_step in self._adjacency.get(cur, []):
                if nxt in accum:
                    continue
                accum[nxt] = accum[cur] @ np.linalg.inv(T_step)
                queue.append(nxt)
        return accum

    # ------------------------------------------------------------------
    # SE(3) 李代数工具
    # ------------------------------------------------------------------
    @staticmethod
    def _se3_log(T: np.ndarray) -> np.ndarray:
        """SE(3) → se(3) 对数映射（4x4 → 6 维向量 [rx, ry, rz, tx, ty, tz]）。"""
        R = T[:3, :3]
        t = T[:3, 3]
        # 旋转部分：矩阵对数（简化为轴角）
        cos_theta = (np.trace(R) - 1.0) / 2.0
        cos_theta = np.clip(cos_theta, -1.0, 1.0)
        theta = np.arccos(cos_theta)
        if abs(theta) < 1e-6:
            omega = np.zeros(3, dtype=np.float64)
        else:
            omega = theta / (2.0 * np.sin(theta)) * np.array([
                R[2, 1] - R[1, 2],
                R[0, 2] - R[2, 0],
                R[1, 0] - R[0, 1],
            ], dtype=np.float64)
        return np.concatenate([omega, t])

    @staticmethod
    def _se3_exp(x: np.ndarray) -> np.ndarray:
        """se(3) → SE(3) 指数映射（6 维向量 → 4x4）。"""
        omega = x[:3]
        t = x[3:]
        theta = np.linalg.norm(omega)
        if theta < 1e-6:
            R = np.eye(3, dtype=np.float64)
        else:
            k = omega / theta
            K = np.array([
                [0, -k[2], k[1]],
                [k[2], 0, -k[0]],
                [-k[1], k[0], 0],
            ], dtype=np.float64)
            R = (np.eye(3, dtype=np.float64) +
                 np.sin(theta) * K +
                 (1.0 - np.cos(theta)) * (K @ K))
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = R
        T[:3, 3] = t
        return T
