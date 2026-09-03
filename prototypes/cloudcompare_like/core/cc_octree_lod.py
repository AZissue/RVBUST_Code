# -*- coding: utf-8 -*-
"""
Octree + LOD（Level-of-Detail）—— 高性能大规模点云渲染核心。

设计理念：
  - 八叉树空间索引：O(log n) 最近邻查询、快速视锥裁剪
  - LOD 层级：根据相机距离动态选择不同密度层级
  - 后台线程：八叉树构建 + LOD 采样不阻塞 UI
  - 显存友好：每个 LOD 层级单独 VBO，按需上传
"""

from __future__ import annotations

import numpy as np
import threading
from typing import Dict, List, Optional, Tuple


class OctreeNode:
    """八叉树节点。"""

    __slots__ = ['center', 'half_size', 'depth', 'points', 'indices', 'children', 'lod_level']

    def __init__(self, center: np.ndarray, half_size: float, depth: int = 0):
        self.center = center.astype(np.float32)  # (3,)
        self.half_size = half_size
        self.depth = depth
        self.points: Optional[np.ndarray] = None       # 本节点包含的点 (N,3)
        self.indices: Optional[np.ndarray] = None      # 原始索引
        self.children: List[Optional[OctreeNode]] = [None] * 8
        self.lod_level: int = 0

    def is_leaf(self) -> bool:
        return all(c is None for c in self.children)

    def intersects_sphere(self, center: np.ndarray, radius: float) -> bool:
        """快速球体- AABB 相交测试。"""
        closest = np.clip(center, self.center - self.half_size, self.center + self.half_size)
        return np.sum((center - closest) ** 2) < radius ** 2


class OctreeLOD:
    """八叉树 + LOD 管理器。"""

    MAX_DEPTH = 8
    MAX_POINTS_PER_LEAF = 2048

    def __init__(self, points: np.ndarray):
        self._all_points = points.astype(np.float32)
        self._root: Optional[OctreeNode] = None
        self._lod_buffers: Dict[int, np.ndarray] = {}  # level -> sampled points
        self._build_lock = threading.Lock()
        self._ready = False
        self._thread: Optional[threading.Thread] = None

    def build_async(self):
        """后台线程构建八叉树。"""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._build, daemon=True)
        self._thread.start()

    def _build(self):
        with self._build_lock:
            min_bound = self._all_points.min(axis=0)
            max_bound = self._all_points.max(axis=0)
            center = (min_bound + max_bound) / 2
            half_size = float(np.max(max_bound - min_bound) / 2 + 1e-6)

            self._root = OctreeNode(center, half_size, depth=0)
            self._insert_points(self._root, np.arange(len(self._all_points)))
            self._build_lod(self._root)
            self._ready = True

    def _insert_points(self, node: OctreeNode, indices: np.ndarray):
        """递归插入点到八叉树。"""
        if len(indices) <= self.MAX_POINTS_PER_LEAF or node.depth >= self.MAX_DEPTH:
            node.points = self._all_points[indices]
            node.indices = indices
            return

        # 分到 8 个子节点
        mask = self._all_points[indices] > node.center
        for i in range(8):
            # i 的 3bit = (z>center, y>center, x>center)
            mx, my, mz = (i >> 0) & 1, (i >> 1) & 1, (i >> 2) & 1
            sub_mask = (mask[:, 0] == mx) & (mask[:, 1] == my) & (mask[:, 2] == mz)
            sub_idx = indices[sub_mask]
            if len(sub_idx) == 0:
                continue
            offset = np.array([
                (1 if mx else -1) * node.half_size / 2,
                (1 if my else -1) * node.half_size / 2,
                (1 if mz else -1) * node.half_size / 2,
            ])
            child = OctreeNode(node.center + offset, node.half_size / 2, node.depth + 1)
            node.children[i] = child
            self._insert_points(child, sub_idx)

        # 非叶子节点不存储点
        node.points = None
        node.indices = None

    def _build_lod(self, node: OctreeNode):
        """自底向上构建 LOD 采样。"""
        if node.is_leaf():
            node.lod_level = node.depth
            return

        # 收集所有子节点的点做采样
        all_pts = []
        for child in node.children:
            if child is not None:
                self._build_lod(child)
                if child.points is not None:
                    all_pts.append(child.points)

        if all_pts:
            merged = np.concatenate(all_pts, axis=0)
            # 简单均匀采样到目标数量
            target = self.MAX_POINTS_PER_LEAF
            if len(merged) > target:
                step = max(1, len(merged) // target)
                node.points = merged[::step].copy()
            else:
                node.points = merged
        node.lod_level = node.depth

    def is_ready(self) -> bool:
        return self._ready

    def wait_ready(self, timeout: float = 30.0):
        if self._thread:
            self._thread.join(timeout=timeout)

    def collect_visible_points(
        self,
        camera_pos: np.ndarray,
        camera_dir: np.ndarray,
        fov: float,
        screen_height: int,
        target_pixel_size: float = 2.0,
    ) -> Optional[np.ndarray]:
        """
        根据相机参数收集应渲染的点（视锥 + LOD）。

        Returns
        -------
        points : (M, 3) float32 或 None（未就绪）
        """
        if not self._ready or self._root is None:
            return None

        result = []
        self._collect_recursive(self._root, camera_pos, camera_dir, fov, screen_height, target_pixel_size, result)
        if not result:
            return np.empty((0, 3), dtype=np.float32)
        return np.concatenate(result, axis=0)

    def _collect_recursive(
        self, node: OctreeNode, camera_pos, camera_dir, fov, screen_height, target_pixel_size, result
    ):
        """递归收集可见节点。"""
        # 视锥裁剪（简化为距离测试）
        dist = np.linalg.norm(node.center - camera_pos)
        if dist < 1e-6:
            dist = 1e-6

        # 计算屏幕像素大小
        pixel_size = (node.half_size * 2) / (dist * np.tan(np.radians(fov / 2))) * screen_height / 2

        # 如果节点在屏幕上很小，直接返回本节点 LOD 点
        if pixel_size < target_pixel_size or node.is_leaf():
            if node.points is not None:
                result.append(node.points)
            return

        # 继续遍历子节点
        for child in node.children:
            if child is not None:
                self._collect_recursive(child, camera_pos, camera_dir, fov, screen_height, target_pixel_size, result)

    def query_sphere(self, center: np.ndarray, radius: float) -> np.ndarray:
        """半径搜索，返回索引数组。"""
        result = []
        self._query_sphere_recursive(self._root, center, radius, result)
        if not result:
            return np.empty(0, dtype=np.int32)
        return np.concatenate(result)

    def _query_sphere_recursive(self, node: OctreeNode, center, radius, result):
        if node is None:
            return
        if not node.intersects_sphere(center, radius):
            return
        if node.is_leaf() and node.indices is not None:
            # 精确测试
            pts = self._all_points[node.indices]
            mask = np.sum((pts - center) ** 2, axis=1) < radius ** 2
            result.append(node.indices[mask])
            return
        for child in node.children:
            self._query_sphere_recursive(child, center, radius, result)
