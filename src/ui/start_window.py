from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from src.project.library import Project, ProjectLibrary

from .icons import icon, set_button_icon
from .main_window import MainWindow, label
from .project_cards import DETAIL_ROLE, PREVIEW_ROLE, ProjectCardDelegate
from .viewport import PartViewport


class StartWindow(QMainWindow):
    def __init__(self, library: ProjectLibrary):
        super().__init__()
        self.library = library
        self.workbench = None
        self.flange_preview = None
        self.setWindowTitle("RVC-3D-Metrix · 工程中心")
        self.setWindowIcon(icon("metrix", 24))
        self.resize(1120, 700)
        self.setMinimumSize(860, 490)
        resources = Path(__file__).resolve().parents[2] / "resources"
        self.setStyleSheet((resources / "startup.qss").read_text(encoding="utf-8"))
        try:
            self.library.install_demo(resources / "flange-demo.rvcproj")
        except OSError as error:
            self.statusBar().showMessage(f"无法安装演示工程：{error}")

        root = QWidget()
        root.setObjectName("startup")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_files_page())
        self.pages.addWidget(self.build_settings_page())
        layout.addWidget(self.build_sidebar())
        layout.addWidget(self.pages, 1)
        self.refresh_projects()

    def build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("startupSidebar")
        sidebar.setFixedWidth(146)
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(12, 28, 12, 14)
        column.setSpacing(12)
        column.addWidget(label("RVC  /  METRIX", "productName"))

        navigation = QButtonGroup(sidebar)
        files = QPushButton("会话文件")
        files.setObjectName("sessionFilesNav")
        set_button_icon(files, "files", 18)
        files.setCheckable(True)
        navigation.addButton(files, 0)
        files.setChecked(True)
        column.addWidget(files)
        column.addStretch()

        settings = QPushButton("设置")
        settings.setObjectName("settingsNav")
        set_button_icon(settings, "settings", 18)
        settings.setCheckable(True)
        navigation.addButton(settings, 1)
        column.addWidget(settings)
        navigation.idClicked.connect(self.pages.setCurrentIndex)
        return sidebar

    def build_files_page(self):
        widget = QWidget()
        page = QVBoxLayout(widget)
        page.setContentsMargins(36, 28, 36, 30)
        page.setSpacing(16)
        page.addWidget(label("会话文件", "pageTitle"))

        actions = QHBoxLayout()
        actions.setSpacing(12)
        for title, name, glyph, action in (
            ("新建测量工程", "newProject", "new-file", self.create_project),
            ("打开工程文件", "openProject", "open-file", self.browse_project),
        ):
            button = QPushButton(title)
            button.setObjectName(name)
            button.setProperty("entry", True)
            set_button_icon(button, glyph, 24)
            button.clicked.connect(action)
            actions.addWidget(button, 1)
        page.addLayout(actions)

        library_panel = QFrame()
        library_panel.setObjectName("libraryPanel")
        content = QVBoxLayout(library_panel)
        content.setContentsMargins(18, 14, 18, 14)
        row = QHBoxLayout()
        self.library_title = label("本地工程", "libraryTitle")
        row.addWidget(self.library_title)
        row.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索工程名称")
        self.search.setAccessibleName("搜索工程名称")
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        clear = self.search.addAction(icon("clear"), QLineEdit.ActionPosition.TrailingPosition)
        clear.setText("清除搜索")
        clear.setVisible(False)
        clear.triggered.connect(self.search.clear)
        self.search.textChanged.connect(lambda query: clear.setVisible(bool(query)))
        row.addWidget(self.search)
        self.open_selected = QPushButton("打开所选")
        self.open_selected.setObjectName("openSelectedProject")
        set_button_icon(self.open_selected, "enter")
        self.open_selected.clicked.connect(self.open_selected_project)
        row.addWidget(self.open_selected)
        content.addLayout(row)

        self.project_list = QListWidget()
        self.project_list.setAccessibleName("本地工程")
        self.project_list.setViewMode(QListView.ViewMode.IconMode)
        self.project_list.setMovement(QListView.Movement.Static)
        self.project_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.project_list.setGridSize(QSize(218, 175))
        self.project_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.project_list.setMouseTracking(True)
        self.project_list.setItemDelegate(ProjectCardDelegate(self.project_list))
        self.project_list.itemActivated.connect(self.open_list_item)
        self.project_list.itemSelectionChanged.connect(self.update_open_selected)
        self.search.textChanged.connect(self.filter_projects)
        content.addWidget(self.project_list, 1)
        self.empty = label("", "emptyLibrary")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(self.empty, 1)
        page.addWidget(library_panel, 1)
        return widget

    def build_settings_page(self):
        widget = QWidget()
        page = QVBoxLayout(widget)
        page.setContentsMargins(36, 28, 36, 30)
        page.setSpacing(16)
        page.addWidget(label("设置", "pageTitle"))

        panel = QFrame()
        panel.setObjectName("libraryPanel")
        fields = QVBoxLayout(panel)
        fields.setContentsMargins(18, 14, 18, 14)
        fields.addWidget(label("本地工程保存位置", "libraryTitle"))
        row = QHBoxLayout()
        location = QLineEdit(str(self.library.directory.resolve()))
        location.setObjectName("projectDirectory")
        location.setAccessibleName("本地工程保存位置")
        location.setReadOnly(True)
        row.addWidget(location, 1)
        browse = QPushButton("打开目录")
        set_button_icon(browse, "folder-location", 18)
        browse.clicked.connect(self.open_project_directory)
        row.addWidget(browse)
        fields.addLayout(row)
        page.addWidget(panel)
        page.addStretch()
        return widget

    def open_project_directory(self):
        directory = self.library.directory
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.warning(self, "无法打开目录", str(error))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve()))):
            QMessageBox.warning(self, "无法打开目录", str(directory))

    def refresh_projects(self):
        self.project_list.clear()
        projects = self.library.list_projects()
        for project in projects:
            item = QListWidgetItem(project.name)
            item.setSizeHint(self.project_list.gridSize())
            if project.sample == "flange":
                if self.flange_preview is None:
                    viewport = PartViewport()
                    viewport.resize(540, 300)
                    self.flange_preview = viewport.grab()
                item.setIcon(icon("model", 40))
                item.setData(PREVIEW_ROLE, self.flange_preview)
                item.setData(DETAIL_ROLE, "演示工程 · 三维模型")
            else:
                item.setIcon(icon("files", 40))
                item.setData(DETAIL_ROLE, "测量工程")
            item.setData(Qt.ItemDataRole.UserRole, project.path)
            item.setToolTip(str(project.path))
            self.project_list.addItem(item)
        self.library_title.setText(f"本地工程（{len(projects)}）")
        self.filter_projects(self.search.text())

    def filter_projects(self, query):
        query = query.strip().casefold()
        matches = 0
        for index in range(self.project_list.count()):
            item = self.project_list.item(index)
            matched = query in item.text().casefold()
            item.setHidden(not matched)
            matches += matched
        self.project_list.setVisible(bool(matches))
        self.empty.setVisible(not matches)
        self.empty.setText(
            "没有匹配的工程" if self.project_list.count() else "新建测量工程后，它会显示在这里。"
        )
        self.update_open_selected()

    def update_open_selected(self):
        item = self.project_list.currentItem()
        self.open_selected.setEnabled(
            item is not None and item.isSelected() and not item.isHidden()
        )

    def open_selected_project(self):
        item = self.project_list.currentItem()
        if item is not None and item.isSelected() and not item.isHidden():
            self.open_list_item(item)

    def create_project(self):
        name, accepted = QInputDialog.getText(self, "新建测量工程", "工程名称")
        if accepted:
            try:
                project = self.library.create(name)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "无法新建工程", str(error))
                return
            self.search.clear()
            self.open_project(project)

    def browse_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开测量工程", str(self.library.directory), "RVC 测量工程 (*.rvcproj)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.open_path(Path(path))

    def open_list_item(self, item):
        self.open_path(item.data(Qt.ItemDataRole.UserRole))

    def open_path(self, path: Path):
        try:
            project = self.library.load(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法打开工程", str(error))
            self.refresh_projects()
            return
        self.open_project(project)

    def open_project(self, project: Project | None):
        self.workbench = MainWindow(project, self)
        self.workbench.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.workbench.closed.connect(self.return_to_projects)
        self.workbench.show()
        self.hide()

    def return_to_projects(self):
        self.workbench = None
        self.refresh_projects()
        self.show()
