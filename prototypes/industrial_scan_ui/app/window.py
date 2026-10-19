"""Reference-inspired scan workbench. No camera initialization or business changes."""
from pathlib import Path
import os
from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QGroupBox, QFormLayout,
    QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QProgressBar,
    QPlainTextEdit, QFileDialog, QMessageBox, QScrollArea, QHeaderView,
)
from ui_common.symbols import icon
from ui_common.worker_thread import WorkerThread
from ..core.session import ScanSession, demo_cloud, crop_background, read_cloud, write_cloud
from .viewer_factory import create_canvas


STYLE = '''
QWidget { background:#252b33; color:#d6dce3; font-family:"Microsoft YaHei"; font-size:12px; }
QWidget#ribbon { background:#303741; border-bottom:1px solid #171d24; }
QWidget#menubar { background:#1d232a; }
QLabel#brand { color:#e5eddd; font-size:17px; font-weight:700; }
QLabel#muted { color:#8e9ba9; }
QLabel#badge { background:#354431; color:#c3e596; padding:5px 10px; border-radius:3px; }
QLabel#status { background:#1d232a; color:#9aa9b9; padding:6px; }
QLabel#section { color:#9dabb9; font-size:11px; }
QPushButton,QToolButton { background:#343d48; border:1px solid #475360; border-radius:3px; padding:6px 11px; }
QPushButton:hover,QToolButton:hover { background:#424f5d; border-color:#8098ad; }
QPushButton:disabled,QToolButton:disabled { background:#2b323b; border-color:#343e49; color:#65717f; }
QPushButton#primary { background:#b9d883; border-color:#c5e295; color:#202a1b; font-weight:700; }
QPushButton#primary:hover { background:#cbe89d; }
QPushButton#primary:disabled { background:#46543e; color:#839078; border-color:#536049; }
QToolButton { border:0; background:transparent; padding:5px; }
QToolButton:checked { background:#456582; }
QGroupBox { font-weight:600; border:1px solid #39434f; border-radius:3px; margin-top:12px; padding-top:10px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; color:#bbc7d3; }
QTreeWidget { background:#20262e; border:0; outline:0; }
QTreeWidget::item { height:29px; }
QTreeWidget::item:selected { background:#3c6485; color:white; }
QHeaderView::section { background:#2c3540; border:0; padding:5px; color:#8e9ba9; }
QDoubleSpinBox,QSpinBox,QComboBox { background:#1f252d; border:1px solid #46515f; border-radius:2px; min-height:25px; padding:1px 5px; }
QComboBox QAbstractItemView { background:#28323e; selection-background-color:#3c6485; }
QCheckBox { spacing:7px; padding:4px 0; }
QCheckBox::indicator { width:13px; height:13px; border:1px solid #647487; background:#20262e; border-radius:2px; }
QCheckBox::indicator:checked { background:#b9d883; border-color:#b9d883; }
QSplitter::handle { background:#171e26; }
QPlainTextEdit { background:#1e252d; border:0; color:#9eafbe; font-family:Consolas; font-size:11px; }
QProgressBar { background:#1c232b; border:0; border-radius:3px; height:7px; text-align:center; }
QProgressBar::chunk { background:#b9d883; border-radius:3px; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#20262e; width:8px; }
QScrollBar::handle:vertical { background:#4d5967; min-height:24px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
'''


class ScanWorkbench(QWidget):
    """Embeddable QWidget with explicit integration hooks; demo controller is local."""
    log_message = Signal(str, str)
    dirty_changed = Signal(bool)
    save_session_requested = Signal()

    def __init__(self, parent=None, *, load_demo=True, renderer='auto'):
        super().__init__(parent)
        # Qt's offscreen Windows plugin may enumerate zero system fonts.
        # Register the installed font in memory, without copying a font asset.
        if 'Microsoft YaHei' not in QFontDatabase.families():
            font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
        self.setFont(QFont('Microsoft YaHei', 9))
        self.setWindowTitle('MCC · 工业扫描 UI 原型')
        self.resize(1440, 900)
        self.setMinimumSize(1000, 660)
        self.setStyleSheet(STYLE)
        self.session = ScanSession()
        self._devices = []
        self._background_runner = None
        self._worker = None
        self._busy = False
        self._completion = None
        self._undo = []
        self._dirty = False
        self._rebuilding = False
        self._retired_canvases = []
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._tick)
        self._renderer = renderer
        self._build()
        if load_demo:
            self.session.layers.append(demo_cloud())
            self.session.sequence = 1
        self._refresh(fit=True)
        self.log('原型就绪：当前为合成演示点云，未连接真实相机。')
        QTimer.singleShot(800, self._check_renderer)

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)
        menubar = QWidget(objectName='menubar')
        menu = QHBoxLayout(menubar)
        menu.setContentsMargins(18, 10, 16, 10)
        brand = QLabel('MCC   /   SCAN STUDIO', objectName='brand')
        menu.addWidget(brand)
        menu.addSpacing(30)
        self.mode = QComboBox()
        self.mode.addItems(['转台扫描 · 演示', '多相机拼接 · 演示', '移动链式 · 演示'])
        self.mode.setToolTip('仅切换原型视图标签；不接入 A/B/C 真实算法或相机。')
        self.mode.currentTextChanged.connect(lambda text: self.log(f'切换场景标签：{text}；仍使用同一模拟流程。'))
        menu.addWidget(self.mode)
        menu.addStretch()
        menu.addWidget(QLabel('OFFLINE PROTOTYPE', objectName='badge'))
        help_btn = QPushButton('原型说明')
        help_btn.clicked.connect(self._help)
        menu.addWidget(help_btn)
        root.addWidget(menubar)

        ribbon = QWidget(objectName='ribbon')
        ribbon_layout = QHBoxLayout(ribbon)
        ribbon_layout.setContentsMargins(10, 5, 12, 4)
        ribbon_layout.setSpacing(14)
        self._actions = {}
        groups = [
            ('项目', [('new', '新建', 'folder_open', self.new_project), ('import', '导入点云', 'layers', self.import_dialog), ('export', '导出点云', 'save', self.export_dialog)]),
            ('模拟采集', [('scan', '开始扫描', 'camera', self.start_scan), ('pause', '暂停', 'lock', self.pause_scan), ('finish', '完成', 'stitch', self.finish_scan)]),
            ('点云编辑', [('crop', '移除背景', 'filter', self.remove_background), ('undo', '撤销编辑', 'undo', self.undo), ('delete', '删除图层', 'trash', self.delete_layer)]),
            ('视图', [('fit', '适配视图', 'reset_view', self._fit), ('shot', '视图截图', 'video', self.screenshot_dialog)]),
        ]
        for title, actions in groups:
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            row = QHBoxLayout()
            row.setSpacing(2)
            for key, text, glyph, callback in actions:
                button = QToolButton()
                button.setText(text)
                button.setIcon(icon(glyph, '#d6e0e8', 23))
                button.setIconSize(QSize(23, 23))
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setMinimumSize(66, 53)
                button.clicked.connect(callback)
                row.addWidget(button)
                self._actions[key] = button
            col.addLayout(row)
            caption = QLabel(title, alignment=Qt.AlignCenter, objectName='section')
            col.addWidget(caption)
            ribbon_layout.addWidget(box)
        ribbon_layout.addStretch()
        root.addWidget(ribbon)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        sidebar = QWidget()
        sidebar.setMinimumWidth(260)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 8)
        side.setSpacing(8)
        tree_title = QHBoxLayout()
        tree_title.addWidget(QLabel('项目导航'))
        tree_title.addStretch()
        self.layer_count = QLabel('0 图层', objectName='muted')
        tree_title.addWidget(self.layer_count)
        side.addLayout(tree_title)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['扫描项目', '点数'])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setMinimumHeight(130)
        self.tree.setMaximumHeight(220)
        self.tree.itemChanged.connect(self._visibility_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._refresh_details())
        side.addWidget(self.tree, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        params = QWidget()
        form_col = QVBoxLayout(params)
        form_col.setContentsMargins(0, 0, 0, 0)
        device_group = QGroupBox('01  设备与场景')
        device_form = QFormLayout(device_group)
        self.device_label = QLabel('模拟设备 · 不连接硬件')
        self.device_label.setWordWrap(True)
        device_form.addRow(self.device_label)
        self.units = QComboBox()
        self.units.addItems(['mm', 'm'])
        self.units.setToolTip('仅用于下一次导入。m 输入转换为内部 mm；导出始终为 mm。')
        device_form.addRow('导入源单位', self.units)
        form_col.addWidget(device_group)
        scan_group = QGroupBox('02  模拟扫描参数')
        scan_form = QFormLayout(scan_group)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(.5, 3.)
        self.spacing.setValue(.8)
        self.spacing.setSingleStep(.1)
        self.spacing.setSuffix(' mm')
        scan_form.addRow('合成采样间距', self.spacing)
        self.speed = QComboBox()
        self.speed.addItems(['标准 · 约 3 秒', '精细 · 约 6 秒'])
        scan_form.addRow('演示扫描时长', self.speed)
        note = QLabel('扫描按钮只生成合成点云；不执行标定、机器人运动或真实采集。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        scan_form.addRow(note)
        form_col.addWidget(scan_group)
        edit_group = QGroupBox('03  显示与背景裁切')
        edit_form = QFormLayout(edit_group)
        self.color_mode = QComboBox()
        self.color_mode.addItems(['原始颜色', '高度着色', '统一颜色'])
        self.color_mode.currentTextChanged.connect(self._display_changed)
        edit_form.addRow('点云颜色', self.color_mode)
        self.render_quality = QComboBox()
        self.render_quality.addItems(['流畅', '均衡', '细节'])
        self.render_quality.setCurrentText('均衡')
        self.render_quality.setToolTip('GPU 静止 / 拖动预算：100万/10万、500万/50万、1000万/100万；兼容预览仅1.8万/3000点。')
        self.render_quality.currentTextChanged.connect(lambda name: self.canvas.set_policy(name))
        edit_form.addRow('显示质量', self.render_quality)
        self.point_size = QSpinBox()
        self.point_size.setRange(1, 5)
        self.point_size.setValue(2)
        self.point_size.valueChanged.connect(self._display_changed)
        edit_form.addRow('点大小', self.point_size)
        self.z_cut = QDoubleSpinBox()
        self.z_cut.setRange(-100000, 100000)
        self.z_cut.setValue(5.)
        self.z_cut.setSuffix(' mm')
        self.z_cut.setToolTip('作用于当前所选图层：保留 Z 大于阈值的点；可撤销。')
        edit_form.addRow('保留 Z >', self.z_cut)
        self.grid_toggle = QCheckBox('参考网格')
        self.grid_toggle.setChecked(True)
        self.grid_toggle.toggled.connect(self._display_changed)
        edit_form.addRow(self.grid_toggle)
        self.axes_toggle = QCheckBox('坐标轴')
        self.axes_toggle.setChecked(True)
        self.axes_toggle.toggled.connect(self._display_changed)
        edit_form.addRow(self.axes_toggle)
        form_col.addWidget(edit_group)
        form_col.addStretch()
        scroll.setWidget(params)
        side.addWidget(scroll, 3)
        split.addWidget(sidebar)

        view = QWidget()
        view_layout = QVBoxLayout(view)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(0)
        tools = QHBoxLayout()
        tools.setContentsMargins(14, 6, 14, 6)
        self.view_title = QLabel('3D 扫描视图')
        tools.addWidget(self.view_title)
        tools.addStretch()
        for name in ['等轴测', '顶视', '正视', '右视']:
            button = QPushButton(name)
            button.clicked.connect(lambda checked=False, value=name: self.canvas.set_view(value))
            tools.addWidget(button)
        view_layout.addLayout(tools)
        self.canvas = create_canvas(renderer=self._renderer)
        self.canvas.status_changed.connect(self._render_status)
        if hasattr(self.canvas, 'render_failed'):
            self.canvas.render_failed.connect(self._renderer_failed)
        self._view_layout = view_layout
        view_layout.addWidget(self.canvas, 1)
        details = QWidget()
        details_layout = QHBoxLayout(details)
        details_layout.setContentsMargins(16, 8, 16, 8)
        self.details = QLabel('选择项目树图层查看数据来源', objectName='muted')
        self.details.setWordWrap(True)
        details_layout.addWidget(self.details, 1)
        self.reset_button = QPushButton('适配全部')
        self.reset_button.clicked.connect(self._fit)
        details_layout.addWidget(self.reset_button)
        view_layout.addWidget(details)
        split.addWidget(view)
        split.setSizes([290, 1150])
        root.addWidget(split, 1)

        scan_strip = QWidget()
        scan_layout = QHBoxLayout(scan_strip)
        scan_layout.setContentsMargins(15, 10, 15, 10)
        self.state_label = QLabel('待机')
        self.state_label.setMinimumWidth(130)
        scan_layout.addWidget(self.state_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        scan_layout.addWidget(self.progress, 1)
        self.progress_text = QLabel('0%')
        scan_layout.addWidget(self.progress_text)
        self.scan_button = QPushButton('开始模拟扫描', objectName='primary')
        self.scan_button.clicked.connect(self.start_scan)
        scan_layout.addSpacing(12)
        scan_layout.addWidget(self.scan_button)
        self.log_toggle = QPushButton('运行日志')
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(lambda on: self.logs.setVisible(on))
        scan_layout.addWidget(self.log_toggle)
        root.addWidget(scan_strip)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(200)
        self.logs.setFixedHeight(100)
        self.logs.hide()
        root.addWidget(self.logs)
        self.status = QLabel('离线演示  |  单位 mm  |  未连接相机', objectName='status')
        root.addWidget(self.status)

    def set_devices(self, devices):
        self._devices = list(devices)
        self.device_label.setText(f'收到 {len(self._devices)} 个设备描述 · 未连接硬件')

    def set_background_runner(self, runner):
        self._background_runner = runner

    def set_state(self, state):
        if state not in ('ready', 'scanning', 'paused', 'captured', 'finished'):
            raise ValueError(f'未知原型状态：{state}')
        self.session.state = state
        if state == 'scanning':
            self._timer.start()
        else:
            self._timer.stop()
        self._refresh_controls()

    def current_state(self):
        return self.session.state

    def log(self, text, level='info'):
        self.logs.appendPlainText(text)
        self.log_message.emit(text, level)

    def _changed(self):
        self._dirty = True
        self.dirty_changed.emit(True)

    def _selected_index(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def _refresh(self, fit=False, select=None):
        old = self._selected_index() if select is None else select
        self._rebuilding = True
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, ['扫描项目', ''])
        root.setIcon(0, icon('folder_open'))
        for i, layer in enumerate(self.session.layers):
            item = QTreeWidgetItem(root, [layer.name, f'{len(layer.points):,}'])
            item.setData(0, Qt.UserRole, i)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if layer.visible else Qt.Unchecked)
            item.setIcon(0, icon('layers', '#b8d983'))
            if i == old or (old is None and i == 0):
                self.tree.setCurrentItem(item)
        root.setExpanded(True)
        self._rebuilding = False
        self.layer_count.setText(f'{len(self.session.layers)} 图层')
        self.canvas.set_layers(self.session.layers, fit=fit)
        self._refresh_details()
        self._refresh_controls()

    def _refresh_details(self):
        if self._rebuilding:
            return
        idx = self._selected_index()
        if idx is None or idx >= len(self.session.layers):
            self.details.setText('选择图层查看点数和数据来源')
        else:
            layer = self.session.layers[idx]
            self.details.setText(f'{layer.name}  /  {len(layer.points):,} 点  /  {layer.source}')
            self.details.setToolTip(layer.source)
        self._refresh_controls()

    def _refresh_controls(self):
        active = self.session.state in ('scanning', 'paused')
        available = not active and not self._busy
        selected = self._selected_index() is not None
        for name in ('new', 'import', 'crop', 'delete', 'undo', 'export'):
            self._actions[name].setEnabled(available)
        self._actions['crop'].setEnabled(available and selected)
        self._actions['delete'].setEnabled(available and selected)
        self._actions['undo'].setEnabled(available and bool(self._undo))
        self._actions['export'].setEnabled(available and any(l.visible for l in self.session.layers))
        self._actions['scan'].setEnabled(not self._busy and self.session.state != 'scanning')
        self.scan_button.setEnabled(not self._busy and self.session.state != 'scanning')
        self.scan_button.setText('继续模拟扫描' if self.session.state == 'paused' else '开始模拟扫描')
        self._actions['pause'].setEnabled(self.session.state == 'scanning')
        self._actions['finish'].setEnabled(available and any(l.visible for l in self.session.layers))
        self.tree.setEnabled(available)
        self.mode.setEnabled(available)
        self.spacing.setEnabled(available)
        self.speed.setEnabled(available)
        states = {'ready': '待机 · 离线演示', 'scanning': '正在模拟扫描', 'paused': '扫描已暂停',
                  'captured': '模拟采集完成', 'finished': '会话已完成'}
        self.state_label.setText('文件处理中…' if self._busy else states[self.session.state])
        self.progress.setValue(self.session.progress)
        self.progress_text.setText(f'{self.session.progress}%')
        self._render_status()

    def _render_status(self):
        if not hasattr(self, 'status'):
            return
        self.render_quality.setEnabled(hasattr(self.canvas, 'render_failed'))
        self.status.setText(f'原始 {self.canvas.total_points:,} 点 / 显示 {self.canvas.displayed_points:,} 点   |   {self.canvas.backend_name}   |   内部/导出 mm   |   未连接相机')

    def _check_renderer(self):
        if hasattr(self.canvas, 'isValid') and self.isVisible() and not self.canvas.isValid():
            self._renderer_failed('未能创建 OpenGL 上下文，已切换兼容软件预览。')

    def _renderer_failed(self, message):
        if not hasattr(self.canvas, 'render_failed'):
            return
        old = self.canvas
        old._pending = None
        old._closed = True
        old._restore.stop()
        old.hide()
        self._retired_canvases.append(old)
        self.canvas = create_canvas(renderer='software')
        self._view_layout.replaceWidget(old, self.canvas)
        self.canvas.status_changed.connect(self._render_status)
        self.canvas.set_layers(self.session.layers, fit=True)
        self._display_changed()
        self.canvas.show()
        self.log(message + ' 兼容模式仅用于预览，非大点云 GPU 渲染。', 'error')
        self.log_toggle.setChecked(True)
        self._render_status()

    def _visibility_changed(self, item, column):
        if self._rebuilding:
            return
        idx = item.data(0, Qt.UserRole)
        if idx is not None:
            self.session.layers[idx].visible = item.checkState(0) == Qt.Checked
            self._changed()
            self.canvas.set_layers(self.session.layers)
            self._refresh_controls()

    def _display_changed(self, *_):
        self.canvas.grid = self.grid_toggle.isChecked()
        self.canvas.axes = self.axes_toggle.isChecked()
        self.canvas.point_size = self.point_size.value()
        self.canvas.color_mode = self.color_mode.currentText()
        self.canvas.update()

    def _fit(self):
        self.canvas.fit_view()

    def start_scan(self):
        if self._busy or not self.session.start():
            return
        self.log('模拟扫描开始；使用参数生成合成点云，不访问设备。')
        self._timer.start()
        self._refresh_controls()

    def pause_scan(self):
        if self.session.pause():
            self._timer.stop()
            self.log('模拟扫描已暂停，可点击继续。')
        self._refresh_controls()

    def _tick(self):
        layer = self.session.advance(4 if self.speed.currentIndex() == 0 else 2, self.spacing.value())
        if layer is not None:
            self._timer.stop()
            self._changed()
            self.log(f'{layer.name} 完成：{len(layer.points):,} 个合成点。')
            self._refresh(fit=len(self.session.layers) == 1, select=len(self.session.layers) - 1)
        else:
            self._refresh_controls()

    def finish_scan(self):
        try:
            self.session.finish()
            self.log('演示会话已完成，可导出可见图层（mm）。未进行精度验收。')
        except ValueError as exc:
            self.log(str(exc), 'warn')
        self._refresh_controls()

    def _snapshot(self):
        self._undo.append(list(self.session.layers))
        self._undo = self._undo[-10:]

    def remove_background(self):
        idx = self._selected_index()
        if idx is None:
            return
        try:
            old = self.session.layers[idx]
            replacement = crop_background(old, self.z_cut.value())
            self._snapshot()
            self.session.layers[idx] = replacement
            self._changed()
            self.log(f'{old.name}：保留 Z > {self.z_cut.value():g} mm，{len(old.points):,} → {len(replacement.points):,} 点。')
            self._refresh()
        except ValueError as exc:
            self.log(str(exc), 'warn')

    def undo(self):
        if self._undo:
            self.session.layers = self._undo.pop()
            self._changed()
            self.log('已撤销上一次编辑。')
            self._refresh()

    def delete_layer(self):
        idx = self._selected_index()
        if idx is not None:
            self._snapshot()
            layer = self.session.layers.pop(idx)
            self._changed()
            self.log(f'已删除 {layer.name}；可撤销。')
            self._refresh(select=0)

    def new_project(self):
        if self._dirty and QMessageBox.question(self, '新建项目', '清空当前原型会话？未导出的修改将丢失。') != QMessageBox.Yes:
            return
        self._timer.stop()
        self.session = ScanSession()
        self._undo.clear()
        self._dirty = False
        self.dirty_changed.emit(False)
        self._refresh(fit=True)
        self.log('已创建空白原型项目。')

    def _run(self, func, done):
        if self._busy:
            return
        self._busy = True
        self._completion = done
        self._refresh_controls()
        if self._background_runner is not None:
            try:
                self._background_runner(func, self._job_result)
            except Exception as exc:
                self._job_result(None, exc)
            return
        self._worker = WorkerThread(func)
        self._worker.result_ready.connect(self._job_result)
        self._worker.finished.connect(self._job_finished)
        self._worker.start()

    def _job_result(self, result, error):
        try:
            if error:
                self.log(f'文件操作失败：{error}', 'error')
                QMessageBox.warning(self, '文件操作失败', str(error))
            else:
                self._completion(result)
        finally:
            if self._background_runner is not None:
                self._job_finished()

    def _job_finished(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._busy = False
        self._completion = None
        self._refresh_controls()

    def import_file(self, path, unit='mm'):
        def done(layer):
            self._snapshot()
            self.session.layers.append(layer)
            self._changed()
            self.log(f'导入 {layer.name}：{len(layer.points):,} 点，源单位 {unit}，内部 mm。')
            self._refresh(fit=len(self.session.layers) == 1, select=len(self.session.layers) - 1)
        self._run(lambda: read_cloud(path, unit), done)

    def import_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入点云（请先确认左侧源单位）', '', '点云 (*.ply *.pcd *.xyz *.pts)')
        if path:
            self.import_file(path, self.units.currentText())

    def export_file(self, path):
        layers = list(self.session.layers)
        self._run(lambda: write_cloud(path, layers),
                  lambda count: self.log(f'已导出 {count:,} 点（mm）：{path}'))

    def export_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出全部可见点云（mm；演示数据仍为合成数据）', 'scan_preview_mm.ply', 'PLY (*.ply)')
        if path:
            self.export_file(str(Path(path).with_suffix('.ply')))

    def screenshot_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存视区截图', 'scan_view.png', 'PNG (*.png)')
        if path:
            if not self.canvas.grab().save(path):
                QMessageBox.warning(self, '截图失败', '文件无法写入。')
            else:
                self.log(f'已保存视区截图：{path}')

    def _help(self):
        QMessageBox.information(self, '工业扫描 UI 原型',
            '参考视频的顶部功能带、项目树、参数面板与大视区布局。\n\n'
            '可用：导入/导出点云、图层显隐、旋转缩放、正交视图、Z 裁切与撤销、模拟扫描。\n'
            '视角：左键轨迹球自由旋转，右键/中键或 Shift 平移；双击可见点设置旋转中心，F/Z 适配。\n'
            '模拟扫描只生成合成点云，不连接相机、不控制机器人、不执行标定。\n'
            'GPU 按帧缓存：静止高细节、拖动低密度，停止后恢复。显示降采样不影响原始数据与导出。\n'
            'OpenGL 不可用时明确降级为 18,000 点兼容预览，拖动 3,000 点。内部和导出单位均为 mm。\n'
            '本原型尚未接入正式 A/B/C 工作流，也不提供性能或精度验收结果。')

    def closeEvent(self, event):
        if self._busy or self.canvas.is_busy or any(canvas.is_busy for canvas in self._retired_canvases):
            self.log('文件任务仍在运行，请等待完成后关闭。', 'warn')
            event.ignore()
            return
        if self._dirty and QMessageBox.question(self, '关闭原型', '关闭当前会话？未导出的修改将丢失。') != QMessageBox.Yes:
            event.ignore()
            return
        self._timer.stop()
        self.canvas.shutdown()
        for canvas in self._retired_canvases:
            canvas.shutdown()
        event.accept()
