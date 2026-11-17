# -*- coding: utf-8 -*-
"""
属性面板（Properties Panel）。

CloudCompare 式右侧面板：
  - 点云基础属性：名称、点数、包围盒、中心
  - 显示属性：点大小、颜色模式、标量场选择
  - 标量场 Colorbar 控制
  - 法线显示开关
  - 测量结果
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QPushButton,
    QFormLayout, QSlider, QSizePolicy,
)

from ui_v2.theme import TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, STATUS_WARN, BG_PANEL, BORDER


def _is_number(token: str) -> bool:
    """判断 token 是否为数字（供从包围盒显示串中挑数值，容忍中文标签）。"""
    try:
        float(token)
        return True
    except (TypeError, ValueError):
        return False


class PropertiesPanel(QWidget):
    """点云属性面板。"""

    # 信号
    point_size_changed = Signal(int)
    color_mode_changed = Signal(str)       # "rgb" | "height" | "density" | "curvature" | "intensity"
    scalar_field_changed = Signal(str)     # 标量场名称或 ""
    colormap_changed = Signal(str)
    show_normals_changed = Signal(bool)
    auto_tune_requested = Signal()
    # 法线估计：参数 = (搜索半径 0=自适应, 最大邻居)
    estimate_normals_requested = Signal(float, int)
    detect_plane_requested = Signal()
    euclidean_cluster_requested = Signal()
    # ICP 配准：源 = 当前选中点云；参数 = (目标 node_id, 估计方法, 最大对应距离 0=自动)
    icp_requested = Signal(str, str, float)
    # 合并：无参，选中集合由工作区从 DB 树读（树为唯一真值）
    merge_requested = Signal()
    # ---- K4 新增 ----
    # 后处理参数（含裁切/离群点）：dict = {enable_outlier_removal, outlier_nb_neighbors,
    # outlier_std_ratio, crop_mode, crop_ratio, crop_radius}，作用于当前选中节点。
    apply_process_requested = Signal(dict)
    # ROI 保留 / 剔除：无参，选区由工作区从 viewer 取（viewer 为选区唯一真值）
    roi_keep_requested = Signal()
    roi_remove_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._node_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(12)

        lbl = QLabel("属性")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        lo.addWidget(lbl)

        # ===== 基础信息 =====
        info_group = QGroupBox("基本信息")
        info_lo = QFormLayout(info_group)
        self._lbl_name = QLabel("未选择")
        self._lbl_name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600;")
        info_lo.addRow("名称:", self._lbl_name)

        self._lbl_points = QLabel("-")
        self._lbl_points.setStyleSheet(f"color: {TEXT_MUTED};")
        info_lo.addRow("点数:", self._lbl_points)

        self._lbl_bbox = QLabel("-")
        self._lbl_bbox.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._lbl_bbox.setWordWrap(True)
        info_lo.addRow("包围盒:", self._lbl_bbox)

        self._lbl_center = QLabel("-")
        self._lbl_center.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        info_lo.addRow("中心:", self._lbl_center)
        lo.addWidget(info_group)

        # ===== 显示属性 =====
        display_group = QGroupBox("显示")
        disp_lo = QFormLayout(display_group)

        row_size = QHBoxLayout()
        self._spin_size = QSpinBox()
        self._spin_size.setRange(1, 10)
        self._spin_size.setValue(1)
        self._spin_size.valueChanged.connect(self.point_size_changed.emit)
        row_size.addWidget(self._spin_size)
        row_size.addStretch(1)
        disp_lo.addRow("点大小:", row_size)

        self._combo_color = QComboBox()
        self._combo_color.addItem("RGB 颜色", "rgb")
        self._combo_color.addItem("高度 (Z)", "height")
        self._combo_color.addItem("点密度", "density")
        self._combo_color.addItem("曲率", "curvature")
        self._combo_color.addItem("灰度", "gray")
        self._combo_color.currentIndexChanged.connect(
            lambda: self.color_mode_changed.emit(self._combo_color.currentData()))
        disp_lo.addRow("着色模式:", self._combo_color)

        self._combo_scalar = QComboBox()
        self._combo_scalar.addItem("无", "")
        self._combo_scalar.currentIndexChanged.connect(
            lambda: self.scalar_field_changed.emit(self._combo_scalar.currentData() or ""))
        disp_lo.addRow("标量场:", self._combo_scalar)

        self._combo_colormap = QComboBox()
        self._combo_colormap.addItem("Jet", "jet")
        self._combo_colormap.addItem("Hot", "hot")
        self._combo_colormap.addItem("Coolwarm", "coolwarm")
        self._combo_colormap.addItem("Viridis", "viridis")
        self._combo_colormap.currentIndexChanged.connect(
            lambda: self.colormap_changed.emit(self._combo_colormap.currentData()))
        disp_lo.addRow("色映射:", self._combo_colormap)

        self._chk_normals = QCheckBox("显示法线")
        self._chk_normals.stateChanged.connect(
            lambda s: self.show_normals_changed.emit(s == Qt.Checked))
        disp_lo.addRow(self._chk_normals)

        lo.addWidget(display_group)

        # ===== 后处理快捷操作 =====
        process_group = QGroupBox("处理")
        proc_lo = QVBoxLayout(process_group)

        # --- 法线估计（半径 0 = 按点距自适应；运算中按钮禁用防连点） ---
        row_radius = QHBoxLayout()
        row_radius.addWidget(QLabel("法线半径:"))
        self._spin_normals_radius = QDoubleSpinBox()
        self._spin_normals_radius.setDecimals(4)
        self._spin_normals_radius.setRange(0.0, 1e6)
        self._spin_normals_radius.setValue(0.0)
        self._spin_normals_radius.setSpecialValueText("自适应")
        self._spin_normals_radius.setToolTip("0 = 按最近邻点距中位数×3 自动估计；单位与点云数据一致")
        row_radius.addWidget(self._spin_normals_radius, 1)
        proc_lo.addLayout(row_radius)

        row_nn = QHBoxLayout()
        row_nn.addWidget(QLabel("最大邻居:"))
        self._spin_normals_nn = QSpinBox()
        self._spin_normals_nn.setRange(1, 500)
        self._spin_normals_nn.setValue(30)
        row_nn.addWidget(self._spin_normals_nn, 1)
        proc_lo.addLayout(row_nn)

        self._btn_normals = QPushButton("估计法线")
        self._btn_normals.clicked.connect(self._emit_estimate_normals)
        proc_lo.addWidget(self._btn_normals)

        btn_plane = QPushButton("检测平面 (RANSAC)")
        btn_plane.clicked.connect(self.detect_plane_requested.emit)
        proc_lo.addWidget(btn_plane)

        btn_cluster = QPushButton("欧式聚类分割")
        btn_cluster.clicked.connect(self.euclidean_cluster_requested.emit)
        proc_lo.addWidget(btn_cluster)

        btn_auto = QPushButton("自动参数估计")
        btn_auto.clicked.connect(self.auto_tune_requested.emit)
        proc_lo.addWidget(btn_auto)

        # --- ICP 配准（源 = 当前选中点云，目标在下方选择） ---
        row_tgt = QHBoxLayout()
        row_tgt.addWidget(QLabel("ICP 目标:"))
        self._combo_icp_target = QComboBox()
        self._combo_icp_target.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_tgt.addWidget(self._combo_icp_target, 1)
        proc_lo.addLayout(row_tgt)

        row_meth = QHBoxLayout()
        row_meth.addWidget(QLabel("估计方法:"))
        self._combo_icp_method = QComboBox()
        self._combo_icp_method.addItem("点到点", "point_to_point")
        self._combo_icp_method.addItem("点到面", "point_to_plane")
        row_meth.addWidget(self._combo_icp_method, 1)
        proc_lo.addLayout(row_meth)

        row_dist = QHBoxLayout()
        row_dist.addWidget(QLabel("最大距离:"))
        self._spin_icp_max_dist = QDoubleSpinBox()
        self._spin_icp_max_dist.setDecimals(3)
        self._spin_icp_max_dist.setRange(0.0, 1e6)
        self._spin_icp_max_dist.setValue(0.0)
        self._spin_icp_max_dist.setToolTip("0 = 自动（按平均点距估计）；单位与点云数据一致")
        row_dist.addWidget(self._spin_icp_max_dist, 1)
        proc_lo.addLayout(row_dist)

        self._btn_icp = QPushButton("ICP 配准")
        self._btn_icp.clicked.connect(self._emit_icp_requested)
        proc_lo.addWidget(self._btn_icp)

        self._lbl_icp_result = QLabel("")
        self._lbl_icp_result.setWordWrap(True)
        self._lbl_icp_result.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        proc_lo.addWidget(self._lbl_icp_result)

        # --- 合并选中点云（源 = DB 树多选，≥2 朵；入口与处理组统一） ---
        self._btn_merge = QPushButton("合并选中点云")
        self._btn_merge.setEnabled(False)
        self._btn_merge.clicked.connect(self.merge_requested.emit)
        proc_lo.addWidget(self._btn_merge)

        self._lbl_merge = QLabel("已选 0 朵（需 ≥2）")
        self._lbl_merge.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        proc_lo.addWidget(self._lbl_merge)

        # --- K4：后处理参数（裁切 + 离群点）---------------------------------
        # 设计口径：**参数可见**。src 侧 `PointCloudProcessor` 自 `885063e` 起默认
        # 开启统计离群点去除，本原型显式关闭以守「未启用算子=无操作」契约
        # （P0-B），故必须把真实生效值摆在界面上，避免"看不见的参数在改数据"。
        proc_lo.addWidget(QLabel("— 后处理参数 —"))

        self._chk_outlier = QCheckBox("统计离群点去除")
        self._chk_outlier.setChecked(False)
        self._chk_outlier.setToolTip(
            "默认关闭：本原型「未启用任何算子 = 无操作」。勾选后按下方邻居数/标准差倍数剔点。")
        proc_lo.addWidget(self._chk_outlier)

        row_nb = QHBoxLayout()
        row_nb.addWidget(QLabel("邻居数:"))
        self._spin_outlier_nb = QSpinBox()
        self._spin_outlier_nb.setRange(1, 500)
        self._spin_outlier_nb.setValue(20)
        row_nb.addWidget(self._spin_outlier_nb, 1)
        proc_lo.addLayout(row_nb)

        row_std = QHBoxLayout()
        row_std.addWidget(QLabel("标准差倍数:"))
        self._spin_outlier_std = QDoubleSpinBox()
        self._spin_outlier_std.setDecimals(2)
        self._spin_outlier_std.setRange(0.1, 20.0)
        self._spin_outlier_std.setValue(2.0)
        row_std.addWidget(self._spin_outlier_std, 1)
        proc_lo.addLayout(row_std)

        row_crop = QHBoxLayout()
        row_crop.addWidget(QLabel("裁切模式:"))
        self._combo_crop = QComboBox()
        self._combo_crop.addItem("无", "none")
        self._combo_crop.addItem("AABB", "aabb")
        self._combo_crop.addItem("中心球", "sphere")
        self._combo_crop.addItem("OBB", "obb")
        self._combo_crop.currentIndexChanged.connect(self._on_crop_mode_changed)
        row_crop.addWidget(self._combo_crop, 1)
        proc_lo.addLayout(row_crop)

        self._lbl_crop_param = QLabel("裁切比例 (0~1):")
        proc_lo.addWidget(self._lbl_crop_param)
        self._spin_crop_param = QDoubleSpinBox()
        self._spin_crop_param.setDecimals(4)
        self._spin_crop_param.setRange(0.0, 1e6)
        self._spin_crop_param.setValue(0.6)
        self._spin_crop_param.setToolTip(
            "AABB / OBB：保留包围盒中心的该比例区域（0~1）。"
            "中心球：半径，单位与点云数据一致（载入点云后自动填入对角线 25%）。")
        proc_lo.addWidget(self._spin_crop_param)

        self._btn_apply_process = QPushButton("应用后处理")
        self._btn_apply_process.setToolTip("按上方参数处理当前选中点云（可撤销）")
        self._btn_apply_process.clicked.connect(self._emit_apply_process)
        proc_lo.addWidget(self._btn_apply_process)

        # --- K4：ROI 保留 / 剔除（选区来自 viewer，源节点不被改写） ---------
        proc_lo.addWidget(QLabel("— ROI 选区 —"))
        row_roi = QHBoxLayout()
        self._btn_roi_keep = QPushButton("保留选中")
        self._btn_roi_keep.setToolTip("把 ROI 框选内的点另存为新点云（源点云不变，可撤销）")
        self._btn_roi_keep.clicked.connect(self.roi_keep_requested.emit)
        row_roi.addWidget(self._btn_roi_keep)
        self._btn_roi_remove = QPushButton("剔除选中")
        self._btn_roi_remove.setToolTip("把 ROI 框选内的点剔除后另存为新点云（源点云不变，可撤销）")
        self._btn_roi_remove.clicked.connect(self.roi_remove_requested.emit)
        row_roi.addWidget(self._btn_roi_remove)
        proc_lo.addLayout(row_roi)

        self._lbl_roi = QLabel("未框选")
        self._lbl_roi.setWordWrap(True)
        self._lbl_roi.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        proc_lo.addWidget(self._lbl_roi)

        lo.addWidget(process_group)

        lo.addStretch(1)

    # ------------------------------------------------------------------
    # 数据绑定
    # ------------------------------------------------------------------
    def set_node(self, node_id: str, name: str, point_count: int,
                 bbox_str: str = "", center_str: str = "",
                 scalar_fields: Optional[list] = None):
        self._node_id = node_id
        self._lbl_name.setText(name)
        self._lbl_points.setText(f"{point_count:,}")
        self._lbl_bbox.setText(bbox_str or "-")
        self._lbl_center.setText(center_str or "-")

        # 更新标量场下拉
        self._combo_scalar.clear()
        self._combo_scalar.addItem("无", "")
        if scalar_fields:
            for sf_name in scalar_fields:
                self._combo_scalar.addItem(sf_name, sf_name)

        self._set_process_enabled(True)
        # K4：球裁切半径默认值 = 包围盒对角线 25%（点云单位），仅在用户未输入时填。
        if point_count > 0 and bbox_str:
            self._apply_default_radius_from_bbox(bbox_str)

    def _apply_default_radius_from_bbox(self, bbox_str: str):
        """从包围盒显示串解析尺寸 → 给球裁切半径一个可用默认值。

        bbox_str 形如 `X 12.345 × Y 6.789 × Z 3.456`（缺失/异常则跳过，不报错）。
        """
        try:
            nums = [float(t) for t in bbox_str.replace("×", " ").split()
                    if _is_number(t)]
        except Exception:
            return
        if len(nums) < 3:
            return
        diag = float((nums[0] ** 2 + nums[1] ** 2 + nums[2] ** 2) ** 0.5)
        self.set_default_crop_radius(diag * 0.25)

    def _set_process_enabled(self, enabled: bool):
        """无选中点云时禁用后处理入口，避免点了没反应（禁静默失效）。"""
        for w in (self._btn_apply_process, self._chk_outlier,
                  self._spin_outlier_nb, self._spin_outlier_std,
                  self._combo_crop, self._spin_crop_param):
            w.setEnabled(enabled)
        if not enabled:
            self.set_roi_state(0)

    def clear(self):
        self._node_id = None
        self._lbl_name.setText("未选择")
        self._lbl_points.setText("-")
        self._lbl_bbox.setText("-")
        self._lbl_center.setText("-")
        self._combo_scalar.clear()
        self._combo_scalar.addItem("无", "")
        self._lbl_icp_result.setText("")
        self._set_process_enabled(False)

    # ------------------------------------------------------------------
    # ICP 配准控件
    # ------------------------------------------------------------------
    def _emit_icp_requested(self):
        self.icp_requested.emit(self.get_icp_target(), self.get_icp_method(),
                                float(self._spin_icp_max_dist.value()))

    def _emit_estimate_normals(self):
        self.estimate_normals_requested.emit(self.get_normals_radius(),
                                             self.get_normals_max_nn())

    def get_normals_radius(self) -> float:
        """搜索半径；0 = 自适应（按点距中位数×3）。"""
        return float(self._spin_normals_radius.value())

    def get_normals_max_nn(self) -> int:
        return int(self._spin_normals_nn.value())

    def set_normals_busy(self, busy: bool):
        """运算中禁用入口按钮并改文案，防重复点击排队/并发写同一节点。"""
        self._btn_normals.setEnabled(not busy)
        self._btn_normals.setText("估计法线…" if busy else "估计法线")

    def set_icp_targets(self, items):
        """刷新可选目标点云；items = [(node_id, 显示名)]，选择项仍在列表里则保留。"""
        current = self.get_icp_target()
        self._combo_icp_target.clear()
        for node_id, label in items:
            self._combo_icp_target.addItem(label, node_id)
        if current:
            idx = self._combo_icp_target.findData(current)
            if idx >= 0:
                self._combo_icp_target.setCurrentIndex(idx)

    def get_icp_target(self) -> str:
        return self._combo_icp_target.currentData() or ""

    def get_icp_method(self) -> str:
        return self._combo_icp_method.currentData()

    def set_icp_result(self, text: str, warn: bool = False):
        """显示 ICP 结果；warn=True（疑局部极小）改用告警色，避免与普通结果同色被忽略。"""
        color = STATUS_WARN if warn else TEXT_MUTED
        self._lbl_icp_result.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._lbl_icp_result.setText(text or "")

    def set_merge_state(self, n: int):
        """合并入口状态：n = 当前选中的点云数；<2 禁用按钮并提示。"""
        self._btn_merge.setEnabled(n >= 2)
        self._lbl_merge.setText(f"已选 {n} 朵（需 ≥2）" if n < 2 else f"已选 {n} 朵")

    def set_point_size(self, size: int):
        self._spin_size.setValue(size)

    def get_point_size(self) -> int:
        return self._spin_size.value()

    # ------------------------------------------------------------------
    # K4：后处理参数（裁切 + 离群点）
    # ------------------------------------------------------------------
    def _on_crop_mode_changed(self):
        """裁切模式切换：比例与半径两种量纲共用同一控件，切模式时换标签与默认值。"""
        mode = self.get_crop_mode()
        if mode == "sphere":
            self._lbl_crop_param.setText("球半径 (点云单位):")
            self._spin_crop_param.setRange(0.0, 1e6)
            if self._spin_crop_param.value() < 1.0:
                self._spin_crop_param.setValue(500.0)
        else:
            self._lbl_crop_param.setText("裁切比例 (0~1):")
            self._spin_crop_param.setRange(0.0, 1.0)
            if self._spin_crop_param.value() > 1.0:
                self._spin_crop_param.setValue(0.6)

    def get_crop_mode(self) -> str:
        return self._combo_crop.currentData() or "none"

    def set_default_crop_radius(self, radius: float):
        """载入点云后按包围盒对角线给球裁切半径一个可用默认值。

        仅当当前未处于球模式、或用户还没改过半径时填充，不覆盖用户输入。
        """
        if radius <= 0:
            return
        if self.get_crop_mode() != "sphere" and self._spin_crop_param.value() >= 1.0:
            return
        self._spin_crop_param.setValue(float(radius))

    def set_process_params(self, params: dict):
        """由工作区回填真实生效的参数（单一真相源 = workflow.processor）。"""
        if "enable_outlier_removal" in params:
            self._chk_outlier.setChecked(bool(params["enable_outlier_removal"]))
        if "outlier_nb_neighbors" in params:
            self._spin_outlier_nb.setValue(int(params["outlier_nb_neighbors"]))
        if "outlier_std_ratio" in params:
            self._spin_outlier_std.setValue(float(params["outlier_std_ratio"]))

    def get_process_params(self) -> dict:
        return {
            "enable_outlier_removal": self._chk_outlier.isChecked(),
            "outlier_nb_neighbors": int(self._spin_outlier_nb.value()),
            "outlier_std_ratio": float(self._spin_outlier_std.value()),
            "crop_mode": self.get_crop_mode(),
            "crop_ratio": float(self._spin_crop_param.value()),
            "crop_radius": float(self._spin_crop_param.value()),
        }

    def _emit_apply_process(self):
        self.apply_process_requested.emit(self.get_process_params())

    def set_roi_state(self, n_selected: int, warn: str = ""):
        """ROI 选区状态：n_selected = 当前框选命中点数（0 = 未框选/空选区）。

        warn 非空时用告警色显示原因（W9：GL 不可用等降级必须可见，禁静默）。
        """
        enabled = n_selected > 0
        self._btn_roi_keep.setEnabled(enabled)
        self._btn_roi_remove.setEnabled(enabled)
        if warn:
            self._lbl_roi.setStyleSheet(f"color: {STATUS_WARN}; font-size: 11px;")
            self._lbl_roi.setText(warn)
        else:
            self._lbl_roi.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            self._lbl_roi.setText(
                f"已框选 {n_selected:,} 点" if enabled else "未框选（工具栏「ROI框选」后拖框）")

    def set_roi_busy(self, busy: bool):
        self._btn_roi_keep.setEnabled(not busy)
        self._btn_roi_remove.setEnabled(not busy)
