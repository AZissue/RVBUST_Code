"""Layer tree panel modeled on the ui_v2 FrameBrowser structure and semantics."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from ui_common.symbols import icon
from ui_v2 import theme


class CloudTreePanel(QWidget):
    remove_requested = Signal(list)
    clear_requested = Signal()
    restore_requested = Signal()
    visibility_changed = Signal(int, bool)
    current_changed = Signal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setObjectName('cloudTreePanel')
        self.setStyleSheet(f'''
            QWidget#cloudTreePanel QTreeWidget {{ background:{theme.BG_PANEL};
                border:1px solid {theme.BORDER}; border-radius:6px; }}
            QWidget#cloudTreePanel QTreeWidget::item {{ min-height:22px; }}
            QWidget#cloudTreePanel QTreeWidget::item:selected {{
                background:{theme.ACCENT_DIM}; color:{theme.ACCENT}; }}
        ''')
        self.setMinimumHeight(180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(5)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('图层 / 项目数据'))
        bar.addStretch()
        self.count = QLabel('0 图层')
        bar.addWidget(self.count)
        self.delete_button = QPushButton('删除')
        self.delete_button.setToolTip('删除选中图层（移入回收区，可在右键菜单恢复上次删除）')
        self.delete_button.clicked.connect(self._delete_selected)
        bar.addWidget(self.delete_button)
        layout.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['点云 / 对应数据', '点数'])
        self.tree.headerItem().setToolTip(1, '图层完整点数；显示采样不改变图层点数。')
        self.tree.setIndentation(14)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._current_item_changed)
        self.tree.itemSelectionChanged.connect(self._update_delete_button)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree, 1)
        self.details = QLabel('暂无图层，请打开点云文件。')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self._items = {}
        self._rebuilding = False
        self._known_root = False
        self._enabled = True
        self.refresh()

    def refresh(self, select=None):
        selected = {item.data(0, Qt.UserRole) for item in self.tree.selectedItems()}
        selected.discard(None)
        previous_root = self.tree.topLevelItem(0)
        was_expanded = previous_root.isExpanded() if previous_root is not None else True
        self._rebuilding = True
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items.clear()
        root = QTreeWidgetItem(self.tree, ['点云项目', f'{len(self.session.layers)} 图层'])
        root.setIcon(0, icon('folder_open', '#bbbbbb', 16))
        root.setToolTip(0, '当前点云项目 · 回收区图层不计入\n'
                           '删除的图层可通过右键"恢复上次删除"还原。')
        for index, layer in enumerate(self.session.layers):
            row = QTreeWidgetItem(root, [layer.name, f'{len(layer.points):,}'])
            row.setData(0, Qt.UserRole, index)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(0, Qt.Checked if layer.visible else Qt.Unchecked)
            row.setIcon(0, icon('layers', '#bbbbbb', 16))
            row.setToolTip(0, f'来源：{layer.source}\n'
                              f'可见性：{"显示" if layer.visible else "隐藏"}\n'
                              '显示采样不改变图层点数。')
            row.setToolTip(1, '图层完整点数；显示采样不改变图层点数。')
            self._items[index] = row
        root.setExpanded(was_expanded if self._known_root else True)
        self._known_root = True
        target = select
        if target not in self._items:
            target = next((index for index in sorted(selected) if index in self._items), None)
        if target is None and self._items:
            target = min(self._items)
        if target is not None:
            self.tree.setCurrentItem(self._items[target])
        for uid in selected:
            if uid in self._items:
                self._items[uid].setSelected(True)
        self.tree.blockSignals(False)
        self._rebuilding = False
        self.count.setText(f'{len(self.session.layers)} 图层')
        self._update_details()
        self._update_delete_button()

    def current_index(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.UserRole)

    def selected_indices(self):
        indices = set()
        for item in self.tree.selectedItems():
            uid = item.data(0, Qt.UserRole)
            if uid is None:
                indices.update(self._items)
            else:
                indices.add(uid)
        return sorted(indices)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self.tree.setEnabled(self._enabled)
        self._update_delete_button()

    def _update_delete_button(self):
        self.delete_button.setEnabled(self._enabled and bool(self.selected_indices()))

    def _delete_selected(self):
        indices = self.selected_indices()
        if indices:
            self.remove_requested.emit(indices)

    def _item_changed(self, item, column):
        if self._rebuilding:
            return
        uid = item.data(0, Qt.UserRole)
        if uid is not None:
            self.visibility_changed.emit(uid, item.checkState(0) == Qt.Checked)

    def _current_item_changed(self, item, previous):
        if self._rebuilding:
            return
        self._update_details()
        self.current_changed.emit(item.data(0, Qt.UserRole) if item is not None else None)

    def _update_details(self):
        item = self.tree.currentItem()
        uid = item.data(0, Qt.UserRole) if item is not None else None
        if uid is None or uid not in self._items:
            if not self.session.layers:
                self.details.setText('暂无图层，请打开点云文件。')
            else:
                self.details.setText(f'点云项目 · {len(self.session.layers)} 图层\n'
                                     '选择图层查看来源；勾选控制 3D 显隐。')
            return
        layer = self.session.layers[uid]
        self.details.setText(f'{layer.name} · {len(layer.points):,} 点\n来源 {layer.source}')

    def _context_menu(self, position):
        item = self.tree.itemAt(position)
        if item is not None and not item.isSelected():
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item)
            self.tree.blockSignals(False)
            self._update_details()
            self._update_delete_button()
            self.current_changed.emit(self.current_index())
        menu = QMenu(self)
        action = menu.addAction('删除选中图层', self._delete_selected)
        action.setEnabled(bool(self.selected_indices()))
        action = menu.addAction('清空项目', self.clear_requested.emit)
        action.setEnabled(bool(self.session.layers))
        action = menu.addAction('恢复上次删除', self.restore_requested.emit)
        action.setEnabled(bool(self.session.removed))
        menu.addSeparator()
        menu.addAction('展开全部', self.tree.expandAll)
        menu.addAction('折叠全部', self.tree.collapseAll)
        menu.exec(self.tree.viewport().mapToGlobal(position))
