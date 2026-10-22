"""Industrial presentation of production controls, with reversible layout mounts.

There is one set of controls, signals, data models and renderers per business mode.
Changing presentation never instantiates a camera service or connects an action.
"""
from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal, QPoint, QObject, QEvent, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedLayout, QSplitter, QScrollArea, QGroupBox, QLabel, QToolButton, QButtonGroup, QComboBox, QSizePolicy)


class _Viewport(QWidget):
    view_changed = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view_changed.emit()


class _PreviewAnchor(QObject):
    """Follow the final canvas geometry, including renderer replacements."""
    def __init__(self, presentation):
        super().__init__(presentation.viewport)
        self.presentation = presentation
        self.canvas = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.position)

    def bind(self, canvas):
        if self.canvas is not None:
            try:
                self.canvas.removeEventFilter(self)
            except RuntimeError:
                pass  # The renderer may already have destroyed its old canvas.
        self.canvas = canvas
        if canvas is not None:
            canvas.installEventFilter(self)
            self.schedule()

    def schedule(self):
        if not self.timer.isActive():
            self.timer.start(0)

    def position(self):
        if self.presentation.active:
            self.presentation._size_preview()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show):
            self.schedule()
        return False


def _locate(layout, widget):
    if layout is None:
        return None
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            return layout, index
        if item.layout():
            found = _locate(item.layout(), widget)
            if found:
                return found
    return None


@dataclass
class _Mount:
    widget: QWidget
    parent: QWidget
    layout: object
    index: int
    stretch: int
    minimum: object
    maximum: object
    target: object

    @classmethod
    def capture(cls, widget, target):
        parent = widget.parentWidget()
        if isinstance(parent, QSplitter):
            layout, index, stretch = parent, parent.indexOf(widget), 0
        else:
            found = _locate(parent.layout(), widget)
            if found is None:
                raise RuntimeError(f'Cannot mount {type(widget).__name__}')
            layout, index = found
            stretch = layout.stretch(index) if hasattr(layout, 'stretch') else 0
        return cls(widget, parent, layout, index, stretch,
                   widget.minimumSize(), widget.maximumSize(), target)

    def move(self):
        self.widget.setMinimumSize(0, 0)
        self.widget.setMaximumSize(16777215, 16777215)
        # Controls belong before the trailing stretch. Appending after it can
        # push the entire sidebar down once duplicate action buttons are hidden.
        count = self.target.count()
        if isinstance(self.target, (QVBoxLayout, QHBoxLayout)) and count and self.target.itemAt(count-1).spacerItem():
            self.target.insertWidget(count-1, self.widget)
        else:
            self.target.addWidget(self.widget)
        self.widget.show()

    def restore(self):
        if isinstance(self.layout, QSplitter):
            self.layout.insertWidget(self.index, self.widget)
        else:
            self.layout.insertWidget(self.index, self.widget, self.stretch)
        self.widget.setMinimumSize(self.minimum)
        self.widget.setMaximumSize(self.maximum)
        self.widget.show()


class IndustrialPresentation:
    def __init__(self, workspace, mode):
        self.workspace = workspace
        self.mode = mode
        self.active = False
        self.mounts = []
        self._split_sizes = {}
        # Move the existing root intact; it remains the classic presentation.
        self.classic = QWidget()
        self.classic.setLayout(workspace.layout())
        self.stack = QStackedLayout(workspace)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.classic)
        self.surface = QWidget()
        self.surface.setObjectName('industrialSurface')
        root = QVBoxLayout(self.surface)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        self.body = QSplitter(Qt.Horizontal)
        self.body.setChildrenCollapsible(False)
        root.addWidget(self.body, 1)
        self.sidebar = QScrollArea()
        self.sidebar.setWidgetResizable(True)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar.setMinimumWidth(290)
        self.sidebar.setMaximumWidth(420)
        content = QWidget()
        self.controls = QVBoxLayout(content)
        self.controls.setContentsMargins(0, 0, 6, 0)
        self.controls.setSpacing(8)
        self.sidebar.setWidget(content)
        self.side_column = QSplitter(Qt.Vertical)
        self.side_column.setChildrenCollapsible(False)
        self.side_column.setMinimumWidth(290)
        self.side_column.setMaximumWidth(420)
        from core.frame_database import FrameDatabase
        from .frame_database import FrameBrowser
        if not hasattr(workspace, 'frame_database'):
            workspace.frame_database = FrameDatabase(mode)
        self.frame_browser = FrameBrowser(workspace.frame_database)
        self.side_column.addWidget(self.frame_browser)
        self.legacy_panel = None
        if mode in ('multi_cam', 'mobile_chain', 'turntable'):
            self.legacy_panel = QWidget()
            legacy_layout = QVBoxLayout(self.legacy_panel)
            legacy_layout.setContentsMargins(0, 0, 0, 0)
            legacy_layout.setSpacing(4)
            self.legacy_toggle = QToolButton()
            self.legacy_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.legacy_toggle.setCheckable(True)
            self.legacy_toggle.setMinimumHeight(30)
            self.legacy_toggle.toggled.connect(self.set_legacy_expanded)
            legacy_layout.addWidget(self.legacy_toggle)
            legacy_layout.addWidget(self.sidebar, 1)
            self.side_column.addWidget(self.legacy_panel)
            self.set_legacy_expanded(False)
        else:
            self.side_column.addWidget(self.sidebar)
        self.side_column.setSizes([320, 440])
        self.calibration_panel = None
        if mode == 'turntable':
            from .widgets.turntable_calibration_panel import TurntableCalibrationPanel
            self.frame_browser.setMinimumHeight(200)
            self.frame_browser.tree.setMinimumHeight(90)
            self.calibration_panel = TurntableCalibrationPanel(workspace)
            self.side_column.insertWidget(1, self.calibration_panel)
            self.side_column.setSizes([400, 210, 30])
        if mode == 'multi_cam':
            self.side_scroll = QScrollArea()
            self.side_scroll.setWidgetResizable(True)
            self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.side_scroll.setMinimumWidth(310)
            self.side_scroll.setMaximumWidth(420)
            self.side_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
            self.side_scroll.setWidget(self.side_column)
            self.body.addWidget(self.side_scroll)
        else:
            self.body.addWidget(self.side_column)
        self.stage = QWidget()
        stage = QVBoxLayout(self.stage)
        stage.setContentsMargins(0, 0, 0, 0)
        stage.setSpacing(6)
        self.body.addWidget(self.stage)
        self.body.setStretchFactor(1, 1)
        self.body.setSizes([320, 1120])
        self.overlay = None
        self.inspector = None
        self._business_marker_image = None
        self._database_result = False
        self.grid = None
        self._multi_view = 'joint'
        self._view_before_focus = None
        if mode == 'multi_cam':
            self._mount(workspace._left_widget, self.controls)
            self._mount(workspace._right_widget, self.controls)
            self.calibration_panel = QScrollArea()
            self.calibration_panel.setWidgetResizable(True)
            self.calibration_panel.setMinimumHeight(140)
            result_content = QWidget()
            result_layout = QVBoxLayout(result_content)
            result_layout.setContentsMargins(0, 0, 0, 0)
            self._mount(workspace._gate_card, result_layout)
            self._mount(workspace._result_card, result_layout)
            result_layout.addStretch(1)
            self.calibration_panel.setWidget(result_content)
            self._calibration_styles = {widget: widget.styleSheet() for widget in
                (workspace._gate_card, workspace._result_card)}
            workspace._gate_card.setObjectName('multiGateCard')
            workspace._result_card.setObjectName('multiResultCard')
            self.side_column.insertWidget(1, self.calibration_panel)
            from .widgets.multi_camera_status import MultiCameraStatus
            self.camera_status = MultiCameraStatus(workspace)
            self.side_column.setSizes([360, 300, 30])
            self.frame_browser.calibration_selected.connect(self._show_calibration)
            self.view_bar = QWidget()
            bar = QHBoxLayout(self.view_bar)
            bar.setContentsMargins(0, 0, 0, 0)
            bar.setSpacing(4)
            bar.addWidget(QLabel('标定工作视图'))
            self.view_buttons = {}
            self.view_group = QButtonGroup(self.view_bar)
            for key, title in (('2d', '2D 对比'), ('joint', '联合视图'), ('3d', '3D 主视图')):
                button = QToolButton()
                button.setText(title)
                button.setCheckable(True)
                button.setStyleSheet('QToolButton {padding:5px 12px;border:1px solid #454545;background:#303030;}'
                    'QToolButton:checked {background:#563030;border-color:#d12d30;color:#ffffff;}')
                button.clicked.connect(lambda checked=False, value=key: self.set_multi_view(value))
                self.view_group.addButton(button)
                self.view_buttons[key] = button
                bar.addWidget(button)
            self.all_cameras_button = QToolButton()
            self.all_cameras_button.setText('全部相机')
            self.all_cameras_button.setEnabled(False)
            self.all_cameras_button.clicked.connect(lambda: workspace._camera_grid.focus_camera())
            bar.addWidget(self.all_cameras_button)
            bar.addStretch(1)
            hint = QLabel('双击画面放大 / 返回')
            hint.setStyleSheet('color:#aaaaaa;')
            bar.addWidget(hint)
            stage.addWidget(self.view_bar)
            self.preview_all = QToolButton()
            self.preview_all.setText('全部预览')
            self.preview_all.setToolTip('开启全部已连接相机的2D取景')
            self.preview_all.clicked.connect(lambda: self._preview_all(True))
            self.preview_stop = QToolButton()
            self.preview_stop.setText('停止')
            self.preview_stop.setToolTip('停止全部相机的2D取景')
            self.preview_stop.clicked.connect(lambda: self._preview_all(False))
            workspace._camera_grid.focus_changed.connect(self._camera_focus_changed)
            workspace._camera_grid.database_focus_requested.connect(self._focus_database)
            self.grid = QSplitter(Qt.Horizontal)
            self.grid.setChildrenCollapsible(False)
            self.grid.setHandleWidth(8)
            stage.addWidget(self.grid, 1)
            self.viewport = _Viewport()
            self.viewport.view_changed.connect(self._size_preview)
            self.scene = QGridLayout(self.viewport)
            self.scene.setContentsMargins(0, 0, 0, 0)
            self.grid.addWidget(self.viewport)
            base = QWidget()
            base_layout = QVBoxLayout(base)
            base_layout.setContentsMargins(0, 0, 0, 0)
            self._mount(workspace._viewer, base_layout)
            self.scene.addWidget(base, 0, 0)
            self.preview_panel = QWidget()
            self.preview_panel.setObjectName('multiPreviewPanel')
            self.preview_panel.setStyleSheet('''
                QWidget#multiPreviewPanel {background:#252525;border:1px solid #484848;border-radius:4px;}
                QWidget#multiPreviewPanel QToolButton {background:transparent;border:0;padding:4px 6px;color:#cccccc;}
                QWidget#multiPreviewPanel QToolButton:hover {background:#3a3a3a;}
                QWidget#multiPreviewPanel QToolButton:checked {color:#eeeeee;}
            ''')
            preview_layout = QVBoxLayout(self.preview_panel)
            preview_layout.setContentsMargins(4, 4, 4, 4)
            self.preview_toggle = QToolButton()
            self.preview_toggle.setText('2D 预览')
            self.preview_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.preview_toggle.setArrowType(Qt.DownArrow)
            self.preview_toggle.setCheckable(True)
            self.preview_toggle.setChecked(True)
            self.preview_toggle.toggled.connect(self._toggle_preview)
            preview_header = QHBoxLayout()
            preview_header.addWidget(self.preview_toggle)
            preview_header.addStretch(1)
            preview_header.addWidget(self.preview_all)
            preview_header.addWidget(self.preview_stop)
            preview_layout.addLayout(preview_header)
            self.fill_button = QToolButton()
            self.fill_button.setObjectName('previewCrop')
            self.fill_button.setText('裁边')
            self.fill_button.setToolTip('保持比例铺满，可裁去图像边缘；取消后显示完整图像，标记同步缩放。')
            self.fill_button.setCheckable(True)
            self.fill_button.setChecked(False)
            self.fill_button.toggled.connect(self._fill_images)
            preview_header.addWidget(self.fill_button)
            self.fill_button.setStyleSheet('QToolButton#previewCrop:checked {background:#493232;border:1px solid #704242;}')
            self.preview_images = QWidget()
            images_layout = QVBoxLayout(self.preview_images)
            images_layout.setContentsMargins(0, 0, 0, 0)
            self._mount(workspace._camera_grid, images_layout)
            preview_layout.addWidget(self.preview_images, 1)
            self.preview_panel.setParent(self.viewport)
            self.grid.setStretchFactor(0, 1)
            self.layout_choice = QComboBox()
            for text, columns in (('自动布局', 0), ('1 列', 1), ('2 列', 2), ('3 列', 3), ('4 列', 4)):
                self.layout_choice.addItem(text, columns)
            self.layout_choice.setMaximumWidth(110)
            self.layout_choice.currentIndexChanged.connect(self._change_camera_layout)
            preview_layout.insertWidget(1, self.layout_choice)
            self.preview_anchor = _PreviewAnchor(self)
            self._preview_signal_sources = set()
            self.preview_panel.raise_()
        else:
            viewport = _Viewport()
            self.viewport = viewport
            scene = QGridLayout(viewport)
            scene.setContentsMargins(0, 0, 0, 0)
            stage.addWidget(viewport, 1)
            base = QWidget()
            base_lo = QVBoxLayout(base)
            base_lo.setContentsMargins(0, 0, 0, 0)
            viewer = workspace._viewer if mode == 'mobile_chain' else workspace.viewer
            self._mount(viewer, base_lo)
            scene.addWidget(base, 0, 0)
            self.overlay = QGroupBox('当前相机 · 2D图像与编码圆')
            self.overlay.setMaximumSize(390, 310)
            self.overlay.setMinimumSize(260, 200)
            preview = QVBoxLayout(self.overlay)
            preview.setContentsMargins(6, 12, 6, 6)
            scene.addWidget(self.overlay, 0, 0, Qt.AlignTop | Qt.AlignRight)
            from ui_common.industrial_scene.marker_inspector import MarkerInspector
            self.inspector = MarkerInspector(viewport, show_world=False)
            self.inspector.hide()
            if mode == 'mobile_chain':
                self._mount(workspace._live_view, self.controls)
                workspace._live_view.frame_changed.connect(self._preview_frame)
                workspace._live_view.marker_context_changed.connect(self._marker_context)
                buttons = QGroupBox('采集与会话')
                actions = QVBoxLayout(buttons)
                self.controls.addWidget(buttons)
                for name in ('_btn_preview','_btn_capture','_btn_undo','_btn_recapture',
                             '_btn_save','_btn_offline_load','_btn_delete_node'):
                    self._mount(getattr(workspace, name), actions)
                self._mount(workspace._timeline, self.controls)
                # Classic evaluation widgets stay in the inactive classic page.
                # Industrial evaluation is presented by the shell status bar.
            else:
                self._mount(workspace._left_panel, self.controls)
                self._mount(workspace._preview_panel, preview)
        # Turntable already contains a scroll area; let it fill the sidebar.
        if mode != 'turntable':
            self.controls.addStretch(1)
        self.stack.addWidget(self.surface)
        self.stack.setCurrentWidget(self.classic)

    def _mount(self, widget, target):
        self.mounts.append(_Mount.capture(widget, target))

    def set_legacy_expanded(self, expanded):
        """Keep production controls mounted and reachable during sidebar migration."""
        if self.legacy_panel is None:
            return
        self.legacy_toggle.setChecked(expanded)
        self.legacy_toggle.setText('旧版操作栏 · 收起' if expanded else '旧版操作栏 · 展开')
        self.legacy_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.sidebar.setVisible(expanded)
        self.legacy_panel.setMaximumHeight(16777215 if expanded else 30)
        if expanded:
            self.side_column.setSizes([260, 220, 300] if self.mode == 'multi_cam' else
                [320, 210, 440] if getattr(self, 'calibration_panel', None) else [320, 440])

    def activate(self, enabled):
        if self.active == enabled:
            return
        if enabled:
            self._split_sizes = {mount.layout: mount.layout.sizes() for mount in self.mounts
                                 if isinstance(mount.layout, QSplitter)}
            for mount in self.mounts:
                mount.move()
            if self.mode == 'multi_cam':
                self._style_calibration(True)
            if self.mode == 'mobile_chain':
                self.workspace._timeline.setMinimumHeight(220)
                self.workspace._live_view._canvas.hide()
                self.workspace._live_view.setMaximumHeight(100)
            if self.grid:
                self.workspace._camera_grid.set_overview(True)
            self.stack.setCurrentWidget(self.surface)
            if self.grid:
                self.set_multi_view(self._multi_view)
            if self.overlay:
                if self.inspector:
                    self.overlay.hide()
                    self.inspector.show()
                    self.inspector.raise_()
                    if self.mode == 'turntable':
                        self.workspace._preview_panel.hide()
                    elif self.workspace._live_view.marker_context:
                        self._marker_context(*self.workspace._live_view.marker_context)
                    else:
                        self._preview_frame(self.workspace._live_view._current_pixmap)
                else:
                    self.overlay.raise_()
        else:
            self.maximize(False)
            if self.grid:
                self._fill_images(False)
                self.workspace._camera_grid.set_overview(False)
                self._style_calibration(False)
            if self.inspector:
                self.inspector.bind_viewport(self.viewport)
            # Captured indices are original indices; restore in that order per layout.
            for mount in sorted(self.mounts, key=lambda item: item.index):
                mount.restore()
            for splitter, sizes in self._split_sizes.items():
                splitter.setSizes(sizes)
            if self.mode == 'mobile_chain':
                self.workspace._live_view._canvas.show()
            if self.inspector:
                self.inspector.hide()
            self.stack.setCurrentWidget(self.classic)
        self.active = enabled
        if self.mode == 'multi_cam' and enabled:
            self.workspace.refresh_marker_pair()
        if self.mode == 'multi_cam':
            self.camera_status.set_active(enabled)
            if not enabled:
                self.preview_anchor.bind(None)
        viewer = self.workspace.viewer if self.mode == 'turntable' else self.workspace._viewer
        viewer.set_industrial(enabled)
        if self.mode == 'multi_cam' and enabled:
            renderer = viewer.viewer()
            self.preview_anchor.bind(renderer.canvas)
            if hasattr(renderer, 'canvas_changed') and renderer not in self._preview_signal_sources:
                renderer.canvas_changed.connect(self.preview_anchor.bind)
                self._preview_signal_sources.add(renderer)
        if self.calibration_panel and enabled and self.mode == 'turntable':
            self.calibration_panel.refresh()
        if self.inspector and enabled:
            self.inspector.bind_viewport(viewer.viewer().canvas)
            viewer.viewer().canvas_changed.connect(self._bind_canvas)

    def _bind_canvas(self, canvas):
        if self.active:
            self.inspector.bind_viewport(canvas)

    def maximize(self, enabled):
        if hasattr(self, 'side_scroll'):
            self.side_scroll.setVisible(not enabled)
        self.side_column.setVisible(not enabled)
        self.sidebar.setVisible(not enabled and (self.legacy_panel is None or self.legacy_toggle.isChecked()))
        if self.overlay:
            self.overlay.setVisible(False if self.inspector else not enabled)
        if self.inspector:
            self.inspector.setVisible(not enabled and not self._database_result)
        if self.mode == 'multi_cam':
            self.view_bar.setVisible(not enabled)
            if enabled:
                self.preview_panel.hide()
                self.workspace._camera_grid.hide()
                self.workspace._viewer.show()
            else:
                self.set_multi_view(self._multi_view, resize=False)

    def _preview_frame(self, pixmap):
        if self.inspector:
            self.set_marker_image(pixmap.toImage() if pixmap is not None else None, [])

    def set_multi_view(self, view, *, resize=True):
        if self.mode != 'multi_cam' or view not in ('2d', 'joint', '3d'):
            return
        self._multi_view = view
        self.view_buttons[view].setChecked(True)
        if view == '2d':
            if self.preview_panel.parentWidget() is not self.grid:
                self.grid.insertWidget(0, self.preview_panel)
            self.preview_panel.setMaximumSize(16777215, 16777215)
            self.preview_panel.setMinimumSize(0, 0)
            self.viewport.hide()
        else:
            if self.preview_panel.parentWidget() is not self.viewport:
                self.preview_panel.setParent(self.viewport)
            self.viewport.show()
            self._size_preview()
        self.preview_panel.setVisible(view != '3d')
        self.preview_images.setVisible(view == '2d' or self.preview_toggle.isChecked())
        self.layout_choice.setVisible(view == '2d' or self.preview_toggle.isChecked())
        self.fill_button.setVisible(view == '2d' or self.preview_toggle.isChecked())
        self.preview_all.setVisible(view == '2d' or self.preview_toggle.isChecked())
        self.preview_stop.setVisible(view == '2d' or self.preview_toggle.isChecked())
        self.workspace._camera_grid.setVisible(view != '3d')
        self.workspace._viewer.setVisible(view != '2d')
        self.preview_panel.raise_()
        self._fill_images(self.fill_button.isChecked())

    def _toggle_preview(self, expanded):
        if not expanded and self._multi_view == '2d':
            self.set_multi_view('joint')
        self.preview_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.preview_images.setVisible(expanded or self._multi_view == '2d')
        self.layout_choice.setVisible(expanded or self._multi_view == '2d')
        self.fill_button.setVisible(expanded or self._multi_view == '2d')
        self.preview_all.setVisible(expanded)
        self.preview_stop.setVisible(expanded)
        self._size_preview()

    def _fill_images(self, enabled):
        grid = self.workspace._camera_grid
        for card in list(grid._cards.values()) + ([grid._database_card] if grid._database_card else []):
            if hasattr(card._thumb, 'set_fill'):
                card._thumb.set_fill(enabled)

    def _size_preview(self):
        if not hasattr(self, 'preview_panel') or self._multi_view == '2d':
            return
        canvas = getattr(self.workspace._viewer.viewer(), 'canvas', None)
        top = canvas.mapTo(self.viewport, QPoint(0, 0)).y() + 12 if canvas else 46
        width = min(380, max(240, self.viewport.width()-24))
        grid = self.workspace._camera_grid
        cards = [grid._database_card] if grid._database_card else list(grid._cards.values())
        ratios = [card.current_frame().image_np.shape[1]/card.current_frame().image_np.shape[0]
                  for card in cards if card.current_frame() is not None and card.current_frame().image_np is not None]
        ratio = sum(ratios)/len(ratios) if ratios else 4/3
        expanded = self.preview_toggle.isChecked()
        height = min(620, max(40, self.viewport.height()-top-12),
                     int(max(1, len(cards))*((width-24)/ratio+94)+78)) if expanded else self.preview_toggle.sizeHint().height()+12
        self.preview_panel.setFixedSize(width, height)
        self.preview_panel.move(max(8, self.viewport.width()-width-12), top)
        self.preview_panel.raise_()

    def _change_camera_layout(self):
        columns = self.layout_choice.currentData()
        self.workspace._camera_grid.set_layout_columns(columns)
        if columns > 1:
            self.set_multi_view('2d')

    def _style_calibration(self, enabled):
        self.workspace._result_table.setVisible(not enabled or self.workspace._result_table.rowCount() > 0)
        self.workspace._matrix_values.setVisible(not enabled)
        for widget, original in self._calibration_styles.items():
            if not enabled:
                widget.setStyleSheet(original)
            else:
                name = widget.objectName()
                widget.setStyleSheet(f'QFrame#{name} {{background:#292929;border:1px solid #414141;border-radius:4px;}} '
                                    f'QFrame#{name} QLabel {{background:transparent;border:0;}}')

    def _preview_all(self, enabled):
        # Drive the production buttons, preserving backend permission checks.
        if enabled:
            self.restore_business_image()
        for card in self.workspace._camera_grid._cards.values():
            if card._btn_preview.isEnabled():
                card._btn_preview.setChecked(enabled)

    def _show_calibration(self):
        self.calibration_panel.show()
        self.side_column.setSizes([280, 330, 30])
        self.calibration_panel.ensureWidgetVisible(self.workspace._result_card)

    def _camera_focus_changed(self, camera_id):
        self.all_cameras_button.setEnabled(bool(camera_id))
        if camera_id:
            if self._view_before_focus is None:
                self._view_before_focus = self._multi_view
            self.set_multi_view('2d')
        elif self._view_before_focus is not None:
            previous, self._view_before_focus = self._view_before_focus, None
            self.set_multi_view(previous)
        elif self.active:
            self.set_multi_view(self._multi_view)

    def _focus_database(self):
        if self.active:
            self.set_multi_view('joint' if self._multi_view == '2d' else '2d')

    def _marker_context(self, frame, reference=None, accepted=None):
        if frame is None:
            self._preview_frame(None)
            return
        if reference is frame:
            reference = None
        self.set_marker_image(frame.image_np, frame.markers_all or frame.markers,
                              reference.markers_all or reference.markers if reference else None,
                              accepted, frame_id=getattr(frame, 'frame_id', '—'),
                              reference_id=getattr(reference, 'frame_id', '参考帧'))

    def set_marker_image(self, image, markers, reference=None, accepted=None,
                         *, frame_id='—', reference_id='参考帧'):
        self._business_marker_image = ((image, markers, reference, accepted),
                                       dict(frame_id=frame_id, reference_id=reference_id))
        if self.inspector:
            self.inspector.set_frame(image, markers or [], frame_id=frame_id,
                reference_id=reference_id if reference is not None else None,
                reference_markers=reference, registration_accepted=accepted,
                current_visible=False)

    def show_database_image(self, frame):
        self._database_result = False
        if self.mode == 'multi_cam':
            self.workspace._camera_grid.show_database_frame(frame)
            self.all_cameras_button.setEnabled(False)
            self.set_multi_view('joint')
            return
        self.inspector.set_frame(frame.image_np, frame.markers_all or frame.markers,
            frame_id=f'DB原始帧 {frame.frame_id:03d}', current_visible=False)
        self.inspector.show()
        self.inspector.raise_()

    def show_database_result(self):
        self._database_result = True
        if self.mode == 'multi_cam':
            self.workspace._camera_grid.show_database_frame(None)
            self._size_preview()
            if self._multi_view == '2d':
                self.set_multi_view('joint')
        elif self.inspector:
            self.inspector.hide()

    def restore_business_image(self):
        self._database_result = False
        if self.mode == 'multi_cam':
            self.workspace._camera_grid.show_database_frame(None)
            self._size_preview()
            self.all_cameras_button.setEnabled(bool(self.workspace._camera_grid._focused_id))
            self.workspace.refresh_marker_pair()
            return
        if self._business_marker_image:
            args, kwargs = self._business_marker_image
            self.set_marker_image(*args, **kwargs)
            self.inspector.setVisible(args[0] is not None)
        elif self.inspector:
            self.inspector.set_frame(None, [], current_visible=False)
            self.inspector.hide()


def set_presentation(workspace, mode, enabled):
    presentation = getattr(workspace, '_industrial', None)
    if presentation is None and enabled:
        presentation = IndustrialPresentation(workspace, mode)
        workspace._industrial = presentation
    if presentation:
        presentation.activate(enabled)
