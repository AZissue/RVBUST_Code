"""Industrial presentation of production controls, with reversible layout mounts.

There is one set of controls, signals, data models and renderers per business mode.
Changing presentation never instantiates a camera service or connects an action.
"""
from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedLayout, QSplitter, QScrollArea, QGroupBox, QLabel, QToolButton, QButtonGroup)


class _Viewport(QWidget):
    view_changed = Signal()


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
            workspace._camera_grid.focus_changed.connect(self._camera_focus_changed)
            self.grid = QSplitter(Qt.Horizontal)
            self.grid.setChildrenCollapsible(False)
            stage.addWidget(self.grid, 1)
            self._mount(workspace._camera_grid, self.grid)
            self._mount(workspace._viewer, self.grid)
            self.grid.setStretchFactor(0, 1)
            self.grid.setStretchFactor(1, 2)
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
            self.side_column.setSizes([320, 210, 440] if getattr(self, 'calibration_panel', None) else [320, 440])

    def activate(self, enabled):
        if self.active == enabled:
            return
        if enabled:
            self._split_sizes = {mount.layout: mount.layout.sizes() for mount in self.mounts
                                 if isinstance(mount.layout, QSplitter)}
            for mount in self.mounts:
                mount.move()
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
                self.workspace._camera_grid.set_overview(False)
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
        viewer = self.workspace.viewer if self.mode == 'turntable' else self.workspace._viewer
        viewer.set_industrial(enabled)
        if self.calibration_panel and enabled:
            self.calibration_panel.refresh()
        if self.inspector and enabled:
            self.inspector.bind_viewport(viewer.viewer().canvas)
            viewer.viewer().canvas_changed.connect(self._bind_canvas)

    def _bind_canvas(self, canvas):
        if self.active:
            self.inspector.bind_viewport(canvas)

    def maximize(self, enabled):
        self.side_column.setVisible(not enabled)
        self.sidebar.setVisible(not enabled and (self.legacy_panel is None or self.legacy_toggle.isChecked()))
        if self.overlay:
            self.overlay.setVisible(False if self.inspector else not enabled)
        if self.inspector:
            self.inspector.setVisible(not enabled and not self._database_result)
        if self.mode == 'multi_cam':
            self.view_bar.setVisible(not enabled)
            if enabled:
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
        self.workspace._camera_grid.setVisible(view != '3d')
        self.workspace._viewer.setVisible(view != '2d')
        if view == 'joint' and resize:
            count = len(self.workspace._camera_grid.camera_ids())
            self.grid.setSizes([380 if count <= 2 else 540, 820])

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
            if self._multi_view == '2d':
                self.set_multi_view('joint')
        elif self.inspector:
            self.inspector.hide()

    def restore_business_image(self):
        self._database_result = False
        if self.mode == 'multi_cam':
            self.workspace._camera_grid.show_database_frame(None)
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
