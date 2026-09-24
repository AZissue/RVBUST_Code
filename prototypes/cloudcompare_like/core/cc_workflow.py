# -*- coding: utf-8 -*-
"""
CloudCompare 式后处理工作流（CloudCompareWorkflow）。

设计约束：
  - 无 PySide6 依赖，纯 core 层；
  - 接口对齐 src/core/workflow_base.py 模式；
  - open3d / numpy 延迟导入，方便单元测试。
"""

from __future__ import annotations

import os
import copy
from typing import Any, Dict, List, Optional, Tuple

from core.utils import logger
from core.point_cloud_processor import PointCloudProcessor
from core.pcd_utils import merge_pointclouds


class ScalarField:
    """标量场：与点云节点关联的可视化数据。"""

    def __init__(self, name: str, values: np.ndarray,
                 colormap: str = "jet",
                 min_val: Optional[float] = None,
                 max_val: Optional[float] = None):
        import numpy as np
        self.name = name
        self.values = np.asarray(values, dtype=np.float64)
        self.colormap = colormap
        self.min_val = min_val if min_val is not None else float(np.nanmin(self.values))
        self.max_val = max_val if max_val is not None else float(np.nanmax(self.values))
        self.visible = True

    def normalized(self) -> np.ndarray:
        """返回 [0,1] 归一化值（用于着色）。"""
        span = self.max_val - self.min_val
        if span < 1e-12:
            return np.zeros_like(self.values)
        return np.clip((self.values - self.min_val) / span, 0.0, 1.0)


class CCNode:
    """DB 树中的通用节点（文件/点云/标量场/法线/网格）。"""

    NODE_FILE = "file"
    NODE_CLOUD = "cloud"
    NODE_SCALAR = "scalar"
    NODE_MESH = "mesh"

    def __init__(self, node_id: str, name: str, node_type: str,
                 parent_id: Optional[str] = None,
                 visible: bool = True,
                 color: Optional[Tuple[float, float, float]] = None):
        self.node_id = node_id
        self.name = name
        self.node_type = node_type
        self.parent_id = parent_id
        self.visible = visible
        self.color = color or (0.7, 0.7, 0.7)
        self.point_size = 1
        # 点云数据
        self.pcd: Optional[Any] = None
        # 标量场列表
        self.scalar_fields: Dict[str, ScalarField] = {}
        # 当前激活的标量场（None=使用 RGB/默认色）
        self.active_scalar: Optional[str] = None
        # 网格数据
        self.mesh: Optional[Any] = None
        # 包围盒缓存
        self._bbox: Optional[Any] = None

    @property
    def point_count(self) -> int:
        return len(self.pcd.points) if self.pcd is not None else 0

    def clone(self) -> "CCNode":
        return copy.deepcopy(self)

    def get_display_colors(self) -> Optional[np.ndarray]:
        """获取当前用于显示的颜色数组（考虑标量场激活状态）。"""
        import numpy as np
        if self.active_scalar and self.active_scalar in self.scalar_fields:
            sf = self.scalar_fields[self.active_scalar]
            from .cc_scalar_field import apply_colormap
            return apply_colormap(sf.normalized(), sf.colormap)
        if self.pcd is not None and self.pcd.has_colors():
            cols = np.asarray(self.pcd.colors, dtype=np.float32)
            if cols.size and cols.max() > 1.0:
                cols = cols / 255.0
            return cols
        return None


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


class CloudCompareWorkflow:
    """CloudCompare 式后处理工作流（无 UI 依赖）。"""

    STATES = ("idle", "loaded", "processing")

    def __init__(self):
        self._state = "idle"
        self._nodes: Dict[str, CCNode] = {}
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
        return "cloudcompare"

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
        return f"cc_{self._next_id}"

    def add_cloud(self, name: str, pcd: Any,
                  parent_id: Optional[str] = None,
                  color: Optional[Tuple[float, float, float]] = None) -> str:
        """添加点云节点，返回 node_id。"""
        if pcd is None or len(pcd.points) == 0:
            raise ValueError("点云为空，无法添加")
        node_id = self._generate_id()
        self._next_id += 1
        node = CCNode(node_id, name, CCNode.NODE_CLOUD, parent_id, color=color)
        node.pcd = pcd
        self._nodes[node_id] = node
        self._node_order.append(node_id)
        self._selected_id = node_id
        self._state = "loaded"
        logger.info(f"添加点云 {name} ({len(pcd.points)} 点)，id={node_id}")
        return node_id

    def add_file_node(self, name: str) -> str:
        """添加文件节点（DB 树顶层容器）。"""
        node_id = self._generate_id()
        self._next_id += 1
        node = CCNode(node_id, name, CCNode.NODE_FILE)
        self._nodes[node_id] = node
        self._node_order.append(node_id)
        return node_id

    def add_scalar_field(self, node_id: str, name: str, values: np.ndarray,
                         colormap: str = "jet") -> bool:
        """为点云节点添加标量场。"""
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False
        sf = ScalarField(name, values, colormap)
        node.scalar_fields[name] = sf
        logger.info(f"标量场 '{name}' 已添加到 {node.name}")
        return True

    def set_active_scalar(self, node_id: str, name: Optional[str]) -> bool:
        """设置激活的标量场（None=关闭标量场着色）。"""
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False
        if name is not None and name not in node.scalar_fields:
            return False
        node.active_scalar = name
        logger.info(f"{node.name} 激活标量场: {name}")
        return True

    def remove_node(self, node_id: str) -> bool:
        """删除节点（及子节点）。"""
        node = self._nodes.pop(node_id, None)
        if node is None:
            return False
        # 递归删除子节点
        children = [nid for nid, n in self._nodes.items() if n.parent_id == node_id]
        for child_id in children:
            self.remove_node(child_id)
        self._node_order.remove(node_id)
        if self._selected_id == node_id:
            self._selected_id = self._node_order[-1] if self._node_order else None
        logger.info(f"删除节点 {node.name} (id={node_id})")
        if not any(n.node_type == CCNode.NODE_CLOUD for n in self._nodes.values()):
            self._state = "idle"
        return True

    def get_node(self, node_id: str) -> Optional[CCNode]:
        return self._nodes.get(node_id)

    def list_nodes(self) -> List[CCNode]:
        return [self._nodes[nid] for nid in self._node_order]

    def list_cloud_nodes(self) -> List[CCNode]:
        return [n for n in self.list_nodes() if n.node_type == CCNode.NODE_CLOUD]

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
    # 处理历史（撤销/重做）
    # ------------------------------------------------------------------
    def _push_history(self, action: str, node_id: str,
                      before_pcd: Any, after_pcd: Any):
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
    # 后处理（复用 PointCloudProcessor）
    # ------------------------------------------------------------------
    def apply_process(self, node_id: str, **overrides) -> Tuple[bool, str, Optional[Dict[str, int]]]:
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "点云不存在", None

        before = node.pcd
        proc = PointCloudProcessor()
        proc.voxel_size = self.processor.voxel_size
        proc.enable_voxel_downsample = self.processor.enable_voxel_downsample
        proc.crop_mode = self.processor.crop_mode
        proc.crop_ratio = self.processor.crop_ratio
        proc.crop_radius = self.processor.crop_radius
        proc.enable_outlier_removal = self.processor.enable_outlier_removal
        proc.outlier_nb_neighbors = self.processor.outlier_nb_neighbors
        proc.outlier_std_ratio = self.processor.outlier_std_ratio
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

        # D1：全算子禁用（且无 NaN/零点可剔）时 process() 原样返回入参对象，before 即
        # result → 压进历史就是一条空操作（占撤销栈但什么都没变）。口径：不产生变化的
        # 调用不入历史，并如实回报未执行，不伪装成功。
        if result is before:
            self._state = "loaded"
            logger.warning(f"{node.name} 后处理未执行：未启用任何算子且无无效点")
            return False, "后处理未执行：未启用任何算子且无无效点", None

        node.pcd = result
        self._push_history("后处理", node_id, before, result)
        self._state = "loaded"
        stats_text = " | ".join(f"{k}:{v}" for k, v in stats.items())
        logger.info(f"{node.name} 后处理完成: {stats_text}")
        return True, f"后处理完成: {stats_text}", stats

    # ------------------------------------------------------------------
    # 扩展后处理（法线、标量场）
    # ------------------------------------------------------------------
    def estimate_normals(self, node_id: str,
                         radius: float = 10.0, max_nn: int = 30) -> Tuple[bool, str]:
        """估计点云法线。"""
        import open3d as o3d
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "点云不存在"
        before = copy.deepcopy(node.pcd)
        try:
            node.pcd.estimate_normals(
                o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=max_nn))
            self._push_history("法线估计", node_id, before, node.pcd)
            logger.info(f"{node.name} 法线估计完成")
            return True, "法线估计完成"
        except Exception as e:
            logger.error(f"法线估计失败: {e}")
            return False, f"法线估计失败: {e}"

    def compute_scalar(self, node_id: str, field: str, **kwargs) -> Tuple[bool, str]:
        """计算标量场并自动附加到节点。"""
        from .cc_scalar_field import compute_scalar_field
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "点云不存在"
        try:
            values = compute_scalar_field(node.pcd, field, **kwargs)
            if values is None:
                return False, f"标量场 '{field}' 计算失败"
            self.add_scalar_field(node_id, field, values, kwargs.get("colormap", "jet"))
            self.set_active_scalar(node_id, field)
            return True, f"标量场 '{field}' 计算完成"
        except Exception as e:
            logger.error(f"标量场计算失败: {e}")
            return False, f"标量场计算失败: {e}"

    def detect_geometry(self, node_id: str, shape: str,
                        **kwargs) -> Tuple[bool, str, Optional[Dict]]:
        """RANSAC 几何检测（平面/球/圆柱）。"""
        from .cc_geometry import detect_shape
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "点云不存在", None
        try:
            result = detect_shape(node.pcd, shape, **kwargs)
            if result is None:
                return False, f"未检测到 {shape}", None
            return True, f"检测到 {shape}: {result.get('summary', '')}", result
        except Exception as e:
            logger.error(f"几何检测失败: {e}")
            return False, f"几何检测失败: {e}", None

    def euclidean_clustering(self, node_id: str,
                             eps: float = 10.0, min_points: int = 100) -> Tuple[bool, str, List[str]]:
        """欧式聚类分割，每个聚类生成新点云节点。"""
        import numpy as np
        import open3d as o3d
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "点云不存在", []
        try:
            labels = np.array(node.pcd.cluster_dbscan(eps=eps, min_points=min_points))
            max_label = labels.max()
            created = []
            for i in range(max_label + 1):
                mask = labels == i
                if mask.sum() < min_points:
                    continue
                cluster_pcd = node.pcd.select_by_index(np.where(mask)[0])
                new_id = self.add_cloud(f"{node.name}_cluster_{i}", cluster_pcd,
                                        parent_id=node.node_id)
                created.append(new_id)
            logger.info(f"欧式聚类: {node.name} → {len(created)} 个聚类")
            return True, f"分割为 {len(created)} 个聚类", created
        except Exception as e:
            logger.error(f"聚类失败: {e}")
            return False, f"聚类失败: {e}", []

    # ------------------------------------------------------------------
    # ICP 配准
    # ------------------------------------------------------------------
    def icp_register(self, source_id: str, target_id: str,
                     max_distance: Optional[float] = None,
                     init_transform: Optional[Any] = None,
                     estimation_method: str = "point_to_point") -> Tuple[bool, str, Optional[ICPResult]]:
        import numpy as np
        import open3d as o3d

        src_node = self._nodes.get(source_id)
        tgt_node = self._nodes.get(target_id)
        if src_node is None or tgt_node is None:
            return False, "源或目标点云不存在", None
        if src_node.node_type != CCNode.NODE_CLOUD or tgt_node.node_type != CCNode.NODE_CLOUD:
            return False, "选择的不是点云节点", None

        src = src_node.pcd
        tgt = tgt_node.pcd
        if src is None or tgt is None or len(src.points) == 0 or len(tgt.points) == 0:
            return False, "源或目标点云为空", None

        self._state = "processing"
        try:
            if max_distance is None:
                def _avg_spacing(pcd):
                    n = len(pcd.points)
                    if n < 10:
                        return 1.0
                    tree = o3d.geometry.KDTreeFlann(pcd)
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

            # D2：目标节点不被就地改写。point_to_plane 需要目标法线，法线只在本轮配准的
            # 临时副本上估计（节点自身无历史可撤，就地写入会凭空多出从未记录的属性）。
            if estimation_method == "point_to_plane":
                tgt_for_icp = tgt
                if not tgt.has_normals():
                    tgt_for_icp = copy.deepcopy(tgt)
                    tgt_for_icp.estimate_normals(
                        o3d.geometry.KDTreeSearchParamHybrid(radius=max_distance * 2, max_nn=30))
                criteria = o3d.pipelines.registration.TransformationEstimationPointToPlane()
            else:
                tgt_for_icp = tgt
                criteria = o3d.pipelines.registration.TransformationEstimationPointToPoint()

            result = o3d.pipelines.registration.registration_icp(
                src, tgt_for_icp, max_distance, init_transform,
                criteria,
                o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=50))

            # open3d 的 transform() 就地改写并返回 self，若直接 push 会把 before/after
            # 指向同一对象 → undo 变成空操作。必须先深拷贝再变换（其余 handler 同理）。
            aligned = copy.deepcopy(src)
            aligned.transform(result.transformation)
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
        import open3d as o3d
        if len(node_ids) < 2:
            return False, "至少选择两朵点云进行合并", None

        pcds = []
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node is None or node.node_type != CCNode.NODE_CLOUD or node.pcd is None:
                return False, f"点云 {nid} 不存在或为空", None
            # 保护性副本：merge_pointclouds 会对缺色/缺法线的输入就地补默认属性，
            # 直接传 node.pcd 本体将不可逆改写源节点（S3b）。
            pcds.append(copy.deepcopy(node.pcd))

        self._state = "processing"
        try:
            merged = o3d.geometry.PointCloud()
            for pcd in pcds:
                merged = merge_pointclouds(merged, pcd)
            new_id = self.add_cloud(merged_name, merged, color=(1.0, 0.8, 0.2))
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
        import open3d as o3d
        if not os.path.isfile(path):
            return False, f"文件不存在: {path}", None
        try:
            pcd = o3d.io.read_point_cloud(path)
            if len(pcd.points) == 0:
                return False, "文件为空或无法解析", None
            name = os.path.basename(path)
            # 创建文件节点
            file_id = self.add_file_node(name)
            # 在文件节点下创建点云节点
            node_id = self.add_cloud(name, pcd, parent_id=file_id)
            return True, f"已加载 {name} ({len(pcd.points)} 点)", node_id
        except Exception as e:
            return False, f"加载失败: {e}", None

    def export_cloud(self, node_id: str, path: str) -> Tuple[bool, str]:
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
