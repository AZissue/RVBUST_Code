"""Industrial-style point-cloud postprocess workbench. No camera initialization."""
from pathlib import Path
import os
import logging
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QSignalBlocker
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QGroupBox, QFormLayout,
    QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QScrollArea, QHeaderView,
)
from ui_common.symbols import icon
from ui_common.worker_thread import WorkerThread
from ui_common.activity_log import ActivityLogPanel
from ..core.session import CloudLayer, PostProcessSession, demo_cloud, read_cloud, write_cloud
from ..core.processing import polygon_crop_mask, voxel_downsample, random_downsample
from .viewer_factory import create_canvas
from .selection import PolygonSelectionOverlay

logger = logging.getLogger('industrial_pointcloud_postprocess')

STYLE = '''
QWidget { background:#292929; color:#dedede; font-family:"Microsoft YaHei"; font-size:12px; }
QWidget#ribbon { background:#333333; border-bottom:1px solid #1b1b1b; }
QWidget#menubar { background:#222222; }
QLabel#brand { color:#eeeeee; font-size:17px; font-weight:700; }
QLabel#muted { color:#aaaaaa; }
QLabel#badge { background:#353535; color:#c7c7c7; padding:5px 10px; border-radius:3px; }
QLabel#status { background:#222222; color:#aaaaaa; padding:6px; }
QLabel#section { color:#aaaaaa; font-size:11px; }
QPushButton,QToolButton { background:#393939; border:1px solid #555555; border-radius:3px; padding:6px 11px; }
QPushButton:hover,QToolButton:hover { background:#464646; border-color:#888888; }
QPushButton:disabled,QToolButton:disabled { background:#303030; border-color:#3c3c3c; color:#777777; }
QPushButton#primary { background:#d32f2f; border-color:#df4a4a; color:#ffffff; font-weight:700; }
QPushButton#primary:hover { background:#e04343; }
QPushButton#primary:disabled { background:#463333; color:#9b8585; border-color:#604242; }
QToolButton { border:0; background:transparent; padding:5px; }
QToolButton:checked { background:#583737; }
QGroupBox { font-weight:600; border:1px solid #454545; border-radius:3px; margin-top:12px; padding-top:10px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; color:#cccccc; }
QTreeWidget { background:#242424; border:0; outline:0; }
QTreeWidget::item { height:29px; }
QTreeWidget::item:selected { background:#583737; color:white; }
QHeaderView::section { background:#343434; border:0; padding:5px; color:#aaaaaa; }
QDoubleSpinBox,QSpinBox,QComboBox { background:#222222; border:1px solid #555555; border-radius:2px; min-height:25px; padding:1px 5px; }
QComboBox QAbstractItemView { background:#2c2c2c; selection-background-color:#583737; }
QCheckBox { spacing:7px; padding:4px 0; }
QCheckBox::indicator { width:13px; height:13px; border:1px solid #777777; background:#242424; border-radius:2px; }
QCheckBox::indicator:checked { background:#d32f2f; border-color:#d32f2f; }
QSplitter::handle { background:#1d1d1d; }
QPlainTextEdit { background:#222222; border:0; color:#b6b6b6; font-family:Consolas; font-size:11px; }
QLineEdit { background:#222222; border:1px solid #555555; padding:6px; border-radius:3px; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#242424; width:8px; }
QScrollBar::handle:vertical { background:#555555; min-height:24px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
'''


class PostProcessWorkbench(QWidget):
    log_message = Signal(str, str)

    def __init__(self, parent=None, *, load_demo=True, renderer='auto'):
        super().__init__(parent)
        if 'Microsoft YaHei' not in QFontDatabase.families():
            font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
        self.setFont(QFont('Microsoft YaHei', 9))
        self.setWindowTitle('MCC · 点云后处理原型')
        self.resize(1440, 900)
        self.setMinimumSize(1000, 660)
        self.setStyleSheet(STYLE)
        self.session = PostProcessSession()
        self._latest_message = '就绪'
        self._task_label = ''
        self._worker = None
        self._busy = False
        self._completion = None
        self._rebuilding = False
        self._retired_canvases = []
        self._renderer = renderer
        self._build()
        if load_demo:
            self.session.layers.append(demo_cloud())
            self.session.sequence = 1
        self._refresh(fit=True)
        self.log('原型就绪：离线点云后处理。' + ('已载入合成演示点云。' if load_demo else '等待打开点云文件。'))
        QTimer.singleShot(800, self._check_renderer)

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)
        menubar = QWidget(objectName='menubar')
        menu = QHBoxLayout(menubar)
        menu.setContentsMargins(18, 10, 16, 10)
        menu.addWidget(QLabel('MCC   /   POINT STUDIO', objectName='brand'))
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
            ('文件', [('open', '打开点云', 'folder_open', self.open_dialog),
                      ('export', '导出PLY', 'save', self.export_dialog)]),
            ('编辑', [('select', '多边形框选', 'detect', None),
                      ('undo', '撤销', 'undo', self.undo),
                      ('delete', '删除图层', 'trash', self.delete_layer)]),
            ('视图', [('fit', '适配全部', 'reset_view', self._fit),
                      ('shot', '视区截图', 'video', self.screenshot_dialog)]),
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
                if key == 'select':
                    button.setCheckable(True)
                    button.toggled.connect(self._selection_toggled)
                else:
                    button.clicked.connect(callback)
                row.addWidget(button)
                self._actions[key] = button
            col.addLayout(row)
            col.addWidget(QLabel(title, alignment=Qt.AlignCenter, objectName='section'))
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
        tree_title.addWidget(QLabel('图层'))
        tree_title.addStretch()
        self.layer_count = QLabel('0 图层', objectName='muted')
        tree_title.addWidget(self.layer_count)
        side.addLayout(tree_title)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['名称', '点数'])
        self.tree.setToolTip('勾选控制显隐；选中图层作为编辑对象')
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setMinimumHeight(130)
        self.tree.setMaximumHeight(220)
        self.tree.itemChanged.connect(self._visibility_changed)
        side.addWidget(self.tree, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        params = QWidget()
        form_col = QVBoxLayout(params)
        form_col.setContentsMargins(0, 0, 0, 0)
        data_group = QGroupBox('01  数据')
        data_form = QFormLayout(data_group)
        self.units = QComboBox()
        self.units.addItems(['mm', 'm'])
        self.units.setToolTip('仅用于下一次打开。m 输入转换为内部 mm；导出始终为 mm。')
        data_form.addRow('导入源单位', self.units)
        data_note = QLabel('支持 ply / pcd / xyz / pts；打开与导出在后台线程执行。')
        data_note.setWordWrap(True)
        data_note.setObjectName('muted')
        data_form.addRow(data_note)
        form_col.addWidget(data_group)

        crop_group = QGroupBox('02  框选裁剪')
        crop_form = QFormLayout(crop_group)
        self.crop_mode = QComboBox()
        self.crop_mode.addItems(['保留框内', '移除框内'])
        self.crop_mode.setToolTip('沿当前视线方向正交投影框选，作用于当前选中图层。')
        crop_form.addRow('裁剪模式', self.crop_mode)
        crop_note = QLabel('点击工具条“多边形框选”进入框选：左键加顶点，双击或右键闭合，Esc 取消；可撤销。')
        crop_note.setWordWrap(True)
        crop_note.setObjectName('muted')
        crop_form.addRow(crop_note)
        form_col.addWidget(crop_group)

        sample_group = QGroupBox('03  下采样')
        sample_form = QFormLayout(sample_group)
        self.voxel_size = QDoubleSpinBox()
        self.voxel_size.setRange(0.01, 100000)
        self.voxel_size.setValue(2.0)
        self.voxel_size.setDecimals(2)
        self.voxel_size.setSuffix(' mm')
        sample_form.addRow('体素尺寸', self.voxel_size)
        self.voxel_button = QPushButton('应用体素下采样')
        self.voxel_button.clicked.connect(self._voxel_clicked)
        sample_form.addRow(self.voxel_button)
        self.sample_ratio = QDoubleSpinBox()
        self.sample_ratio.setRange(0.1, 100)
        self.sample_ratio.setValue(50)
        self.sample_ratio.setDecimals(1)
        self.sample_ratio.setSuffix(' %')
        sample_form.addRow('随机保留比例', self.sample_ratio)
        self.random_button = QPushButton('应用随机抽样')
        self.random_button.clicked.connect(self._random_clicked)
        sample_form.addRow(self.random_button)
        form_col.addWidget(sample_group)

        display_group = QGroupBox('04  显示')
        display_form = QFormLayout(display_group)
        self.color_mode = QComboBox()
        self.color_mode.addItems(['原始颜色', '高度着色', '统一颜色'])
        self.color_mode.currentTextChanged.connect(self._display_changed)
        display_form.addRow('颜色模式', self.color_mode)
        self.render_quality = QComboBox()
        self.render_quality.addItems(['流畅', '均衡', '细节'])
        self.render_quality.setCurrentText('均衡')
        self.render_quality.setToolTip('显示抽稀只影响预览，不影响原始数据与导出。')
        self.render_quality.currentTextChanged.connect(lambda name: self.canvas.set_policy(name))
        display_form.addRow('显示质量', self.render_quality)
        self.point_size = QSpinBox()
        self.point_size.setRange(1, 5)
        self.point_size.setValue(2)
        self.point_size.valueChanged.connect(self._display_changed)
        display_form.addRow('点大小', self.point_size)
        self.grid_toggle = QCheckBox('参考网格')
        self.grid_toggle.setChecked(True)
        self.grid_toggle.toggled.connect(self._display_changed)
        display_form.addRow(self.grid_toggle)
        self.axes_toggle = QCheckBox('坐标轴')
        self.axes_toggle.setChecked(True)
        self.axes_toggle.toggled.connect(self._display_changed)
        display_form.addRow(self.axes_toggle)
        form_col.addWidget(display_group)
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
        tools.addWidget(QLabel('3D 点云视图'))
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
        self._make_overlay()
        details = QWidget()
        self.details_bar = details
        details_layout = QHBoxLayout(details)
        details_layout.setContentsMargins(16, 8, 16, 8)
        self.details = QLabel('选择图层查看点数和数据来源', objectName='muted')
        self.details.setWordWrap(True)
        details_layout.addWidget(self.details, 1)
        self.reset_button = QPushButton('适配全部')
        self.reset_button.clicked.connect(self._fit)
        details_layout.addWidget(self.reset_button)
        view_layout.addWidget(details)
        split.addWidget(view)
        split.setSizes([290, 1150])
        self.content_splitter = QSplitter(Qt.Vertical)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(6)
        self.content_splitter.addWidget(split)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.splitterMoved.connect(self._log_splitter_moved)
        self._log_height = 200
        root.addWidget(self.content_splitter, 1)

        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(15, 6, 15, 6)
        self.state_label = QLabel('待机 · 离线后处理')
        bottom_layout.addWidget(self.state_label, 1)
        self.log_toggle = QPushButton('运行日志')
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_logs)
        bottom_layout.addWidget(self.log_toggle)
        root.addWidget(bottom)
        self.logs = ActivityLogPanel(docked=True)
        self.logs.setMinimumHeight(140)
        self.content_splitter.addWidget(self.logs)
        self.content_splitter.setStretchFactor(1, 0)
        self.logs.attach_logger(logger)
        self.logs.closed.connect(lambda: self.log_toggle.setChecked(False))
        self.logs.hide()
        self.status = QLabel(objectName='status')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.latest_status = QLabel('就绪', objectName='status')
        self.latest_status.setMaximumHeight(28)
        root.addWidget(self.latest_status)

    def _make_overlay(self):
        self.overlay = PolygonSelectionOverlay(self.canvas)
        self.overlay.polygon_closed.connect(self._polygon_closed)
        self.overlay.cancelled.connect(self._selection_cancelled)

    def _log_splitter_moved(self, *_):
        if self.logs.isVisible():
            self._log_height = self.content_splitter.sizes()[1]

    def _toggle_logs(self, visible):
        self.latest_status.setVisible(not visible)
        self.details_bar.setVisible(not (visible and self.height() < 800))
        if visible:
            self.canvas.setMinimumHeight(140)
            self.tree.setMinimumHeight(80)
            self.logs._render()
            self.logs.show()
            total = self.content_splitter.height()-self.content_splitter.handleWidth()
            height = min(self._log_height, max(140, total//2))
            self.content_splitter.setSizes([max(1, total-height), height])
        else:
            if self.logs.isVisible():
                self._log_height = self.content_splitter.sizes()[1]
            self.logs.hide()
            self.canvas.setMinimumHeight(300)
            self.tree.setMinimumHeight(130)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'logs'):
            self.details_bar.setVisible(not (self.log_toggle.isChecked() and self.height() < 800))

    def log(self, text, level='info', *, task=''):
        self.logs.append(text, level, '', task or self._task_label)
        logger.log({'error': logging.ERROR, 'warn': logging.WARNING}.get(level, logging.INFO),
                   text, extra={'activity_owned': True})
        self._latest_message = str(text)
        self.latest_status.setText(self._latest_message[:180])
        self.latest_status.setToolTip(self._latest_message)
        self.log_message.emit(text, level)

    def _selected_index(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def _refresh(self, fit=False, select=None):
        old = self._selected_index() if select is None else select
        self._rebuilding = True
        self.tree.clear()
        for i, layer in enumerate(self.session.layers):
            item = QTreeWidgetItem(self.tree, [layer.name, f'{len(layer.points):,}'])
            item.setData(0, Qt.UserRole, i)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if layer.visible else Qt.Unchecked)
            item.setIcon(0, icon('layers', '#bbbbbb'))
            item.setToolTip(0, layer.source)
            if i == old or (old is None and i == 0):
                self.tree.setCurrentItem(item)
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
        available = not self._busy
        selected = self._selected_index() is not None
        self._actions['open'].setEnabled(available)
        self._actions['export'].setEnabled(available and any(l.visible for l in self.session.layers))
        self._actions['select'].setEnabled(available and selected and not self.overlay.active)
        if not available or not selected:
            self._actions['select'].setChecked(False)
        self._actions['undo'].setEnabled(available and self.session.can_undo)
        self._actions['delete'].setEnabled(available and selected)
        self.tree.setEnabled(available)
        self.voxel_button.setEnabled(available and selected)
        self.random_button.setEnabled(available and selected)
        self.voxel_size.setEnabled(available)
        self.sample_ratio.setEnabled(available)
        self.crop_mode.setEnabled(available)
        self.units.setEnabled(available)
        self.state_label.setText('文件处理中…' if self._busy else '待机 · 离线后处理')
        self._render_status()

    def _render_status(self):
        if not hasattr(self, 'status'):
            return
        self.render_quality.setEnabled(hasattr(self.canvas, 'render_failed'))
        original = sum(layer.source_points if layer.source_points is not None else len(layer.points)
                       for layer in self.session.layers if layer.visible)
        self.status.setText(f'原始 {original:,} / 载入 {self.canvas.total_points:,} / 显示 {self.canvas.displayed_points:,} 点'
                            f'  |  {self.canvas.backend_name}  |  mm')

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
        if self.log_toggle.isChecked():
            self.canvas.setMinimumHeight(140)
        self._view_layout.replaceWidget(old, self.canvas)
        self.canvas.status_changed.connect(self._render_status)
        self.canvas.set_layers(self.session.layers, fit=True)
        self._display_changed()
        self.canvas.show()
        self._make_overlay()
        self.log(message + ' 兼容模式仅用于预览，非大点云 GPU 渲染。', 'error')
        self.log_toggle.setChecked(True)
        self._render_status()

    def _visibility_changed(self, item, column):
        if self._rebuilding:
            return
        idx = item.data(0, Qt.UserRole)
        if idx is not None:
            self.session.layers[idx].visible = item.checkState(0) == Qt.Checked
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

    def _replace_layer(self, index, points, colors, note):
        layer = self.session.layers[index]
        self.session.snapshot()
        self.session.layers[index] = CloudLayer(
            layer.name, points, colors, layer.visible, layer.source + ' | ' + note,
            layer.source_points if layer.source_points is not None else len(layer.points))
        return layer

    def apply_polygon_crop(self, layer_index, polygon_xy):
        polygon = [(float(x), float(y)) for x, y in polygon_xy]
        if len(polygon) < 3:
            self.log('多边形顶点不足 3 个，无法裁剪。', 'warn')
            return False
        if not 0 <= layer_index < len(self.session.layers):
            self.log('请先选择要裁剪的图层。', 'warn')
            return False
        layer = self.session.layers[layer_index]
        if not len(layer.points):
            self.log(f'{layer.name}：图层为空，无法裁剪。', 'warn')
            return False
        canvas = self.canvas
        mask = polygon_crop_mask(layer.points, polygon, center=canvas.center,
                                 rotation_matrix=canvas.rotation.matrix, extent=canvas.extent,
                                 zoom=canvas.zoom, pan=canvas.pan,
                                 width=max(1, canvas.width()), height=max(1, canvas.height()))
        keep_inside = self.crop_mode.currentIndex() == 0
        mode_text = '保留框内' if keep_inside else '移除框内'
        keep = mask if keep_inside else ~mask
        if not keep.any():
            self.log(f'{layer.name}：{mode_text}将清空图层，已取消操作。', 'warn')
            return False
        if keep.all():
            self.log(f'{layer.name}：多边形未影响任何点，未做修改。', 'warn')
            return False
        self._replace_layer(layer_index, layer.points[keep],
                            None if layer.colors is None else layer.colors[keep],
                            f'多边形裁剪({mode_text})')
        self.log(f'{layer.name}：{mode_text}，{len(layer.points):,} → {keep.sum():,} 点。')
        self._refresh()
        return True

    def apply_voxel_downsample(self, layer_index, voxel_size):
        if not 0 <= layer_index < len(self.session.layers):
            self.log('请先选择要下采样的图层。', 'warn')
            return False
        layer = self.session.layers[layer_index]
        try:
            points, colors = voxel_downsample(layer.points, layer.colors, voxel_size)
        except ValueError as exc:
            self.log(f'{layer.name}：{exc}', 'warn')
            return False
        self._replace_layer(layer_index, points, colors, f'体素下采样({voxel_size:g} mm)')
        self.log(f'{layer.name}：体素 {voxel_size:g} mm，{len(layer.points):,} → {len(points):,} 点（体素内取均值）。')
        self._refresh()
        return True

    def apply_random_downsample(self, layer_index, ratio):
        if not 0 <= layer_index < len(self.session.layers):
            self.log('请先选择要抽样的图层。', 'warn')
            return False
        layer = self.session.layers[layer_index]
        try:
            points, colors, _ = random_downsample(layer.points, layer.colors, ratio)
        except ValueError as exc:
            self.log(f'{layer.name}：{exc}', 'warn')
            return False
        self._replace_layer(layer_index, points, colors, f'随机抽样(保留 {ratio * 100:g}%)')
        self.log(f'{layer.name}：随机保留 {ratio * 100:g}%，{len(layer.points):,} → {len(points):,} 点。')
        self._refresh()
        return True

    def undo(self):
        if self.session.undo():
            self.log('已撤销上一次编辑。')
            self._refresh()
        else:
            self.log('没有可撤销的编辑。', 'warn')

    def delete_layer(self):
        idx = self._selected_index()
        if idx is not None:
            self.session.snapshot()
            layer = self.session.layers.pop(idx)
            self.log(f'已删除 {layer.name}；可撤销。')
            self._refresh(select=0)

    def _voxel_clicked(self):
        idx = self._selected_index()
        if idx is not None:
            self.apply_voxel_downsample(idx, self.voxel_size.value())

    def _random_clicked(self):
        idx = self._selected_index()
        if idx is not None:
            self.apply_random_downsample(idx, self.sample_ratio.value() / 100)

    def _selection_toggled(self, checked):
        if not checked:
            if self.overlay.active:
                self.overlay.deactivate()
            return
        if self._selected_index() is None:
            self.log('请先在图层树中选择要裁剪的图层。', 'warn')
            with QSignalBlocker(self._actions['select']):
                self._actions['select'].setChecked(False)
            return
        self.overlay.activate()
        self.log('已进入框选模式：左键加顶点，双击或右键闭合，Esc 取消。')

    def _polygon_closed(self, polygon):
        idx = self._selected_index()
        self.overlay.deactivate()
        self._actions['select'].setChecked(False)
        if idx is not None:
            self.apply_polygon_crop(idx, polygon)

    def _selection_cancelled(self):
        self.overlay.deactivate()
        self._actions['select'].setChecked(False)
        self.log('已取消框选。')

    def add_layer(self, layer, fit=None):
        self.session.layers.append(layer)
        self._refresh(fit=(len(self.session.layers) == 1) if fit is None else fit,
                      select=len(self.session.layers) - 1)

    def load_layer_from_arrays(self, name, points, colors=None):
        layer = CloudLayer(name, points, colors, source='内存数组载入')
        self.add_layer(layer)
        self.log(f'载入 {layer.name}：{len(layer.points):,} 点。')
        return layer

    def _run(self, func, done, task='文件处理'):
        if self._busy:
            return
        self._busy = True
        self._task_label = task
        self._completion = done
        self._refresh_controls()
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
            pass

    def _job_finished(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._busy = False
        self._task_label = ''
        self._completion = None
        self._refresh_controls()

    def import_file(self, path, unit='mm'):
        def done(layer):
            self.add_layer(layer)
            self.log(f'打开 {layer.name}：{len(layer.points):,} 点，源单位 {unit}，内部 mm。')
        self._run(lambda: read_cloud(path, unit), done, task='打开点云')

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, '打开点云（请先确认左侧源单位）', '', '点云 (*.ply *.pcd *.xyz *.pts)')
        if path:
            self.import_file(path, self.units.currentText())

    def export_file(self, path):
        layers = list(self.session.layers)
        self._run(lambda: write_cloud(path, layers),
                  lambda count: self.log(f'已导出 {count:,} 点（mm）：{path}'), task='导出点云')

    def export_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出全部可见点云合并为 PLY（mm）', 'pointcloud_mm.ply', 'PLY (*.ply)')
        if path:
            self.export_file(str(Path(path).with_suffix('.ply')))

    def screenshot_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存视区截图', 'pointcloud_view.png', 'PNG (*.png)')
        if path:
            if not self.canvas.grab().save(path):
                QMessageBox.warning(self, '截图失败', '文件无法写入。')
            else:
                self.log(f'已保存视区截图：{path}')

    def _help(self):
        QMessageBox.information(self, '点云后处理原型',
            '工业风 UI 的轻量点云后处理工具（CloudCompare 基础子集对照版）。\n\n'
            '可用：打开/导出点云（ply/pcd/xyz/pts，mm/m 源单位）、多图层显隐与删除、\n'
            '多边形框选裁剪（保留/移除框内，沿当前视线正交投影）、体素与随机下采样、撤销（8 步）。\n'
            '视角：左键轨迹球旋转，右键/中键或 Shift 平移，滚轮缩放，双击设旋转中心，F/Z 适配。\n'
            '显示抽稀只影响预览，不影响原始数据与导出。内部与导出单位均为 mm。\n'
            'OpenGL 不可用时明确降级为 18,000 点兼容软件预览。')

    def can_leave(self):
        if self._busy or self.canvas.is_busy or any(canvas.is_busy for canvas in self._retired_canvases):
            self.log('文件任务仍在运行，请等待完成后关闭。', 'warn')
            return False
        return True

    def shutdown(self):
        self.logs.detach_loggers()
        self.canvas.shutdown()
        for canvas in self._retired_canvases:
            canvas.shutdown()

    def closeEvent(self, event):
        if not self.can_leave():
            event.ignore()
            return
        self.shutdown()
        event.accept()
