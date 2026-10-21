"""Industrial-style point-cloud postprocess workbench. No camera initialization."""
from pathlib import Path
import os
import logging
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QSignalBlocker
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QSplitter, QGroupBox, QFormLayout,
    QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QFrame,
    QFileDialog, QMessageBox, QScrollArea,
)
from ui_common.symbols import icon
from ui_common.worker_thread import WorkerThread
from ui_common.activity_log import ActivityLogPanel
from ui_v2 import theme
from ..core.session import CloudLayer, PostProcessSession, demo_cloud, read_cloud, write_cloud
from ..core.processing import polygon_crop_mask, voxel_downsample, random_downsample
from .viewer_factory import create_canvas
from .selection import PolygonSelectionOverlay
from .db_tree import CloudTreePanel

logger = logging.getLogger('industrial_pointcloud_postprocess')

STYLE = f'''
QWidget {{ background:{theme.BG_WINDOW}; color:{theme.TEXT_PRIMARY};
    font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif; font-size:13px; }}
QLabel {{ background:transparent; }}
QLabel#mutedLabel {{ color:{theme.TEXT_MUTED}; font-size:12px; }}
QWidget#studioHeader {{ background:#222222; border-bottom:1px solid {theme.BORDER}; }}
QLabel#studioBrand {{ color:#eeeeee; font-size:18px; font-weight:700; }}
QLabel#studioBadge {{ color:{theme.TEXT_SECONDARY}; background:{theme.BG_CARD};
    border:1px solid {theme.BORDER}; border-radius:6px; padding:5px 10px; }}
QWidget#industrialRibbon {{ background:#2e2e2e; border-bottom:1px solid #444444; }}
QFrame#ribbonGroup {{ background:transparent; border:0; border-right:1px solid #454545; }}
QLabel#ribbonCaption {{ color:{theme.TEXT_SECONDARY}; font-size:11px; }}
QWidget#industrialRibbon QToolButton {{ color:#dddddd; background:transparent;
    border:1px solid transparent; border-radius:6px; padding:3px; font-size:12px; }}
QWidget#industrialRibbon QToolButton:hover {{ background:#414141; border-color:#565656; }}
QWidget#industrialRibbon QToolButton:pressed {{ background:{theme.ACCENT_PRESSED}; border-color:{theme.ACCENT}; }}
QWidget#industrialRibbon QToolButton:checked {{ background:{theme.ACCENT_DIM}; border-color:{theme.ACCENT}; color:#ffffff; }}
QWidget#industrialRibbon QToolButton:disabled {{ color:#727272; background:transparent; border-color:transparent; }}
QToolButton[headerAction="true"] {{ background:{theme.BG_CARD}; color:{theme.TEXT_PRIMARY};
    border:1px solid {theme.BORDER}; border-radius:6px; padding:5px 12px; }}
QToolButton[headerAction="true"]:hover {{ background:#363943; border-color:{theme.BORDER_HOVER}; }}
QToolButton[headerAction="true"]:checked {{ background:{theme.ACCENT_DIM}; border-color:{theme.ACCENT}; color:{theme.ACCENT}; }}
QPushButton {{ background:{theme.BG_CARD}; border:1px solid {theme.BORDER};
    border-radius:6px; padding:6px 14px; min-height:26px; color:{theme.TEXT_PRIMARY}; }}
QPushButton:hover {{ background:#363943; border-color:{theme.BORDER_HOVER}; }}
QPushButton:pressed {{ background:#3E424E; }}
QPushButton:disabled {{ background:{theme.BG_PANEL}; color:{theme.TEXT_MUTED}; border-color:#2E313A; }}
QGroupBox {{ background:{theme.BG_PANEL}; border:none; border-radius:6px;
    margin-top:14px; padding-top:12px; font-weight:600; }}
QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 4px; color:{theme.TEXT_SECONDARY}; }}
QTreeWidget {{ background:{theme.BG_PANEL}; border:1px solid {theme.BORDER}; border-radius:6px; outline:0; }}
QTreeWidget::item {{ height:28px; }}
QTreeWidget::item:selected {{ background:{theme.ACCENT_DIM}; color:{theme.TEXT_PRIMARY}; }}
QTreeWidget::item:hover {{ background:{theme.BG_CARD}; }}
QHeaderView::section {{ background:{theme.BG_CARD}; border:0; padding:6px 8px;
    color:{theme.TEXT_SECONDARY}; font-weight:600; }}
QDoubleSpinBox,QSpinBox,QComboBox {{ background:{theme.BG_INPUT}; border:1px solid {theme.BORDER};
    border-radius:6px; min-height:26px; padding:4px 8px; }}
QDoubleSpinBox:focus,QSpinBox:focus,QComboBox:focus {{ border-color:{theme.ACCENT}; }}
QComboBox::drop-down {{ border:none; width:22px; }}
QComboBox QAbstractItemView {{ background:{theme.BG_CARD}; border:1px solid {theme.BORDER};
    selection-background-color:{theme.ACCENT}; }}
QCheckBox {{ spacing:8px; }}
QCheckBox::indicator {{ width:16px; height:16px; border-radius:4px;
    border:2px solid {theme.BORDER}; background:transparent; }}
QCheckBox::indicator:hover {{ border-color:{theme.ACCENT}; }}
QCheckBox::indicator:checked {{ border-color:{theme.ACCENT}; background:{theme.ACCENT}; }}
QSplitter::handle {{ background:#26282F; }}
QSplitter::handle:horizontal {{ width:2px; }}
QSplitter::handle:vertical {{ height:2px; }}
QSplitter::handle:hover {{ background:{theme.ACCENT}; }}
QPlainTextEdit {{ background:{theme.BG_PANEL}; border:1px solid {theme.BORDER};
    border-radius:6px; font-family:Consolas,"Courier New",monospace; font-size:12px; color:{theme.TEXT_SECONDARY}; }}
QLineEdit {{ background:{theme.BG_INPUT}; border:1px solid {theme.BORDER}; border-radius:6px; padding:5px 10px; }}
QScrollArea {{ background:transparent; border:0; }}
QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{theme.BORDER}; border-radius:5px; min-height:28px; }}
QScrollBar::handle:vertical:hover {{ background:{theme.BORDER_HOVER}; }}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
QLabel#statusBar {{ background:{theme.BG_PANEL}; color:{theme.TEXT_SECONDARY}; padding:6px 10px; }}
QLabel#viewTitle {{ font-size:14px; font-weight:600; }}
QToolTip {{ background:{theme.BG_CARD}; color:{theme.TEXT_PRIMARY}; border:1px solid {theme.BORDER}; padding:4px 8px; }}
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
        self._current_index = None
        self._segment = None
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
        header = QWidget(objectName='studioHeader')
        header_line = QHBoxLayout(header)
        header_line.setContentsMargins(18, 8, 14, 8)
        header_line.setSpacing(10)
        header_line.addWidget(QLabel('MCC   /   POINT STUDIO', objectName='studioBrand'))
        header_line.addStretch(1)
        header_line.addWidget(QLabel('OFFLINE PROTOTYPE', objectName='studioBadge'))
        self.log_toggle = QToolButton()
        self.log_toggle.setProperty('headerAction', True)
        self.log_toggle.setText('运行日志')
        self.log_toggle.setIcon(icon('terminal', '#cccccc', 15))
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_logs)
        header_line.addWidget(self.log_toggle)
        help_btn = QToolButton()
        help_btn.setProperty('headerAction', True)
        help_btn.setText('原型说明')
        help_btn.setIcon(icon('help', '#cccccc', 15))
        help_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        help_btn.clicked.connect(self._help)
        header_line.addWidget(help_btn)
        root.addWidget(header)

        ribbon = QWidget(objectName='industrialRibbon')
        ribbon_row = QHBoxLayout(ribbon)
        ribbon_row.setContentsMargins(10, 6, 10, 5)
        ribbon_row.setSpacing(10)
        self._actions = {}
        groups = [
            ('文件', [('open', '打开点云', 'folder_open', self.open_dialog),
                      ('export', '导出PLY', 'save', self.export_dialog)]),
            ('编辑', [('select', '多边形框选', 'detect', None),
                      ('merge', '合并图层', 'stitch', self.merge_selected),
                      ('undo', '撤销', 'undo', self.undo),
                      ('delete', '删除图层', 'trash', self.delete_layer)]),
            ('视图', [('fit', '适配全部', 'reset_view', self._fit),
                      ('shot', '视区截图', 'video', self.screenshot_dialog)]),
        ]
        for title, actions in groups:
            group = QFrame(objectName='ribbonGroup')
            col = QVBoxLayout(group)
            col.setContentsMargins(4, 0, 10, 2)
            col.setSpacing(2)
            row = QHBoxLayout()
            row.setSpacing(2)
            for key, text, glyph, callback in actions:
                button = QToolButton()
                button.setText(text)
                button.setIcon(icon(glyph, '#d6d6d6', 23))
                button.setIconSize(QSize(23, 23))
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setFixedSize(78, 55)
                if key == 'select':
                    button.setCheckable(True)
                    button.toggled.connect(self._selection_toggled)
                else:
                    button.clicked.connect(callback)
                row.addWidget(button)
                self._actions[key] = button
            col.addLayout(row)
            col.addWidget(QLabel(title, alignment=Qt.AlignCenter, objectName='ribbonCaption'))
            ribbon_row.addWidget(group)
        ribbon_row.addStretch(1)
        root.addWidget(ribbon)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)
        root.addWidget(content, 1)
        self.content_splitter = QSplitter(Qt.Vertical)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(2)
        self.content_splitter.splitterMoved.connect(self._log_splitter_moved)
        self._log_height = 200
        content_layout.addWidget(self.content_splitter, 1)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        side_column = QSplitter(Qt.Vertical)
        side_column.setChildrenCollapsible(False)
        side_column.setMinimumWidth(290)
        side_column.setMaximumWidth(420)
        self.panel = CloudTreePanel(self.session)
        self.panel.remove_requested.connect(self._remove_with_confirm)
        self.panel.clear_requested.connect(self._clear_with_confirm)
        self.panel.restore_requested.connect(self.restore_last_removal)
        self.panel.visibility_changed.connect(self._visibility_changed)
        self.panel.current_changed.connect(self._current_changed)
        self.panel.selection_changed.connect(self._refresh_controls)
        side_column.addWidget(self.panel)

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
        data_note.setObjectName('mutedLabel')
        data_form.addRow(data_note)
        form_col.addWidget(data_group)

        seg_group = QGroupBox('02  框选分割')
        seg_form = QFormLayout(seg_group)
        self.seg_state = QLabel('未框选')
        self.seg_state.setWordWrap(True)
        seg_form.addRow(self.seg_state)
        self.seg_in_button = QPushButton('保留框内')
        self.seg_in_button.clicked.connect(lambda: self._apply_segment(True))
        seg_form.addRow(self.seg_in_button)
        self.seg_out_button = QPushButton('保留框外')
        self.seg_out_button.clicked.connect(lambda: self._apply_segment(False))
        seg_form.addRow(self.seg_out_button)
        self.seg_discard_button = QPushButton('放弃框选')
        self.seg_discard_button.clicked.connect(lambda: self._discard_segment('已放弃框选暂存。'))
        seg_form.addRow(self.seg_discard_button)
        seg_note = QLabel('工具条“多边形框选”进入绘制：左键加顶点，Alt+左键撤点，右键或双击封闭；'
                          '封闭后在此执行分割，舍去部分作为分支图层保留。')
        seg_note.setWordWrap(True)
        seg_note.setObjectName('mutedLabel')
        seg_form.addRow(seg_note)
        form_col.addWidget(seg_group)

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
        side_column.addWidget(scroll)
        side_column.setSizes([260, 560])
        body.addWidget(side_column)

        stage = QWidget()
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(6)
        view_bar = QWidget()
        bar = QHBoxLayout(view_bar)
        bar.setContentsMargins(2, 0, 2, 0)
        bar.setSpacing(6)
        bar.addWidget(QLabel('3D 点云视图', objectName='viewTitle'))
        bar.addStretch(1)
        for name in ['等轴测', '顶视', '正视', '右视']:
            button = QPushButton(name)
            button.clicked.connect(lambda checked=False, value=name: self.canvas.set_view(value))
            bar.addWidget(button)
        stage_layout.addWidget(view_bar)
        self.canvas = create_canvas(renderer=self._renderer)
        self.canvas.status_changed.connect(self._render_status)
        if hasattr(self.canvas, 'render_failed'):
            self.canvas.render_failed.connect(self._renderer_failed)
        self._view_layout = stage_layout
        stage_layout.addWidget(self.canvas, 1)
        self._make_overlay()
        details = QWidget()
        self.details_bar = details
        details_layout = QHBoxLayout(details)
        details_layout.setContentsMargins(4, 0, 0, 0)
        self.details = QLabel('选择图层查看点数和数据来源', objectName='mutedLabel')
        self.details.setWordWrap(True)
        details_layout.addWidget(self.details, 1)
        self.reset_button = QPushButton('适配全部')
        self.reset_button.clicked.connect(self._fit)
        details_layout.addWidget(self.reset_button)
        stage_layout.addWidget(details)
        body.addWidget(stage)
        body.setStretchFactor(1, 1)
        body.setSizes([320, 1120])
        self.content_splitter.addWidget(body)
        self.content_splitter.setStretchFactor(0, 1)

        self.logs = ActivityLogPanel(docked=True)
        self.logs.setMinimumHeight(140)
        self.content_splitter.addWidget(self.logs)
        self.content_splitter.setStretchFactor(1, 0)
        self.logs.attach_logger(logger)
        self.logs.closed.connect(lambda: self.log_toggle.setChecked(False))
        self.logs.hide()

        bottom = QWidget()
        bottom_line = QHBoxLayout(bottom)
        bottom_line.setContentsMargins(10, 0, 10, 0)
        bottom_line.setSpacing(12)
        self.state_label = QLabel('待机 · 离线后处理', objectName='statusBar')
        bottom_line.addWidget(self.state_label)
        self.status = QLabel(objectName='statusBar')
        self.status.setWordWrap(True)
        bottom_line.addWidget(self.status, 1)
        root.addWidget(bottom)
        self.latest_status = QLabel('就绪', objectName='statusBar')
        self.latest_status.setMaximumHeight(28)
        root.addWidget(self.latest_status)

    def _make_overlay(self):
        self.overlay = PolygonSelectionOverlay(self.canvas)
        self.overlay.polygon_confirmed.connect(self._polygon_confirmed)
        self.overlay.cancelled.connect(self._selection_cancelled)

    def _log_splitter_moved(self, *_):
        if self.logs.isVisible():
            self._log_height = self.content_splitter.sizes()[1]

    def _toggle_logs(self, visible):
        self.latest_status.setVisible(not visible)
        self.details_bar.setVisible(not (visible and self.height() < 800))
        if visible:
            self.canvas.setMinimumHeight(140)
            self.panel.setMinimumHeight(80)
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
            self.panel.setMinimumHeight(180)

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
        return self._current_index

    def _current_changed(self, index):
        if index != self._current_index:
            self._invalidate_segment('当前图层已切换')
        self._current_index = index
        self._refresh_details()
        self._refresh_controls()

    def _refresh(self, fit=False, select=None):
        self.canvas.set_layers(self.session.layers, fit=fit)
        self.panel.refresh(select=self._current_index if select is None else select)
        current = self.panel.current_index()
        if current != self._current_index:
            self._current_index = current
        self._refresh_details()
        self._refresh_controls()

    def _refresh_details(self):
        idx = self._current_index
        if idx is None or idx >= len(self.session.layers):
            self.details.setText('选择图层查看点数和数据来源')
            self.details.setToolTip('')
        else:
            layer = self.session.layers[idx]
            self.details.setText(f'{layer.name}  /  {len(layer.points):,} 点  /  {layer.source}')
            self.details.setToolTip(layer.source)
        self._refresh_controls()

    def _refresh_controls(self):
        available = not self._busy
        selected = self._current_index is not None
        staged = self._segment is not None
        self._actions['open'].setEnabled(available)
        self._actions['export'].setEnabled(available and any(l.visible for l in self.session.layers))
        self._actions['select'].setEnabled(available and selected and not self.overlay.active)
        if not available or not selected:
            self._actions['select'].setChecked(False)
        self._actions['merge'].setEnabled(available and len(self.panel.selected_indices()) >= 2)
        self._actions['undo'].setEnabled(available and self.session.can_undo)
        self._actions['delete'].setEnabled(available and selected)
        self.panel.set_enabled(available)
        self.seg_in_button.setEnabled(available and staged)
        self.seg_out_button.setEnabled(available and staged)
        self.seg_discard_button.setEnabled(available and (staged or self.overlay.active))
        self.voxel_button.setEnabled(available and selected)
        self.random_button.setEnabled(available and selected)
        self.voxel_size.setEnabled(available)
        self.sample_ratio.setEnabled(available)
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

    def _visibility_changed(self, index, visible):
        if 0 <= index < len(self.session.layers):
            self.session.layers[index].visible = visible
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

    def apply_polygon_split(self, layer_index, polygon_xy, keep_inside):
        polygon = [(float(x), float(y)) for x, y in polygon_xy]
        if len(polygon) < 3:
            self.log('多边形顶点不足 3 个，无法分割。', 'warn')
            return None
        if not 0 <= layer_index < len(self.session.layers):
            self.log('请先选择要分割的图层。', 'warn')
            return None
        layer = self.session.layers[layer_index]
        if not len(layer.points):
            self.log(f'{layer.name}：图层为空，无法分割。', 'warn')
            return None
        canvas = self.canvas
        mask = polygon_crop_mask(layer.points, polygon, center=canvas.center,
                                 rotation_matrix=canvas.rotation.matrix, extent=canvas.extent,
                                 zoom=canvas.zoom, pan=canvas.pan,
                                 width=max(1, canvas.width()), height=max(1, canvas.height()))
        inside = int(mask.sum())
        outside = len(layer.points) - inside
        keep_mask = mask if keep_inside else ~mask
        remainder_mask = ~keep_mask
        mode_text = '框内' if keep_inside else '框外'
        if not keep_mask.any():
            self.log(f'{layer.name}：保留{mode_text}将清空图层，已取消分割。', 'warn')
            return None
        self._invalidate_segment('图层数据已变化')
        self.session.snapshot()
        kept = CloudLayer(layer.name, layer.points[keep_mask],
                          None if layer.colors is None else layer.colors[keep_mask],
                          layer.visible, layer.source + f' | 多边形分割(保留{mode_text})',
                          layer.source_points if layer.source_points is not None else len(layer.points))
        self.session.layers[layer_index] = kept
        branch = None
        if remainder_mask.any():
            branch_text = '框外' if keep_inside else '框内'
            branch = CloudLayer(f'{layer.name} · 分割({branch_text})',
                                layer.points[remainder_mask],
                                None if layer.colors is None else layer.colors[remainder_mask],
                                layer.visible, f'由 {layer.name} 多边形分割生成')
            self.session.layers.insert(layer_index + 1, branch)
        kept_count = int(keep_mask.sum())
        remainder_count = int(remainder_mask.sum())
        self.log(f'{layer.name}：多边形分割保留{mode_text} {kept_count:,} 点' +
                 (f'，舍去部分 {remainder_count:,} 点已生成分支图层。' if branch is not None else '，舍去部分为空。'))
        self._refresh(select=layer_index)
        return kept_count, remainder_count

    def merge_layers(self, indices):
        indices = sorted({int(i) for i in indices if isinstance(i, int) and 0 <= i < len(self.session.layers)})
        if len(indices) < 2:
            self.log('请至少选择 2 个图层进行合并。', 'warn')
            return None
        layers = [self.session.layers[i] for i in indices]
        points = np.vstack([layer.points for layer in layers])
        if not len(points):
            self.log('选中图层没有可合并的点。', 'warn')
            return None
        colors = (np.vstack([layer.colors for layer in layers])
                  if all(layer.colors is not None for layer in layers) else None)
        names = '、'.join(layer.name for layer in layers)
        merged = CloudLayer(f'合并点云 ({len(indices)} 层)', points, colors,
                            any(layer.visible for layer in layers), '合并自：' + names)
        self._invalidate_segment('图层数据已变化')
        self.session.snapshot()
        for index in reversed(indices):
            self.session.layers.pop(index)
        position = min(indices[0], len(self.session.layers))
        self.session.layers.insert(position, merged)
        self.log(f'已合并 {len(indices)} 个图层（{names}）→ {merged.name}：{len(points):,} 点；原图层已移除，可撤销。')
        self._refresh(select=position)
        return len(points)

    def merge_selected(self):
        indices = self.panel.selected_indices()
        if len(indices) < 2:
            self.log('请至少选择 2 个图层进行合并。', 'warn')
            return
        self.merge_layers(indices)

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
        self._invalidate_segment('图层数据已变化')
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
        self._invalidate_segment('图层数据已变化')
        self._replace_layer(layer_index, points, colors, f'随机抽样(保留 {ratio * 100:g}%)')
        self.log(f'{layer.name}：随机保留 {ratio * 100:g}%，{len(layer.points):,} → {len(points):,} 点。')
        self._refresh()
        return True

    def undo(self):
        self._invalidate_segment('撤销改变了图层数据')
        if self.session.undo():
            self.log('已撤销上一次编辑。')
            self._refresh()
        else:
            self.log('没有可撤销的编辑。', 'warn')

    def delete_layer(self):
        indices = self.panel.selected_indices()
        if not indices and self._current_index is not None:
            indices = [self._current_index]
        if indices:
            self._remove_with_confirm(indices)

    def _remove_with_confirm(self, indices):
        if self._busy or not indices:
            return
        answer = QMessageBox.question(self, '删除图层',
            f'将选中的 {len(indices)} 个图层移入回收区？可通过右键"恢复上次删除"还原。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.remove_layer_indices(indices)

    def _clear_with_confirm(self):
        if self._busy or not self.session.layers:
            return
        answer = QMessageBox.question(self, '清空项目',
            f'清空项目：将全部 {len(self.session.layers)} 个图层移入回收区？'
            '可通过右键"恢复上次删除"还原。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.remove_layer_indices(list(range(len(self.session.layers))))

    def remove_layer_indices(self, indices):
        indices = sorted({int(i) for i in indices if isinstance(i, int) and 0 <= i < len(self.session.layers)})
        if not indices:
            return False
        batch = []
        for index in reversed(indices):
            batch.append((index, self.session.layers.pop(index)))
        batch.reverse()
        self.session.removed.append(batch)
        names = '、'.join(layer.name for _, layer in batch)
        self._invalidate_segment('图层已被删除')
        self.log(f'已移入回收区 {len(batch)} 个图层：{names}；可右键"恢复上次删除"。')
        self._refresh(select=0)
        return True

    def restore_last_removal(self):
        if self._busy:
            return False
        if not self.session.removed:
            self.log('回收区为空，没有可恢复的删除。', 'warn')
            return False
        batch = self.session.removed.pop()
        for index, layer in batch:
            self.session.layers.insert(min(index, len(self.session.layers)), layer)
        names = '、'.join(layer.name for _, layer in batch)
        self._invalidate_segment('回收区恢复改变了图层列表')
        self.log(f'已恢复上次删除：{names}（{len(batch)} 个图层按原索引放回）。')
        self._refresh(select=batch[0][0])
        return True

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
            if self._segment is not None or self.overlay.active:
                self._discard_segment('已退出框选。')
            return
        if self._selected_index() is None:
            self.log('请先在图层树中选择要分割的图层。', 'warn')
            with QSignalBlocker(self._actions['select']):
                self._actions['select'].setChecked(False)
            return
        self._segment = None
        self.seg_state.setText('正在绘制多边形：左键加顶点，Alt+左键撤点，右键封闭。')
        self.overlay.activate()
        self.log('已进入框选模式：左键加顶点，Alt+左键撤销顶点，右键或双击封闭，Esc 取消。')
        self._refresh_controls()

    def _polygon_confirmed(self, polygon):
        idx = self._selected_index()
        if idx is None or idx >= len(self.session.layers):
            self.log('请先选择要分割的图层。', 'warn')
            self._discard_segment()
            return
        layer = self.session.layers[idx]
        canvas = self.canvas
        mask = polygon_crop_mask(layer.points, polygon, center=canvas.center,
                                 rotation_matrix=canvas.rotation.matrix, extent=canvas.extent,
                                 zoom=canvas.zoom, pan=canvas.pan,
                                 width=max(1, canvas.width()), height=max(1, canvas.height()))
        inside = int(mask.sum())
        outside = len(layer.points) - inside
        self._segment = dict(polygon=polygon, layer_index=idx)
        self.overlay.show_confirmed(f'框内 {inside:,} 点 / 框外 {outside:,} 点')
        self.seg_state.setText(f'已封闭 {len(polygon)} 顶点：框内 {inside:,} 点，框外 {outside:,} 点')
        self.log(f'多边形已封闭（{len(polygon)} 顶点）：框内 {inside:,} 点 / 框外 {outside:,} 点；请选择 保留框内 / 保留框外。')
        self._refresh_controls()

    def _apply_segment(self, keep_inside):
        staged = self._segment
        if staged is None:
            self.log('请先完成多边形框选。', 'warn')
            return
        self._segment = None
        self.seg_state.setText('未框选')
        if self.overlay.active:
            self.overlay.clear()
        with QSignalBlocker(self._actions['select']):
            self._actions['select'].setChecked(False)
        self.apply_polygon_split(staged['layer_index'], staged['polygon'], keep_inside)

    def _discard_segment(self, message=None):
        had = self._segment is not None or self.overlay.active
        self._segment = None
        self.seg_state.setText('未框选')
        if self.overlay.active:
            self.overlay.clear()
        with QSignalBlocker(self._actions['select']):
            self._actions['select'].setChecked(False)
        if message and had:
            self.log(message)
        self._refresh_controls()

    def _invalidate_segment(self, reason=''):
        if self._segment is not None:
            self._discard_segment(f'框选暂存已失效：{reason}。')

    def _selection_cancelled(self):
        self._discard_segment('已取消框选。')

    def add_layer(self, layer, fit=None):
        self._invalidate_segment('图层列表已变化')
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
            '可用：打开/导出点云（ply/pcd/xyz/pts，mm/m 源单位）、多图层显隐与回收区删除、\n'
            '多边形分割（左键加顶点、Alt+左键撤点、右键封闭；保留框内/框外，舍去部分生成分支图层）、\n'
            '多选合并图层、体素与随机下采样、撤销（8 步）。\n'
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
