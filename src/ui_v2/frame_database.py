"""New-UI frame archive controller and hierarchical browser."""
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QAbstractItemView, QMenu, QMessageBox)
from dataclasses import replace
from pathlib import Path

from core.frame_database import DEFAULT_ROOT
from core.frame_data import FrameData
from . import icons


class FrameBrowser(QWidget):
    frame_selected = Signal(str)
    open_requested = Signal()
    restore_requested = Signal()
    delete_requested = Signal(list)
    recover_requested = Signal()
    manage_requested = Signal()

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        self.setObjectName('frameDatabaseBrowser')
        self.setStyleSheet('''
            QWidget#frameDatabaseBrowser QTreeWidget { background:#252525; border:1px solid #454545; }
            QWidget#frameDatabaseBrowser QTreeWidget::item { min-height:22px; }
            QWidget#frameDatabaseBrowser QTreeWidget::item:selected { background:#573232; color:#ffffff; }
        ''')
        self.setMinimumHeight(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(5)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('DB / 项目数据'))
        bar.addStretch()
        self.count = QLabel('0 帧')
        bar.addWidget(self.count)
        self.delete_button = QPushButton('删除')
        self.delete_button.setToolTip('删除选中原始帧、拼接结果或整批数据（可在右键菜单恢复）')
        self.delete_button.clicked.connect(self.delete_selected)
        bar.addWidget(self.delete_button)
        layout.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['单帧 / 对应数据', '点数'])
        self.tree.setIndentation(14)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setMinimumHeight(180)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.currentItemChanged.connect(self._selected)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._update_delete_button)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree, 1)
        self.details = QLabel('临时工作区 · 请主动保存会话')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.open_button = QPushButton('打开 DB 项目')
        self.open_button.clicked.connect(self.open_requested)
        actions.addWidget(self.open_button)
        self.restore_button = QPushButton('返回工作视图')
        self.restore_button.clicked.connect(self.restore_requested)
        actions.addWidget(self.restore_button)
        layout.addLayout(actions)
        self.manage_button = QPushButton('会话占用 / 管理')
        self.manage_button.clicked.connect(self.manage_requested)
        layout.addWidget(self.manage_button)
        self._items = {}
        self.refresh()

    def refresh(self):
        selected = {item.data(0, Qt.UserRole) for item in self.tree.selectedItems()}
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
        sessions, records = self.database.snapshot()
        results = sum(record.kind == 'result' for record in records)
        count_text = f'{len(records)-results} 帧' + (f' / {results} 结果' if results else '')
        groups = {}
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
            title = record.logical_name if record.kind == 'result' else f'帧 {record.frame_id:04d}'
            if self.database.mode == 'multi_cam' and record.kind == 'raw':
                title += ' · ' + record.camera
            row = QTreeWidgetItem(groups[session_key], [title, f'{record.points:,}' if record.points is not None else '—'])
            row.setData(0, Qt.UserRole, record.uid)
            row.setToolTip(0, f'{record.camera} · {record.purpose} · {record.logical_name}\n{record.status}\n'
                f'原始PLY + 2D PNG（{record.image_size[0]} × {record.image_size[1]}）\n'
                '原始相机坐标；选择后在右侧查看2D / 3D。\n' + record.created)
            row.setIcon(0, icons.icon('layers', '#bbbbbb', 16))
            row.setToolTip(1, '原始点槽位数，包含有序点云中的无效占位点；文件不下采样。')
            if record.kind == 'result':
                row.setIcon(0, icons.icon('stitch', '#d65050', 16))
                row.setToolTip(0, '独立拼接结果 · mm\n来源帧：' + '\n'.join(record.source_ids) + '\n' + record.created)
                row.setToolTip(1, '拼接结果点数；原始帧保持独立。')
            self._items[record.uid] = row
        def restore(item, key=''):
            key += '/' + item.text(0)
            if item.childCount():
                item.setExpanded(key in expanded or key not in self._known_groups)
            for i in range(item.childCount()):
                restore(item.child(i), key)
        self._known_groups = getattr(self, '_known_groups', set())
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            restore(item)
            self._known_groups.add('/' + item.text(0))
        for uid in selected:
            if uid in self._items:
                self._items[uid].setSelected(True)
        self.tree.blockSignals(False)
        self.count.setText(count_text)
        self._update_delete_button()

    def selected_ids(self):
        identifiers = set()
        for item in self.tree.selectedItems():
            uid = item.data(0, Qt.UserRole)
            if uid:
                identifiers.add(uid)
            else:
                for i in range(item.childCount()):
                    identifiers.add(item.child(i).data(0, Qt.UserRole))
        return [uid for uid in self.database.records if uid in identifiers]

    def _update_delete_button(self):
        self.delete_button.setEnabled(bool(self.selected_ids()))

    def delete_selected(self):
        identifiers = self.selected_ids()
        if identifiers:
            self.delete_requested.emit(identifiers)

    def _context_menu(self, position):
        item = self.tree.itemAt(position)
        if item and not item.isSelected():
            # A context click selects the deletion target without starting a
            # large PLY preview that would immediately make deletion busy.
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item)
            self.tree.blockSignals(False)
            self._update_delete_button()
        menu = QMenu(self)
        if item and item.data(0, Qt.UserRole):
            menu.addAction('查看2D / 3D', lambda: self.frame_selected.emit(item.data(0, Qt.UserRole)))
        action = menu.addAction('删除选中数据', self.delete_selected)
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
        if item and item.data(0, Qt.UserRole):
            self.frame_selected.emit(item.data(0, Qt.UserRole))

    def show_frame(self, uid, frame):
        row = self.database.records[uid]
        if row.kind == 'result':
            self.details.setText(f'{row.logical_name} · {row.points:,} 点\n来源 {len(row.source_ids)} 帧 · 独立结果，原始数据保留')
            return
        self.details.setText(f'{row.logical_name} · {row.status}\n原始PLY + 2D PNG · 在右侧联动查看')


class FrameDatabaseController(QObject):
    changed = Signal(str)

    def __init__(self, bridge):
        super().__init__(bridge)
        self.bridge = bridge
        self.databases = bridge.shell._frame_databases
        self.browsers = {}
        self._selection = 0
        for mode, database in self.databases.items():
            database.on_changed = lambda key=mode: self.changed.emit(key)
        self.changed.connect(self._changed)

    def ingest(self, mode, frame, **kwargs):
        return self.databases[mode].ingest(frame, **kwargs)

    def capture(self, frame):
        manager = self.bridge.mobile_workflow.station_manager
        if self.bridge.shell._presentation != 'industrial' and not (
                self.bridge._current_mode == 'mobile_chain' and manager and manager.managed_frames):
            return
        mode = self.bridge._current_mode
        purpose = '移动机位' if mode == 'mobile_chain' else '转台采集' if mode == 'turntable' else (
            '扫描数据' if self.bridge.fixed_workflow.is_calibration_locked else '标定数据')
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
        if hasattr(self.bridge.shell, '_industrial_ribbon'):
            self.bridge.shell._industrial_ribbon.update_status()

    def bind(self, mode, browser):
        if mode in self.browsers:
            return
        self.browsers[mode] = browser
        browser.frame_selected.connect(lambda uid: self.select(mode, uid))
        browser.open_button.setText('打开会话')
        browser.open_requested.connect(self.bridge._on_open_session)
        browser.manage_requested.connect(lambda: self.bridge.projects.manage())
        browser.restore_requested.connect(lambda: self.restore(mode))
        browser.delete_requested.connect(lambda identifiers: self.remove(mode, identifiers))
        browser.recover_requested.connect(lambda: self.recover(mode))
        browser.refresh()

    def restore(self, mode):
        self._selection += 1
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
            browser.tree.blockSignals(True)
            browser.tree.setCurrentItem(None)
            browser.tree.clearSelection()
            browser.tree.blockSignals(False)
            browser._update_delete_button()
        if had_preview and hasattr(workspace, '_industrial'):
            workspace._industrial.restore_business_image()

    def select(self, mode, uid):
        bridge = self.bridge
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
            self.display_frame(mode, uid, frame, cloud)
            bridge.shell.log('已显示DB选中数据。', 'info')
        bridge._run_background(lambda: self.databases[mode].load_frame(uid), done, name='db_frame_preview')

    def display_frame(self, mode, uid, frame, cloud):
        browser = self.browsers.get(mode)
        if browser:
            browser.show_frame(uid, frame)
            browser.tree.blockSignals(True)
            browser.tree.setCurrentItem(browser._items.get(uid))
            browser.tree.blockSignals(False)
        workspace = self.bridge.shell._stack.currentWidget()
        viewer = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
        viewer.show_database_frame(cloud)
        if self.databases[mode].records[uid].kind == 'result':
            workspace._industrial.show_database_result()
        else:
            workspace._industrial.show_database_image(frame)
        viewer.reset_view()

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
            bridge.shell.log(f'已{verb} {len(moves)} 项DB数据。', 'success')
        bridge._run_background(work, done, name='db_mutation', must_finish=True)

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
            purpose = {'calib': '标定数据', 'scan': '扫描数据'}.get(frame.kind, frame.kind)
            status = None
            if mode == 'mobile_chain':
                status = '已入链' if frame.camera_name in active else '未入链 / 原始帧已保留'
            database.annotate(frame, purpose=purpose, status=status)
        if mode == 'mobile_chain':
            active_ids = {frame.database_id for frame in active.values()}
            for row in database.snapshot()[1]:
                if row.status == '已入链' and row.uid not in active_ids:
                    database.set_status(row.uid, '原始帧保留 / 已退出拼接')
