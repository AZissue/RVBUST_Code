"""Industrial standalone offline-stitch prototype window."""
from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))

from offline_workflow import (
    OfflineWorkflow, load_preview_cloud, preview_markers,
)
from ui_common.image_preview import AspectRatioLabel, numpy_to_qpixmap
from ui_common.worker_thread import WorkerThread
from ui_v2 import icons as ui_icons
from ui_v2.theme import (
    ACCENT_DIM, BG_PANEL, BORDER, STATUS_ERR,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)
from ui_v2.widgets.floating_log_panel import FloatingLogPanel
from ui_v2.widgets.loading_overlay import LoadingOverlay
from ui_v2.widgets.viewer_panel import ViewerPanel


class OfflineStitchWindow(QMainWindow):
    def __init__(self, detector=None):
        super().__init__()
        self.workflow = OfflineWorkflow(detector=detector)
        self.pairs = []
        self._busy = False
        self._worker = None
        self._preview_generation = 0
        self._initial_preview_pending = False
        self._closing = False
        self.setWindowTitle('MCC · 离线拼接 · 工业原型')
        self.resize(1440, 900)
        self.setMinimumSize(1000, 650)
        self._build_ui()
        self._center_on_screen()
        self._refresh_controls()
        self.log('离线原型就绪；请选择 PNG/PLY 文件目录或加载凳子示例。')

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.viewer = ViewerPanel('3D 离线拼接预览')
        self.viewer.set_industrial(True)
        self.viewer.viewer_message.connect(self.log)
        root.addWidget(self._build_header())
        root.addWidget(self._build_ribbon())

        self.content_split = QSplitter(Qt.Vertical)
        self.content_split.setChildrenCollapsible(False)
        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_frame_panel())
        body.addWidget(self.viewer)
        body.addWidget(self._build_preview_panel())
        body.setStretchFactor(1, 1)
        body.setSizes([280, 850, 310])
        self.content_split.addWidget(body)
        self.log_panel = FloatingLogPanel(self, docked=True)
        self.log_panel.setMinimumHeight(110)
        self.content_split.addWidget(self.log_panel)
        self.content_split.setSizes([680, 170])
        root.addWidget(self.content_split, 1)

        self.status = QLabel('就绪')
        self.status.setStyleSheet(
            f'background:{BG_PANEL};color:{TEXT_SECONDARY};padding:6px 10px;'
            f'border-top:1px solid {BORDER};')
        root.addWidget(self.status)
        self.overlay = LoadingOverlay(central)
        self.overlay.hide()

    def _build_header(self):
        bar = QFrame()
        bar.setStyleSheet(f'background:{BG_PANEL};border-bottom:1px solid {BORDER};')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        logo = QLabel('MCC')
        logo.setStyleSheet('background:#b93638;color:white;font-size:17px;font-weight:800;'
                           'padding:4px 9px;border-radius:5px;')
        layout.addWidget(logo)
        layout.addWidget(QLabel('SCAN STUDIO'))
        title = QLabel('离线拼接 · 工业原型')
        title.setStyleSheet(f'color:{TEXT_PRIMARY};font-size:15px;font-weight:600;')
        layout.addWidget(title)
        layout.addStretch(1)
        badge = QLabel('OFFLINE PROTOTYPE')
        badge.setStyleSheet(f'background:{ACCENT_DIM};color:{TEXT_SECONDARY};'
                            'padding:5px 10px;border-radius:10px;')
        layout.addWidget(badge)
        help_button = QPushButton('说明')
        ui_icons.apply(help_button, 'help', TEXT_SECONDARY, 15)
        help_button.clicked.connect(self._show_help)
        layout.addWidget(help_button)
        return bar

    def _build_ribbon(self):
        bar = QFrame()
        bar.setStyleSheet(f'background:{BG_PANEL};border-bottom:1px solid {BORDER};')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)
        self.btn_directory = self._ribbon_button(bar, layout, '选择目录', 'folder_open', self.select_directory)
        self.btn_stool = self._ribbon_button(bar, layout, '加载凳子', 'layers', self.load_stool)
        self.btn_stitch = self._ribbon_button(bar, layout, '开始拼接', 'stitch', self.start_stitch, primary=True)
        self.btn_export = self._ribbon_button(bar, layout, '导出 PLY', 'save', self.export_merged)
        self.btn_clear = self._ribbon_button(bar, layout, '清空项目', 'trash', self.clear_project)
        self.btn_fit = self._ribbon_button(bar, layout, '适配视图', 'reset_view', self.viewer.reset_view)
        layout.addStretch(1)
        return bar

    def _ribbon_button(self, parent, layout, text, glyph, callback, primary=False):
        button = QPushButton(text)
        button.setMinimumHeight(34)
        ui_icons.apply(button, glyph, TEXT_SECONDARY, 16)
        if primary:
            button.setObjectName('primary')
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _build_frame_panel(self):
        panel = QGroupBox('离线帧 / 拼接状态')
        layout = QVBoxLayout(panel)
        self.directory_label = QLabel('未选择数据目录')
        self.directory_label.setWordWrap(True)
        self.directory_label.setStyleSheet(f'color:{TEXT_MUTED};')
        layout.addWidget(self.directory_label)
        self.recursive = QCheckBox('递归扫描子目录')
        self.recursive.setChecked(True)
        layout.addWidget(self.recursive)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['帧', '状态'])
        self.tree.setColumnWidth(0, 180)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.currentItemChanged.connect(self._on_frame_selected)
        layout.addWidget(self.tree, 1)
        self.summary = QLabel('0 帧')
        self.summary.setStyleSheet(f'color:{TEXT_SECONDARY};')
        layout.addWidget(self.summary)
        return panel

    def _build_preview_panel(self):
        panel = QGroupBox('当前帧 · 2D 与编码圆')
        panel.setMinimumWidth(270)
        panel.setMaximumWidth(390)
        layout = QVBoxLayout(panel)
        self.preview = AspectRatioLabel(ratio=4 / 3)
        self.preview.setMinimumSize(250, 200)
        layout.addWidget(self.preview, 1)
        self.preview_info = QLabel('选择左侧帧查看原始数据')
        self.preview_info.setWordWrap(True)
        self.preview_info.setStyleSheet(f'color:{TEXT_SECONDARY};')
        layout.addWidget(self.preview_info)
        return panel

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.x() + (area.width() - self.width()) // 2,
                      area.y() + (area.height() - self.height()) // 2)

    def log(self, text, level='info'):
        self.log_panel.append(str(text), level)
        self.status.setText(str(text))
        self.status.setStyleSheet(
            f'background:{BG_PANEL};color:{STATUS_ERR if level == "error" else TEXT_SECONDARY};'
            f'padding:6px 10px;border-top:1px solid {BORDER};')

    def _refresh_controls(self):
        has_pairs = bool(self.pairs)
        has_result = bool(self.workflow.last_result and self.workflow.last_result.ok)
        for button in (self.btn_directory, self.btn_stool, self.btn_clear):
            button.setEnabled(not self._busy)
        self.recursive.setEnabled(not self._busy)
        self.tree.setEnabled(not self._busy)
        self.btn_stitch.setEnabled(has_pairs and not self._busy)
        self.btn_export.setEnabled(has_result and not self._busy)
        self.btn_fit.setEnabled(True)

    def _run(self, work, done, message):
        if self._closing:
            return None
        if self._busy:
            self.log('当前任务进行中，请稍候。', 'warn')
            return None
        self._busy = True
        self._refresh_controls()
        self.overlay.show_message(message)
        worker = WorkerThread(work)
        self._worker = worker

        def result_ready(result, error):
            if self._closing:
                return
            try:
                done(result, error)
            except Exception as exc:
                self.log(f'界面回填失败：{exc}', 'error')

        def finished():
            self.overlay.hide_overlay()
            self._busy = False
            self._worker = None
            worker.deleteLater()
            self._refresh_controls()
            if self._initial_preview_pending:
                self._initial_preview_pending = False
                self._on_frame_selected(self.tree.currentItem())

        worker.result_ready.connect(result_ready)
        worker.finished.connect(finished)
        worker.start()
        return worker

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, '选择离线图像与点云目录')
        if directory:
            self.load_directory(directory)

    def load_directory(self, directory):
        def work():
            return self.workflow.load_directory(directory, self.recursive.isChecked())

        def done(pairs, error):
            if error:
                self.log(f'目录读取失败：{error}', 'error')
                return
            self.directory_label.setText(directory)
            self.set_pairs(pairs)
            self.log(f'发现 {len(pairs)} 对图像/点云。' if pairs else
                     '未找到匹配的图像/点云文件对。', 'success' if pairs else 'warn')

        return self._run(work, done, '正在扫描离线文件...')

    def load_stool(self):
        def work():
            return self.workflow.load_stool()

        def done(pairs, error):
            if error:
                self.log(f'凳子数据读取失败：{error}', 'error')
                return
            self.directory_label.setText('项目内置凳子第 1、2 帧')
            self.set_pairs(pairs)
            self.log(f'已加载 {len(pairs)} 个凳子离线视角。', 'success')

        return self._run(work, done, '正在加载凳子离线数据...')

    def set_pairs(self, pairs):
        self.pairs = list(pairs)
        self.tree.clear()
        self.viewer.clear_all()
        self.preview.clear_image()
        for pair in self.pairs:
            item = QTreeWidgetItem([pair.name, '待拼接'])
            item.setData(0, Qt.UserRole, pair)
            self.tree.addTopLevelItem(item)
        self.summary.setText(f'{len(self.pairs)} 帧')
        self._refresh_controls()
        if self.pairs:
            self._initial_preview_pending = True
            QTimer.singleShot(0, lambda: self.tree.setCurrentItem(self.tree.topLevelItem(0)))

    def _on_frame_selected(self, current, previous=None):
        if current is None or self._busy or self._closing:
            return
        pair = current.data(0, Qt.UserRole)
        if pair not in self.pairs:
            return
        self._preview_generation += 1
        generation = self._preview_generation
        self.viewer.set_pointcloud('raw', None)
        self.preview.clear_image()
        self.preview_info.setText(f'正在读取 {pair.name}...')

        def work():
            frame = self.workflow.load_pair(pair)
            return load_preview_cloud(pair), frame

        def done(result, error):
            if generation != self._preview_generation:
                return
            if error:
                self.viewer.set_pointcloud('raw', None)
                self.preview.clear_image()
                self.preview_info.setText(f'{pair.name} 预览失败：{error}')
                self.log(f'{pair.name} 预览失败：{error}', 'error')
                return
            cloud, frame = result
            self.viewer.set_pointcloud('raw', cloud)
            self.viewer.set_pointcloud_merged(None)
            self.preview.setPixmap(numpy_to_qpixmap(frame.image_np))
            self.preview.set_markers(preview_markers(frame))
            self.preview_info.setText(f'{pair.name} · {len(cloud.points):,} 有效点 · '
                                      f'{len(frame.markers)} 个有效3D标记')
            self.viewer.reset_view()

        self._run(work, done, f'正在读取 {pair.name}...')

    def start_stitch(self):
        if not self.pairs:
            self.log('请先加载离线帧。', 'warn')
            return None
        self.workflow.last_result = None
        self.viewer.set_pointcloud_merged(None)
        self._refresh_controls()

        def work():
            return self.workflow.stitch(self.pairs)

        def done(result, error):
            if error:
                self.workflow.last_result = None
                self.viewer.set_pointcloud_merged(None)
                self.log(f'拼接失败：{error}', 'error')
                return
            for item_index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(item_index)
                pair = item.data(0, Qt.UserRole)
                ok, message = result.frame_results.get(pair.name, (False, '未处理'))
                item.setText(1, '已入链' if ok else '未入链')
                item.setToolTip(0, message)
            if result.cloud is not None:
                self.viewer.set_pointcloud_merged(result.cloud)
                self.viewer.reset_view()
            self.log(result.message, 'success' if result.ok else 'warn')

        return self._run(work, done, '正在检测、配准并拼接离线帧...')

    def export_merged(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, '导出合并点云', 'offline_merged.ply', 'PLY (*.ply)')
        if not path:
            return None

        def work():
            return self.workflow.export(path)

        def done(_, error):
            self.log(f'合并点云已导出：{path}' if not error else f'导出失败：{error}',
                     'success' if not error else 'error')

        return self._run(work, done, '正在原子写出合并点云...')

    def clear_project(self):
        if self._busy:
            self.log('当前任务进行中，不能清空项目。', 'warn')
            return
        self._preview_generation += 1
        self.pairs = []
        self.workflow.last_result = None
        self.tree.clear()
        self.viewer.clear_all()
        self.preview.clear_image()
        self.preview_info.setText('选择左侧帧查看原始数据')
        self.directory_label.setText('未选择数据目录')
        self.summary.setText('0 帧')
        self._refresh_controls()
        self.log('已清空离线项目。')

    def _show_help(self):
        QMessageBox.information(self, '离线拼接原型说明',
            '1. 选择包含同名 PNG/JPG 与 PLY 的目录，或加载项目凳子示例。\n'
            '2. 点击左侧帧查看原始 2D 标记与 3D 点云。\n'
            '3. 开始拼接后，真实 ChainStitcher 逐帧检测、配准并合并；失败帧会标明原因。\n'
            '4. 至少两个机位成功入链才允许导出 PLY。\n\n'
            '本原型不初始化相机 SDK，不并入主程序，也不修改主程序版本。')

    def closeEvent(self, event):
        self._closing = True
        self._preview_generation += 1
        if self._worker is not None and not self._worker.wait(5000):
            self._closing = False
            self._preview_generation += 1
            self.log('后台任务尚未结束，请稍后关闭。', 'warn')
            event.ignore()
            return
        self.viewer.shutdown()
        event.accept()
