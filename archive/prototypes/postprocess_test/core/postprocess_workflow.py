# -*- coding: utf-8 -*-
"""
后处理工作流核心（PostprocessWorkflow）。

管理 DB 树中的多路点云节点，提供：
  - 点云加载 / 添加 / 删除 / 选择；
  - 后处理：体素下采样、统计离群点去除、AABB/球/OBB 裁切；
  - ICP 点云配准（source 对齐到 target）；
  - 点云合并（安全属性对齐）；
  - 导出 PLY/PCD；
  - 处理历史（撤销 / 重做）。

设计约束：
  - 不导入 PySide6，日志通过 core.utils.logger 输出；
  - open3d / numpy 延迟导入，无 SDK / GPU 环境可跑单元测试；
  - 接口尽量对齐 src/core/workflow_base.py 的模式，方便后期并入主程序。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from core.point_cloud_processor import PointCloudProcessor
from core.pcd_utils import merge_pointclouds
from core.utils import logger


class CloudNode:
    """DB 树中的一路点云节点。"""

    def __init__(self, node_id: str, name: str, pcd: Any,
                 parent_id: Optional[str] = None,
                 visible: bool = True,
                 color: Optional[Tuple[float, float, float]] = None):
        self.node_id = node_id
        self.name = name
        self.pcd = pcd
        self.parent_id = parent_id
        self.visible = visible
        self.color = color or (0.7, 0.7, 0.7)
        self.point_size = 1

    @property
    def point_count(self) -> int:
        return len(self.pcd.points) if self.pcd is not None else 0

    def clone(self) -> "CloudNode":
        import copy
        return copy.deepcopy(self)


class ICPResult:
    """ICP 配准结果。"""

    def __init__(self, transformation, fitness: float, inlier_rmse: float,
                 message: str = ""):
        self.transformation = transformation
        self.fitness = fitness
        self.inlier_rmse = inlier_rmse
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        import numpy as np
        return {
            "fitness": self.fitness,
            "inlier_rmse": self.inlier_rmse,
            "message": self.message,
            "transformation": np.asarray(self.transformation).tolist(),
        }


class PostprocessWorkflow:
    """后处理工作流（无 UI 依赖）。"""

    STATES = ("idle", "loaded", "processing")

    def __init__(self):
        self._state = "idle"
        self._nodes: Dict[str, CloudNode] = {}
        self._node_order: List[str] = []
        self._selected_id: Optional[str] = None
        self._next_id = 1

        # 后处理参数
        self.processor = PointCloudProcessor()

        # 处理历史：item = {"action", "node_id", "before_pcd", "after_pcd"}
        self._history: List[Dict[str, Any]] = []
        self._history_index: int = -1

    # ------------------------------------------------------------------
    # 状态与查询
    # ------------------------------------------------------------------
    def get_state(self) -> str:
        return self._state

    def get_mode_name(self) -> str:
        return "postprocess"

    def can_proceed(self) -> Tuple[bool, str]:
        if not self._nodes:
            return False, "尚未加载任何点云"
        return True, ""

    def reset(self):
        self._nodes.clear()
        self._node_order.clear()
        self._selected_id = None
        self._history.clear()
        self._history_index = -1
        self._state = "idle"

    # ------------------------------------------------------------------
    # 节点管理
    # ------------------------------------------------------------------
    def _generate_id(self) -> str:
        return f"cloud_{self._next_id}"

    def add_cloud(self, name: str, pcd: Any,
                  parent_id: Optional[str] = None,
                  color: Optional[Tuple[float, float, float]] = None) -> str:
        """添加点云节点，返回 node_id。"""
        import numpy as np
        if pcd is None or len(pcd.points) == 0:
            raise ValueError("点云为空，无法添加")
        node_id = self._generate_id()
        self._next_id += 1
        node = CloudNode(node_id, name, pcd, parent_id, color=color)
        self._nodes[node_id] = node
        self._node_order.append(node_id)
        self._selected_id = node_id
        self._state = "loaded"
        logger.info(f"添加点云 {name} ({len(pcd.points)} 点)，id={node_id}")
        return node_id

    def remove_cloud(self, node_id: str) -> bool:
        """删除点云节点。"""
        node = self._nodes.pop(node_id, None)
        if node is None:
            return False
        self._node_order.remove(node_id)
        if self._selected_id == node_id:
            self._selected_id = self._node_order[-1] if self._node_order else None
        logger.info(f"删除点云 {node.name} (id={node_id})")
        if not self._nodes:
            self._state = "idle"
        return True

    def get_cloud(self, node_id: str) -> Optional[Any]:
        node = self._nodes.get(node_id)
        return node.pcd if node else None

    def get_node(self, node_id: str) -> Optional[CloudNode]:
        return self._nodes.get(node_id)

    def list_nodes(self) -> List[CloudNode]:
        return [self._nodes[nid] for nid in self._node_order]

    def select(self, node_id: str) -> bool:
        if node_id in self._nodes:
            self._selected_id = node_id
            return True
        return False

    def selected_id(self) -> Optional[str]:
        return self._selected_id

    def set_visible(self, node_id: str, visible: bool):
        node = self._nodes.get(node_id)
        if node:
            node.visible = visible

    # ------------------------------------------------------------------
    # 处理历史
    # ------------------------------------------------------------------
    def _push_history(self, action: str, node_id: str,
                      before_pcd: Any, after_pcd: Any):
        # 丢弃当前位置之后的重做历史
        self._history = self._history[: self._history_index + 1]
        self._history.append({
            "action": action,
            "node_id": node_id,
            "before_pcd": before_pcd,
            "after_pcd": after_pcd,
        })
        self._history_index = len(self._history) - 1

    def can_undo(self) -> bool:
        return self._history_index >= 0

    def can_redo(self) -> bool:
        return self._history_index < len(self._history) - 1

    def undo(self) -> Tuple[bool, str]:
        if not self.can_undo():
            return False, "没有可撤销的操作"
        item = self._history[self._history_index]
        node_id = item["node_id"]
        node = self._nodes.get(node_id)
        if node is None:
            return False, "对应点云已被删除"
        node.pcd = item["before_pcd"]
        self._history_index -= 1
        msg = f"撤销 {item['action']} -> {node.name}"
        logger.info(msg)
        return True, msg

    def redo(self) -> Tuple[bool, str]:
        if not self.can_redo():
            return False, "没有可重做的操作"
        item = self._history[self._history_index + 1]
        node_id = item["node_id"]
        node = self._nodes.get(node_id)
        if node is None:
            return False, "对应点云已被删除"
        node.pcd = item["after_pcd"]
        self._history_index += 1
        msg = f"重做 {item['action']} -> {node.name}"
        logger.info(msg)
        return True, msg

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------
    def _backup_node_pcd(self, node_id: str) -> Any:
        node = self._nodes.get(node_id)
        return node.pcd if node else None

    def apply_process(self, node_id: str, **overrides) -> Tuple[bool, str, Optional[Dict[str, int]]]:
        """对指定点云执行后处理（使用当前 processor 配置 + 临时覆盖参数）。

        Returns:
            (ok, message, stats)
        """
        node = self._nodes.get(node_id)
        if node is None:
            return False, "点云不存在", None

        before = node.pcd
        proc = PointCloudProcessor()
        # 拷贝当前配置
        proc.voxel_size = self.processor.voxel_size
        proc.enable_voxel_downsample = self.processor.enable_voxel_downsample
        proc.crop_mode = self.processor.crop_mode
        proc.crop_ratio = self.processor.crop_ratio
        proc.crop_radius = self.processor.crop_radius
        proc.enable_outlier_removal = self.processor.enable_outlier_removal
        proc.outlier_nb_neighbors = self.processor.outlier_nb_neighbors
        proc.outlier_std_ratio = self.processor.outlier_std_ratio
        # 应用临时覆盖
        for key, value in overrides.items():
            if hasattr(proc, key):
                setattr(proc, key, value)

        self._state = "processing"
        try:
            result, stats = proc.process(node.pcd)
        except Exception as e:
            self._state = "loaded"
            logger.error(f"后处理失败: {e}")
            return False, f"后处理失败: {e}", None

        node.pcd = result
        self._push_history("后处理", node_id, before, result)
        self._state = "loaded"
        stats_text = " | ".join(f"{k}:{v}" for k, v in stats.items())
        logger.info(f"{node.name} 后处理完成: {stats_text}")
        return True, f"后处理完成: {stats_text}", stats

    # ------------------------------------------------------------------
    # ICP 配准
    # ------------------------------------------------------------------
    def icp_register(self, source_id: str, target_id: str,
                     max_distance: Optional[float] = None,
                     init_transform: Optional[Any] = None,
                     estimation_method: str = "point_to_point") -> Tuple[bool, str, Optional[ICPResult]]:
        """ICP 点云配准：把 source 对齐到 target。

        Args:
            source_id: 源点云 id
            target_id: 目标点云 id
            max_distance: 对应点最大距离（None 则按点云尺度自动估计）
            init_transform: 初始 4x4 变换矩阵（None 用单位阵）
            estimation_method: "point_to_point" | "point_to_plane"
        """
        import numpy as np
        import open3d as o3d

        src_node = self._nodes.get(source_id)
        tgt_node = self._nodes.get(target_id)
        if src_node is None or tgt_node is None:
            return False, "源或目标点云不存在", None
        if source_id == target_id:
            return False, "源点云与目标点云不能相同", None

        src = src_node.pcd
        tgt = tgt_node.pcd
        if src is None or tgt is None or len(src.points) == 0 or len(tgt.points) == 0:
            return False, "源或目标点云为空", None

        self._state = "processing"
        try:
            # 自动估计 max_distance：取两朵点云平均点距的 4 倍
            if max_distance is None:
                def _avg_spacing(pcd):
                    n = len(pcd.points)
                    if n < 10:
                        return 1.0
                    tree = o3d.geometry.KDTreeFlann(pcd)
                    import numpy as np
                    rng = np.random.default_rng(42)
                    sample = rng.choice(n, size=min(500, n), replace=False)
                    dists = []
                    for pi in sample:
                        _, _, d2 = tree.search_knn_vector_3d(pcd.points[int(pi)], 2)
                        if len(d2) > 1:
                            dists.append(np.sqrt(d2[1]))
                    return float(np.median(dists)) if dists else 1.0

                avg = (_avg_spacing(src) + _avg_spacing(tgt)) / 2.0
                max_distance = max(avg * 4.0, 0.1)

            if init_transform is None:
                init_transform = np.eye(4)

            if estimation_method == "point_to_plane":
                if not tgt.has_normals():
                    tgt.estimate_normals(
                        o3d.geometry.KDTreeSearchParamHybrid(radius=max_distance * 2, max_nn=30))
                criteria = o3d.pipelines.registration.TransformationEstimationPointToPlane()
            else:
                criteria = o3d.pipelines.registration.TransformationEstimationPointToPoint()

            result = o3d.pipelines.registration.registration_icp(
                src, tgt, max_distance, init_transform,
                criteria,
                o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=50))

            aligned = src.transform(result.transformation)
            src_node.pcd = aligned
            self._push_history("ICP配准", source_id, src, aligned)

            icp_res = ICPResult(
                transformation=result.transformation,
                fitness=float(result.fitness),
                inlier_rmse=float(result.inlier_rmse),
                message=f"ICP 完成: fitness={result.fitness:.4f}, rmse={result.inlier_rmse:.4f}",
            )
            logger.info(icp_res.message)
            self._state = "loaded"
            return True, icp_res.message, icp_res
        except Exception as e:
            self._state = "loaded"
            logger.error(f"ICP 配准失败: {e}")
            return False, f"ICP 配准失败: {e}", None

    # ------------------------------------------------------------------
    # 点云合并
    # ------------------------------------------------------------------
    def merge_clouds(self, node_ids: List[str],
                     merged_name: str = "merged") -> Tuple[bool, str, Optional[str]]:
        """合并多朵点云，生成新节点。"""
        import open3d as o3d

        if len(node_ids) < 2:
            return False, "至少选择两朵点云进行合并", None

        pcds = []
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node is None or node.pcd is None or len(node.pcd.points) == 0:
                return False, f"点云 {nid} 不存在或为空", None
            pcds.append(node.pcd)

        self._state = "processing"
        try:
            merged = o3d.geometry.PointCloud()
            for pcd in pcds:
                merged = merge_pointclouds(merged, pcd)
            new_id = self.add_cloud(merged_name, merged,
                                    color=(1.0, 0.8, 0.2))
            self._state = "loaded"
            msg = f"合并完成: {len(pcds)} 朵点云 -> {len(merged.points)} 点"
            logger.info(msg)
            return True, msg, new_id
        except Exception as e:
            self._state = "loaded"
            logger.error(f"合并失败: {e}")
            return False, f"合并失败: {e}", None

    # ------------------------------------------------------------------
    # 导入导出
    # ------------------------------------------------------------------
    def load_from_file(self, path: str) -> Tuple[bool, str, Optional[str]]:
        """从文件加载点云。"""
        import open3d as o3d
        if not os.path.isfile(path):
            return False, f"文件不存在: {path}", None
        try:
            pcd = o3d.io.read_point_cloud(path)
            if len(pcd.points) == 0:
                return False, "文件为空或无法解析", None
            name = os.path.basename(path)
            node_id = self.add_cloud(name, pcd)
            return True, f"已加载 {name} ({len(pcd.points)} 点)", node_id
        except Exception as e:
            return False, f"加载失败: {e}", None

    def export_cloud(self, node_id: str, path: str) -> Tuple[bool, str]:
        """导出点云到文件。"""
        import open3d as o3d
        node = self._nodes.get(node_id)
        if node is None or node.pcd is None or len(node.pcd.points) == 0:
            return False, "点云不存在或为空"
        try:
            ok = o3d.io.write_point_cloud(path, node.pcd)
            if not ok:
                return False, f"写入失败: {path}"
            msg = f"已导出 {node.name} -> {path}"
            logger.info(msg)
            return True, msg
        except Exception as e:
            return False, f"导出失败: {e}"

    def auto_tune(self, node_id: str, target_points: int = 800_000) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """自动估计后处理参数。"""
        node = self._nodes.get(node_id)
        if node is None or node.pcd is None:
            return False, "点云不存在", None
        try:
            params = self.processor.auto_tune(node.pcd, target_points=target_points)
            return True, "参数估计完成", params
        except Exception as e:
            return False, f"参数估计失败: {e}", None
