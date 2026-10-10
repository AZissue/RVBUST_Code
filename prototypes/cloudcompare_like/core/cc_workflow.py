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

import numpy as np

from core.utils import logger
from core.point_cloud_processor import PointCloudProcessor
from core.pcd_utils import merge_pointclouds


def sanitize_cloud(pcd: Any) -> Tuple[Any, int]:
    """剔除非有限点（NaN/Inf），返回 (清洗后点云, 剔除行数)。

    口径：points / colors / normals 任一属性含非有限值的行整体剔除，保证清洗后
    各属性行数一致；原始对象不被修改（剔除数=0 时返回原对象，调用方不得改写）。
    非有限点会让 open3d KDTree 半径搜索退化（实测 50 万点含 1% Inf：1.7 s → 88 s），
    故 load 与法线估计两条路径都必须过这道防线。
    """
    import numpy as np
    n = len(pcd.points)
    mask = np.isfinite(np.asarray(pcd.points)).all(axis=1)
    if pcd.has_colors():
        mask &= np.isfinite(np.asarray(pcd.colors)).all(axis=1)
    if pcd.has_normals():
        mask &= np.isfinite(np.asarray(pcd.normals)).all(axis=1)
    dropped = int(n - int(mask.sum()))
    if dropped == 0:
        return pcd, 0
    return pcd.select_by_index(np.where(mask)[0]), dropped


def _median_point_spacing(pcd: Any, sample: int = 500) -> float:
    """最近邻点距中位数（半径自适应口径，同 icp_register 的 _avg_spacing）。"""
    import numpy as np
    import open3d as o3d
    n = len(pcd.points)
    if n < 10:
        return 1.0
    tree = o3d.geometry.KDTreeFlann(pcd)
    rng = np.random.default_rng(42)
    idx = rng.choice(n, size=min(sample, n), replace=False)
    dists = []
    for pi in idx:
        _, _, d2 = tree.search_knn_vector_3d(pcd.points[int(pi)], 2)
        if len(d2) > 1:
            dists.append(float(np.sqrt(d2[1])))
    return float(np.median(dists)) if dists else 1.0


def compute_normals(pcd: Any, radius: Optional[float] = None,
                    max_nn: int = 30) -> Tuple[Any, Dict[str, Any]]:
    """清洗 + 法线估计，返回 (结果点云, 统计信息)。

    重活（open3d KDTree 半径搜索）全部在本函数内，可在工作线程调用；
    不含任何 workflow 状态/节点操作（写回与历史在调用方的主线程做）。
    radius=None 时按「最近邻点距中位数 × 3」自适应（毫米级 ~mm 半径、
    米制 ~cm 半径，避免写死 10.0 在米制云上退化为全连通）。
    """
    import time
    import copy
    import open3d as o3d
    t0 = time.perf_counter()
    n_in = len(pcd.points)
    work, dropped = sanitize_cloud(pcd)
    if dropped == 0:
        # estimate_normals 就地改写：必须副本，否则调用方的撤销底账被污染
        work = copy.deepcopy(pcd)
    if len(work.points) == 0:
        raise ValueError("点云全部为非有限点（NaN/Inf），无法估计法线")
    if radius is None:
        radius = max(_median_point_spacing(work) * 3.0, 1e-9)
    work.estimate_normals(
        o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=max_nn))
    elapsed = time.perf_counter() - t0
    info = {
        "points_in": n_in,
        "dropped": dropped,
        "points_out": len(work.points),
        "radius": float(radius),
        "max_nn": int(max_nn),
        "elapsed": elapsed,
    }
    return work, info


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

        # 后处理参数。
        # ⚠️ P0-B：`src/core/point_cloud_processor.PointCloudProcessor` 自 commit
        # `885063e` 起把 `enable_outlier_removal` 默认改成 True（为修主程序拼接输出
        # 飞点）。本工作流的契约是「未启用任何算子 = 无操作」（D1，见 `apply_process`
        # 的 `result is before` 短路）——若继承该默认值，用户在 UI 上一次「未启用
        # 任何算子」的调用会静默剔点（实测 500→477），契约被破坏且 UI 无参数可见。
        # 口径（@user 2026-10-10 拍板）：原型侧显式关闭以守住 D1，并由 UI 暴露该
        # 参数让用户自己开；不动 `src/`。
        self.processor = PointCloudProcessor()
        self.processor.enable_outlier_removal = False

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

    def create_node_from_mask(self, node_id: str, keep_mask: np.ndarray,
                              name: str,
                              action: str = "ROI 保留") -> Tuple[bool, str, Optional[str]]:
        """按布尔掩码从源节点派生**新节点**（K4：ROI 保留 / 剔除）。

        口径（@lead 2026-09-24 §10.15 裁定，遵 v1 `postprocess_workspace.py:502-509`）：
          - 产出新节点，**源节点几何/属性一律不被改写**（与合并、重命名同哲学）。
          - 操作**入历史**，且必须可撤销（entry kind="create"）。
          - 新节点插在源节点**之后**，与用户"派生自谁"的心理模型一致。

        Args:
            node_id: 源点云节点 id。
            keep_mask: 与源节点点数等长的 bool 数组，True = 保留。
            name: 新节点名。
            action: 历史条目显示名（"ROI 保留" / "ROI 剔除"）。

        Returns:
            (ok, msg, new_node_id)
        """
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "源点云不存在", None
        if node.pcd is None or len(node.pcd.points) == 0:
            return False, "源点云为空", None
        mask = np.asarray(keep_mask)
        n_total = len(node.pcd.points)
        if mask.shape != (n_total,):
            return False, (f"掩码长度与点云不一致（掩码 {mask.shape} ≠ 点数 {n_total}），"
                           f"拒绝派生以免静默错位"), None
        if not mask.any():
            return False, "选区为空：没有点可保留，未创建节点", None
        try:
            new_pcd = node.pcd.select_by_index(np.nonzero(mask)[0].tolist())
        except Exception as e:
            return False, f"派生点云失败: {e}", None
        if len(new_pcd.points) == 0:
            return False, "选区为空：没有点可保留，未创建节点", None

        n_keep = int(mask.sum())
        new_id = self.add_cloud(name, new_pcd)
        # 挪到源节点之后（add_cloud 追加在末尾），再登记 create 型历史。
        self._node_order.remove(new_id)
        insert_at = self._node_order.index(node_id) + 1
        self._node_order.insert(insert_at, new_id)
        self._push_history(action, node_id, None, None, kind="create",
                           created_id=new_id, position=insert_at,
                           snapshot=self._nodes[new_id])
        logger.info(f"{node.name} {action} -> 新节点 {name}"
                    f"（{n_keep:,}/{n_total:,} 点），id={new_id}")
        return True, (f"{action}：从 {node.name} 派生 {name}，"
                      f"{n_keep:,}/{n_total:,} 点"), new_id

    # ------------------------------------------------------------------
    # 裁切（K4：AABB / 球 / OBB，就地改写 + 入历史）
    # ------------------------------------------------------------------
    def crop_cloud(self, node_id: str, mode: str, **params) -> Tuple[bool, str, Optional[Dict[str, int]]]:
        """对节点做裁切（就地改写，进撤销历史）。

        mode 与 `src/core/point_cloud_processor.py:48` 的 `crop_mode` 同口径：
          - "aabb"   + ratio（0~1，保留 AABB 中心的该比例区域）
          - "sphere" + radius（与点云同单位，中心=点云质心）
          - "obb"    + ratio（0~1，保留 OBB 中心的该比例区域）
        实现直接复用既有 `apply_process`（同一套 deepcopy 历史 + 同样的
        `result is before` 空操作短路），不另开一套裁切实现。
        """
        if mode not in ("aabb", "sphere", "obb"):
            return False, f"未知裁切模式: {mode}", None
        overrides: Dict[str, Any] = {"crop_mode": mode}
        if mode in ("aabb", "obb"):
            if not (0.0 < params.get("ratio", 0.0) <= 1.0):
                return False, "裁切比例必须在 (0, 1] 内", None
            overrides["crop_ratio"] = float(params["ratio"])
        else:
            if params.get("radius", 0.0) <= 0:
                return False, "球裁切半径必须 > 0", None
            overrides["crop_radius"] = float(params["radius"])
        return self.apply_process(node_id, **overrides)

    def rename_node(self, node_id: str, name: str) -> bool:
        """重命名节点（K2-D2/W12：树、workflow、属性面板三方同一份名字）。

        不进撤销历史（K1-fix 口径，与 remove_node 同级、无 undo/redo 记录）。
        """
        node = self._nodes.get(node_id)
        if node is None or not name:
            return False
        node.name = name
        logger.info(f"重命名节点 {node_id} -> {name}")
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
    #
    # 两种 entry（K4 扩展，@lead 2026-09-24 裁定）：
    #   kind="process" —— 就地改写既有节点（pcd 前后快照），undo/redo 换回 pcd。
    #   kind="create"  —— 产出**新节点**（ROI 保留/剔除），源节点不被改写。
    #                     undo = 移除新节点 + 恢复选中；redo = 原位置重新插入。
    # 之所以不能复用 process：其 entry 只有单节点 pcd 前后快照，表达不了
    # "新增了一个节点"这件事，撤销会无处落脚（源节点本身没变）。
    # ------------------------------------------------------------------
    def _push_history(self, action: str, node_id: Optional[str],
                      before_pcd: Any = None, after_pcd: Any = None,
                      kind: str = "process",
                      created_id: Optional[str] = None,
                      position: Optional[int] = None,
                      snapshot: Any = None):
        self._history = self._history[: self._history_index + 1]
        self._history.append({
            "action": action,
            "kind": kind,
            "node_id": node_id,
            "before_pcd": before_pcd,
            "after_pcd": after_pcd,
            "created_id": created_id,
            "position": position,
            # kind="create" 专用：被创建节点对象的引用，redo 时按原位置放回。
            # 持引用而非深拷贝：该节点从建立到 undo 之间不被就地改写（ROI 产出
            # 新节点后源节点与新节点都只读），与合并的结果节点同口径。
            "snapshot": snapshot,
        })
        self._history_index = len(self._history) - 1

    def history_depth(self) -> Tuple[int, int]:
        """返回 (历史栈深, 当前指针)，供"导出/估计不得污染撤销栈"类断言做快照。"""
        return len(self._history), self._history_index

    def can_undo(self) -> bool:
        return self._history_index >= 0

    def can_redo(self) -> bool:
        return self._history_index < len(self._history) - 1

    def undo(self) -> Tuple[bool, str]:
        if not self.can_undo():
            return False, "没有可撤销的操作"
        item = self._history[self._history_index]
        if item["kind"] == "create":
            ok, msg = self._undo_create(item)
            if not ok:
                return False, msg
            self._history_index -= 1
            logger.info(msg)
            return True, msg

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
        if item["kind"] == "create":
            ok, msg = self._redo_create(item)
            if not ok:
                return False, msg
            self._history_index += 1
            logger.info(msg)
            return True, msg

        node_id = item["node_id"]
        node = self._nodes.get(node_id)
        if node is None:
            return False, "对应点云已被删除"
        node.pcd = item["after_pcd"]
        self._history_index += 1
        msg = f"重做 {item['action']} -> {node.name}"
        logger.info(msg)
        return True, msg

    def _undo_create(self, item: Dict[str, Any]) -> Tuple[bool, str]:
        """撤销"新增节点"：移除新节点并恢复选中（源节点几何/属性全程未被改写）。"""
        created_id = item.get("created_id")
        node = self._nodes.get(created_id)
        if node is None:
            # 新节点已被用户删除：不算失败，指针照常回退，如实说明。
            return True, f"撤销 {item['action']}（新节点已不存在，仅回退历史指针）"
        name = node.name
        self.remove_node(created_id)
        self._selected_id = item.get("node_id")
        return True, f"撤销 {item['action']} -> 移除 {name}"

    def _redo_create(self, item: Dict[str, Any]) -> Tuple[bool, str]:
        """重做"新增节点"：把快照节点按原插入位置放回。"""
        created_id = item.get("created_id")
        if created_id in self._nodes:
            return False, "重做失败：新节点已存在"
        snapshot = item.get("snapshot")
        if snapshot is None:
            return False, "重做失败：缺少节点快照"
        self._nodes[created_id] = snapshot
        pos = item.get("position")
        if pos is None or pos > len(self._node_order):
            self._node_order.append(created_id)
        else:
            self._node_order.insert(pos, created_id)
        self._selected_id = created_id
        self._state = "loaded"
        return True, f"重做 {item['action']} -> 恢复 {snapshot.name}"

    # ------------------------------------------------------------------
    # 后处理（复用 PointCloudProcessor）
    # ------------------------------------------------------------------
    def apply_process(self, node_id: str, **overrides) -> Tuple[bool, str, Optional[Dict[str, int]]]:
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "点云不存在", None

        before = node.pcd
        proc = PointCloudProcessor()
        # P0-B：必须显式覆盖，不能用 PointCloudProcessor() 的构造默认值
        # （src 侧默认为 True，见 __init__ 注释）。
        proc.enable_outlier_removal = False
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
                         radius: Optional[float] = None, max_nn: int = 30) -> Tuple[bool, str]:
        """估计点云法线（同步路径；UI 走 NormalsEstimationWorker + commit_estimate_normals）。

        调用前先深拷贝原始点云作为撤销底账；计算本体（清洗 + open3d 估计）在
        compute_normals 内完成，radius=None 时半径按点距中位数 ×3 自适应。
        """
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return False, "点云不存在"
        before = copy.deepcopy(node.pcd)
        try:
            result, info = compute_normals(node.pcd, radius, max_nn)
        except Exception as e:
            logger.error(f"法线估计失败: {e}")
            return False, f"法线估计失败: {e}"
        self.commit_estimate_normals(node_id, before, result, info)
        return True, self._normals_msg(node.name, info)

    def commit_estimate_normals(self, node_id: str, before_pcd: Any,
                                after_pcd: Any, info: Optional[Dict[str, Any]] = None):
        """法线估计的写回：替换节点点云并压撤销历史（必须在主线程调用）。

        worker 线程只负责计算（compute_normals），节点与历史的写回统一走这里，
        避免工作线程与主线程并发改同一节点。
        """
        node = self._nodes.get(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            raise ValueError("点云不存在")
        node.pcd = after_pcd
        self._push_history("法线估计", node_id, before_pcd, after_pcd)
        logger.info(self._normals_msg(node.name, info or {}))

    @staticmethod
    def _normals_msg(name: str, info: Dict[str, Any]) -> str:
        msg = f"{name} 法线估计完成: {info.get('points_out', '?')} 点"
        if info.get("dropped"):
            msg += f"（剔除非有限点 {info['dropped']} 行）"
        if info.get("elapsed") is not None:
            msg += f"，耗时 {info['elapsed']:.2f} s"
        if info.get("radius") is not None:
            msg += f"，半径={info['radius']:.4g}，max_nn={info.get('max_nn', '?')}"
        return msg

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
            pcd, dropped = sanitize_cloud(pcd)
            name = os.path.basename(path)
            # 创建文件节点
            file_id = self.add_file_node(name)
            # 在文件节点下创建点云节点
            node_id = self.add_cloud(name, pcd, parent_id=file_id)
            if dropped:
                self._log_load_dropped(name, dropped)
            # R3：剔除行数必须随返回消息进 UI（日志面板/状态栏），不能只进日志文件
            msg = f"已加载 {name} ({len(pcd.points)} 点)"
            if dropped:
                msg += f"，剔除 {dropped} 行非有限点（NaN/Inf）"
            return True, msg, node_id
        except Exception as e:
            return False, f"加载失败: {e}", None

    @staticmethod
    def _log_load_dropped(name: str, dropped: int):
        logger.warning(f"加载 {name} 时剔除 {dropped} 行非有限点（NaN/Inf）")

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
