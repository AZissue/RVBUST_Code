"""New-UI frame archive controller and hierarchical browser."""
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from dataclasses import replace

from core.frame_database import FrameDatabase, DEFAULT_ROOT
from core.frame_data import FrameData
from ui_common.image_preview import numpy_to_qpixmap, AspectRatioLabel
from . import icons


class FrameBrowser(QWidget):
    frame_selected = Signal(str)
    open_requested = Signal()
    restore_requested = Signal()

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
        layout.addWidget(self.tree, 1)
        self.details = QLabel('原始帧自动保存 · 选择单帧联动2D / 3D')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.image = AspectRatioLabel()
        self.image.setMinimumHeight(90)
        self.image.setMaximumHeight(110)
        self.image.hide()
        layout.addWidget(self.image)
        actions = QHBoxLayout()
        self.open_button = QPushButton('打开 DB 项目')
        self.open_button.clicked.connect(self.open_requested)
        actions.addWidget(self.open_button)
        self.restore_button = QPushButton('返回工作视图')
        self.restore_button.clicked.connect(self.restore_requested)
        actions.addWidget(self.restore_button)
        layout.addLayout(actions)
        self._items = {}
        self.refresh()

    def refresh(self):
        current = self.tree.currentItem()
        selected = current.data(0, Qt.UserRole) if current else None
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
        root = QTreeWidgetItem(self.tree, ['原始采集数据', ''])
        root.setIcon(0, icons.icon('folder_open', '#bbbbbb', 16))
        groups = {}
        for record in records:
            session = sessions[record.session_id]
            session_key = record.session_id
            if session_key not in groups:
                groups[session_key] = QTreeWidgetItem(root, [session['title'] + ' · ' + session['created'][11:], ''])
                groups[session_key].setToolTip(0, session['created'])
                groups[session_key].setIcon(0, icons.icon('folder_open', '#bbbbbb', 16))
            key = (record.session_id, record.purpose)
            if key not in groups:
                groups[key] = QTreeWidgetItem(groups[session_key], [record.purpose, ''])
            camera_key = (*key, record.camera)
            if camera_key not in groups:
                groups[camera_key] = QTreeWidgetItem(groups[key], [record.camera, ''])
                groups[camera_key].setIcon(0, icons.icon('camera', '#bbbbbb', 16))
            title = f'帧 {record.frame_id:04d}'
            row = QTreeWidgetItem(groups[camera_key], [title, f'{record.points:,}' if record.points is not None else '—'])
            row.setData(0, Qt.UserRole, record.uid)
            row.setToolTip(0, record.logical_name + ' · ' + record.status + '\n原始相机坐标；查看不改变拼接输入。\n' + record.created)
            row.setIcon(0, icons.icon('layers', '#bbbbbb', 16))
            row.setToolTip(1, '原始点槽位数，包含有序点云中的无效占位点；文件不下采样。')
            cloud = QTreeWidgetItem(row, ['点云 · 原始 PLY', ''])
            image = QTreeWidgetItem(row, [f'2D 图像 · {record.image_size[0]} × {record.image_size[1]}', ''])
            cloud.setIcon(0, icons.icon('layers', '#bbbbbb', 16))
            image.setIcon(0, icons.icon('camera', '#bbbbbb', 16))
            cloud.setData(0, Qt.UserRole, record.uid)
            image.setData(0, Qt.UserRole, record.uid)
            self._items[record.uid] = row
        root.setExpanded(True)
        def restore(item, key=''):
            key += '/' + item.text(0)
            if item.childCount():
                item.setExpanded(key in expanded or item.data(0, Qt.UserRole) is None)
            for i in range(item.childCount()):
                restore(item.child(i), key)
        restore(root)
        if selected in self._items:
            self.tree.setCurrentItem(self._items[selected])
        self.tree.blockSignals(False)
        self.count.setText(f'{len(records)} 帧')

    def _selected(self, item, previous):
        if item and item.data(0, Qt.UserRole):
            self.frame_selected.emit(item.data(0, Qt.UserRole))

    def show_frame(self, uid, frame):
        row = self.database.records[uid]
        self.image.setPixmap(numpy_to_qpixmap(frame.image_np))
        self.image.show()
        self.setMinimumHeight(380)
        self.details.setText(f'{row.logical_name} · {row.status}\n原始相机坐标 / mm；点云和2D图像为同一次拍摄。')


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
        if self.bridge.shell._presentation != 'industrial':
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
        browser = self.browsers.get(mode)
        if browser:
            browser.refresh()

    def bind(self, mode, browser):
        if mode in self.browsers:
            return
        self.browsers[mode] = browser
        browser.frame_selected.connect(lambda uid: self.select(mode, uid))
        browser.open_requested.connect(lambda: self.open_project(mode))
        browser.restore_requested.connect(lambda: self.restore(mode))
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
            browser.image.hide()
            browser.setMinimumHeight(280)
            browser.details.setText('原始帧自动保存 · 选择单帧联动2D / 3D')
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
            self.browsers[mode].show_frame(uid, frame)
            workspace = bridge.shell._stack.currentWidget()
            viewer = workspace.viewer() if callable(workspace.viewer) else workspace.viewer
            viewer.show_database_frame(cloud)
            workspace._industrial.show_database_image(frame)
            viewer.reset_view()
            bridge.shell.log('正在查看DB原始单帧；返回工作视图可继续查看拼接结果。', 'info')
        bridge._run_background(lambda: self.databases[mode].load_frame(uid), done, name='db_frame_preview')

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
            if getattr(frame, 'database_id', None) not in database.records and frame.has_pointcloud:
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
