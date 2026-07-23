# -*- coding: utf-8 -*-
"""
位姿图模块（pose_graph）—— 链式拓扑 BFS 复合 + 全局优化预留（Phase 2 已实现）。

说明：
  - **星型拓扑**（单块标定板全共视）通常不经过本模块：
    CalibrationEngine.get_transform 通过直达 pair 或求逆即可得到任意
    from→to 变换；只有直达失败时才委托 find_path_transform。
  - **链式拓扑**（相邻相机两两共视，如环绕式多相机布局）使用本模块：
    当 from→to 没有直达 pair 时，在 pair 结果构成的无向图上做 BFS
    找一条最短变换链并依次复合（矩阵链乘）。
  - optimize_global 当前简化为 BFS 生成树复合；真正的全局 BA
    （g2o/Ceres 风格最小二乘）留待 Phase 2+（见函数内 TODO）。

方向约定与 calibration_engine 一致：
  pair_results[(ref_id, cam_id)]['T'] 是 cam→ref 的 4x4 变换，
  即 p_ref = T @ p_cam（齐次左乘）。pair (a, b) 视为无向边：
    - 沿 b→a 方向（存储方向）取 T；
    - 沿 a→b 方向取 np.linalg.inv(T)。
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

from .utils import logger


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
