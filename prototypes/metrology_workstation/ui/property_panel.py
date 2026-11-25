from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget

from core.data_model import DataNode


MODULE_INFO = {
    "项目": ("项目概览", "管理工件、扫描、模型及检测数据。", ("选择数据对象", "检查对象属性", "进入下一工作模块")),
    "数据采集": ("数据采集", "管理设备状态并记录多角度扫描任务。", ("确认设备连接", "设置采集参数", "执行扫描并保存原始帧")),
    "三维重建": ("三维重建", "统一预览点云并配置后续重建任务。", ("选择点云", "检查点云质量", "配置重建参数")),
    "模型封装": ("模型封装", "管理网格结果、显示属性与模型版本。", ("选择网格", "检查法线和孔洞", "导出或进入检测")),
    "CAD 对比": ("CAD 对比", "区分基准特征对齐与最佳拟合，查看叠加场景。", ("选择 CAD 与点云", "选择独立对齐方式", "检查偏差结果")),
    "尺寸测量": ("尺寸测量", "管理几何测量、公差与合格判定。", ("选择测量任务", "查看结果和公差", "追溯原始数据")),
    "检测报告": ("检测报告", "汇总测量结果并管理报告输出。", ("选择报告模板", "核对测量项目", "生成检测报告")),
}


class PropertyPanel(QWidget):
    visibility_requested = Signal(object, bool)
    representation_requested = Signal(str)
    message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.current_node: DataNode | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(10)
        header = QHBoxLayout()
        self.title = QLabel("项目属性")
        self.title.setObjectName("sectionTitle")
        header.addWidget(self.title)
        header.addStretch()
        self.badge = QLabel("工作站")
        self.badge.setObjectName("badge")
        header.addWidget(self.badge)
        outer.addLayout(header)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #34475C;")
        outer.addWidget(line)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self._build_module_page()
        self._build_asset_page()

    def _build_module_page(self) -> None:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        self.module_name = QLabel()
        self.module_name.setObjectName("sectionTitle")
        layout.addWidget(self.module_name)
        self.module_description = QLabel()
        self.module_description.setWordWrap(True)
        self.module_description.setObjectName("muted")
        layout.addWidget(self.module_description)
        layout.addSpacing(18)
        self.workflow_group = QGroupBox("建议工作流程")
        workflow = QVBoxLayout(self.workflow_group)
        self.step_labels = []
        for index in range(3):
            label = QLabel()
            label.setWordWrap(True)
            label.setMinimumHeight(36)
            self.step_labels.append(label)
            workflow.addWidget(label)
        layout.addWidget(self.workflow_group)
        self.project_group = QGroupBox("当前项目")
        project_form = QFormLayout(self.project_group)
        project_form.addRow("项目编号", QLabel("PRJ-2026-0148"))
        project_form.addRow("工件", QLabel("Housing_A17"))
        project_form.addRow("单位", QLabel("mm"))
        project_form.addRow("数据状态", QLabel("示例项目 · 只读原始数据"))
        layout.addWidget(self.project_group)
        layout.addStretch()
        page.setWidget(content)
        self.stack.addWidget(page)

    def _build_asset_page(self) -> None:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        self.object_name = QLabel()
        self.object_name.setObjectName("sectionTitle")
        self.object_name.setWordWrap(True)
        layout.addWidget(self.object_name)
        self.object_kind = QLabel()
        self.object_kind.setObjectName("muted")
        layout.addWidget(self.object_kind)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setVisible(False)
        self.result_label.setStyleSheet("background:#173D32;color:#86EFAC;border:1px solid #24734F;padding:9px;border-radius:4px;")
        layout.addWidget(self.result_label)
        self.metadata_group = QGroupBox("数据信息")
        self.metadata_form = QFormLayout(self.metadata_group)
        self.metadata_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addWidget(self.metadata_group)
        self.display_group = QGroupBox("显示属性")
        display = QFormLayout(self.display_group)
        self.visible_check = QCheckBox("在三维视图中显示")
        self.visible_check.toggled.connect(self._visibility_changed)
        display.addRow(self.visible_check)
        self.representation = QComboBox()
        self.representation.addItems(("实体", "线框", "顶点"))
        self.representation.currentTextChanged.connect(self.representation_requested)
        display.addRow("显示模式", self.representation)
        self.point_size = QSlider(Qt.Orientation.Horizontal)
        self.point_size.setRange(1, 8)
        self.point_size.setValue(2)
        self.point_size.setAccessibleName("点大小")
        display.addRow("点大小", self.point_size)
        layout.addWidget(self.display_group)
        self.engineer_group = QGroupBox("工程师参数")
        engineer = QFormLayout(self.engineer_group)
        self.voxel_size = QDoubleSpinBox()
        self.voxel_size.setRange(0.001, 100.0)
        self.voxel_size.setDecimals(3)
        self.voxel_size.setValue(0.100)
        self.voxel_size.setSuffix(" mm")
        engineer.addRow("默认体素", self.voxel_size)
        self.iterations = QComboBox()
        self.iterations.addItems(("30 次", "50 次", "100 次"))
        engineer.addRow("配准迭代上限", self.iterations)
        note = QLabel("参数仅作为后续算法接口的默认配置，本阶段不执行重建。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        engineer.addRow(note)
        layout.addWidget(self.engineer_group)
        layout.addStretch()
        page.setWidget(content)
        self.stack.addWidget(page)

    def set_module(self, module: str) -> None:
        title, description, steps = MODULE_INFO[module]
        self.title.setText("模块属性")
        self.module_name.setText(title)
        self.module_description.setText(description)
        for index, (label, text) in enumerate(zip(self.step_labels, steps), 1):
            label.setText(f"{index:02d}   {text}")
        self.stack.setCurrentIndex(0)

    def set_node(self, node: DataNode) -> None:
        self.current_node = node
        if node.kind in ("project", "group"):
            self.set_module("项目")
            return
        self.title.setText("对象属性")
        self.object_name.setText(node.name)
        kind_names = {"part": "工件", "scan": "扫描任务", "point_cloud": "点云", "mesh": "三角网格", "cad": "CAD 模型", "measurement": "尺寸测量", "analysis": "偏差分析", "report": "检测报告"}
        self.object_kind.setText(f"{kind_names.get(node.kind, node.kind)}  ·  {node.status}  ·  ID {node.node_id}")
        while self.metadata_form.rowCount():
            self.metadata_form.removeRow(0)
        for key, value in node.metadata.items():
            label = QLabel(str(value))
            label.setWordWrap(True)
            self.metadata_form.addRow(key, label)
        result = node.metadata.get("判定")
        self.result_label.setVisible(bool(result))
        if result:
            self.result_label.setText(f"检验判定：{result}    {node.metadata.get('计算结果', '')}")
        self.visible_check.blockSignals(True)
        self.visible_check.setChecked(node.visible)
        self.visible_check.blockSignals(False)
        self.representation.setEnabled(node.kind in ("mesh", "cad"))
        self.point_size.setEnabled(node.kind == "point_cloud")
        self.engineer_group.setVisible(self.badge.text() == "工程师" and node.kind in ("point_cloud", "mesh", "analysis"))
        self.stack.setCurrentIndex(1)

    def set_mode(self, mode: str) -> None:
        self.badge.setText(mode)
        if self.current_node:
            self.engineer_group.setVisible(mode == "工程师" and self.current_node.kind in ("point_cloud", "mesh", "analysis"))

    def _visibility_changed(self, visible: bool) -> None:
        if self.current_node:
            self.current_node.visible = visible
            self.visibility_requested.emit(self.current_node, visible)
            self.message.emit(f"{'显示' if visible else '隐藏'}：{self.current_node.name}")
