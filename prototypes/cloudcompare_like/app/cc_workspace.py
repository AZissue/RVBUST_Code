# -*- coding: utf-8 -*-
"""
CloudCompare 式主工作区（CloudCompareWorkspace）。

布局（S3.5 外壳重构后）：
  - 顶部：CCToolBar
  - 左侧：CloudDBTree（DB 树），包在 QScrollArea 内
  - 中间：PointCloudViewerLOD（3D 查看器）
  - 右侧：PropertiesPanel（属性面板）
  - 日志：不内置面板，经 `log_message` 信号交给宿主（浮动日志叠加层）

宿主壳（顶栏 / 状态栏 / 浮动日志）见同文件 `CloudCompareWindow`，照
prototypes/robot_handeye_transform/app/host.py 口径，合入形态下由主程序提供。

信号/接口与 src/ui_v2/workspaces/ 现有工作区对齐，方便后期合并。
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

import numpy as np

from PySide6.QtCore import Qt, QTimer, Signal, QMimeData, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QFileDialog, QMessageBox, QScrollArea, QFrame, QLabel,
    QToolButton,
)

# 让原型能引用 src/ 下的模块
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_APP_DIR)))
if os.path.join(_PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from core.utils import logger
from ui_v2 import icons as ui_icons
from ui_v2.theme import (
    ACCENT, ACCENT_DIM, BG_CARD, BG_PANEL, BG_WINDOW, BORDER, GLOBAL_QSS,
    RADIUS, SPACE, STATUS_ERR, STATUS_OK, STATUS_WARN, TEXT_MUTED,
    TEXT_PRIMARY, TEXT_SECONDARY,
)
from ui_v2.widgets.floating_log_panel import FloatingLogPanel

from ..core.cc_workflow import CloudCompareWorkflow, CCNode
from .cc_gl_viewer import PointCloudViewerLOD
from .cc_db_tree import CloudDBTree
from .cc_properties import PropertiesPanel
from .cc_toolbar import CCToolBar


# 载入接受的扩展名（小写，含点）
LOAD_SUFFIXES = (".ply", ".pcd", ".xyz")


# 默认调色板
COLOR_PALETTE = [
    (0.20, 0.80, 1.00), (1.00, 0.60, 0.20), (0.40, 1.00, 0.40),
    (1.00, 0.40, 0.70), (1.00, 1.00, 0.30), (0.70, 0.50, 1.00),
    (0.40, 0.90, 0.80), (0.95, 0.50, 0.50),
]


# =========================================================================
# ICP 结果解读（纯函数、无 Qt 依赖：日志 / 属性面板 / 单测共用同一口径）
# =========================================================================
# §10.2 G-S2 裁定：实测 12 组 fitness 全部为 1.000000（含姿态差 1.13° 的局部极小那
# 组），单报 fitness 会把局部极小当成功。故结果必须同时给 inlier_rmse 与姿态角/平
# 移；「fitness 高但残差没落到点距以下」时提示给初值。
ICP_LOCAL_MIN_FITNESS = 0.90      # 低于此值不算"看起来已经对齐上"
ICP_LOCAL_MIN_RMSE_RATIO = 0.50   # inlier_rmse / 平均点距 的超阈比


def rotation_angle_deg(R) -> float:
    """3x3 旋转矩阵 → 等效轴角（度）。"""
    R = np.asarray(R, dtype=np.float64)[:3, :3]
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))


def avg_point_spacing(pcd, sample: int = 500) -> Optional[float]:
    """平均点距（最近邻距离中位数）；口径同 core.cc_workflow.icp_register 的自动 max_distance。"""
    import open3d as o3d
    if pcd is None:
        return None
    pts = pcd.points
    n = len(pts)
    if n < 10:
        return None
    tree = o3d.geometry.KDTreeFlann(pcd)
    rng = np.random.default_rng(42)
    idx = rng.choice(n, size=min(sample, n), replace=False)
    ds = []
    for i in idx:
        _, _, d2 = tree.search_knn_vector_3d(pts[int(i)], 2)
        if len(d2) > 1:
            ds.append(float(np.sqrt(d2[1])))
    return float(np.median(ds)) if ds else None


def judge_icp_result(result, point_spacing: Optional[float] = None,
                     init_transform=None):
    """ICP 结果 → (属性面板文本, 是否疑似局部极小, 日志文本)。

    姿态角/平移按**相对初值**的口径给出（未给初值 = 单位阵 = 相对原始位姿），算法与
    单测真值比对一致：angle(R_est @ R_init^T)、‖t_est − t_init‖。UI 里没有真值，
    能给的"误差"就是相对初值（默认即原始位姿）的偏差；初值被真正使用时该值才趋 0。
    疑局部极小 = fitness 高但 inlier_rmse 未落到平均点距的 ICP_LOCAL_MIN_RMSE_RATIO
    倍以下；点距未知则不下判断（不臆造阈值）。
    """
    T = np.asarray(result.transformation, dtype=np.float64)
    init = np.eye(4) if init_transform is None else np.asarray(init_transform, dtype=np.float64)
    angle = rotation_angle_deg(T[:3, :3] @ init[:3, :3].T)
    trans = float(np.linalg.norm(T[:3, 3] - init[:3, 3]))
    rmse = float(result.inlier_rmse)
    fitness = float(result.fitness)

    head = f"fitness={fitness:.6f}  inlier_rmse={rmse:.4e}"
    if point_spacing:
        head += f"  inlier_rmse/点距={rmse / point_spacing:.2f}"
    # 长度量的单位随点云数据（本工具不做单位换算），角度恒为度 —— 显式标注，免得读成 mm
    pose_short = f"姿态角误差={angle:.3f}°  平移误差={trans:.4f}（相对初值，长度=点云单位）"
    rows = "\n".join(" ".join(f"{v: .4f}" for v in row) for row in T)

    # 两类别报警：① fitness=0 = 一个对应点都没有，此时 open3d 的 inlier_rmse 恒为 0，
    # 单看"残差 0"会被读成完美对齐；② 高 fitness 但残差没落到点距以下 = 疑局部极小。
    if fitness <= 0.0:
        warn_short = "无有效对应点（fitness=0），本次结果不可用"
        warn_long = ("⚠ 无有效对应点（fitness=0.000000），本次结果不可用："
                     "inlier_rmse=0 只表示「没有点参与残差」，不是对齐精度。"
                     "请检查两点云是否重叠，或调大最大距离后重试")
    elif fitness < ICP_LOCAL_MIN_FITNESS:
        # 0 < fitness < 阈值：有对应点但参与残差的点太少，rmse 只代表少数点
        warn_short = "对应点过少，结果需人工确认"
        warn_long = (f"⚠ fitness={fitness:.6f} 低于 {ICP_LOCAL_MIN_FITNESS:g}："
                     f"仅少数点参与残差，inlier_rmse={rmse:.4e} 不代表整体对齐精度，"
                     f"请检查重叠区或调大最大距离")
    elif (point_spacing and rmse > ICP_LOCAL_MIN_RMSE_RATIO * point_spacing
          and fitness >= ICP_LOCAL_MIN_FITNESS):
        warn_short = "疑落入局部极小，建议给初值"
        warn_long = (f"⚠ 疑落入局部极小，建议给初值：fitness={fitness:.6f} 已高，"
                     f"但 inlier_rmse={rmse:.4e} 未落到点距 {point_spacing:.4e} 的 "
                     f"{ICP_LOCAL_MIN_RMSE_RATIO:g} 倍以下")
    else:
        warn_short = warn_long = ""
    warn = bool(warn_long)

    panel = f"{head}\n{pose_short}\n{rows}"
    if warn:
        panel += f"\n⚠ {warn_short}"
    log = (f"ICP 结果: {head}\n"
           f"姿态角误差={angle:.3f}°  平移误差={trans:.4f}"
           f"（相对初值；长度=点云单位；未给初值即原始位姿）")
    if warn:
        log += "\n" + warn_long
    log += f"\n变换矩阵 (源→目标):\n{rows}"
    return panel, warn, log


class CloudCompareWorkspace(QWidget):
    """CloudCompare 式后处理工作区。"""

    # §10.10 裁定 B：保留四态（failed 由真坏文件触发，禁三态化抹掉 STATUS_ERR）
    STATES = ("idle", "loaded", "processing", "failed")

    log_message = Signal(str, str)
    dirty_changed = Signal(bool)
    cloud_list_changed = Signal()
    state_changed = Signal(str)          # set_state 后发射（宿主状态栏同步）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._workflow = CloudCompareWorkflow()
        self._current_node_id: Optional[str] = None
        self._color_idx = 0

        self.setAcceptDrops(True)        # 拖拽载入点云（与「打开」同一 _load_files 路径）

        self._setup_ui()
        self._connect_signals()
        self.set_state("idle")

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 工具栏
        self._toolbar = CCToolBar(self)
        root.addWidget(self._toolbar)

        # 主体：左 DB 树 | 中 3D | 右属性
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        self._left_panel = self._build_left_panel()
        self._left_panel.setMinimumWidth(240)
        self._left_panel.setMaximumWidth(360)

        self._viewer = PointCloudViewerLOD(self)
        self._viewer.setStyleSheet(f"background-color: {BG_WINDOW}; border: none;")

        self._right_panel = self._build_right_panel()
        self._right_panel.setMinimumWidth(280)
        self._right_panel.setMaximumWidth(380)

        body.addWidget(self._left_panel)
        body.addWidget(self._viewer, 1)
        body.addWidget(self._right_panel)

        root.addLayout(body, 1)

    def _build_left_panel(self) -> QScrollArea:
        """左面板：DB 树包进 QScrollArea（外壳四件之一，小窗/窄栏不裁列）。"""
        self._db_tree = CloudDBTree(self)

        inner = QWidget()
        lo = QVBoxLayout(inner)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)
        lo.addWidget(self._db_tree)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QScrollArea.NoFrame)
        return scroll

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._props = PropertiesPanel(self)
        lo.addWidget(self._props)
        return panel

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # 工具栏
        self._toolbar.open_requested.connect(self._on_open_files)
        self._toolbar.save_requested.connect(self._on_export)
        self._toolbar.delete_requested.connect(self._on_delete)
        self._toolbar.undo_requested.connect(self._on_undo)
        self._toolbar.redo_requested.connect(self._on_redo)
        self._toolbar.view_preset_requested.connect(self._viewer.set_view_preset)
        self._toolbar.point_size_changed.connect(self._on_point_size_changed)
        self._toolbar.background_toggled.connect(self._viewer.set_background)
        self._toolbar.roi_mode_toggled.connect(self._on_roi_mode)
        self._toolbar.colorbar_toggled.connect(self._on_colorbar_toggled)
        self._toolbar.reset_view_requested.connect(self._viewer.reset_view)

        # DB 树
        self._db_tree.selection_changed.connect(self._on_tree_selection)
        self._db_tree.visibility_changed.connect(self._on_tree_visibility)
        self._db_tree.delete_requested.connect(self._on_delete_node)
        self._db_tree.rename_requested.connect(self._on_rename_node)
        self._db_tree.fit_view_requested.connect(self._on_fit_view)

        # 属性面板
        self._props.point_size_changed.connect(self._on_point_size_changed)
        self._props.color_mode_changed.connect(self._on_color_mode_changed)
        self._props.scalar_field_changed.connect(self._on_scalar_field_changed)
        self._props.colormap_changed.connect(self._on_colormap_changed)
        self._props.estimate_normals_requested.connect(self._on_estimate_normals)
        self._props.detect_plane_requested.connect(self._on_detect_plane)
        self._props.euclidean_cluster_requested.connect(self._on_euclidean_cluster)
        self._props.auto_tune_requested.connect(self._on_auto_tune)
        self._props.icp_requested.connect(self._on_icp)
        self._props.merge_requested.connect(self._on_merge)

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------
    def set_state(self, state: str):
        if state not in self.STATES:
            raise ValueError(f"未知状态: {state}")
        self._state = state
        has_cloud = len(self._workflow.list_cloud_nodes()) > 0
        self._toolbar.set_undo_enabled(self._workflow.can_undo())
        self._toolbar.set_redo_enabled(self._workflow.can_redo())
        if not has_cloud:
            self._props.clear()
        self.state_changed.emit(state)

    def current_state(self) -> str:
        return self._state

    # ------------------------------------------------------------------
    # 点云加载
    # ------------------------------------------------------------------
    def _on_open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择点云文件", "",
            "点云文件 (*.ply *.pcd *.xyz);;所有文件 (*)")
        if not files:
            return
        self._load_files(list(files))

    def _load_files(self, paths: List[str]):
        """载入入口（对话框 / 拖拽共用同一条路径，W14 口径）。

        失败不静默（W11）：不支持的扩展名与解析失败都落 error 级日志，且不新增
        树节点。状态语义：有成功 → loaded；整批失败且当前无点云 → failed（S4 真
        分支）；已有点云时的失败批次保持原状态（不打扰当前工作）。
        """
        ok_count = 0
        fail_count = 0
        for path in paths:
            suffix = os.path.splitext(path)[1].lower()
            if suffix not in LOAD_SUFFIXES:
                fail_count += 1
                self._log(f"不支持的文件类型（{suffix or '无扩展名'}）: {path}", "error")
                continue
            ok, msg, node_id = self._workflow.load_from_file(path)
            if not ok:
                fail_count += 1
                # W11 失败可见：error 级日志必须带文件名（workflow 报错文案本身不含路径）
                self._log(f"{msg}（{os.path.basename(path)}）", "error")
                continue
            ok_count += 1
            self._log(msg, "info")
            node = self._workflow.get_node(node_id)
            self._add_node_to_ui(node)
        if ok_count:
            self._refresh_viewer()
            self.set_state("loaded")
        elif fail_count:
            if not self._workflow.list_cloud_nodes():
                self.set_state("failed")

    # ------------------------------------------------------------------
    # 拖拽载入（与「打开」同一条 _load_files 路径）
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._accepted_drop_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        paths = self._accepted_drop_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self._load_files(paths)
        else:
            event.ignore()

    @staticmethod
    def _accepted_drop_paths(mime: QMimeData) -> List[str]:
        """mime 中可载入的本地文件路径（无则空表 → 不触发载入，W14 口径）。"""
        if not mime.hasUrls():
            return []
        out = []
        for url in mime.urls():
            if url.isLocalFile():
                p = url.toLocalFile()
                if os.path.splitext(p)[1].lower() in LOAD_SUFFIXES:
                    out.append(p)
        return out

    def _add_node_to_ui(self, node: CCNode):
        color = COLOR_PALETTE[self._color_idx % len(COLOR_PALETTE)]
        self._color_idx += 1
        node.color = color

        if node.parent_id:
            parent = self._workflow.get_node(node.parent_id)
            if parent:
                # 文件父节点首次出现时先落树（层级：file → cloud，G-S3.5-d）
                if self._db_tree._node_items.get(parent.node_id) is None:
                    self._db_tree.add_file_node(parent.node_id, parent.name)
                self._db_tree.add_cloud_node(node.node_id, node.name,
                                              parent_id=parent.node_id, color=color,
                                              point_count=node.point_count)
        else:
            self._db_tree.add_cloud_node(node.node_id, node.name, color=color,
                                          point_count=node.point_count)

        self._current_node_id = node.node_id
        self._update_properties()
        self.cloud_list_changed.emit()
        self.dirty_changed.emit(True)

    # ------------------------------------------------------------------
    # DB 树事件
    # ------------------------------------------------------------------
    def _on_tree_selection(self, node_id: str):
        node = self._workflow.get_node(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return
        self._current_node_id = node_id
        self._workflow.select(node_id)
        self._update_properties()
        self._update_bbox_highlight()
        self._props.set_merge_state(len(self._db_tree.selected_cloud_ids()))

    def _on_tree_visibility(self, node_id: str, visible: bool):
        node = self._workflow.get_node(node_id)
        if node is None:
            return
        node.visible = visible
        self._workflow.set_visible(node_id, visible)
        self._refresh_viewer()

    def _on_rename_node(self, node_id: str, name: str):
        """K2-D2：树已由 _rename_item 改完显示，这里同步 workflow 与属性面板。"""
        if not self._workflow.rename_node(node_id, name):
            self._log(f"重命名失败（节点不存在或空名）: {node_id}", "error")
            return
        if self._current_node_id == node_id and self._props._node_id == node_id:
            self._props._lbl_name.setText(name)

    def _on_delete_node(self, node_id: str):
        self._workflow.remove_node(node_id)
        self._db_tree.remove_node(node_id)
        self._viewer.clear_pointclouds()
        # 当前选中被删除（或其父支被删）时清理选中状态
        if self._current_node_id and self._workflow.get_node(self._current_node_id) is None:
            self._current_node_id = None
        self._refresh_viewer()
        self._update_properties()
        self.set_state("loaded" if self._workflow.list_cloud_nodes() else "idle")

    def _on_delete(self):
        node_id = self._db_tree.selected_node_id()
        if node_id:
            self._on_delete_node(node_id)

    def _on_fit_view(self, node_id: str):
        """双击 / 右键「适配视角」：相机对准指定点云（文件节点取其第一朵子点云）。"""
        node = self._workflow.get_node(node_id)
        if node is None:
            return
        if node.node_type == CCNode.NODE_CLOUD:
            self._viewer.fit_to_cloud(node_id)
            return
        for child in self._workflow.list_cloud_nodes():
            if child.parent_id == node_id:
                self._viewer.fit_to_cloud(child.node_id)
                return
        self._log("该节点下没有可适配的点云", "warn")

    # ------------------------------------------------------------------
    # 属性面板事件
    # ------------------------------------------------------------------
    def _update_properties(self):
        node_id = self._current_node_id
        node = self._workflow.get_node(node_id) if node_id else None
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            self._props.clear()
            self._props.set_icp_targets([])
            return

        pts = np.asarray(node.pcd.points) if node.pcd else np.zeros((0, 3))
        n = len(pts)
        bbox_str = "-"
        center_str = "-"
        if n > 0:
            mask = np.isfinite(pts).all(axis=1)
            if mask.any():
                valid = pts[mask]
                mins = valid.min(axis=0)
                maxs = valid.max(axis=0)
                center = (mins + maxs) / 2
                bbox_str = f"X[{mins[0]:.1f},{maxs[0]:.1f}] Y[{mins[1]:.1f},{maxs[1]:.1f}] Z[{mins[2]:.1f},{maxs[2]:.1f}]"
                center_str = f"({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})"

        scalar_names = list(node.scalar_fields.keys()) if node.scalar_fields else []
        self._props.set_node(node_id, node.name, n, bbox_str, center_str, scalar_names)
        self._refresh_icp_targets()

    def _refresh_icp_targets(self):
        """ICP 目标候选 = 除当前源点云以外的全部点云节点。"""
        items = [(node.node_id, f"{node.name} ({node.point_count:,} 点)")
                 for node in self._workflow.list_cloud_nodes()
                 if node.node_id != self._current_node_id]
        self._props.set_icp_targets(items)

    def _on_point_size_changed(self, size: int):
        self._viewer.set_point_size(size)
        if self._current_node_id:
            node = self._workflow.get_node(self._current_node_id)
            if node:
                node.point_size = size

    def _on_color_mode_changed(self, mode: str):
        self._refresh_viewer()

    def _on_scalar_field_changed(self, name: str):
        if not self._current_node_id:
            return
        self._workflow.set_active_scalar(self._current_node_id, name or None)
        self._refresh_viewer()

    def _on_colormap_changed(self, cmap: str):
        if self._current_node_id:
            node = self._workflow.get_node(self._current_node_id)
            if node and node.active_scalar:
                sf = node.scalar_fields.get(node.active_scalar)
                if sf:
                    sf.colormap = cmap
        self._refresh_viewer()

    # ------------------------------------------------------------------
    # 后处理操作
    # ------------------------------------------------------------------
    def _on_estimate_normals(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        self.set_state("processing")
        ok, msg = self._workflow.estimate_normals(self._current_node_id)
        self._log(msg, "success" if ok else "error")
        self.set_state("loaded")

    def _on_detect_plane(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        self.set_state("processing")
        ok, msg, result = self._workflow.detect_geometry(self._current_node_id, "plane")
        self._log(msg, "success" if ok else "error")
        if ok and result:
            inliers = result.get("inliers", [])
            if inliers:
                node = self._workflow.get_node(self._current_node_id)
                # 平面内点作为子节点挂在源点云下（CloudCompare 风格分支）
                inlier_pcd = node.pcd.select_by_index(inliers)
                new_id = self._workflow.add_cloud(f"{node.name}_plane", inlier_pcd,
                                                   parent_id=node.node_id)
                new_node = self._workflow.get_node(new_id)
                self._add_node_to_ui(new_node)
        self.set_state("loaded")

    def _on_euclidean_cluster(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        self.set_state("processing")
        ok, msg, created = self._workflow.euclidean_clustering(self._current_node_id)
        self._log(msg, "success" if ok else "error")
        if ok:
            for cid in created:
                node = self._workflow.get_node(cid)
                if node:
                    self._add_node_to_ui(node)
        self.set_state("loaded")

    def _on_auto_tune(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        ok, msg, params = self._workflow.auto_tune(self._current_node_id)
        self._log(msg, "info" if ok else "error")
        if ok and params:
            notes = "\n".join(f"• {n}" for n in params.get("notes", []))
            QMessageBox.information(self, "自动参数估计", notes)

    def _on_icp(self, target_id: str, method: str, max_distance: float):
        """ICP 配准：源 = 当前选中点云，目标 = 属性面板下拉选择。"""
        if not self._current_node_id:
            self._log("请先选择源点云（ICP 源为当前选中点云）", "warn")
            return
        if not target_id:
            self._log("请先选择 ICP 目标点云", "warn")
            return
        if target_id == self._current_node_id:
            self._log("ICP 源与目标不能是同一点云", "warn")
            return

        src_node = self._workflow.get_node(self._current_node_id)
        # 点距用于判"残差是否真的落到点距以下"（局部极小与真收敛在这里才分得开）
        spacing = avg_point_spacing(src_node.pcd) if src_node is not None else None

        self.set_state("processing")
        ok, msg, result = self._workflow.icp_register(
            self._current_node_id, target_id,
            max_distance=(max_distance if max_distance > 0 else None),
            estimation_method=method)
        if not ok or result is None:
            self._log(msg, "error")
            self.set_state("loaded")
            return

        self._refresh_viewer()
        self._update_properties()
        panel, warn, log_text = judge_icp_result(result, point_spacing=spacing)
        self._props.set_icp_result(panel, warn=warn)
        self._log(log_text, "warn" if warn else "success")
        self.set_state("loaded")

    def _on_merge(self):
        """合并 DB 树多选的点云；树为唯一真值，选中集从树读（同构 v1 工作区）。"""
        ids = self._db_tree.selected_cloud_ids()
        if len(ids) < 2:
            self._log("请至少选择两朵点云进行合并", "warn")
            return
        self.set_state("processing")
        ok, msg, new_id = self._workflow.merge_clouds(ids)
        self._log(msg, "success" if ok else "error")
        if ok and new_id:
            node = self._workflow.get_node(new_id)
            if node is not None:
                self._db_tree.add_cloud_node(node.node_id, node.name, parent_id=None,
                                             color=(1.0, 0.8, 0.2),  # 顶层，与 v1 一致
                                             point_count=node.point_count)
                self._refresh_viewer()
                self._update_properties()
                self._refresh_icp_targets()  # 新节点进 ICP 目标下拉
        self.set_state("loaded")

    # ------------------------------------------------------------------
    # 撤销/重做
    # ------------------------------------------------------------------
    def _on_undo(self):
        ok, msg = self._workflow.undo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            self._refresh_viewer()
            self._update_properties()
        self.set_state("loaded")

    def _on_redo(self):
        ok, msg = self._workflow.redo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            self._refresh_viewer()
            self._update_properties()
        self.set_state("loaded")

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------
    def _on_export(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出点云", "processed.ply",
            "PLY 文件 (*.ply);;PCD 文件 (*.pcd)")
        if not path:
            return
        ok, msg = self._workflow.export_cloud(self._current_node_id, path)
        self._log(msg, "success" if ok else "error")
        if ok:
            self.dirty_changed.emit(False)

    # ------------------------------------------------------------------
    # ROI
    # ------------------------------------------------------------------
    def _on_roi_mode(self, enabled: bool):
        self._viewer.set_roi_mode(enabled)
        if enabled:
            self._roi_timer = QTimer(self)
            self._roi_timer.timeout.connect(self._check_roi)
            self._roi_timer.start(200)
        else:
            if hasattr(self, '_roi_timer') and self._roi_timer:
                self._roi_timer.stop()

    def _check_roi(self):
        selection = self._viewer.get_roi_selection()
        total = sum(len(v) for v in selection.values())
        if total > 0:
            self._log(f"ROI 已选中 {total:,} 个点", "info")

    def _on_colorbar_toggled(self, on: bool):
        if on and self._current_node_id:
            node = self._workflow.get_node(self._current_node_id)
            if node and node.active_scalar:
                sf = node.scalar_fields.get(node.active_scalar)
                if sf:
                    self._viewer.set_show_colorbar(True, sf.min_val, sf.max_val, sf.name)
                    return
        self._viewer.set_show_colorbar(False)

    # ------------------------------------------------------------------
    # 3D 刷新
    # ------------------------------------------------------------------
    def _refresh_viewer(self):
        self._viewer.clear_pointclouds()
        for node in self._workflow.list_cloud_nodes():
            if not node.visible:
                continue
            pts = np.asarray(node.pcd.points, dtype=np.float32)
            cols = node.get_display_colors()
            if cols is None:
                cols = np.tile(np.array(node.color, dtype=np.float32), (len(pts), 1))
            self._viewer.set_pointcloud(node.node_id, pts, cols,
                                         visible=True, point_size=node.point_size)
        self._update_bbox_highlight()

    def _update_bbox_highlight(self):
        if not self._current_node_id:
            self._viewer.set_selection_bbox([])
            return
        node = self._workflow.get_node(self._current_node_id)
        if node is None or node.pcd is None or len(node.pcd.points) == 0:
            self._viewer.set_selection_bbox([])
            return
        pts = np.asarray(node.pcd.points)
        mask = np.isfinite(pts).all(axis=1)
        if not mask.any():
            self._viewer.set_selection_bbox([])
            return
        valid = pts[mask]
        self._viewer.set_selection_bbox([(valid.min(axis=0).tolist(), valid.max(axis=0).tolist())])

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _log(self, message: str, level: str = "info"):
        # 工作区不内置日志面板：交给宿主浮动日志（CloudCompareWindow 接线），
        # 独立测试里只发信号（W15：宿主侧断言 blockCount 递增）。
        self.log_message.emit(message, level)


# =========================================================================
# 独立运行入口（宿主壳：顶栏 + 工作区 + 状态栏 + 浮动日志叠加层）
# =========================================================================
# 照 prototypes/robot_handeye_transform/app/host.py 口径（M2a-1 设计语言复刻）：
# 顶栏/状态栏形态照 src/ui_v2/main_window.py；合入形态下壳由主程序提供，
# 本壳只是把同一套接口拉起来，避免「验证的形态 ≠ 最终形态」。

# 工作区状态 → 状态栏状态点颜色（§10.10 裁定 B：四态）
_STATE_DOT = {"idle": TEXT_MUTED, "loaded": STATUS_OK,
              "processing": STATUS_WARN, "failed": STATUS_ERR}
_STATE_TEXT = {"idle": "待机", "loaded": "已载入",
               "processing": "处理中", "failed": "载入失败"}


class CloudCompareWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CloudCompare-Like 后处理原型")
        self.resize(1600, 1000)

        central = QWidget()
        self.setCentralWidget(central)
        lo = QVBoxLayout(central)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._toolbar = self._build_toolbar()
        lo.addWidget(self._toolbar)

        self.workspace = CloudCompareWorkspace()
        lo.addWidget(self.workspace, 1)

        self._statusbar = self._build_statusbar()
        lo.addWidget(self._statusbar)

        # 浮动日志面板：叠加层（不挤占中央工作区），「日志」按钮 toggle
        self._log_panel = FloatingLogPanel(self)
        self._log_panel.closed.connect(self._on_log_panel_closed)
        self._log_panel.hide()

        self.workspace.log_message.connect(self._on_workspace_log)
        self.workspace.state_changed.connect(self._refresh_statusbar)
        self._refresh_statusbar(self.workspace.current_state())

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)

    # ------------------------------------------------------------------ 顶栏
    def _build_toolbar(self) -> QWidget:
        """顶栏（照 main_window.py 口径：模式徽章 ｜ QToolButton 组 ｜ 右侧日志开关）。"""
        bar = QWidget()
        bar.setObjectName("hostToolbar")
        bar.setStyleSheet(
            f"QWidget#hostToolbar {{ background-color: {BG_PANEL}; "
            f"border-bottom: 1px solid {BORDER}; }}")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(4)

        badge = QLabel("后处理")
        badge.setStyleSheet(
            f"background-color: {ACCENT_DIM}; color: {ACCENT}; border: none; "
            f"border-radius: 10px; padding: 1px 8px; font-weight: 700;")
        lo.addWidget(badge)

        sep = QLabel("｜")
        sep.setStyleSheet(f"color: {TEXT_MUTED};")
        lo.addWidget(sep)

        btn_help = QToolButton()
        btn_help.setText("帮助")
        btn_help.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(btn_help, "help", TEXT_SECONDARY, 15)
        btn_help.clicked.connect(self._show_help)
        lo.addWidget(btn_help)

        lo.addStretch(1)

        self._btn_log = QToolButton()
        self._btn_log.setText("日志")
        self._btn_log.setCheckable(True)
        self._btn_log.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        ui_icons.apply(self._btn_log, "terminal", TEXT_SECONDARY, 15)
        self._btn_log.toggled.connect(self._log_dock_toggle)
        lo.addWidget(self._btn_log)

        return bar

    # ---------------------------------------------------------------- 状态栏
    def _build_statusbar(self) -> QWidget:
        """状态栏（照 main_window.py 口径：状态点 + 步骤 ｜ 最近一条日志）。"""
        bar = QWidget()
        bar.setObjectName("hostStatusbar")
        bar.setStyleSheet(
            f"QWidget#hostStatusbar {{ background-color: {BG_PANEL}; "
            f"border-top: 1px solid {BORDER}; }}")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(10, 5, 10, 5)
        lo.setSpacing(10)

        left = QFrame()
        left.setStyleSheet(
            f"QFrame {{ background-color: {BG_CARD}; border: none; "
            f"border-radius: {RADIUS}; }}")
        left_lo = QHBoxLayout(left)
        left_lo.setContentsMargins(8, 3, 8, 3)
        left_lo.setSpacing(8)

        self._st_state_dot = QLabel("●")
        self._st_state_dot.setObjectName("stateDot")
        self._st_state_dot.setStyleSheet(
            f"color: {_STATE_DOT['idle']}; font-size: 12px;")
        left_lo.addWidget(self._st_state_dot)

        self._st_step = QLabel(_STATE_TEXT["idle"])
        self._st_step.setStyleSheet(f"color: {TEXT_SECONDARY};")
        left_lo.addWidget(self._st_step)

        lo.addWidget(left)
        lo.addStretch(1)

        right = QFrame()
        right.setStyleSheet(
            f"QFrame {{ background-color: {BG_CARD}; border: none; "
            f"border-radius: {RADIUS}; }}")
        right_lo = QHBoxLayout(right)
        right_lo.setContentsMargins(8, 3, 8, 3)

        self._st_hint = QLabel("")
        self._st_hint.setStyleSheet(f"color: {TEXT_MUTED};")
        right_lo.addWidget(self._st_hint)
        lo.addWidget(right, 1)

        return bar

    def _refresh_statusbar(self, state: str):
        self._st_state_dot.setStyleSheet(
            f"color: {_STATE_DOT.get(state, TEXT_MUTED)}; font-size: 12px;")
        self._st_step.setText(_STATE_TEXT.get(state, state))

    # ------------------------------------------------------------------ 日志
    def set_log_visible(self, visible: bool):
        """显示/隐藏浮动日志面板（截图脚本与外部调用用；等价于点「日志」）。"""
        self._btn_log.setChecked(bool(visible))

    def _log_dock_toggle(self, checked: bool):
        if checked:
            self._position_log_panel()
            self._log_panel.show()
            self._log_panel.raise_()
        else:
            self._log_panel.hide()

    def _on_log_panel_closed(self):
        """用户点面板关闭按钮：隐藏面板并取消顶栏「日志」勾选。"""
        self._btn_log.setChecked(False)
        self._log_panel.hide()

    def _position_log_panel(self):
        """把浮动日志面板定位到窗口右侧偏下（避开顶栏与状态栏），照 main_window.py。"""
        margin = SPACE
        panel_w = self._log_panel.width()
        panel_h = self._log_panel.height()
        x = self.width() - panel_w - margin
        toolbar_h = self._toolbar.height() if self._toolbar else 42
        status_h = self._statusbar.height() if self._statusbar else 28
        y = self.height() - panel_h - status_h - margin
        x = max(margin, x)
        y = max(toolbar_h + margin, y)
        self._log_panel.move(x, y)

    def _on_workspace_log(self, text: str, level: str = "info"):
        self._log_panel.append(str(text), level)
        self._st_hint.setText(str(text).splitlines()[-1][:120])

    # ------------------------------------------------------------------ 帮助
    def _show_help(self):
        QMessageBox.information(
            self, "后处理原型 · 使用说明",
            "1) 「打开」或直接把 .ply / .pcd / .xyz 拖进窗口载入点云\n"
            "2) DB 树多选点云 → 属性面板「合并」；选中单朵 → ICP 配准\n"
            "3) 双击节点 / 右键「适配视角」把相机对准该点云\n"
            "4) 顶栏「日志」开关浮动日志面板")

    # ------------------------------------------------------------------ 事件
    def resizeEvent(self, event):
        """窗口尺寸变化时重定位浮动日志面板（S7：小窗也不许跑出窗外）。"""
        super().resizeEvent(event)
        if getattr(self, "_log_panel", None) is not None and self._log_panel.isVisible():
            self._position_log_panel()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    win = CloudCompareWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
