from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QButtonGroup, QComboBox, QDialog, QDockWidget, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget

from app.app_state import AppState
from core.data_model import DataNode, make_demo_project, make_empty_project, node_from_dict, node_to_dict
from core.project import ProjectRepository
from core.tasks import TaskManager, TaskRecord
from ui.dialogs import NewProjectDialog
from ui.icons import icon
from ui.project_tree import ProjectTree, ProjectTreeModel
from ui.property_panel import MODULE_INFO, PropertyPanel
from ui.task_center import TaskCenter
from ui.viewport import VTKViewport


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Metrology Studio — 半自动三维测量工作站")
        self.resize(1600, 950)
        self.setMinimumSize(1100, 700)
        self.state = AppState()
        self.settings = settings or QSettings("MetrologyStudio", "MetrologyStudio")
        self.repository = ProjectRepository()
        self.tasks = TaskManager()
        self.viewport: VTKViewport | None = None
        self._build_actions()
        self._build_menu()
        self._build_top_toolbar()
        self._build_workspace()
        self._build_docks()
        self._build_statusbar()
        self._connect_signals()
        self._default_state = self.saveState()
        self._restore_workspace()
        self.state.set_module("三维重建")
        self.nav_buttons["三维重建"].setChecked(True)
        self.property_panel.set_mode(self.state.mode)
        self.task_center.add_task(TaskRecord("bootstrap", "工作区初始化", "系统", "COMPLETED", 100))
        self.task_center.append_log("INFO", "Metrology Studio 工作区初始化完成")
        self.task_center.append_log("INFO", "当前载入内置示例项目；原始数据已锁定")

    def _build_actions(self) -> None:
        self.new_action = QAction(icon("new"), "新建项目", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_project)
        self.open_action = QAction(icon("open"), "打开项目", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_project)
        self.save_action = QAction(icon("save"), "保存项目", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project)
        self.close_project_action = QAction("关闭项目", self)
        self.close_project_action.triggered.connect(self.close_project)
        self.exit_action = QAction("退出", self)
        self.exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.exit_action.triggered.connect(self.close)
        self.import_action = QAction(icon("upload"), "导入数据", self)
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_action.triggered.connect(self.import_data)

    def _build_menu(self) -> None:
        project_menu = self.menuBar().addMenu("项目(&P)")
        project_menu.addActions((self.new_action, self.open_action, self.save_action, self.close_project_action))
        project_menu.addSeparator()
        project_menu.addAction(self.import_action)
        project_menu.addSeparator()
        project_menu.addAction(self.exit_action)
        self.view_menu = self.menuBar().addMenu("视图(&V)")
        help_menu = self.menuBar().addMenu("帮助(&H)")
        about = QAction("关于 Metrology Studio", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _build_top_toolbar(self) -> None:
        toolbar = QToolBar("主导航")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(self.iconSize())
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(12, 7, 18, 7)
        brand_layout.setSpacing(0)
        name = QLabel("METROLOGY STUDIO")
        name.setObjectName("brand")
        subtitle = QLabel("SEMI-AUTOMATED 3D INSPECTION")
        subtitle.setObjectName("brandAccent")
        brand_layout.addWidget(name)
        brand_layout.addWidget(subtitle)
        toolbar.addWidget(brand)
        for action in (self.new_action, self.open_action, self.save_action):
            toolbar.addAction(action)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color:#34475C;margin:12px 7px;")
        toolbar.addWidget(separator)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for module in self.state.MODULES:
            button = QPushButton(module)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setMinimumHeight(34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, name=module: self.state.set_module(name))
            self.nav_group.addButton(button)
            self.nav_buttons[module] = button
            toolbar.addWidget(button)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        status = QWidget()
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(8, 7, 12, 7)
        status_layout.setSpacing(2)
        project_row = QHBoxLayout()
        self.project_label = QLabel(self.state.project_name)
        self.project_label.setStyleSheet("font-weight:600;")
        self.save_label = QLabel("● 已保存")
        self.save_label.setObjectName("statusOk")
        project_row.addWidget(self.project_label)
        project_row.addWidget(self.save_label)
        device_row = QHBoxLayout()
        self.device_label = QLabel("● 演示设备已连接")
        self.device_label.setObjectName("statusOk")
        device_row.addWidget(self.device_label)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(("工作站模式", "工程师模式"))
        self.mode_combo.setAccessibleName("工作模式")
        self.mode_combo.setMinimumWidth(116)
        device_row.addWidget(self.mode_combo)
        status_layout.addLayout(project_row)
        status_layout.addLayout(device_row)
        toolbar.addWidget(status)

    def _build_workspace(self) -> None:
        central = QWidget()
        central.setStyleSheet("background:#111C2B;")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header.setStyleSheet("background:#172333;border-bottom:1px solid #34475C;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 9, 14, 9)
        title_column = QVBoxLayout()
        self.workspace_title = QLabel("项目工作区")
        self.workspace_title.setObjectName("sectionTitle")
        self.workspace_subtitle = QLabel("统一三维场景  /  工件坐标系  /  mm")
        self.workspace_subtitle.setObjectName("muted")
        title_column.addWidget(self.workspace_title)
        title_column.addWidget(self.workspace_subtitle)
        header_layout.addLayout(title_column)
        header_layout.addStretch()
        self.scene_info_label = QLabel("场景对象 3  ·  可见 1")
        self.scene_info_label.setObjectName("muted")
        header_layout.addWidget(self.scene_info_label)
        import_button = QPushButton("导入数据")
        import_button.setObjectName("primaryButton")
        import_button.setIcon(icon("upload", "#FFFFFF"))
        import_button.clicked.connect(self.import_data)
        header_layout.addWidget(import_button)
        layout.addWidget(header)
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setDocumentMode(True)
        scene_page = QWidget()
        scene_layout = QVBoxLayout(scene_page)
        scene_layout.setContentsMargins(0, 0, 0, 0)
        scene_layout.setSpacing(0)
        view_toolbar = QToolBar("三维视图工具")
        view_toolbar.setMovable(False)
        view_toolbar.setStyleSheet("QToolBar{padding:4px 8px;border-bottom:1px solid #34475C;}")
        self.view_actions = QActionGroup(self)
        self.view_actions.setExclusive(False)
        for name in ("等轴测", "正视图", "俯视图", "左视图", "右视图"):
            action = QAction(name, self)
            action.triggered.connect(lambda checked=False, view=name: self.viewport.set_standard_view(view))
            view_toolbar.addAction(action)
        view_toolbar.addSeparator()
        reset = QAction("适应窗口", self)
        reset.setShortcut(QKeySequence("F"))
        reset.triggered.connect(lambda: self.viewport.reset_view())
        view_toolbar.addAction(reset)
        self.grid_action = QAction("网格", self)
        self.grid_action.setCheckable(True)
        self.grid_action.setChecked(True)
        self.grid_action.toggled.connect(lambda visible: self.viewport.set_grid_visible(visible))
        view_toolbar.addAction(self.grid_action)
        scene_layout.addWidget(view_toolbar)
        self.viewport = VTKViewport()
        scene_layout.addWidget(self.viewport, 1)
        self.workspace_tabs.addTab(scene_page, "三维工作区")
        self.scene_table = QTableWidget(0, 4)
        self.scene_table.setHorizontalHeaderLabels(("场景对象 ID", "类型", "可见", "渲染器"))
        self.scene_table.horizontalHeader().setStretchLastSection(True)
        self.scene_table.verticalHeader().setVisible(False)
        self.workspace_tabs.addTab(self.scene_table, "场景信息")
        layout.addWidget(self.workspace_tabs, 1)
        self.setCentralWidget(central)

    def _build_docks(self) -> None:
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks | QMainWindow.DockOption.AnimatedDocks)
        self.project_dock = QDockWidget("项目数据库", self)
        self.project_dock.setObjectName("projectDock")
        self.project_tree = ProjectTree()
        self.project_dock.setWidget(self.project_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)
        self.property_dock = QDockWidget("属性与参数", self)
        self.property_dock.setObjectName("propertyDock")
        self.property_panel = PropertyPanel()
        self.property_dock.setWidget(self.property_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
        self.task_dock = QDockWidget("任务中心", self)
        self.task_dock.setObjectName("taskDock")
        self.task_center = TaskCenter()
        self.task_dock.setWidget(self.task_center)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.task_dock)
        self.resizeDocks((self.project_dock, self.property_dock), (270, 300), Qt.Orientation.Horizontal)
        self.resizeDocks((self.task_dock,), [190], Qt.Orientation.Vertical)
        for title, dock in (("项目数据库", self.project_dock), ("属性与参数", self.property_dock), ("任务中心", self.task_dock)):
            action = dock.toggleViewAction()
            action.setText(title)
            self.view_menu.addAction(action)
        self.view_menu.addSeparator()
        reset_layout = QAction("恢复默认布局", self)
        reset_layout.triggered.connect(lambda: self.restoreState(self._default_state))
        self.view_menu.addAction(reset_layout)

    def _build_statusbar(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_message = QLabel("就绪  ·  左键旋转 / 中键平移 / 滚轮缩放")
        status.addWidget(self.status_message, 1)
        status.addPermanentWidget(QLabel("VTK 9  ·  OpenGL"))
        status.addPermanentWidget(QLabel("单位：mm"))
        self.statusBar().showMessage("工作区已就绪", 3000)

    def _connect_signals(self) -> None:
        self.state.module_changed.connect(self._module_changed)
        self.state.project_changed.connect(self.project_label.setText)
        self.state.save_state_changed.connect(self._save_state_changed)
        self.mode_combo.currentTextChanged.connect(lambda text: self.state.set_mode("工程师" if text.startswith("工程师") else "工作站"))
        self.state.mode_changed.connect(self.property_panel.set_mode)
        self.state.mode_changed.connect(lambda mode: self.task_center.append_log("INFO", f"已切换至{mode}模式"))
        self.project_tree.node_selected.connect(self._node_selected)
        self.project_tree.node_opened.connect(self._node_opened)
        self.project_tree.visibility_changed.connect(self._visibility_changed)
        self.project_tree.message.connect(self._log)
        self.property_panel.visibility_requested.connect(self._visibility_changed)
        self.property_panel.representation_requested.connect(lambda value: self.viewport.set_representation(value))
        self.property_panel.message.connect(self._log)
        self.tasks.task_added.connect(self.task_center.add_task)
        self.tasks.task_updated.connect(self.task_center.update_task)
        self.tasks.log_message.connect(self.task_center.append_log)

    def _module_changed(self, module: str) -> None:
        self.nav_buttons[module].setChecked(True)
        self.workspace_title.setText(MODULE_INFO[module][0])
        self.workspace_subtitle.setText(MODULE_INFO[module][1])
        self.property_panel.set_module(module)
        self.viewport.set_module_scene(module)
        self._update_scene_info()
        self.task_center.append_log("INFO", f"进入模块：{module}（共用三维视口）")

    def _node_selected(self, node: DataNode) -> None:
        self.property_panel.set_node(node)
        self.viewport.show_node(node.node_id)
        self._update_scene_info()

    def _node_opened(self, node: DataNode) -> None:
        modules = {"scan": "数据采集", "point_cloud": "三维重建", "mesh": "模型封装", "cad": "CAD 对比", "measurement": "尺寸测量", "analysis": "CAD 对比", "report": "检测报告"}
        module = modules.get(node.kind)
        if module:
            self.state.set_module(module)
        self.property_panel.set_node(node)
        self.viewport.show_node(node.node_id)
        self._update_scene_info()
        self._log(f"已打开对象：{node.name}")

    def _visibility_changed(self, node: DataNode, visible: bool) -> None:
        node.visible = visible
        self.viewport.set_node_visible(node.node_id, visible)
        self.state.mark_saved(False)
        self._update_scene_info()

    def _update_scene_info(self) -> None:
        actors = self.viewport.scene.actors
        self.scene_table.setRowCount(len(actors))
        visible_count = 0
        for row, (object_id, items) in enumerate(actors.items()):
            visible = bool(items and items[0].GetVisibility())
            visible_count += int(visible)
            values = (object_id, "VTK Actor", "是" if visible else "否", "统一 VTK Renderer")
            for column, value in enumerate(values):
                self.scene_table.setItem(row, column, QTableWidgetItem(value))
        self.scene_info_label.setText(f"场景对象 {len(actors)}  ·  可见 {visible_count}")

    def _save_state_changed(self, saved: bool) -> None:
        self.save_label.setText("● 已保存" if saved else "● 有未保存更改")
        self.save_label.setObjectName("statusOk" if saved else "")
        self.save_label.setStyleSheet("color:#6EE7A0;" if saved else "color:#FBBF24;")

    def _log(self, message: str) -> None:
        self.task_center.append_log("INFO", message)
        self.statusBar().showMessage(message, 4000)

    def new_project(self) -> None:
        if not self._confirm_unsaved():
            return
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            path = self.repository.create(dialog.project_directory, dialog.project_name, dialog.part_number)
        except OSError as error:
            QMessageBox.critical(self, "无法创建项目", str(error))
            return
        self.project_tree.load_root(make_empty_project(dialog.project_name, dialog.part_number))
        self.state.set_project(dialog.project_name, str(path))
        self._hide_all_scene_objects()
        self._log(f"已创建项目：{path}")

    def open_project(self) -> None:
        if not self._confirm_unsaved():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "打开项目", str(Path.home()), "Metrology 项目 (project.json);;JSON 文件 (*.json)")
        if not filename:
            return
        try:
            data = self.repository.load(filename)
            tree_data = data.get("tree")
            root = DataNode("root", "", "root")
            root.add_child(node_from_dict(tree_data)) if tree_data else root.add_child(make_empty_project(data["name"]).children[0])
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.critical(self, "无法打开项目", f"项目文件无效或无法读取：\n{error}")
            return
        self.project_tree.load_root(root)
        self.state.set_project(data["name"], filename)
        self._restore_scene_visibility()
        self._log(f"已打开项目：{filename}")

    def save_project(self) -> bool:
        if not self.state.project_path:
            filename, _ = QFileDialog.getSaveFileName(self, "保存项目", str(Path.home() / self.state.project_name / "project.json"), "Metrology 项目 (project.json)")
            if not filename:
                return False
            self.state.project_path = filename
        project = self.project_tree.model.root.children[0]
        data = {"name": self.state.project_name, "version": 1, "tree": node_to_dict(project)}
        try:
            self.repository.save(self.state.project_path, data)
        except OSError as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return False
        self.state.mark_saved(True)
        self._log(f"项目已保存：{self.state.project_path}")
        return True

    def close_project(self) -> None:
        if not self._confirm_unsaved():
            return
        self.project_tree.load_root(make_empty_project("未打开项目"))
        self.state.set_project("未打开项目", "")
        self._hide_all_scene_objects()
        self._log("项目已关闭；可随时新建或打开项目")

    def _confirm_unsaved(self) -> bool:
        if self.state.saved:
            return True
        answer = QMessageBox.warning(self, "未保存的项目", "当前项目有未保存更改。是否先保存？", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def import_data(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(self, "导入三维数据", str(Path.home()), "三维数据 (*.ply *.stl *.obj *.step *.stp *.iges *.igs);;点云与网格 (*.ply *.stl *.obj);;CAD (*.step *.stp *.iges *.igs)")
        if not filenames:
            return
        project = self.project_tree.model.root.children[0]
        for filename in filenames:
            path = Path(filename)
            suffix = path.suffix.lower()
            if suffix in (".step", ".stp", ".iges", ".igs"):
                group_index, kind = 4, "cad"
            elif suffix == ".stl" or suffix == ".obj":
                group_index, kind = 3, "mesh"
            else:
                group_index, kind = 2, "point_cloud"
            group = project.children[group_index]
            node = self.project_tree.model.add_asset(group, path.name, kind, {"文件路径": str(path), "文件大小": f"{path.stat().st_size / 1024**2:.2f} MB", "文件格式": suffix[1:].upper()})
            self._log(f"已导入项目数据：{path.name}；文件解析接口待对应阶段接入")
        self.project_tree.tree.expandAll()
        self.state.mark_saved(False)

    def _hide_all_scene_objects(self) -> None:
        for object_id in self.viewport.scene.actors:
            self.viewport.scene.set_visible(object_id, False)
        self.viewport.GetRenderWindow().Render()
        self._update_scene_info()

    def _restore_scene_visibility(self) -> None:
        self._hide_all_scene_objects()
        project = self.project_tree.model.root.children[0]
        for group in project.children:
            for node in group.children:
                if node.node_id in self.viewport.scene.actors:
                    self.viewport.scene.set_visible(node.node_id, node.visible)
        self.viewport.GetRenderWindow().Render()
        self._update_scene_info()

    def _restore_workspace(self) -> None:
        geometry = self.settings.value("geometry")
        state = self.settings.value("windowState")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def _about(self) -> None:
        QMessageBox.about(self, "关于 Metrology Studio", "Metrology Studio\n第一阶段：工业软件 UI 外壳\n\nPySide6 + VTK\n单例三维视口 · 动态属性面板 · 项目数据树\n\n当前为独立原型，不连接真实相机，不执行重建或测量算法。")

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_unsaved():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.tasks.shutdown()
        self.viewport.GetRenderWindow().Finalize()
        event.accept()
