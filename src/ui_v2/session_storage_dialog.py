"""Visible disk accounting and explicit, scoped session cleanup."""
from pathlib import Path
import json
import shutil
import os
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, QItemSelectionModel
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QCheckBox, QHeaderView)
from .dialogs import ChineseMessageBox as QMessageBox
from .launcher_dialog import LauncherDialog
from core.session_project import PROJECT_ROOT, disk_usage


def human_size(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


class _SessionTable(QTableWidget):
    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and index.isValid() and index.column() == 0:
            item = self.item(index.row(), 0)
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.indexAt(event.position().toPoint()).column() == 0:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class SessionStorageDialog(QDialog):
    def __init__(self, controller, mode, parent=None):
        super().__init__(parent)
        self.controller, self.mode = controller, mode
        self.project = controller.projects[mode]
        self.setWindowTitle('会话占用与管理')
        self.resize(960, 560)
        self.setMinimumSize(780, 460)
        self._syncing = False
        self._busy = False
        self.rows = []
        layout = QVBoxLayout(self)
        self.summary = QLabel('正在统计当前工作区、已保存会话和历史离线数据...')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        selection_bar = QHBoxLayout()
        self.select_all = QCheckBox('全选会话')
        self.select_all.setTristate(True)
        self.select_all.clicked.connect(self.toggle_all)
        selection_bar.addWidget(self.select_all)
        self.selection_count = QLabel('已选 0 / 0 项；可勾选多项，或使用 Ctrl / Shift 多选')
        selection_bar.addWidget(self.selection_count)
        selection_bar.addStretch(1)
        layout.addLayout(selection_bar)
        self.table = _SessionTable(0, 5)
        self.table.setHorizontalHeaderLabels(['选择', '已保存会话', '功能', '占用', '保存时间'])
        self.table.verticalHeader().hide()
        self.table.setCornerButtonEnabled(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setStyleSheet('QTableView {selection-background-color:#563030;selection-color:#ffffff;}'
                                 'QTableView::indicator {width:14px;height:14px;}')
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column, width in ((0, 48), (2, 130), (3, 100), (4, 185)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.sync_selection)
        self.table.itemChanged.connect(self.check_item)
        layout.addWidget(self.table, 1)
        note = QLabel('删除已保存会话为永久删除，当前已打开的会话受到保护。\n'
            '清空回收区只处理当前临时工作区中未被工作流引用的数据；保存后更新正式会话。\n'
            '历史离线数据按独立目录列出，可选中删除；当前工作流引用的目录受到保护。')
        note.setWordWrap(True)
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.refresh_button = QPushButton('刷新统计')
        self.refresh_button.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_button)
        self.purge_button = QPushButton('清空未引用回收区')
        self.purge_button.clicked.connect(self.purge)
        bar.addWidget(self.purge_button)
        self.delete_button = QPushButton('删除选中会话')
        self.delete_button.clicked.connect(self.delete)
        bar.addWidget(self.delete_button)
        self.folder_button = QPushButton('打开数据目录')
        self.folder_button.clicked.connect(self.open_folder)
        bar.addWidget(self.folder_button)
        layout.addLayout(bar)
        self.refresh()

    def open_folder(self):
        selected = self.selected_rows()
        path = self.rows[selected[0]][0].resolve() if selected else None
        try:
            if path is not None:
                if not path.is_dir():
                    raise FileNotFoundError('所选目录已不存在，请刷新列表后重试')
            else:
                # Historical captures are not stored in the new snapshot root.
                legacy = (PROJECT_ROOT / 'offline_data').resolve()
                has_saved = any(info['kind'] == 'project' for _, info, _ in self.rows)
                path = legacy if not has_saved and legacy.is_dir() else self.project.save_root.resolve()
                path.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                os.startfile(str(path))
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise OSError('系统未能打开文件管理器')
        except OSError as error:
            QMessageBox.warning(self, '打开存储目录失败', f'无法打开：{path}\n{error}')
            self.refresh()

    def toggle_all(self):
        if self.select_all.checkState() == Qt.Unchecked:
            self.table.clearSelection()
        else:
            self.table.selectAll()

    def selected_rows(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows())

    def check_item(self, item):
        if self._syncing or item.column() != 0:
            return
        flag = QItemSelectionModel.Select if item.checkState() == Qt.Checked else QItemSelectionModel.Deselect
        self.table.selectionModel().select(self.table.model().index(item.row(), 0), flag | QItemSelectionModel.Rows)

    def sync_selection(self):
        if self._syncing:
            return
        self._syncing = True
        selected = set(self.selected_rows())
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item:
                item.setCheckState(Qt.Checked if i in selected else Qt.Unchecked)
        total = len(self.rows)
        self.select_all.blockSignals(True)
        self.select_all.setCheckState(Qt.Unchecked if not selected else
                                     Qt.Checked if len(selected) == total else Qt.PartiallyChecked)
        self.select_all.blockSignals(False)
        self.selection_count.setText(f'已选 {len(selected)} / {total} 项；可勾选多项，或使用 Ctrl / Shift 多选')
        self.delete_button.setText(f'删除选中会话（{len(selected)}）')
        self.delete_button.setEnabled(not self._busy and bool(selected))
        self.folder_button.setText('打开选中目录' if selected else '打开数据目录')
        self._syncing = False

    def busy(self, value):
        self._busy = value
        for button in (self.refresh_button, self.purge_button, self.folder_button, self.select_all, self.table):
            button.setEnabled(not value)
        self.sync_selection()

    def refresh(self):
        selected_paths = {self.rows[i][0] for i in self.selected_rows()}
        self.busy(True)
        root = self.project.save_root
        def work():
            rows = []
            if root.exists():
                for path in root.iterdir():
                    if not path.is_dir() or path.is_symlink() or path.name.startswith('.'):
                        continue
                    try:
                        info = json.loads((path / 'session.json').read_text(encoding='utf-8'))
                        if info.get('format') != 'MCC_SESSION':
                            continue
                        rows.append((path, dict(info, kind='project'), disk_usage(path)))
                    except (OSError, ValueError):
                        continue
            legacy = PROJECT_ROOT / 'offline_data'
            for folder, pattern, label in ((legacy, 'session_*', '历史会话'),
                    (legacy / 'stations', 'session_*', '历史机位'),
                    (legacy / 'preview_sessions', 'stool_*', '离线预览缓存'),
                    (legacy / 'frame_db', '*', '历史DB')):
                if not folder.exists():
                    continue
                for path in folder.glob(pattern):
                    if not path.is_dir() or path.is_symlink():
                        continue
                    if not ((path / 'index.json').exists() or (path / 'meta.json').exists() or
                            (label == '离线预览缓存' and any(path.glob('station_*')))):
                        continue
                    info = dict(kind='legacy', name=path.name, mode=label, saved='',
                                id=path.stat().st_ctime_ns, root=str(folder.resolve()))
                    rows.append((path, info, disk_usage(path)))
            return rows, disk_usage(self.project.directory), disk_usage(PROJECT_ROOT / 'offline_data')
        def done(result, error):
            self.busy(False)
            if error:
                self.summary.setText('统计失败：' + str(error))
                return
            self.rows, current, legacy = result
            self.summary.setText(f'当前工作区：{human_size(current["bytes"])}，回收区 {human_size(current["trash_bytes"])}\n'
                f'已保存会话：{human_size(sum(row[2]["bytes"] for row in self.rows if row[1]["kind"] == "project"))}；'
                f'历史 offline_data：{human_size(legacy["bytes"])}\n'
                f'新格式会话目录：{root}\n历史数据目录：{PROJECT_ROOT / "offline_data"}')
            self._syncing = True
            self.table.clearSelection()
            self.table.setRowCount(len(self.rows))
            for i, (path, info, usage) in enumerate(self.rows):
                saved = info.get('saved')
                try:
                    timestamp = datetime.fromisoformat(saved) if saved else datetime.fromtimestamp(path.stat().st_mtime)
                    saved_text = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    if not saved:
                        saved_text += '（修改）'
                except (OSError, ValueError):
                    saved_text = '—'
                mode_name = LauncherDialog.MODE_NAMES.get(info['mode'], info['mode'])
                for j, text in enumerate(('', info['name'], mode_name, human_size(usage['bytes']), saved_text)):
                    item = QTableWidgetItem(text)
                    item.setToolTip(str(path))
                    if j == 0:
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                        item.setCheckState(Qt.Unchecked)
                    self.table.setItem(i, j, item)
                if path in selected_paths:
                    self.table.selectionModel().select(self.table.model().index(i, 0),
                        QItemSelectionModel.Select | QItemSelectionModel.Rows)
            self._syncing = False
            self.sync_selection()
        self.controller.bridge._run_background(work, done, name='project_stats')

    def purge(self):
        if not self.controller._available():
            return
        answer = QMessageBox.question(self, '永久清空回收区',
            '永久删除当前回收区中未被标定/拼接引用的原始帧和2D图像？此操作不能恢复。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        protected = {frame.database_id for frame in self.controller.bridge.frame_db._frames()}
        self.busy(True)
        def done(count, error):
            self.busy(False)
            if error:
                self.summary.setText('清理失败：' + str(error))
            else:
                self.controller.mark_changed(self.mode)
                self.refresh()
        self.controller.bridge._run_background(
            lambda: self.project.database.purge_removed(protected), done, name='project_purge', must_finish=True)

    def delete(self):
        if not self.controller._available():
            return
        indices = self.selected_rows()
        if not indices:
            return
        targets = [self.rows[i][0] for i in indices]
        protected = {p.saved_path.resolve() for p in self.controller.projects.values() if p.saved_path}
        bridge = self.controller.bridge
        frames = list(bridge.fixed_workflow.frames_calib.values()) + list(bridge.fixed_workflow.frames_scan.values())
        if bridge.mobile_workflow.station_manager:
            frames += list(bridge.mobile_workflow.station_manager.get_frames().values())
        turn = bridge.shell.workspace_turntable()
        frames += [frame for frame in (turn.current_frame0, turn.current_frame1, *turn.session.sequence) if frame]
        frames += list(bridge.robot_workflow.frames)
        for frame in frames:
            for path in (frame.offline_pointmap_path, frame.offline_image_path):
                if path:
                    protected.add(Path(path).resolve())
        if any(any(dependency.is_relative_to(path.resolve()) for dependency in protected) for path in targets):
            QMessageBox.information(self, '会话正在使用', '所选会话当前已打开，请先新建或打开其他会话。')
            return
        if QMessageBox.question(self, '永久删除会话', f'永久删除选中的 {len(targets)} 个已保存会话及全部数据？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        root = self.project.save_root.resolve()
        expected = {path: info for path, info, usage in self.rows if path in targets}
        def work():
            existing = []
            for path in targets:
                entry = expected[path]
                allowed = root if entry['kind'] == 'project' else Path(entry['root'])
                if path.is_symlink() or path.resolve().parent != allowed:
                    raise ValueError('删除目标超出会话根目录')
                if not path.exists():
                    continue  # Removed since the statistics snapshot; do not recreate it.
                if entry['kind'] == 'project':
                    info = json.loads((path / 'session.json').read_text(encoding='utf-8'))
                    if info.get('format') != 'MCC_SESSION' or info.get('id') != entry['id']:
                        raise ValueError('会话已变化，请刷新后重试')
                elif path.stat().st_ctime_ns != entry['id'] or not allowed.is_relative_to((PROJECT_ROOT / 'offline_data').resolve()):
                    raise ValueError('历史目录已变化，请刷新后重试')
                existing.append(path)
            for path in existing:
                try:
                    shutil.rmtree(path)
                except FileNotFoundError:
                    if path.exists():
                        raise
        self.busy(True)
        def done(result, error):
            self.busy(False)
            self.refresh()
            if error:
                QMessageBox.warning(self, '删除会话失败', '部分目录可能已删除，列表已刷新。\n' + str(error))
        self.controller.bridge._run_background(work, done, name='project_delete', must_finish=True)
