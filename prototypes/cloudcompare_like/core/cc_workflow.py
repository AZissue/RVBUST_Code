# -*- coding: utf-8 -*-
"""
工作流管线（Workflow / Pipeline）—— 后处理算法集成。

设计目标：
  - 可配置、可串联的算法节点（Node-Graph）
  - 每个节点：输入点云 → 处理 → 输出点云 + 标量场 / 标签
  - 支持异步执行，进度回调
  - 与主 src/core/postprocess 兼容，方便后期合并

节点清单：
  - VoxelDownsample   : 体素下采样
  - EstimateNormals   : 法线估计
  - StatisticalOutlier: 统计滤波
  - PlaneSegmentation : RANSAC 平面分割
  - EuclideanCluster  : 欧氏距离聚类
  - ScalarFieldCalc   : 标量场计算（曲率、密度）
"""

from __future__ import annotations

import numpy as np
import time
from typing import Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from cc_geometry import estimate_normals, voxel_downsample, bounding_box


# ── 数据容器 ──

@dataclass
class PointCloudData:
    """工作流中的点云数据包。"""
    points: np.ndarray                      # (N, 3) float32
    colors: Optional[np.ndarray] = None     # (N, 3/4) float32
    normals: Optional[np.ndarray] = None    # (N, 3) float32
    scalar_fields: Dict[str, np.ndarray] = field(default_factory=dict)  # name -> (N,) float32
    labels: Optional[np.ndarray] = None     # (N,) int32，分割/聚类标签
    metadata: Dict = field(default_factory=dict)

    @property
    def n_points(self) -> int:
        return len(self.points)

    def copy(self) -> PointCloudData:
        return PointCloudData(
            points=self.points.copy(),
            colors=self.colors.copy() if self.colors is not None else None,
            normals=self.normals.copy() if self.normals is not None else None,
            scalar_fields={k: v.copy() for k, v in self.scalar_fields.items()},
            labels=self.labels.copy() if self.labels is not None else None,
            metadata=dict(self.metadata),
        )


# ── 进度回调 ──

ProgressCallback = Callable[[str, float], None]  # (stage_name, progress_0_to_1)


# ── 节点基类 ──

class PipelineNode:
    """算法节点基类。"""

    name: str = "abstract"

    def __init__(self, **params):
        self.params = params
        self.enabled = True

    def process(self, data: PointCloudData, progress: Optional[ProgressCallback] = None) -> PointCloudData:
        raise NotImplementedError


# ── 具体节点实现 ──

class VoxelDownsampleNode(PipelineNode):
    """体素下采样。"""
    name = "voxel_downsample"

    def __init__(self, voxel_size: float = 0.01):
        super().__init__(voxel_size=voxel_size)

    def process(self, data: PointCloudData, progress=None) -> PointCloudData:
        vs = self.params["voxel_size"]
        pts, cols, norms = voxel_downsample(data.points, vs, data.colors, data.normals)
        out = data.copy()
        out.points = pts
        out.colors = cols
        out.normals = norms
        # 标量场需要重新聚合
        out.scalar_fields = {}
        return out


class EstimateNormalsNode(PipelineNode):
    """法线估计。"""
    name = "estimate_normals"

    def __init__(self, k: int = 10):
        super().__init__(k=k)

    def process(self, data: PointCloudData, progress=None) -> PointCloudData:
        out = data.copy()
        out.normals = estimate_normals(data.points, k=self.params["k"])
        return out


class StatisticalOutlierNode(PipelineNode):
    """统计滤波（离群点去除）。"""
    name = "statistical_outlier"

    def __init__(self, k: int = 6, std_ratio: float = 1.0):
        super().__init__(k=k, std_ratio=std_ratio)

    def process(self, data: PointCloudData, progress=None) -> PointCloudData:
        from sklearn.neighbors import NearestNeighbors
        k = min(self.params["k"] + 1, len(data.points))
        nbrs = NearestNeighbors(n_neighbors=k, algorithm='kd_tree')
        nbrs.fit(data.points)
        distances, _ = nbrs.kneighbors(data.points)
        mean_dist = distances[:, 1:].mean(axis=1)
        global_mean = mean_dist.mean()
        global_std = mean_dist.std()
        threshold = global_mean + self.params["std_ratio"] * global_std
        mask = mean_dist < threshold

        out = data.copy()
        out.points = data.points[mask]
        if data.colors is not None:
            out.colors = data.colors[mask]
        if data.normals is not None:
            out.normals = data.normals[mask]
        out.scalar_fields = {}
        return out


class PlaneSegmentationNode(PipelineNode):
    """RANSAC 平面分割。"""
    name = "plane_segmentation"

    def __init__(self, distance_threshold: float = 0.01, max_iterations: int = 1000,
                 min_points: int = 100, max_planes: int = 5):
        super().__init__(distance_threshold=distance_threshold,
                         max_iterations=max_iterations,
                         min_points=min_points,
                         max_planes=max_planes)

    def process(self, data: PointCloudData, progress=None) -> PointCloudData:
        pts = data.points.copy()
        labels = np.full(len(pts), -1, dtype=np.int32)
        plane_id = 0

        dt = self.params["distance_threshold"]
        max_iter = self.params["max_iterations"]
        min_pts = self.params["min_points"]
        max_planes = self.params["max_planes"]

        remaining = np.ones(len(pts), dtype=bool)

        for _ in range(max_planes):
            if remaining.sum() < min_pts:
                break
            # RANSAC 平面拟合
            best_inliers = None
            best_count = 0
            idx = np.where(remaining)[0]
            for _ in range(max_iter):
                if len(idx) < 3:
                    break
                sample = idx[np.random.choice(len(idx), 3, replace=False)]
                p1, p2, p3 = pts[sample]
                normal = np.cross(p2 - p1, p3 - p1)
                norm = np.linalg.norm(normal)
                if norm < 1e-10:
                    continue
                normal /= norm
                d = -np.dot(normal, p1)
                dists = np.abs(pts[idx] @ normal + d)
                inliers = idx[dists < dt]
                if len(inliers) > best_count:
                    best_count = len(inliers)
                    best_inliers = inliers

            if best_inliers is None or len(best_inliers) < min_pts:
                break

            labels[best_inliers] = plane_id
            remaining[best_inliers] = False
            plane_id += 1

        out = data.copy()
        out.labels = labels
        # 添加平面 ID 作为标量场
        out.scalar_fields["plane_id"] = labels.astype(np.float32)
        return out


class EuclideanClusterNode(PipelineNode):
    """欧氏距离聚类。"""
    name = "euclidean_cluster"

    def __init__(self, cluster_tolerance: float = 0.02, min_cluster_size: int = 100,
                 max_cluster_size: int = 1000000):
        super().__init__(cluster_tolerance=cluster_tolerance,
                         min_cluster_size=min_cluster_size,
                         max_cluster_size=max_cluster_size)

    def process(self, data: PointCloudData, progress=None) -> PointCloudData:
        from sklearn.cluster import DBSCAN
        eps = self.params["cluster_tolerance"]
        min_samples = max(1, self.params["min_cluster_size"] // 10)
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(data.points)
        labels = clustering.labels_.astype(np.int32)

        out = data.copy()
        out.labels = labels
        out.scalar_fields["cluster_id"] = labels.astype(np.float32)
        return out


class CurvatureScalarFieldNode(PipelineNode):
    """计算曲率标量场。"""
    name = "curvature_scalar"

    def __init__(self, k: int = 10):
        super().__init__(k=k)

    def process(self, data: PointCloudData, progress=None) -> PointCloudData:
        from sklearn.neighbors import NearestNeighbors
        k = min(self.params["k"] + 1, len(data.points))
        nbrs = NearestNeighbors(n_neighbors=k, algorithm='kd_tree')
        nbrs.fit(data.points)
        _, indices = nbrs.kneighbors(data.points)

        curvatures = np.empty(len(data.points), dtype=np.float32)
        for i in range(len(data.points)):
            neigh = data.points[indices[i][1:]] - data.points[i]
            cov = neigh.T @ neigh / max(len(neigh), 1)
            eigvals = np.linalg.eigvalsh(cov)
            eigvals = np.sort(eigvals)
            # 曲率 = 最小特征值 / 特征值和
            s = eigvals.sum()
            curvatures[i] = eigvals[0] / s if s > 1e-12 else 0.0

        out = data.copy()
        out.scalar_fields["curvature"] = curvatures
        return out


# ── 管线编排 ──

class Pipeline:
    """可配置后处理管线。"""

    def __init__(self):
        self.nodes: List[PipelineNode] = []
        self._history: List[PointCloudData] = []

    def add(self, node: PipelineNode) -> Pipeline:
        self.nodes.append(node)
        return self

    def clear(self):
        self.nodes.clear()
        self._history.clear()

    def run(self, data: PointCloudData, progress: Optional[ProgressCallback] = None) -> PointCloudData:
        """顺序执行所有节点。"""
        current = data
        self._history = [data.copy()]

        for i, node in enumerate(self.nodes):
            if not node.enabled:
                continue
            stage_name = f"[{i+1}/{len(self.nodes)}] {node.name}"
            if progress:
                progress(stage_name, i / len(self.nodes))
            current = node.process(current, progress)
            self._history.append(current.copy())
            if progress:
                progress(stage_name, (i + 1) / len(self.nodes))

        return current

    def undo(self) -> Optional[PointCloudData]:
        if len(self._history) > 1:
            self._history.pop()
            return self._history[-1]
        return None

    def export_history(self) -> List[PointCloudData]:
        return self._history


# ── 预定义管线模板 ──

def create_default_pipeline() -> Pipeline:
    """默认后处理管线：下采样 → 滤波 → 法线 → 曲率。"""
    p = Pipeline()
    p.add(VoxelDownsampleNode(voxel_size=0.005))
    p.add(StatisticalOutlierNode(k=6, std_ratio=1.0))
    p.add(EstimateNormalsNode(k=10))
    p.add(CurvatureScalarFieldNode(k=10))
    return p


def create_segmentation_pipeline() -> Pipeline:
    """分割管线：下采样 → 平面分割 → 聚类。"""
    p = Pipeline()
    p.add(VoxelDownsampleNode(voxel_size=0.01))
    p.add(PlaneSegmentationNode(distance_threshold=0.01, max_planes=5))
    p.add(EuclideanClusterNode(cluster_tolerance=0.02, min_cluster_size=100))
    return p
