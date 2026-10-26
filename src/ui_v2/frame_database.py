"""New-UI frame archive controller and hierarchical browser."""
from PySide6.QtCore import QObject, Qt, Signal, Slot, QEvent, QSignalBlocker
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QAbstractItemView, QMenu, QLayout, QSizePolicy, QSplitter,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle)
from dataclasses import replace
from pathlib import Path
from contextlib import contextmanager
import threading

from core.frame_database import DEFAULT_ROOT, STALE_RESULT
from core.frame_data import FrameData
from . import icons
from .dialogs import ChineseMessageBox as QMessageBox
from .widgets.db_check_style import DB_CHECK_QSS, paint_component_check


class _ComponentCheckDelegate(QStyledItemDelegate):
    """Use the active style's checkbox geometry, including DPI and indentation."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Native item views can supply a focused/current cell after deselection.
        # The DB highlight represents model selection, never keyboard focus.
        if not self.parent().selectionModel().isSelected(index):
            option.state &= ~(QStyle.State_Selected | QStyle.State_HasFocus)

    def check_rect(self, index):
        view = self.parent()
        option = QStyleOptionViewItem()
        # Match the option used by the view's paint pass, including vertical
        # text/icon alignment and decoration size (initFrom alone omits these).
        view.initViewItemOption(option)
        self.initStyleOption(option, index)
        option.rect = view.visualRect(index)
        return view.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, option, view)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        paint_component_check(painter, option, index, self.check_rect(index))


class FrameBrowser(QWidget):
    """Shared DB tree; component checks are transient display/processing inputs.

    checked_components(component=None) returns ordered (frame_uid, component)
    references, separate from preview/highlight selection and persisted data.
    Consumers can subscribe to checked_components_changed(list).
    """
    calibration_selected = Signal()
    frame_selected = Signal(str)
    component_selected = Signal(str, str)
    open_requested = Signal()
    restore_requested = Signal()
    delete_requested = Signal(list)
    recover_requested = Signal()
    manage_requested = Signal()
    checked_components_changed = Signal(list)
    selection_cleared = Signal()
    export_requested = Signal(str)
    recognize_requested = Signal(list)

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        self.setObjectName('frameDatabaseBrowser')
        self.setStyleSheet('''
            QWidget#frameDatabaseBrowser QTreeWidget { background:#252525; border:1px solid #454545; outline:none; }
            QWidget#frameDatabaseBrowser QTreeWidget:focus { border-color:#805052; }
            QWidget#frameDatabaseBrowser QTreeWidget::item { min-height:22px; }
            QWidget#frameDatabaseBrowser QTreeWidget::item:hover { background:#353030; }
            QWidget#frameDatabaseBrowser QTreeWidget::item:focus:!selected { background:#252525; }
            QWidget#frameDatabaseBrowser QTreeWidget::item:selected { background:#573232; color:#ffffff; }
            QWidget#frameDatabaseBrowser QTreeWidget::item:selected:!active { background:#453435; color:#e3dada; }
        ''' + DB_CHECK_QSS)
        layout = QVBoxLayout(self)
        # Keep the tree and footer minima additive when the workspace shrinks.
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(5)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('DB / 项目数据'))
        bar.addStretch()
        self.count = QLabel('0 帧')
        bar.addWidget(self.count)
        layout.addLayout(bar)
        self.tree = QTreeWidget()
        self._check_delegate = _ComponentCheckDelegate(self.tree)
        self.tree.setItemDelegate(self._check_delegate)
        self._check_pressed = None
        self.tree.viewport().installEventFilter(self)
        self.tree.setHeaderLabels(['单帧 / 对应数据', '数据信息'])
        self.tree.headerItem().setToolTip(1, '点云显示文件点数，2D图像显示像素分辨率，分组显示数据数量。')
        self.tree.setIndentation(14)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setMinimumHeight(100)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.currentItemChanged.connect(self._selected)
        self.tree.itemChanged.connect(self._component_check_changed)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        from .widgets.db_properties import DbProperties
        self.properties = DbProperties()
        self.property_splitter = QSplitter(Qt.Vertical)
        self.property_splitter.setChildrenCollapsible(False)
        self.property_splitter.addWidget(self.tree)
        self.property_splitter.addWidget(self.properties)
        self.properties.setMinimumHeight(100)
        self.property_splitter.setHandleWidth(7)
        self.property_splitter.handle(1).setCursor(Qt.SplitVCursor)
        self.property_splitter.setStyleSheet('QSplitter::handle:vertical {background:#414141;} QSplitter::handle:vertical:hover {background:#805052;}')
        self.property_splitter.setStretchFactor(0, 1)
        self.property_splitter.setStretchFactor(1, 1)
        self.property_splitter.setSizes([260, 210])
        layout.addWidget(self.property_splitter, 1)
        self.footer = QWidget()
        self.footer.setObjectName('frameBrowserFooter')
        self.footer.setStyleSheet('QWidget#frameBrowserFooter {background:#292929;border-top:1px solid #414141;}')
        self.footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        footer_layout = QVBoxLayout(self.footer)
        footer_layout.setContentsMargins(4, 6, 4, 4)
        footer_layout.setSpacing(5)
        footer_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.details = QLabel('临时工作区 · 请主动保存会话')
        self.details.setWordWrap(True)
        footer_layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.open_button = QPushButton('打开 DB 项目')
        self.open_button.clicked.connect(self.open_requested)
        actions.addWidget(self.open_button)
        self.restore_button = QPushButton('返回工作视图')
        self.restore_button.clicked.connect(self.restore_requested)
        actions.addWidget(self.restore_button)
        footer_layout.addLayout(actions)
        self.manage_button = QPushButton('会话占用 / 管理')
        self.manage_button.clicked.connect(self.manage_requested)
        footer_layout.addWidget(self.manage_button)
        layout.addWidget(self.footer)
        self._items = {}
        self._component_items = {}
        self._checks_database = database
        self._published_checks = []
        self.refresh()

    def refresh(self):
        checked = set(self.checked_components())
        self._check_pressed = None
        selected = {(item.data(0, Qt.UserRole), item.data(0, Qt.UserRole + 2)) for item in self.tree.selectedItems()}
        expanded = set()
        def remember(item, key=''):
            key += '/' + item.text(0)
            if item.isExpanded():
                expanded.add(key)
            for i in range(item.childCount()):
                remember(item.child(i), key)
        for i in range(self.tree.topLevelItemCount()):
            remember(self.tree.topLevelItem(i))
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items.clear()
        self._component_items.clear()
        sessions, records = self.database.snapshot()
        results = sum(record.kind == 'result' for record in records)
        count_text = f'{len(records)-results} 帧' + (f' / {results} 结果' if results else '')
        groups = {}
        categories = {}
        project_root = None
        if hasattr(self.database, 'project_title'):
            project_root = QTreeWidgetItem(self.tree, [self.database.project_title, count_text])
            project_root.setIcon(0, icons.icon('folder_open', '#bbbbbb', 16))
        for record in records:
            session = sessions[record.session_id]
            session_key = record.session_id
            if session_key not in groups:
                groups[session_key] = project_root if project_root is not None else QTreeWidgetItem(self.tree, [session['title'] + ' · ' + session['created'][11:], ''])
                groups[session_key].setData(0, Qt.UserRole + 1, session_key)
                groups[session_key].setToolTip(0, session['created'])
                groups[session_key].setIcon(0, icons.icon('folder_open', '#bbbbbb', 16))
            category = (('后处理结果' if record.purpose == '后处理结果' else '拼接结果') if record.kind == 'result' else '标定会话数据'
                if self.database.mode != 'mobile_chain' and ('标定' in record.purpose or record.purpose == 'calib') else '扫描原始帧')
            category_key = (id(groups[session_key]), category)
            if category_key not in categories:
                categories[category_key] = QTreeWidgetItem(groups[session_key], [category, ''])
                categories[category_key].setIcon(0, icons.icon('folder_open', '#aaaaaa', 16))
            parent = categories[category_key]
            title = (record.logical_name if record.purpose == '后处理结果' else f'拼接帧 {record.frame_id:03d}') if record.kind == 'result' else f'帧 {record.frame_id:03d}'
            if record.kind == 'result' and record.status == STALE_RESULT:
                title += ' · 来源已变化' if record.purpose == '后处理结果' else ' · 需重新拼接'
            if self.database.mode == 'multi_cam' and record.kind == 'raw':
                title += ' · ' + record.camera
            row = QTreeWidgetItem(parent, [title, ''])
            row.setData(0, Qt.UserRole, record.uid)
            row.setToolTip(0, f'{record.camera} · {record.purpose} · {record.logical_name}\n{record.status}\n'
                f'原始PLY + 2D PNG（{record.image_size[0]} × {record.image_size[1]}）\n'
                '原始相机坐标；选择后在右侧查看2D / 3D。\n' + record.created)
            row.setIcon(0, icons.icon('layers', '#bbbbbb', 16))
            if record.kind == 'result':
                row.setIcon(0, icons.icon('stitch', '#d65050', 16))
                row.setToolTip(0, '独立' + ('后处理结果' if record.purpose == '后处理结果' else '拼接结果') + ' · mm\n' + record.status + '\n来源帧：' + '\n'.join(record.source_ids) + '\n' + record.created)
            self._items[record.uid] = row
            cloud_item = QTreeWidgetItem(row, ['点云 · PLY', f'{record.points:,}' if record.points is not None else '—'])
            cloud_item.setIcon(0, icons.icon('layers', '#bbbbbb', 16))
            cloud_item.setToolTip(1, '结果有效几何点数；原始帧保持独立。' if record.kind == 'result'
                else '原始点槽位数，包含有序点云中的无效占位点；文件不下采样。')
            components = [('cloud', cloud_item)]
            if record.kind != 'result':
                image_item = QTreeWidgetItem(row, ['2D 图像', f'{record.image_size[0]} × {record.image_size[1]}'])
                image_item.setIcon(0, icons.icon('camera', '#bbbbbb', 16))
                image_item.setToolTip(1, '2D图像分辨率（宽 × 高，像素）。')
                components.append(('image', image_item))
            for component, item in components:
                item.setData(0, Qt.UserRole, record.uid)
                item.setData(0, Qt.UserRole + 2, component)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if (record.uid, component) in checked else Qt.Unchecked)
                item.setToolTip(0, ('仅查看3D点云' if component == 'cloud' else '仅在右侧查看2D图像，不重载点云') +
                    ('\n复选框：在3D画布叠加显示；原始帧不应用标定变换。' if component == 'cloud'
                     else '\n复选框：勾选待处理图像，与预览及多选删除独立。') +
                    '\n删除操作针对所属完整帧，可在回收区恢复。')
                self._component_items[(record.uid, component)] = item
        parameters = None
        if self.database.mode in ('multi_cam', 'turntable') or (project_root is not None and getattr(self.database, 'has_calibration', False)):
            calibration_group = next((item for item in categories.values() if item.text(0) == '标定会话数据'), None)
            if calibration_group is None:
                calibration_group = QTreeWidgetItem(project_root if project_root is not None else self.tree, ['标定会话数据', ''])
                calibration_group.setIcon(0, icons.icon('folder_open', '#aaaaaa', 16))
                categories[('parameters', 'calibration')] = calibration_group
            parameters = QTreeWidgetItem(calibration_group, ['标定参数', '多相机外参' if self.database.mode == 'multi_cam' else '转台轴心'])
            parameters.setData(0, Qt.UserRole + 2, 'calibration')
            parameters.setToolTip(0, '会话中的标定参数；采集帧中的点云和2D图像保存在各自子项。')
        for item in categories.values():
            item.setText(1, f'{item.childCount()} 项')
        def restore(item, key=''):
            key += '/' + item.text(0)
            if item.childCount():
                item.setExpanded(key in expanded or key not in self._known_groups)
            for i in range(item.childCount()):
                restore(item.child(i), key)
            self._known_groups.add(key)
        self._known_groups = getattr(self, '_known_groups', set())
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            restore(item)
            self._known_groups.add('/' + item.text(0))
        for uid, component in selected:
            if component == 'calibration':
                item = parameters
            elif component:
                item = self._component_items.get((uid, component))
            else:
                item = self._items.get(uid)
            if item:
                item.setSelected(True)
        self._checks_database = self.database
        self.tree.blockSignals(False)
        self.count.setText(count_text)
        self._selection_changed()
        self._publish_checks()

    def checked_components(self, component=None):
        """Return checked cloud/image references without loading geometry.

        Checks survive refresh within this database, but are dropped on removal
        or a database switch. They are not saved into the project/session.
        """
        if component not in (None, 'cloud', 'image'):
            raise ValueError('component must be cloud, image or None')
        if self._checks_database is not self.database:
            return []
        return [key for key, item in self._component_items.items()
                if key[0] in self.database.records
                and (component is None or key[1] == component)
                and item.checkState(0) == Qt.Checked]

    def set_component_checked(self, uid, component, checked=True):
        """Set one available component; unknown references raise KeyError."""
        self._component_items[(uid, component)].setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

    def _component_check_changed(self, item, column):
        if column == 0 and item.data(0, Qt.UserRole + 2) in ('cloud', 'image'):
            self._publish_checks()

    def _publish_checks(self):
        checked = self.checked_components()
        if checked != self._published_checks:
            self._published_checks = checked
            self.checked_components_changed.emit(list(checked))

    def selected_ids(self):
        identifiers = set()
        def visit(item):
            uid = item.data(0, Qt.UserRole)
            if uid:
                identifiers.add(uid)
            else:
                for i in range(item.childCount()):
                    visit(item.child(i))
        for item in self.tree.selectedItems():
            visit(item)
        return [uid for uid in self.database.records if uid in identifiers]

    def export_uid(self):
        """Resolve one explicit row, then one checked cloud, then latest result.

        Ambiguous cloud selections never fall back to a different file.
        Record kind is unrestricted so derived DB branches use the same path.
        """
        items = self.tree.selectedItems()
        cloud_items = [item for item in items if item.data(0, Qt.UserRole)
                       and item.data(0, Qt.UserRole+2) != 'image']
        if cloud_items:
            identifiers = list(dict.fromkeys(item.data(0, Qt.UserRole) for item in cloud_items))
        else:
            identifiers = [uid for uid, _ in self.checked_components('cloud')]
            if not identifiers:
                if items:
                    return None
                results = [uid for uid, row in self.database.records.items()
                           if row.kind == 'result' and row.status != STALE_RESULT]
                identifiers = results[-1:]
        if len(identifiers) != 1:
            return None
        uid = identifiers[0]
        record = self.database.records.get(uid)
        return uid if record is not None and record.status != STALE_RESULT else None

    def _selection_changed(self):
        if not self.tree.selectedItems():
            self.tree.setToolTip('')
        if not self.tree.selectedItems() and self.tree.currentItem() is not None:
            with QSignalBlocker(self.tree):
                self.tree.setCurrentItem(None)
            self.selection_cleared.emit()
        self._update_properties()
        self.tree.viewport().update()
        changed = getattr(self, '_edit_selection_changed', None)
        if changed:
            changed()
        export_changed = getattr(self, '_export_selection_changed', None)
        if export_changed:
            export_changed()

    def clear_highlight(self):
        """Clear row selection and its focus cell, keeping component checks."""
        had_selection = bool(self.tree.selectedItems()) or self.tree.currentItem() is not None
        with QSignalBlocker(self.tree):
            self.tree.setCurrentItem(None)
            self.tree.clearSelection()
        self._selection_changed()
        self.tree.viewport().update()
        if had_selection:
            self.selection_cleared.emit()

    def _update_properties(self):
        items = self.tree.selectedItems()
        if not items:
            self.properties.show_values({'提示': '请选择 DB 树中的数据'})
            return
        ids = self.selected_ids()
        if len(items) > 1:
            self.properties.show_values({'类型': '多项选择', '选中项': len(items),
                '关联帧 / 结果': len(ids)})
            return
        item = items[0]
        component = item.data(0, Qt.UserRole + 2)
        record = self.database.records.get(item.data(0, Qt.UserRole))
        if record is None:
            self.properties.show_values({'名称': item.text(0),
                '类型': '标定参数' if component == 'calibration' else '数据分组',
                '说明': item.text(1) or '—', '关联帧 / 结果': len(ids)},
                object_type=component)
            return
        result = record.kind == 'result'
        values = {'名称': record.logical_name, '类型': '2D 图像' if component == 'image' else
                  (('后处理点云' if record.purpose == '后处理结果' else '拼接点云') if result else '原始点云') if component == 'cloud' else
                  (('后处理结果' if record.purpose == '后处理结果' else '拼接结果') if result else '原始帧'),
                  '状态': record.status, '帧编号': f'{record.frame_id:03d}',
                  '相机': record.camera, '用途': record.purpose}
        if component != 'image':
            values['有效点数' if result else '文件点槽位'] = f'{record.points:,}' if record.points is not None else '—'
            values['坐标单位'] = 'mm'
            if not result:
                values['点数说明'] = '含有序点云无效占位点，非有效几何点数。'
        if not result and component != 'cloud':
            values['图像分辨率'] = f'{record.image_size[0]} × {record.image_size[1]} px'
        if result:
            values['来源帧数'] = len(record.source_ids)
        else:
            values['标记物数量'] = len(record.markers)
            values['后台识别'] = {'running': '识别中', 'done': '已完成', 'error': '失败，可右键重新识别'}.get(
                record.recognition.get('state'), '等待后台识别')
            if record.recognition.get('state') == 'done':
                values['有效三维标记'] = sum(row.get('valid_3d', True) for row in record.markers)
                values['识别类型'] = {'coded_circle': '编码圆', 'asymmetric_grid': '非对称圆标定板'}.get(
                    record.recognition.get('marker_type'), record.recognition.get('marker_type', '—'))
            if record.recognition.get('error'):
                values['识别错误'] = record.recognition['error']
            if record.recognition.get('board_pattern_name'):
                values['标定板规格'] = record.recognition['board_pattern_name']
                values['标定板拟合 RMS'] = f"{record.recognition.get('board_rms_mm', 0):.3f} mm"
        self.properties.show_values(values)

    def delete_selected(self):
        identifiers = self.selected_ids()
        if identifiers:
            self.delete_requested.emit(identifiers)

    def eventFilter(self, watched, event):
        if watched is self.tree.viewport() and event.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            if event.button() == Qt.LeftButton:
                index = self.tree.indexAt(event.position().toPoint())
                key = (index.data(Qt.UserRole), index.data(Qt.UserRole + 2))
                on_check = (index.column() == 0 and key in self._component_items
                            and self._check_delegate.check_rect(index).contains(event.position().toPoint()))
                if event.type() == QEvent.MouseButtonPress and on_check:
                    self._check_pressed = key
                    return True
                if event.type() == QEvent.MouseButtonRelease and self._check_pressed is not None:
                    pressed, self._check_pressed = self._check_pressed, None
                    if on_check and key == pressed:
                        item = self._component_items[key]
                        self.set_component_checked(*key, item.checkState(0) != Qt.Checked)
                    return True
                if event.type() == QEvent.MouseButtonDblClick and on_check:
                    return True
                if not index.isValid():
                    if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                        self.clear_highlight()
                    return True
            if event.button() == Qt.RightButton:
                if event.type() == QEvent.MouseButtonPress:
                    self._select_context_target(event.position().toPoint())
                # The view's default press changes the current item before the
                # context menu signal, starting an unwanted frame/component read.
                return True
        return super().eventFilter(watched, event)

    def _select_context_target(self, position):
        item = self.tree.itemAt(position)
        if item and not item.isSelected():
            with QSignalBlocker(self.tree):
                self.tree.setCurrentItem(item)
            self._selection_changed()

    def _context_menu(self, position):
        # Also handles keyboard/programmatic context menu requests.
        self._select_context_target(position)
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        if item and item.data(0, Qt.UserRole):
            label = {'cloud': '查看3D点云', 'image': '查看右侧2D图像'}.get(item.data(0, Qt.UserRole + 2), '查看2D / 3D')
            menu.addAction(label, lambda: self._selected(item, None))
            if item.data(0, Qt.UserRole+2) != 'image':
                uid = item.data(0, Qt.UserRole)
                export = menu.addAction('导出此点云…', lambda: self.export_requested.emit(uid))
                record = self.database.records.get(uid)
                export.setEnabled(record is not None and record.status != STALE_RESULT)
        action = menu.addAction('删除选中数据', self.delete_selected)
        raw_ids = [uid for uid in self.selected_ids() if self.database.records[uid].kind == 'raw']
        recognize = menu.addAction('重新识别标记物', lambda: self.recognize_requested.emit(raw_ids))
        recognize.setEnabled(bool(raw_ids))
        action.setEnabled(bool(self.selected_ids()))
        action = menu.addAction('清空当前 DB', lambda: self.delete_requested.emit(list(self.database.records)))
        action.setEnabled(bool(self.database.records))
        action = menu.addAction('恢复上次删除', self.recover_requested.emit)
        action.setEnabled(bool(self.database.removed))
        menu.addSeparator()
        menu.addAction('展开全部', self.tree.expandAll)
        menu.addAction('折叠全部', self.tree.collapseAll)
        menu.addAction('返回工作视图', self.restore_requested.emit)
        menu.addAction('会话占用 / 管理', self.manage_requested.emit)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _selected(self, item, previous):
        if item and item.data(0, Qt.UserRole + 2) == 'calibration':
            self.calibration_selected.emit()
            return
        if item and item.data(0, Qt.UserRole):
            component = item.data(0, Qt.UserRole + 2)
            if component:
                self.component_selected.emit(item.data(0, Qt.UserRole), component)
            else:
                self.frame_selected.emit(item.data(0, Qt.UserRole))

    def show_frame(self, uid, frame, component='frame'):
        row = self.database.records[uid]
        if row.kind == 'result':
            self.details.setText(f'{row.logical_name} · {row.points:,} 个有效点\n来源 {len(row.source_ids)} 帧 · 独立结果，原始数据保留')
            self.tree.setToolTip(self.details.text())
            return
        description = {'frame': '原始PLY + 2D PNG · 联动查看', 'cloud': '仅查看原始点云 · 相机坐标系 / mm',
                       'image': '仅查看2D图像 · 保留当前3D视图'}[component]
        self.details.setText(f'{row.logical_name} · {row.status}\n{description}')
        self.tree.setToolTip(self.details.text())


class FrameDatabaseController(QObject):
    changed = Signal(str)

    def __init__(self, bridge):
        super().__init__(bridge)
        self.bridge = bridge
        self.databases = bridge.shell._frame_databases
        self.browsers = {}
        self._selection = 0
        self._preview_modes = set()
        self._displayed = {}
        self._capture_target = threading.local()
        from .db_cloud_overlay import DbCloudOverlay
        self.overlay = DbCloudOverlay(self)
        for mode, database in self.databases.items():
            database.on_changed = lambda key=mode: self.changed.emit(key)
        self.changed.connect(self._changed)

    def ingest(self, mode, frame, **kwargs):
        return self.databases[mode].ingest(frame, **kwargs)

    @contextmanager
    def replacing_capture(self, mode, uid):
        self._capture_target.value = (mode, uid)
        try:
            yield
        finally:
            self._capture_target.value = None

    def capture(self, frame):
        manager = self.bridge.mobile_workflow.station_manager
        if self.bridge.shell._presentation != 'industrial' and not (
                self.bridge._current_mode == 'mobile_chain' and manager and manager.managed_frames):
            return
        mode = self.bridge._current_mode
        purpose = ('移动机位' if mode == 'mobile_chain' else '转台采集' if mode == 'turntable'
            else '机器人原始帧' if mode == 'robot_stitch'
            else '扫描数据' if self.bridge.fixed_workflow.is_calibration_locked else '标定数据')
        target = getattr(self._capture_target, 'value', None)
        if target is not None:
            if target[0] != mode:
                raise RuntimeError('重拍期间工作区已变化')
            uid = self.databases[mode].replace_capture(target[1], frame)
        else:
            if mode == 'mobile_chain' and self.bridge.shell._presentation == 'industrial':
                frame.frame_id = 1 + max((row.frame_id for row in self.databases[mode].records.values()
                                         if row.kind == 'raw'), default=0)
            uid = self.ingest(mode, frame, purpose=purpose)
        folder = self.databases[mode].directory / 'frames' / uid
        # Return a stable archive reference to the workflow. CameraManager frees
        # SDK handles after this snapshot is complete, before the next capture.
        return replace(frame, image_np=frame.image_np.copy(), pointmap=None, rvc_image=None,
                       is_offline=True, offline_dir=str(folder),
                       offline_image_path=str(folder / 'image.png'),
                       offline_pointmap_path=str(folder / 'pointmap.ply'))

    @Slot(str)
    def _changed(self, mode):
        projects = getattr(self.bridge, 'projects', None)
        if projects:
            projects.mark_changed(mode)
        browser = self.browsers.get(mode)
        if browser:
            browser.refresh()
            self.overlay.changed(mode, refresh=True)
        if hasattr(self.bridge.shell, '_industrial_ribbon'):
            self.bridge.shell._industrial_ribbon.update_status()

    def bind(self, mode, browser):
        for previous in list(self.overlay.requested):
            if previous != mode:
                self.overlay.drop_inactive(previous)
        if mode in self.browsers:
            return
        self.browsers[mode] = browser
        browser.properties.recognition.bind(self.bridge, mode)
        browser.frame_selected.connect(lambda uid: self.select(mode, uid))
        browser.component_selected.connect(lambda uid, component: self.select(mode, uid, component))
        browser.checked_components_changed.connect(lambda _: self.overlay.changed(mode))
        browser._export_selection_changed = self.bridge.shell._industrial_ribbon.update_status
        browser.checked_components_changed.connect(lambda _: browser._export_selection_changed())
        browser.export_requested.connect(self.bridge.stitching.export)
        browser.recognize_requested.connect(lambda ids: self.bridge.recognition.retry(mode, ids))
        browser.selection_cleared.connect(lambda: self._cancel_selection(mode))
        if mode == 'mobile_chain':
            workspace = self.bridge.shell.workspace_mobile()
            workspace._db_edit_gate = self.bridge.stitching.update_mobile_actions
            workspace._db_delete_action = self.bridge.stitching.delete_mobile
            browser._edit_selection_changed = self.bridge.stitching.update_mobile_actions
        browser.open_button.setText('打开会话')
        browser.open_requested.connect(self.bridge._on_open_session)
        browser.manage_requested.connect(lambda: self.bridge.projects.manage())
        browser.restore_requested.connect(lambda: self.restore(mode))
        browser.delete_requested.connect(lambda identifiers: self.remove(mode, identifiers))
        browser.recover_requested.connect(lambda: self.recover(mode))
        browser.refresh()

    def _cancel_selection(self, mode):
        if mode == self.bridge._current_mode:
            self._selection += 1

    def restore(self, mode):
        self._displayed.pop(mode, None)
        self._selection += 1
        self.overlay.reset(mode)
        if self.bridge._current_mode != mode:
            return
        workspace = self.bridge.shell._stack.currentWidget()
        viewer = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
        had_preview = viewer._database_cloud is not None
        if had_preview:
            viewer.show_database_frame(None)
        browser = self.browsers.get(mode)
        if browser:
            browser.details.setText('临时工作区 · 请主动保存会话')
            browser.tree.setToolTip(browser.details.text())
            browser.tree.blockSignals(True)
            browser.tree.setCurrentItem(None)
            browser.tree.clearSelection()
            browser.tree.blockSignals(False)
            browser._selection_changed()
        if (had_preview or mode in self._preview_modes) and hasattr(workspace, '_industrial'):
            workspace._industrial.restore_business_image()
        self._preview_modes.discard(mode)

    def select(self, mode, uid, component='frame'):
        bridge = self.bridge
        if self.overlay.active(mode) and component != 'image':
            if component == 'cloud' or self.databases[mode].records[uid].kind == 'result':
                return
            component = 'image'
        if not bridge.can_change_workspace():
            bridge.shell.log('正在处理数据，请完成后查看DB单帧。', 'warn')
            return
        self._selection += 1
        token = self._selection
        bridge.shell.show_loading('正在读取DB原始单帧...')
        def done(result, error):
            bridge.shell.hide_loading()
            if token != self._selection or bridge._current_mode != mode:
                return
            if error:
                bridge.shell.log('DB单帧读取失败：' + str(error), 'error')
                return
            frame, cloud = result
            self.display_frame(mode, uid, frame, cloud, component)
        bridge._run_background(lambda: self.databases[mode].load_frame(uid, component), done, name='db_frame_preview')

    def display_frame(self, mode, uid, frame, cloud, component='frame'):
        self._displayed[mode] = (uid, frame, component)
        self._preview_modes.add(mode)
        browser = self.browsers.get(mode)
        if browser:
            browser.show_frame(uid, frame, component)
            browser.tree.blockSignals(True)
            browser.tree.setCurrentItem(browser._component_items.get((uid, component)) if component != 'frame' else browser._items.get(uid))
            browser.tree.blockSignals(False)
            browser._selection_changed()
        workspace = self.bridge.shell._stack.currentWidget()
        viewer = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
        if component != 'image':
            viewer.show_database_frame(cloud)
            from ui_common.industrial_scene.marker_display import classify_markers
            display = classify_markers(frame.markers_all or frame.markers)
            viewer.set_cloud_markers(display.cloud_points()
                                    if self.databases[mode].records[uid].kind == 'raw' else [])
            viewer.reset_view()
        if component == 'cloud' or self.databases[mode].records[uid].kind == 'result':
            workspace._industrial.show_database_result()
        else:
            workspace._industrial.show_database_image(frame)
        record = self.databases[mode].records[uid]
        hint = (f'正在查看：{record.logical_name} · {record.points:,} 个有效点' if record.kind == 'result' else
                f'正在查看：原始帧 {record.frame_id:03d} · {record.points:,} 个槽位（含无效深度）')
        if component == 'image':
            hint = f'正在查看：帧 {record.frame_id:03d} 的2D图像 · {record.image_size[0]} × {record.image_size[1]}'
        elif component == 'cloud':
            hint += ' · 仅3D点云'
        self.bridge.shell._st_hint.setText(hint)
        self.bridge.shell._st_hint.setToolTip(hint)
        if mode == 'mobile_chain':
            self.bridge.stitching.update_mobile_actions()

    def remove(self, mode, identifiers):
        if not self.bridge.can_change_workspace() or mode != self.bridge._current_mode:
            self.bridge.shell.log('正在处理数据，请完成后删除DB数据。', 'warn')
            return
        if not identifiers:
            return
        answer = QMessageBox.question(self.bridge.shell, '删除 DB 数据',
            f'从DB移除选中的 {len(identifiers)} 项原始帧或拼接结果？原始帧的2D图像一并移除。\n'
            '数据移至项目回收区，可通过右键菜单恢复上次删除。\n'
            '当前标定和拼接工作流保持；退出拼接请使用机位删除功能。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._mutate(mode, lambda: self.databases[mode].remove(identifiers), '删除')

    def recover(self, mode):
        if self.bridge.can_change_workspace() and mode == self.bridge._current_mode:
            self._mutate(mode, self.databases[mode].restore_last_removal, '恢复')

    def _mutate(self, mode, work, verb):
        bridge = self.bridge
        previous_results = {uid for uid, row in self.databases[mode].records.items() if row.kind == 'result'}
        self.restore(mode)
        # Retarget only references into this DB. Imported source files and
        # independent station copies remain untouched.
        frames = self._frames()
        bridge.shell.show_loading(f'正在{verb}DB数据...')
        def done(moves, error):
            bridge.shell.hide_loading()
            if error:
                bridge.shell.log(f'DB{verb}失败：{error}', 'error')
                return
            self._finish_mutation(mode, moves, previous_results, frames)
            bridge.shell.log(f'已{verb} {len(moves)} 项DB数据。', 'success')
        bridge._run_background(work, done, name='db_mutation', must_finish=True)

    def _finish_mutation(self, mode, moves, previous_results, frames):
        """GUI completion shared by the main DB and the postprocess editor."""
        bridge = self.bridge
        for frame in frames:
            pair = moves.get(frame.database_id)
            if not pair:
                continue
            old, new = pair
            for attribute in ('offline_dir', 'offline_image_path', 'offline_pointmap_path'):
                value = getattr(frame, attribute)
                if value and Path(value).resolve().is_relative_to(old.resolve()):
                    setattr(frame, attribute, str(new / Path(value).resolve().relative_to(old.resolve())))
        self.browsers[mode].refresh()
        if previous_results - set(self.databases[mode].records):
            workspace = bridge.shell._stack.currentWidget()
            viewer = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
            viewer.clear_all()
            workspace._industrial.restore_business_image()

    def open_project(self, mode):
        if not self.bridge.can_change_workspace():
            return
        path, _ = QFileDialog.getOpenFileName(self.bridge.shell, '打开 DB 原始帧项目', str(DEFAULT_ROOT), 'DB 索引 (index.json)')
        if not path:
            return
        def done(result, error):
            if error:
                self.bridge.shell.log('DB项目打开失败：' + str(error), 'error')
            else:
                self.restore(mode)
                self.browsers[mode].refresh()
                self.bridge.shell.log('DB项目已打开，选择单帧可查看原始数据。', 'success')
        self.bridge._run_background(lambda: self.databases[mode].open_project(path), done, name='db_open_project')

    def _frames(self, result=None):
        bridge = self.bridge
        mode = bridge._current_mode
        found = []
        def visit(value):
            if isinstance(value, FrameData):
                found.append(value)
            elif isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)
        visit(result)
        if mode == 'multi_cam':
            found.extend(bridge.fixed_workflow.frames_calib.values())
            found.extend(bridge.fixed_workflow.frames_scan.values())
        elif mode == 'mobile_chain':
            manager = bridge.mobile_workflow.station_manager
            if manager:
                found.extend(manager.get_frames().values())
        elif mode == 'robot_stitch':
            found.extend(bridge.robot_workflow.frames)
        else:
            ws = bridge.shell.workspace_turntable()
            found.extend(f for f in (ws.current_frame0, ws.current_frame1, *ws.session.sequence) if f is not None)
        return found

    def archive_context(self, result=None):
        if self.bridge.shell._presentation != 'industrial':
            return
        database = self.databases[self.bridge._current_mode]
        for frame in self._frames(result):
            uid = getattr(frame, 'database_id', None)
            if uid not in database.records and uid not in database.removed and frame.has_pointcloud:
                database.ingest(frame, purpose={'calib': '标定数据', 'scan': '扫描数据'}.get(frame.kind, frame.kind or '导入数据'))

    def synchronize(self, result=None):
        """Refresh archive metadata before workflows release/replace frame objects."""
        bridge = self.bridge
        if bridge.shell._presentation != 'industrial':
            return
        mode = bridge._current_mode
        database = self.databases[mode]
        found = self._frames(result)
        active = bridge.mobile_workflow.station_manager.get_frames() if mode == 'mobile_chain' and bridge.mobile_workflow.station_manager else {}
        seen = set()
        for frame in found:
            uid = getattr(frame, 'database_id', None)
            if uid in seen or uid not in database.records:
                continue
            seen.add(uid)
            purpose = (database.records[uid].purpose if mode == 'robot_stitch'
                else {'calib': '标定数据', 'scan': '扫描数据'}.get(frame.kind, frame.kind))
            status = None
            if mode == 'mobile_chain':
                status = '已入链' if frame.camera_name in active else '未入链 / 原始帧已保留'
            database.annotate(frame, purpose=purpose, status=status)
        if mode == 'mobile_chain':
            active_ids = {frame.database_id for frame in active.values()}
            for row in database.snapshot()[1]:
                if row.status == '已入链' and row.uid not in active_ids:
                    database.set_status(row.uid, '原始帧保留 / 已退出拼接')
