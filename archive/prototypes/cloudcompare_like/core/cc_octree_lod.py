# -*- coding: utf-8 -*-
"""
LOD 八叉树（Level-of-Detail Octree）。

核心设计：
  - 每朵点云构建八叉树，每层存储均匀采样的子集；
  - 渲染时根据相机距离和视口大小动态选择层级；
  - Frustum Culling：只渲染与视锥相交的体素；
  - 目标：单路 5000 万点流畅交互。

与现有 viewer_3d.py 的关系：
  - 可独立于 UI 构建 Octree；
  - PointCloudViewerLOD 在 paintGL 中调用 Octree 的 query() 获取可见点集。

实现要点（2026-09 修复）：
  - 构建全程向量化（按层划分索引数组），百万级点秒级完成；
    旧版逐点 Python 递归插入，180 万点需数分钟且阻塞 UI。
  - 每个内部节点缓存"子树均匀采样"（≤ POINTS_PER_NODE），
    LOD 层级 = 该层节点的子树采样并集，保证任意层级点数完整、
    空间覆盖均匀；旧版在目标深度直接返回内部节点的空索引表，
    导致深层级大面积缺数据、点云显示拉丝/残缺。
  - query() 按 (target_count → LOD 层级) 缓存结果，相机不动时
    paintGL 每帧零开销，配合 viewer 的上传缓存避免重复传 VBO。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np


class OctreeNode:
    """八叉树节点。"""

    def __init__(self, center: np.ndarray, half_size: float, depth: int = 0):
        self.center = np.asarray(center, dtype=np.float64)
        self.half_size = half_size
        self.depth = depth
        self.children: List[Optional[OctreeNode]] = [None] * 8
        self.point_indices: Optional[np.ndarray] = None  # 叶子节点存储的点索引
        self.sample: Optional[np.ndarray] = None         # 子树均匀采样（含自身/后代叶子）
        self.is_leaf = True
        self.bbox_min = self.center - self.half_size
        self.bbox_max = self.center + self.half_size

    def contains(self, point: np.ndarray) -> bool:
        """判断点是否在本节点包围盒内。"""
        p = np.asarray(point)
        return np.all((p >= self.bbox_min) & (p <= self.bbox_max))

    def intersects_sphere(self, center: np.ndarray, radius: float) -> bool:
        """判断包围盒是否与球相交（用于视锥裁剪简化版）。"""
        # AABB-Sphere 相交测试
        closest = np.clip(center, self.bbox_min, self.bbox_max)
        dist2 = np.sum((closest - center) ** 2)
        return dist2 <= radius * radius


class PointCloudOctree:
    """点云 LOD 八叉树。"""

    MAX_DEPTH = 8
    POINTS_PER_NODE = 500  # 叶子节点最大点数 / 子树采样上限，超过则分裂或采样

    def __init__(self, points: np.ndarray, colors: Optional[np.ndarray] = None):
        """
        Args:
            points: (N, 3) float32
            colors: (N, 3) float32 or None
        """
        self.points = np.ascontiguousarray(points, dtype=np.float32)
        self.colors = np.ascontiguousarray(colors, dtype=np.float32) if colors is not None else None
        self.n_points = len(self.points)
        self.root: Optional[OctreeNode] = None
        self._lod_levels: Dict[int, np.ndarray] = {}  # depth -> point_indices
        self._query_cache: Dict[int, Tuple[int, np.ndarray, Optional[np.ndarray]]] = {}
        self._rng = np.random.default_rng(42)  # 固定种子，采样结果稳定
        self._build()

    # ------------------------------------------------------------------
    # 构建（向量化）
    # ------------------------------------------------------------------
    def _build(self):
        """构建八叉树 + LOD 层级缓存。"""
        if self.n_points == 0:
            return

        mins = self.points.min(axis=0)
        maxs = self.points.max(axis=0)
        center = (mins + maxs) / 2.0
        half_size = float(np.max(maxs - mins)) / 2.0 * 1.01  # 稍微扩大避免边界点丢失

        self.root = OctreeNode(center, half_size, depth=0)
        self._build_recursive(self.root, np.arange(self.n_points, dtype=np.int64))
        self._build_lod_cache()

    def _build_recursive(self, node: OctreeNode, indices: np.ndarray):
        """按层向量化划分：一次 fancy indexing 把索引分到 8 个子节点。"""
        if len(indices) <= self.POINTS_PER_NODE or node.depth >= self.MAX_DEPTH:
            node.is_leaf = True
            node.point_indices = indices
            return

        node.is_leaf = False
        pts = self.points[indices]
        gt = pts > node.center
        child_no = (gt[:, 0].astype(np.int32)
                    | (gt[:, 1].astype(np.int32) << 1)
                    | (gt[:, 2].astype(np.int32) << 2))

        offset = node.half_size / 2.0
        for c in range(8):
            sub = indices[child_no == c]
            if len(sub) == 0:
                continue
            new_center = node.center.copy()
            if c & 1:
                new_center[0] += offset
            else:
                new_center[0] -= offset
            if c & 2:
                new_center[1] += offset
            else:
                new_center[1] -= offset
            if c & 4:
                new_center[2] += offset
            else:
                new_center[2] -= offset
            child = OctreeNode(new_center, offset, node.depth + 1)
            node.children[c] = child
            self._build_recursive(child, sub)

    # ------------------------------------------------------------------
    # LOD 层级缓存
    # ------------------------------------------------------------------
    def _subtree_sample(self, node: OctreeNode) -> np.ndarray:
        """自底向上为每个节点生成子树均匀采样，缓存到 node.sample。

        叶子节点保留全部点（达到 MAX_DEPTH 仍过密的叶子不截断，
        保证最精细层级 = 完整点云）；内部节点采样到 ≤ POINTS_PER_NODE。
        """
        if node.is_leaf:
            idx = node.point_indices if node.point_indices is not None else np.empty(0, dtype=np.int64)
            node.sample = idx
            return idx
        parts = [self._subtree_sample(c) for c in node.children if c is not None]
        idx = np.concatenate(parts) if parts else np.empty(0, dtype=np.int64)
        if len(idx) > self.POINTS_PER_NODE:
            take = self._rng.choice(len(idx), self.POINTS_PER_NODE, replace=False)
            idx = idx[np.sort(take)]
        node.sample = idx
        return idx

    def _build_lod_cache(self):
        """预计算各 LOD 层级的点索引（每层 = 该层节点子树采样的并集）。"""
        self._subtree_sample(self.root)
        self._lod_levels = {}
        for depth in range(self.MAX_DEPTH + 1):
            indices = self._collect_lod(self.root, depth)
            if len(indices) > 0:
                self._lod_levels[depth] = np.asarray(indices, dtype=np.int32)

    def _collect_lod(self, node: Optional[OctreeNode], target_depth: int) -> np.ndarray:
        """收集指定 LOD 层级的点索引。

        到达目标深度的内部节点返回其子树采样（node.sample），
        叶子节点返回自身点/采样，保证层级数据完整、空间覆盖均匀。
        """
        if node is None:
            return np.empty(0, dtype=np.int64)
        if node.is_leaf or node.depth >= target_depth:
            if node.sample is not None:
                return node.sample
            return node.point_indices if node.point_indices is not None else np.empty(0, dtype=np.int64)
        parts = [self._collect_lod(child, target_depth) for child in node.children if child is not None]
        return np.concatenate(parts) if parts else np.empty(0, dtype=np.int64)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _pick_depth(self, target_count: int) -> int:
        """选择不超过目标点数的最高 LOD 层级。"""
        best_depth = 0
        for depth in range(self.MAX_DEPTH, -1, -1):
            if depth in self._lod_levels and len(self._lod_levels[depth]) <= target_count:
                best_depth = depth
                break
        return best_depth

    def query(self, camera_pos: np.ndarray, target_count: int = 500_000) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """根据相机位置和点数目标查询渲染点集。

        结果按 (target_count → 层级) 缓存：相机不动、预算不变时
        返回同一数组对象，viewer 可据此跳过重复 VBO 上传。

        Args:
            camera_pos: 相机世界坐标 (3,)
            target_count: 目标点数上限

        Returns:
            (points, colors) 或 (points, None)
        """
        if self.root is None:
            return np.zeros((0, 3), dtype=np.float32), None

        best_depth = self._pick_depth(target_count)
        cached = self._query_cache.get(target_count)
        if cached is not None and cached[0] == best_depth:
            return cached[1], cached[2]
        if len(self._query_cache) > 16:  # 防御性上限
            self._query_cache.clear()

        indices = self._lod_levels.get(best_depth)
        if indices is None:
            indices = next(iter(self._lod_levels.values()), np.empty(0, dtype=np.int32))
        pts = self.points[indices]
        cols = self.colors[indices] if self.colors is not None else None
        self._query_cache[target_count] = (best_depth, pts, cols)
        return pts, cols

    def query_frustum(self, frustum_planes: List[np.ndarray],
                      camera_pos: np.ndarray,
                      target_count: int = 500_000) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """视锥体裁剪查询（6 个裁剪平面）。

        Args:
            frustum_planes: 6 个裁剪平面 (a,b,c,d)，ax+by+cz+d>0 为可见
            camera_pos: 相机位置
            target_count: 目标点数

        Returns:
            (points, colors)
        """
        if self.root is None:
            return np.zeros((0, 3), dtype=np.float32), None

        best_depth = self._pick_depth(target_count)
        indices = np.asarray(self._collect_frustum(self.root, frustum_planes, best_depth), dtype=np.int32)
        if len(indices) == 0:
            return np.zeros((0, 3), dtype=np.float32), None

        pts = self.points[indices]
        cols = self.colors[indices] if self.colors is not None else None
        return pts, cols

    def _collect_frustum(self, node: Optional[OctreeNode],
                         frustum_planes: List[np.ndarray],
                         target_depth: int) -> np.ndarray:
        """递归收集视锥内节点的点索引。"""
        if node is None:
            return np.empty(0, dtype=np.int64)

        # 快速包围盒-视锥测试：如果包围盒完全在某一平面外，剔除
        if not self._aabb_in_frustum(node.bbox_min, node.bbox_max, frustum_planes):
            return np.empty(0, dtype=np.int64)

        if node.is_leaf or node.depth >= target_depth:
            if node.sample is not None:
                return node.sample
            return node.point_indices if node.point_indices is not None else np.empty(0, dtype=np.int64)

        parts = [self._collect_frustum(child, frustum_planes, target_depth)
                 for child in node.children if child is not None]
        return np.concatenate(parts) if parts else np.empty(0, dtype=np.int64)

    @staticmethod
    def _aabb_in_frustum(bbox_min: np.ndarray, bbox_max: np.ndarray,
                         frustum_planes: List[np.ndarray]) -> bool:
        """AABB-Frustum 相交测试（保守版）。"""
        for plane in frustum_planes:
            a, b, c, d = plane
            # 找到包围盒在平面法线方向上的最远点
            px = bbox_min[0] if a < 0 else bbox_max[0]
            py = bbox_min[1] if b < 0 else bbox_max[1]
            pz = bbox_min[2] if c < 0 else bbox_max[2]
            if a * px + b * py + c * pz + d < 0:
                # 最远点在平面背面，整个 AABB 在平面外
                return False
        return True


# =========================================================================
# 多路点云 LOD 管理器
# =========================================================================
class MultiCloudLODManager:
    """管理多朵点云的 LOD 八叉树。"""

    def __init__(self, budget_per_cloud: int = 500_000):
        self.budget_per_cloud = budget_per_cloud
        self._octrees: Dict[str, PointCloudOctree] = {}

    def add_cloud(self, cloud_id: str, points: np.ndarray,
                  colors: Optional[np.ndarray] = None):
        """为点云构建 LOD 八叉树。"""
        self._octrees[cloud_id] = PointCloudOctree(points, colors)

    def remove_cloud(self, cloud_id: str):
        self._octrees.pop(cloud_id, None)

    def clear(self):
        self._octrees.clear()

    def query_all(self, camera_pos: np.ndarray,
                  total_budget: Optional[int] = None) -> Dict[str, Tuple[np.ndarray, Optional[np.ndarray]]]:
        """查询所有可见点云的 LOD 点集。

        Returns:
            {cloud_id: (points, colors)}
        """
        if total_budget is None:
            total_budget = self.budget_per_cloud * max(1, len(self._octrees))

        n_clouds = len(self._octrees)
        per_cloud = total_budget // max(n_clouds, 1)

        result = {}
        for cid, octree in self._octrees.items():
            pts, cols = octree.query(camera_pos, per_cloud)
            result[cid] = (pts, cols)
        return result
