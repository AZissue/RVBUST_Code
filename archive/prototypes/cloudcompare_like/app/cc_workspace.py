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

import copy
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
from .cc_normals_worker import NormalsEstimationWorker
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
        self._normals_worker: Optional[NormalsEstimationWorker] = None
        # R4：估计启动时节点点云的对象身份；完成写回前比对，运算期间被
        # 撤销/重做/删除换掉的节点不得被旧结果覆盖（防「撤销后复活」）。
        self._normals_epoch_pcd = None

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
        self._db_tree.export_requested.connect(self._on_export_node)
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
        self._props.apply_process_requested.connect(self._on_apply_process)
        self._props.roi_keep_requested.connect(self._on_roi_keep)
        self._props.roi_remove_requested.connect(self._on_roi_remove)

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

    def _select_ui_node(self, node_id: str):
        """把 UI 选中态同步到指定节点（树 + 属性面板 + 包围盒）。

        K4 新增节点（ROI 派生）后需要立刻选中新节点，故把 `_on_tree_selection`
        的逻辑抽出来复用，避免两条路径漂移。
        """
        node = self._workflow.get_node(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            return
        self._current_node_id = node_id
        self._workflow.select(node_id)
        self._db_tree.select_node(node_id)
        self._update_properties()
        self._update_bbox_highlight()
        self._props.set_merge_state(len(self._db_tree.selected_cloud_ids()))

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
        # K4/P0-B：把 workflow 里真实生效的后处理参数回填到面板
        # （单一真相源 = workflow.processor，面板只做显示与编辑）。
        proc = self._workflow.processor
        self._props.set_process_params({
            "enable_outlier_removal": proc.enable_outlier_removal,
            "outlier_nb_neighbors": proc.outlier_nb_neighbors,
            "outlier_std_ratio": proc.outlier_std_ratio,
        })
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
    def _on_estimate_normals(self, radius: float = 0.0, max_nn: int = 30):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        # AC4：运算进行中重复点击直接忽略（按钮已禁用，这里是信号级兜底）
        if self._normals_worker is not None:
            self._log("法线估计进行中，请等待完成", "warn")
            return
        node = self._workflow.get_node(self._current_node_id)
        if node is None or node.pcd is None:
            self._log("请先选择点云", "warn")
            return
        # 底账在主线程深拷贝（50 万点 ~0.02 s），worker 只碰这份副本
        before = copy.deepcopy(node.pcd)
        radius_eff = radius if radius > 0 else None   # 0 = 自适应
        self._normals_epoch_pcd = node.pcd
        self._normals_worker = NormalsEstimationWorker(
            self._current_node_id, before, radius_eff, max_nn, self)
        self._normals_worker.finished_normals.connect(self._on_normals_finished)
        self.set_state("processing")
        self._props.set_normals_busy(True)
        self._log(f"开始估计法线: {node.name}（{len(before.points):,} 点）…", "info")
        self._normals_worker.start()

    def _on_normals_finished(self, ok: bool, msg: str, info: dict, result):
        worker = self._normals_worker
        self._normals_worker = None
        epoch_pcd = self._normals_epoch_pcd
        self._normals_epoch_pcd = None
        self._props.set_normals_busy(False)
        node_id = worker.node_id if worker is not None else None
        # 运算期间节点可能已被删除/切换选择：按启动时记录的 node_id 写回
        if ok and result is not None and node_id is not None:
            node = self._workflow.get_node(node_id)
            if node is not None and node.node_type == CCNode.NODE_CLOUD:
                # R4：运算期间节点点云被撤销/重做等替换过（对象身份变了），
                # 说明撤销历史已不含当前结果的前提，硬写回会把撤销过的状态
                # 「复活」并压进历史。丢弃结果、保持现状（与删除路径同口径）。
                if node.pcd is not epoch_pcd:
                    ok = False
                    msg = "法线估计完成，但点云在运算期间已被修改（撤销/重做），结果已丢弃"
                else:
                    self._workflow.commit_estimate_normals(node_id, worker.before_pcd,
                                                           result, info)
                    if node_id == self._current_node_id:
                        self._refresh_viewer()
                        self._update_properties()
            else:
                ok = False
                msg = "法线估计完成，但目标点云已被删除，结果已丢弃"
        self._log(msg, "success" if ok else "error")
        self.set_state("loaded")

    def _shutdown_normals_worker(self):
        """退出收尾（R1）：先断信号防收尾期间重入 UI，再杀子进程并等线程结束。

        QThread 仍在跑时对象被销毁 → Qt fail-fast 硬崩（0xC0000409，3/3 复现）；
        abort() 后子进程随即返回，wait 通常亚秒级完成；超时再 terminate 兜底。
        """
        worker = self._normals_worker
        if worker is None:
            return
        try:
            worker.finished_normals.disconnect()
        except (TypeError, RuntimeError):
            pass
        worker.abort()
        if not worker.wait(2000):
            worker.terminate()
            worker.wait(2000)
        self._normals_worker = None
        self._normals_epoch_pcd = None

    def closeEvent(self, event):
        # 退出时终止估算子进程并等线程收尾，防孤儿 python.exe 与硬崩（R1/V8）
        self._shutdown_normals_worker()
        super().closeEvent(event)

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
        self._refresh_undo_state()

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
        self._refresh_undo_state()

    # ------------------------------------------------------------------
    # 撤销/重做
    # ------------------------------------------------------------------
    def _on_undo(self):
        # R4：运算进行中历史随时会被完成回调改写，此刻撤销必产生不自洽状态
        if self._state == "processing":
            self._log("运算进行中，无法撤销", "warn")
            return
        ok, msg = self._workflow.undo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            self._sync_tree_after_history()
            self._refresh_viewer()
            self._update_properties()
        self.set_state("loaded")
        self._refresh_undo_state()

    def _on_redo(self):
        if self._state == "processing":
            self._log("运算进行中，无法重做", "warn")
            return
        ok, msg = self._workflow.redo()
        self._log(msg, "info" if ok else "warn")
        if ok:
            self._sync_tree_after_history()
            self._refresh_viewer()
            self._update_properties()
        self.set_state("loaded")
        self._refresh_undo_state()

    def _sync_tree_after_history(self):
        """把 DB 树对齐到 workflow 当前节点集合（K4：「新增节点」型历史的撤销/重做）。

        仅处理**树里多出/缺少**的顶层点云节点；`kind="process"` 型历史只改 pcd、
        不动节点集合，走这里也是空操作。
        """
        wf_ids = {n.node_id for n in self._workflow.list_cloud_nodes()}
        tree_ids = set(self._db_tree._node_items.keys())
        # 撤销"新增节点"后：树里多出来的节点要移除
        for nid in tree_ids - wf_ids:
            self._db_tree.remove_node(nid)
        # 重做"新增节点"后：树里缺少的节点要补回
        for node in self._workflow.list_cloud_nodes():
            if node.node_id not in tree_ids:
                self._db_tree.add_cloud_node(node.node_id, node.name,
                                              parent_id=node.parent_id,
                                              color=node.color,
                                              point_count=node.point_count)
        self._refresh_icp_targets()
        # 「新增节点」型历史的撤销会把 workflow 选中恢复到源节点；同步回 UI。
        if self._current_node_id is None or self._workflow.get_node(self._current_node_id) is None:
            wf_sel = self._workflow.selected_id()
            if wf_sel and self._workflow.get_node(wf_sel) is not None:
                node = self._workflow.get_node(wf_sel)
                if node.node_type == CCNode.NODE_CLOUD:
                    self._current_node_id = wf_sel
                    self._db_tree.select_node(wf_sel)
                    return
            self._current_node_id = None
            self._db_tree._tree.clearSelection()

    # ------------------------------------------------------------------
    # 导出（G-K3：端到端，触发后文件落地；取消/失败均不静默）
    # ------------------------------------------------------------------
    EXPORT_SUFFIXES = (".ply", ".pcd")

    def _on_export(self):
        if not self._current_node_id:
            self._log("请先选择点云", "warn")
            return
        self._export_node(self._current_node_id)

    def _on_export_node(self, node_id: str):
        """DB 树右键「导出点云」接收方（K3 接线，D3 反回归靠文件落地判据）。"""
        self._export_node(node_id)

    def _notify_error(self, title: str, message: str):
        """G-K3 边界：写出失败明示报错（日志 + 对话框），禁吞异常。"""
        QMessageBox.warning(self, title, message)

    @staticmethod
    def _safe_export_default_name(node_name: str) -> str:
        """导出默认文件名清洗（K3 遗留②）。

        节点名允许任意字符串（K2 重命名不设限），实测 `a/b` → 默认名 `a/b.ply`、
        `a\\b` → `a\\b.ply`：前者会被当成子目录，后者在 Windows 是非法字符。
        清洗 = 把路径分隔符与 Windows 非法字符换成 `_`，再剥掉扩展名。
        """
        base = os.path.splitext(node_name)[0]
        for ch in '\\/:*?"<>|':
            base = base.replace(ch, "_")
        base = base.strip().strip(".") or "cloud"
        return f"{base}.ply"

    def _export_node(self, node_id: str):
        node = self._workflow.get_node(node_id)
        if node is None or node.node_type != CCNode.NODE_CLOUD:
            self._log("导出仅支持点云节点", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出点云", self._safe_export_default_name(node.name),
            "PLY 文件 (*.ply);;PCD 文件 (*.pcd)")
        if not path:
            return  # 取消路径：无文件、无日志、无异常
        # G-K3 边界：非法后缀兜底补 .ply + 日志明示（W9/W11：禁止静默替换口径）
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in self.EXPORT_SUFFIXES:
            fixed = os.path.splitext(path)[0] + ".ply"
            self._log(f"不支持的扩展名（{suffix or '无'}），已按 PLY 导出: {fixed}",
                      "warn")
            path = fixed
        ok, msg = self._workflow.export_cloud(node_id, path)
        if ok:
            self._log(msg, "success")
            self.dirty_changed.emit(False)
        else:
            self._log(msg, "error")
            self._notify_error("导出失败", msg)

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
        """ROI 选区轮询（K4）：把命中数与降级原因同步到属性面板并落日志。

        W9：原因必须上报 —— 旧实现只在 total>0 时打一条 info，GL 不可用导致
        恒选 0 点时界面毫无提示。
        """
        selection = self._viewer.get_roi_selection()
        total = sum(len(v) for v in selection.values())
        err = self._viewer.roi_selection_error()
        self._props.set_roi_state(total, warn=err or "")
        if err and err != getattr(self, "_roi_last_reported", None):
            self._log(f"ROI 提示：{err}", "warn")
            self._roi_last_reported = err
        elif not err:
            self._roi_last_reported = None
        if total > 0 and total != getattr(self, "_roi_last_total", None):
            self._log(f"ROI 已选中 {total:,} 个点", "info")
        self._roi_last_total = total

    # ------------------------------------------------------------------
    # K4：后处理参数（裁切 + 离群点）与 ROI 保留 / 剔除
    # ------------------------------------------------------------------
    def _on_apply_process(self, params: dict):
        """属性面板「应用后处理」：参数落到 workflow.processor（唯一真相源）再执行。

        关键：先把**全部**参数写进 processor，再走 `apply_process` 不带 overrides
        —— 这样"界面上看到的参数"与"实际生效的参数"是同一份，不会出现
        `apply_process(**overrides)` 局部覆盖导致的参数漂移。
        """
        node_id = self._current_node_id
        if not node_id:
            self._log("请先选择点云", "warn")
            return
        proc = self._workflow.processor
        proc.enable_outlier_removal = bool(params.get("enable_outlier_removal", False))
        proc.outlier_nb_neighbors = int(params.get("outlier_nb_neighbors", 20))
        proc.outlier_std_ratio = float(params.get("outlier_std_ratio", 2.0))
        proc.crop_mode = str(params.get("crop_mode", "none"))
        proc.crop_ratio = float(params.get("crop_ratio", 0.6))
        proc.crop_radius = float(params.get("crop_radius", 500.0))

        # 参数合法性前置校验（给出可读原因，不落到 core 的通用报错）
        if proc.crop_mode in ("aabb", "obb") and not (0.0 < proc.crop_ratio <= 1.0):
            self._log("裁切比例必须在 (0, 1] 内", "warn")
            return
        if proc.crop_mode == "sphere" and proc.crop_radius <= 0:
            self._log("球裁切半径必须 > 0", "warn")
            return

        ok, msg, _stats = self._workflow.apply_process(node_id)
        self._log(msg, "success" if ok else "warn")
        if ok:
            node = self._workflow.get_node(node_id)
            self._refresh_viewer()
            self._update_properties()
            self.dirty_changed.emit(True)
            if node is not None:
                self._log(f"{node.name} 现有 {len(node.pcd.points):,} 点", "info")
        self._refresh_undo_state()

    def _roi_mask_for(self, node_id: str):
        """把 viewer 的 ROI 选区（node_id → 命中索引）转成源节点的 bool 掩码。"""
        selection = self._viewer.get_roi_selection()
        node = self._workflow.get_node(node_id)
        if node is None or node.pcd is None:
            return None, 0, "源点云不存在"
        n = len(node.pcd.points)
        idx = selection.get(node_id)
        mask = np.zeros(n, dtype=bool)
        if idx is None or len(idx) == 0:
            return None, 0, "未框选任何点"
        idx = np.asarray(idx, dtype=np.int64)
        if idx.size and (idx.min() < 0 or idx.max() >= n):
            return None, 0, (f"选区索引越界（max={int(idx.max())} ≥ 点数 {n}），"
                             f"拒绝应用以免错位")
        mask[idx] = True
        return mask, int(mask.sum()), ""

    def _on_roi_keep(self):
        self._apply_roi(keep_inside=True)

    def _on_roi_remove(self):
        self._apply_roi(keep_inside=False)

    def _apply_roi(self, keep_inside: bool):
        """ROI 保留 / 剔除：产出**新节点**，源节点几何/属性不被改写（K4 口径）。"""
        node_id = self._current_node_id
        if not node_id:
            self._log("请先选择点云", "warn")
            return
        mask, n_sel, err = self._roi_mask_for(node_id)
        if mask is None:
            self._log(f"ROI 未应用：{err}", "warn")
            return
        node = self._workflow.get_node(node_id)
        base = os.path.splitext(node.name)[0]
        action = "ROI 保留" if keep_inside else "ROI 剔除"
        new_name = f"{base}_{'roi' if keep_inside else 'cut'}"
        keep_mask = mask if keep_inside else ~mask
        ok, msg, new_id = self._workflow.create_node_from_mask(
            node_id, keep_mask, new_name, action=action)
        if not ok:
            self._log(msg, "warn")
            return
        new_node = self._workflow.get_node(new_id)
        self._add_node_to_ui(new_node)
        self._select_ui_node(new_id)
        self._refresh_viewer()
        self._update_properties()
        self.dirty_changed.emit(True)
        self._refresh_undo_state()
        self._log(msg, "success")

        # 选区里的点已被消费：清掉高亮，避免残留红点让人误以为选区还在。
        self._viewer.clear_roi_selection()
        self._props.set_roi_state(0)
        self._roi_last_total = 0
        self._log(f"选区 {n_sel:,} 点已应用，ROI 高亮已清除", "info")

    def _refresh_undo_state(self):
        """K4：撤销/重做按钮随历史栈实时灰显（历史上此前只在 set_state 里刷）。"""
        self._toolbar.set_undo_enabled(self._workflow.can_undo())
        self._toolbar.set_redo_enabled(self._workflow.can_redo())

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
    def closeEvent(self, event):
        """真窗口退出路径的收尾（R1）：工作区是内嵌控件，其自身的
        closeEvent 在窗口关闭时不会触发，必须在这里显式收尾。"""
        self.workspace._shutdown_normals_worker()
        super().closeEvent(event)

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
