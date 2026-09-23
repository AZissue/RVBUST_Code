# -*- coding: utf-8 -*-
"""
CloudCompare 式 DB 树（CloudCompare DB Tree）。

功能：
  - 多级节点：文件节点(父) → 点云节点(子) → 标量场节点(孙)
  - 勾选显隐、拖拽排序
  - 右键菜单：删除、重命名、导出
  - 选中高亮
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QMenu,
)

from ui_v2.theme import TEXT_PRIMARY, TEXT_SECONDARY, BG_CARD, BG_PANEL, BORDER


class DBTreeItem(QTreeWidgetItem):
    """DB 树通用节点。"""

    def __init__(self, node_id: str, name: str, node_type: str,
                 parent=None, color: Optional[tuple] = None):
        super().__init__(parent)
        self.node_id = node_id
        self.node_type = node_type
        self._color = color or (0.7, 0.7, 0.7)
        self.setText(0, name)
        self.setFlags(self.flags() | Qt.ItemIsUserCheckable)
        self.setCheckState(0, Qt.Checked)
        # 所有节点允许选中（文件节点可选中后整支删除）
        self.setFlags(self.flags() | Qt.ItemIsSelectable)

    def set_icon_color(self, color: tuple):
        """设置节点前面的颜色方块图标。"""
        self._color = color
        r, g, b = int(color[0]*255), int(color[1]*255), int(color[2]*255)
        # 用背景色作为视觉标识
        self.setBackground(0, QColor(r, g, b))


class CloudDBTree(QWidget):
    """CloudCompare 式 DB 树控件。"""

    selection_changed = Signal(str)      # 选中的 node_id
    visibility_changed = Signal(str, bool)  # node_id, visible
    delete_requested = Signal(str)       # node_id
    rename_requested = Signal(str, str)  # node_id, new_name
    export_requested = Signal(str)       # node_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._node_items: dict = {}  # node_id -> DBTreeItem
        self._setup_ui()

    def _setup_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(8)

        lbl = QLabel("DB 树")
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        lo.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: 6px;
                color: {TEXT_PRIMARY};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 4px 2px;
                border: none;
            }}
            QTreeWidget::item:selected {{
                background-color: #d32f2f;
                color: #FFFFFF;
            }}
            QTreeWidget::item:selected:!active {{
                background-color: #b71c1c;
                color: #FFFFFF;
            }}
        """)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)

        # Delete 键删除选中节点
        from PySide6.QtGui import QShortcut, QKeySequence
        sc = QShortcut(QKeySequence(Qt.Key_Delete), self._tree)
        sc.activated.connect(self._delete_selected)
        lo.addWidget(self._tree, 1)

    def _delete_selected(self):
        """删除所有选中的节点（依次发信号，由工作流递归处理子节点）。"""
        for item in self._tree.selectedItems():
            if isinstance(item, DBTreeItem):
                self.delete_requested.emit(item.node_id)

    # ------------------------------------------------------------------
    # 节点操作
    # ------------------------------------------------------------------
    def add_file_node(self, node_id: str, name: str) -> DBTreeItem:
        item = DBTreeItem(node_id, name, "file")
        self._tree.addTopLevelItem(item)
        self._node_items[node_id] = item
        item.setExpanded(True)
        return item

    def add_cloud_node(self, node_id: str, name: str, parent_id: Optional[str] = None,
                       color: Optional[tuple] = None) -> DBTreeItem:
        parent = self._node_items.get(parent_id)
        item = DBTreeItem(node_id, name, "cloud", parent=parent, color=color)
        if color:
            item.set_icon_color(color)
        if parent:
            parent.setExpanded(True)
        else:
            self._tree.addTopLevelItem(item)
        self._node_items[node_id] = item
        return item

    def add_scalar_node(self, node_id: str, scalar_name: str, parent_id: str) -> DBTreeItem:
        parent = self._node_items.get(parent_id)
        if parent is None:
            return None
        item = DBTreeItem(f"{node_id}_scalar_{scalar_name}", scalar_name, "scalar", parent=parent)
        item.setForeground(0, QColor(150, 200, 255))
        self._node_items[item.node_id] = item
        parent.setExpanded(True)
        return item

    def remove_node(self, node_id: str):
        item = self._node_items.pop(node_id, None)
        if item is None:
            return
        # 递归删除子节点
        children_ids = [k for k, v in self._node_items.items() if v.parent() == item]
        for cid in children_ids:
            self.remove_node(cid)
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        else:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx >= 0:
                self._tree.takeTopLevelItem(idx)

    def clear_all(self):
        self._tree.clear()
        self._node_items.clear()

    def set_node_visible(self, node_id: str, visible: bool):
        item = self._node_items.get(node_id)
        if item:
            item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)

    def select_node(self, node_id: str):
        item = self._node_items.get(node_id)
        if item:
            self._tree.setCurrentItem(item)

    def selected_node_id(self) -> Optional[str]:
        items = self._tree.selectedItems()
        if not items:
            return None
        for item in items:
            if isinstance(item, DBTreeItem):
                return item.node_id
        return None

    def iter_cloud_items(self) -> List[DBTreeItem]:
        return [item for item in self._node_items.values() if item.node_type == "cloud"]

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None or not isinstance(item, DBTreeItem):
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {BG_CARD}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; padding: 4px; }}")

        if item.node_type == "cloud":
            act_export = QAction("导出点云", self)
            act_export.triggered.connect(lambda: self.export_requested.emit(item.node_id))
            menu.addAction(act_export)
            menu.addSeparator()

        act_rename = QAction("重命名", self)
        act_rename.triggered.connect(lambda: self._rename_item(item))
        menu.addAction(act_rename)

        act_delete = QAction("删除", self)
        act_delete.triggered.connect(lambda: self.delete_requested.emit(item.node_id))
        menu.addAction(act_delete)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _rename_item(self, item: DBTreeItem):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "重命名", "新名称:", text=item.text(0))
        if ok and text:
            item.setText(0, text)
            self.rename_requested.emit(item.node_id, text)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0 or not isinstance(item, DBTreeItem):
            return
        visible = item.checkState(0) == Qt.Checked
        self.visibility_changed.emit(item.node_id, visible)

    def _on_selection_changed(self):
        node_id = self.selected_node_id()
        if node_id:
            self.selection_changed.emit(node_id)
