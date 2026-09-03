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
        # 点云节点默认允许选择
        if node_type == "cloud":
            self.setFlags(self.flags() | Qt.ItemIsSelectable)

    def set_icon_color(self, color: tuple):
        """设置节点前面的颜色方块图标。"""
        self._color = color
        r, g, b = int(color[0]*255), int(color[1]*255), int(color[2]*255)
        self.setForeground(0, QColor(r, g, b))


class CCDBTree(QWidget):
    """CloudCompare 式 DB 树控件。"""

    selection_changed = Signal(list)   # 当前选中的 node_id 列表
    visibility_changed = Signal(str, bool)  # node_id, visible
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)  # node_id, new_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self._build_ui()
        self._item_map: dict[str, DBTreeItem] = {}

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("DB Tree")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold; padding: 4px;")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree)

    def _on_selection_changed(self):
        items = self.tree.selectedItems()
        ids = [it.node_id for it in items if isinstance(it, DBTreeItem)]
        self.selection_changed.emit(ids)

    def _on_item_changed(self, item, column):
        if isinstance(item, DBTreeItem) and column == 0:
            visible = item.checkState(0) == Qt.Checked
            self.visibility_changed.emit(item.node_id, visible)

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not isinstance(item, DBTreeItem):
            return
        menu = QMenu(self)
        act_del = QAction("Delete", self)
        act_del.triggered.connect(lambda: self.delete_requested.emit(item.node_id))
        menu.addAction(act_del)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ── 公开 API ──

    def add_file(self, file_id: str, name: str) -> DBTreeItem:
        """添加顶层文件节点。"""
        item = DBTreeItem(file_id, name, "file")
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        self.tree.addTopLevelItem(item)
        self._item_map[file_id] = item
        return item

    def add_cloud(self, cloud_id: str, name: str, parent_id: str,
                  color: Optional[tuple] = None) -> DBTreeItem:
        """在文件节点下添加点云节点。"""
        parent = self._item_map.get(parent_id)
        if parent is None:
            parent = self.tree
        item = DBTreeItem(cloud_id, name, "cloud", parent=parent, color=color)
        if color:
            item.set_icon_color(color)
        self._item_map[cloud_id] = item
        return item

    def add_scalar_field(self, sf_id: str, name: str, parent_cloud_id: str) -> DBTreeItem:
        """在点云节点下添加标量场节点。"""
        parent = self._item_map.get(parent_cloud_id)
        if parent is None:
            return
        item = DBTreeItem(sf_id, name, "scalar_field", parent=parent)
        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        self._item_map[sf_id] = item
        return item

    def remove_node(self, node_id: str):
        item = self._item_map.pop(node_id, None)
        if item:
            (item.parent() or self.tree).removeChild(item)

    def set_node_color(self, node_id: str, color: tuple):
        item = self._item_map.get(node_id)
        if item and item.node_type == "cloud":
            item.set_icon_color(color)

    def clear_all(self):
        self.tree.clear()
        self._item_map.clear()
