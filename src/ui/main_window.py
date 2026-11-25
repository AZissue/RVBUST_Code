from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSizePolicy, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.project.library import Project

from .icons import icon, set_button_icon
from .viewport import PartViewport


STAGES = (
    ("Preparation", "准备", "确认工件和检测方案。", (
        ("检测方案", "法兰座 · 演示方案"),
        ("参考模型", "法兰座 · 程序生成"),
        ("单位", "毫米 (mm)"),
    )),
    ("Acquisition", "采集", "查看采集设备与工位状态。", (
        ("传感器", "未连接"),
        ("旋转台", "未连接"),
        ("扫描数据", "尚未采集"),
    )),
    ("Inspection", "检测", "检查参考模型和测量输入。", (
        ("参考模型", "法兰座 · 演示模型"),
        ("对齐", "等待实测数据"),
        ("偏差与尺寸", "暂无检测结果"),
    )),
    ("Report", "报告", "汇总检测结果和报告状态。", (
        ("检测结果", "暂无检测结果"),
        ("报告状态", "等待检测完成"),
    )),
)
STAGE_ICONS = ("prepare", "scan", "inspect", "report")


def label(text, name):
    widget = QLabel(text)
    widget.setObjectName(name)
    return widget


def panel(name, margins=(16, 16, 16, 16)):
    widget = QFrame()
    widget.setObjectName(name)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(10)
    return widget, layout


class MainWindow(QMainWindow):
    closed = Signal()

    def __init__(self, project: Project | None = None, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.project = project
        self.is_demo = project is None or project.sample == "flange"
        self.project_name = project.name if project is not None else "法兰座检测"
        self.setWindowTitle(f"RVC-3D-Metrix · {self.project_name}")
        self.setWindowIcon(icon("metrix", 24))
        self.resize(1440, 860)
        self.setMinimumSize(980, 630)
        theme = Path(__file__).resolve().parents[2] / "resources" / "workbench.qss"
        self.setStyleSheet(theme.read_text(encoding="utf-8-sig"))

        root = QWidget()
        root.setObjectName("workbench")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_header())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("workspaceSplitter")
        body.setChildrenCollapsible(False)
        body.addWidget(self.build_object_panel())
        body.addWidget(self.build_viewport())
        body.addWidget(self.build_workflow_panel())
        body.setSizes([224, 912, 294])
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        layout.addWidget(body, 1)
        layout.addWidget(self.build_footer())
        self.show_stage(0)
        if self.sample_item is not None:
            self.sample_item.setSelected(True)

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit()

    def build_header(self):
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(64)
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 0, 20, 0)
        row.setSpacing(12)
        mark = label("", "brandMark")
        mark.setPixmap(icon("metrix", 24).pixmap(QSize(24, 24), self.devicePixelRatioF()))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(34, 34)
        row.addWidget(mark)
        row.addWidget(label("RVC  /  METRIX", "brand"))
        back = QPushButton("工程中心")
        back.setObjectName("backToProjects")
        set_button_icon(back, "back")
        back.clicked.connect(self.close)
        row.addWidget(back)
        row.addSpacing(18)

        self.stage_group = QButtonGroup(self)
        for index, (key, title, _, _) in enumerate(STAGES):
            button = QPushButton(title)
            set_button_icon(button, STAGE_ICONS[index], 18)
            button.setObjectName(f"stage{key}")
            button.setProperty("stage", True)
            button.setCheckable(True)
            self.stage_group.addButton(button, index)
            row.addWidget(button)
        self.stage_group.idClicked.connect(self.show_stage)
        row.addStretch()
        status = "●  离线演示" if self.is_demo else "本地工程"
        row.addWidget(label(status, "demoStatus"))
        return header

    def build_object_panel(self):
        widget, layout = panel("objects")
        widget.setMinimumWidth(190)
        widget.setMaximumWidth(340)
        layout.addWidget(label("项目对象", "sectionTitle"))
        title = label(self.project_name, "projectTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        if self.project is not None:
            title.setToolTip(str(self.project.path))
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setObjectName("objectTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(21)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setUniformRowHeights(True)
        self.tree.setAccessibleName("项目对象")
        reference = self.add_object_group("参考模型", "model")
        self.sample_item = None
        if self.is_demo:
            self.sample_item = QTreeWidgetItem(reference, ["法兰座"])
            self.sample_item.setToolTip(0, "程序生成的演示工件")
            self.sample_item.setFlags(self.sample_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.sample_item.setCheckState(0, Qt.CheckState.Checked)
        else:
            self.add_empty_object(reference, "尚未添加")
        for category, empty, glyph in (
            ("扫描数据", "尚未采集", "scan"),
            ("测量结果", "暂无结果", "report"),
        ):
            self.add_empty_object(self.add_object_group(category, glyph), empty)
        self.tree.expandAll()
        layout.addWidget(self.tree, 1)
        self.tree.itemChanged.connect(self.on_item_changed)
        return widget

    def add_object_group(self, name, glyph):
        group = QTreeWidgetItem(self.tree, [name])
        group.setIcon(0, icon(glyph))
        font = self.tree.font()
        font.setWeight(QFont.Weight.DemiBold)
        group.setFont(0, font)
        return group

    @staticmethod
    def add_empty_object(parent, text):
        item = QTreeWidgetItem(parent, [text])
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        item.setForeground(0, QColor("#a5a5ac"))
        item.setIcon(0, icon("empty"))

    def build_viewport(self):
        widget, layout = panel("view", (0, 0, 0, 0))
        layout.setSpacing(0)
        strip = QFrame()
        strip.setObjectName("viewToolbar")
        strip.setFixedHeight(52)
        row = QHBoxLayout(strip)
        row.setContentsMargins(16, 0, 12, 0)
        row.addWidget(label("三维视图", "sectionTitle"))
        row.addStretch()

        self.toggle = QPushButton("演示模型")
        self.toggle.setObjectName("toggleSample")
        set_button_icon(self.toggle, "model")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setToolTip("显示或隐藏演示工件")
        self.toggle.toggled.connect(self.set_sample_visible)
        row.addWidget(self.toggle)
        self.toggle.setVisible(self.is_demo)
        reset = QPushButton("复位视图")
        reset.setObjectName("resetView")
        set_button_icon(reset, "reset")
        row.addWidget(reset)
        layout.addWidget(strip)

        self.viewport = PartViewport()
        if not self.is_demo:
            self.viewport.setAccessibleName("工程三维视图")
            self.viewport.setToolTip("")
            self.viewport.set_sample_visible(False)
        reset.clicked.connect(self.viewport.reset_view)
        layout.addWidget(self.viewport, 1)

        hint_text = "拖动旋转   /   滚轮缩放   /   双击复位" if self.is_demo else "尚无模型或扫描数据"
        hint = label(hint_text, "viewHint")
        hint.setContentsMargins(16, 0, 16, 0)
        hint.setFixedHeight(34)
        layout.addWidget(hint)
        return widget

    def build_workflow_panel(self):
        widget, layout = panel("workflow", (18, 18, 18, 16))
        widget.setMinimumWidth(246)
        widget.setMaximumWidth(365)
        layout.addWidget(label("工作流程", "sectionTitle"))
        self.step_count = label("", "stepCount")
        layout.addWidget(self.step_count)
        self.stage_title = label("", "stageTitle")
        layout.addWidget(self.stage_title)
        self.stage_description = label("", "stageDescription")
        self.stage_description.setWordWrap(True)
        layout.addWidget(self.stage_description)
        layout.addSpacing(6)

        details, detail_layout = panel("detailPanel", (12, 12, 12, 12))
        self.detail_rows = []
        for _ in range(3):
            field = QWidget()
            row = QVBoxLayout(field)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(3)
            name = label("", "fieldName")
            value = label("", "fieldValue")
            value.setWordWrap(True)
            row.addWidget(name)
            row.addWidget(value)
            detail_layout.addWidget(field)
            self.detail_rows.append((field, name, value))
        layout.addWidget(details)
        self.next_stage = QPushButton()
        self.next_stage.setObjectName("nextStage")
        set_button_icon(self.next_stage, "next")
        self.next_stage.clicked.connect(self.advance_stage)
        layout.addWidget(self.next_stage)
        layout.addStretch()

        device, geometry = panel("devicePanel", (12, 12, 12, 12))
        device.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        geometry.addWidget(label("设备状态", "sectionTitle"))
        geometry.addWidget(label("扫描传感器   ·   未连接", "fieldName"))
        geometry.addWidget(label("运动平台       ·   未连接", "fieldName"))
        layout.addWidget(device)
        return widget

    def build_footer(self):
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(31)
        row = QHBoxLayout(footer)
        row.setContentsMargins(16, 0, 16, 0)
        row.addWidget(label("设备未连接", "footerText"))
        row.addStretch()
        row.addWidget(label("长度单位   mm", "footerText"))
        return footer

    def show_stage(self, index):
        self.stage_index = index
        _, title, description, rows = STAGES[index]
        if not self.is_demo:
            empty_values = {"检测方案": "尚未配置", "参考模型": "尚未添加"}
            rows = tuple((name, empty_values.get(name, value)) for name, value in rows)
        self.stage_group.button(index).setChecked(True)
        self.step_count.setText(f"步骤 {index + 1} / {len(STAGES)}")
        self.stage_title.setText(title)
        self.stage_description.setText(description)
        for position, (field, name, value) in enumerate(self.detail_rows):
            field.setVisible(position < len(rows))
            if position < len(rows):
                name.setText(rows[position][0])
                value.setText(rows[position][1])
        has_next = index < len(STAGES) - 1
        self.next_stage.setVisible(has_next)
        if has_next:
            self.next_stage.setText(f"继续到{STAGES[index + 1][1]}")

    def advance_stage(self):
        if self.stage_index < len(STAGES) - 1:
            self.show_stage(self.stage_index + 1)

    def on_item_changed(self, item, column):
        if item is self.sample_item and column == 0:
            self.toggle.setChecked(item.checkState(0) == Qt.CheckState.Checked)

    def set_sample_visible(self, visible):
        self.viewport.set_sample_visible(visible)
        if self.sample_item is not None:
            self.sample_item.setCheckState(
                0, Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
            )

