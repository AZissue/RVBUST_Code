from __future__ import annotations

import uuid

from PySide6.QtCore import QAbstractItemModel, QByteArray, QMimeData, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QTreeView, QVBoxLayout, QWidget

from core.data_model import DataNode, make_demo_project
from ui.icons import icon


class ProjectTreeModel(QAbstractItemModel):
    MIME_TYPE = "application/x-metrology-node"
    NODE_ROLE = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, root: DataNode | None = None) -> None:
        super().__init__()
        self.root = root or make_demo_project()

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        parent = index.internalPointer().parent
        if parent is None or parent == self.root:
            return QModelIndex()
        return self.createIndex(parent.row, 0, parent)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid():
            return None
        node: DataNode = index.internalPointer()
        if role == self.NODE_ROLE:
            return node
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return node.name
        if role == Qt.ItemDataRole.DecorationRole:
            icons = {"project": "project", "group": "folder", "part": "part", "scan": "scan", "point_cloud": "cloud", "mesh": "mesh", "cad": "cad", "measurement": "measure", "analysis": "measure", "report": "report"}
            return icon(icons.get(node.kind, "part"), "#7DD3FC" if node.kind == "project" else "#A9BED2", 17)
        if role == Qt.ItemDataRole.FontRole and node.kind in ("project", "group"):
            font = QApplication.font()
            font.setWeight(QFont.Weight.DemiBold)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            details = "\n".join(f"{key}: {value}" for key, value in node.metadata.items())
            return f"{node.name}\n状态: {node.status}" + (f"\n{details}" if details else "")
        if role == Qt.ItemDataRole.CheckStateRole and node.is_asset:
            return Qt.CheckState.Checked if node.visible else Qt.CheckState.Unchecked
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        node: DataNode = index.internalPointer()
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if node.kind != "root":
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        if node.kind in ("project", "group"):
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        if node.is_asset:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if not node.locked and node.kind not in ("root", "project"):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role: int = int(Qt.ItemDataRole.EditRole)) -> bool:
        if not index.isValid():
            return False
        node: DataNode = index.internalPointer()
        if role == Qt.ItemDataRole.EditRole and not node.locked:
            name = str(value).strip()
            if not name:
                return False
            node.name = name
        elif role == Qt.ItemDataRole.CheckStateRole and node.is_asset:
            node.visible = Qt.CheckState(value) == Qt.CheckState.Checked
        else:
            return False
        self.dataChanged.emit(index, index, [role])
        return True

    def set_locked(self, node: DataNode, locked: bool) -> None:
        node.locked = locked
        index = self.index_for_node(node)
        if index.isValid():
            self.dataChanged.emit(index, index)

    def index_for_node(self, node: DataNode) -> QModelIndex:
        if node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row, 0, node)

    def add_asset(self, parent: DataNode, name: str, kind: str, metadata: dict | None = None) -> DataNode:
        node = DataNode(f"asset_{uuid.uuid4().hex[:10]}", name, kind, metadata=metadata or {})
        row = len(parent.children)
        self.beginInsertRows(self.index_for_node(parent), row, row)
        parent.add_child(node)
        self.endInsertRows()
        return node

    def removeRows(self, row: int, count: int, parent: QModelIndex = QModelIndex()) -> bool:
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        if row < 0 or row + count > len(parent_node.children):
            return False
        self.beginRemoveRows(parent, row, row + count - 1)
        del parent_node.children[row:row + count]
        self.endRemoveRows()
        return True

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [self.MIME_TYPE]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData | None:
        if not indexes:
            return None
        node = indexes[0].internalPointer()
        data = QMimeData()
        data.setData(self.MIME_TYPE, QByteArray(node.node_id.encode("utf-8")))
        return data

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex) -> bool:
        if action != Qt.DropAction.MoveAction or not data.hasFormat(self.MIME_TYPE):
            return False
        source = self.find_node(bytes(data.data(self.MIME_TYPE)).decode("utf-8"))
        target = parent.internalPointer() if parent.isValid() else self.root
        if source is None or source.parent is None or target.kind not in ("root", "project", "group"):
            return False
        ancestor = target
        while ancestor is not None:
            if ancestor == source:
                return False
            ancestor = ancestor.parent
        if row < 0:
            row = len(target.children)
        old_parent_index = self.index_for_node(source.parent)
        old_row = source.row
        self.beginMoveRows(old_parent_index, old_row, old_row, parent, row)
        source.parent.children.remove(source)
        target.children.insert(row, source)
        source.parent = target
        self.endMoveRows()
        return True

    def find_node(self, node_id: str) -> DataNode | None:
        def visit(node: DataNode) -> DataNode | None:
            if node.node_id == node_id:
                return node
            for child in node.children:
                found = visit(child)
                if found:
                    return found
            return None
        return visit(self.root)


class ProjectFilterProxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setRecursiveFilteringEnabled(True)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)


class ProjectTree(QWidget):
    node_selected = Signal(object)
    node_opened = Signal(object)
    visibility_changed = Signal(object, bool)
    message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.model = ProjectTreeModel()
        self.proxy = ProjectFilterProxy()
        self.proxy.setSourceModel(self.model)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索项目数据…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("搜索项目数据")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        layout.addWidget(self.search)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.SelectedClicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setAccessibleName("项目数据树")
        self.tree.expandAll()
        self.tree.selectionModel().currentChanged.connect(self._selection_changed)
        self.tree.doubleClicked.connect(self._double_clicked)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.model.dataChanged.connect(self._data_changed)
        layout.addWidget(self.tree, 1)
        footer = QHBoxLayout()
        self.count_label = QLabel("7 个数据组  ·  11 个对象")
        self.count_label.setObjectName("muted")
        footer.addWidget(self.count_label)
        layout.addLayout(footer)
        self.select_node(self.model.root.children[0])

    def load_root(self, root: DataNode) -> None:
        self.model.beginResetModel()
        self.model.root = root
        self.model.endResetModel()
        self.tree.expandAll()
        self.select_node(root.children[0])

    def select_node(self, node: DataNode) -> None:
        source = self.model.index_for_node(node)
        index = self.proxy.mapFromSource(source)
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index)

    def _selection_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            self.node_selected.emit(current.data(ProjectTreeModel.NODE_ROLE))

    def _double_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            self.node_opened.emit(index.data(ProjectTreeModel.NODE_ROLE))

    def _data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles: list[int]) -> None:
        if not roles or int(Qt.ItemDataRole.CheckStateRole) in roles:
            node = top_left.data(ProjectTreeModel.NODE_ROLE)
            if node:
                self.visibility_changed.emit(node, node.visible)

    def _show_context_menu(self, position) -> None:
        index = self.tree.indexAt(position)
        if not index.isValid():
            return
        node: DataNode = index.data(ProjectTreeModel.NODE_ROLE)
        menu = QMenu(self)
        open_action = menu.addAction("打开")
        rename_action = menu.addAction("重命名…")
        rename_action.setEnabled(not node.locked and node.kind != "project")
        menu.addSeparator()
        import_action = menu.addAction("导入数据…") if node.kind == "group" else None
        lock_text = "解除锁定" if node.locked else "锁定"
        lock_action = menu.addAction(lock_text) if node.kind != "project" else None
        menu.addSeparator()
        delete_action = menu.addAction("删除") if node.kind not in ("project", "group") else None
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen == open_action:
            self.node_opened.emit(node)
        elif chosen == rename_action:
            self._rename(node)
        elif chosen == lock_action:
            self.model.set_locked(node, not node.locked)
            self.message.emit(f"{'已锁定' if node.locked else '已解除锁定'}：{node.name}")
        elif chosen == delete_action:
            self._delete(node)
        elif import_action and chosen == import_action:
            self.message.emit("可通过顶部「导入数据」添加点云、网格或 CAD 文件")

    def _rename(self, node: DataNode) -> None:
        name, accepted = QInputDialog.getText(self, "重命名数据", "新名称", text=node.name)
        if accepted and name.strip():
            self.model.setData(self.model.index_for_node(node), name.strip())
            self.message.emit(f"已重命名为 {name.strip()}")

    def _delete(self, node: DataNode) -> None:
        answer = QMessageBox.question(self, "删除数据", f"确定从项目中移除「{node.name}」吗？\n原始文件不会被删除。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        index = self.model.index_for_node(node)
        self.model.removeRow(index.row, index.parent())
        self.message.emit(f"已移除：{node.name}")
