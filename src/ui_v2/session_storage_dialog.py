"""Visible disk accounting and explicit, scoped session cleanup."""
from pathlib import Path
import json
import shutil

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)
from core.session_project import PROJECT_ROOT, disk_usage


def human_size(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


class SessionStorageDialog(QDialog):
    def __init__(self, controller, mode, parent=None):
        super().__init__(parent)
        self.controller, self.mode = controller, mode
        self.project = controller.projects[mode]
        self.setWindowTitle('会话占用与管理')
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        self.summary = QLabel('正在统计当前工作区、已保存会话和历史离线数据...')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['已保存会话', '功能', '占用', '保存时间'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
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
        folder = QPushButton('打开存储目录')
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.save_root))))
        bar.addWidget(folder)
        layout.addLayout(bar)
        self.rows = []
        self.refresh()

    def busy(self, value):
        for button in (self.refresh_button, self.purge_button, self.delete_button):
            button.setEnabled(not value)

    def refresh(self):
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
                f'历史 offline_data：{human_size(legacy["bytes"])}\n存储根目录：{root}')
            self.table.setRowCount(len(self.rows))
            for i, (path, info, usage) in enumerate(self.rows):
                for j, text in enumerate((info['name'], info['mode'], human_size(usage['bytes']), info.get('saved', ''))):
                    item = QTableWidgetItem(text)
                    item.setToolTip(str(path))
                    self.table.setItem(i, j, item)
            self.table.resizeColumnsToContents()
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
        indices = sorted({item.row() for item in self.table.selectedItems()})
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
            for path in targets:
                entry = expected[path]
                allowed = root if entry['kind'] == 'project' else Path(entry['root'])
                if path.is_symlink() or path.resolve().parent != allowed:
                    raise ValueError('删除目标超出会话根目录')
                if entry['kind'] == 'project':
                    info = json.loads((path / 'session.json').read_text(encoding='utf-8'))
                    if info.get('format') != 'MCC_SESSION' or info.get('id') != entry['id']:
                        raise ValueError('会话已变化，请刷新后重试')
                elif path.stat().st_ctime_ns != entry['id'] or not allowed.is_relative_to((PROJECT_ROOT / 'offline_data').resolve()):
                    raise ValueError('历史目录已变化，请刷新后重试')
            for path in targets:
                shutil.rmtree(path)
        self.busy(True)
        def done(result, error):
            self.busy(False)
            if error:
                self.summary.setText('删除失败：' + str(error))
            else:
                self.refresh()
        self.controller.bridge._run_background(work, done, name='project_delete', must_finish=True)
