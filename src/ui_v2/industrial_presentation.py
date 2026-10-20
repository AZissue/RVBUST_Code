"""Industrial presentation of production controls, with reversible layout mounts.

There is one set of controls, signals, data models and renderers per business mode.
Changing presentation never instantiates a camera service or connects an action.
"""
from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedLayout, QSplitter, QScrollArea, QGroupBox, QLabel)


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
        self.side_column.addWidget(self.sidebar)
        self.side_column.setSizes([320, 440])
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
        self._database_inspector = None
        self._business_marker_image = None
        self.grid = None
        if mode == 'multi_cam':
            self._mount(workspace._left_widget, self.controls)
            self._mount(workspace._right_widget, self.controls)
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
                self._mount(workspace._eval_card, stage)
                self._mount(workspace._stats_label, stage)
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
                self.grid.setSizes([580, 600])
            self.stack.setCurrentWidget(self.surface)
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
        if self.inspector and enabled:
            self.inspector.bind_viewport(viewer.viewer().canvas)
            viewer.viewer().canvas_changed.connect(self._bind_canvas)

    def _bind_canvas(self, canvas):
        if self.active:
            self.inspector.bind_viewport(canvas)

    def maximize(self, enabled):
        self.side_column.setVisible(not enabled)
        self.sidebar.setVisible(not enabled)
        if self.overlay:
            self.overlay.setVisible(False if self.inspector else not enabled)
        if self.inspector:
            self.inspector.setVisible(not enabled)
        if self._database_inspector:
            self._database_inspector.setVisible(not enabled and self.workspace._viewer._database_cloud is not None)
        if self.mode == 'multi_cam':
            self.workspace._camera_grid.setVisible(not enabled)
        if self.mode == 'mobile_chain':
            self.workspace._eval_card.setVisible(not enabled)
            self.workspace._stats_label.setVisible(not enabled)

    def _preview_frame(self, pixmap):
        if self.inspector:
            self.set_marker_image(pixmap.toImage() if pixmap is not None else None, [])

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
        inspector = self.inspector
        if inspector is None:
            # Multi-camera cards remain bound to acquisition/detection. Show
            # archived frames separately in the right viewport without replacing
            # the cards' current business frame objects.
            viewer = self.workspace._viewer.viewer()
            if self._database_inspector is None:
                from ui_common.industrial_scene.marker_inspector import MarkerInspector
                self._database_inspector = MarkerInspector(viewer.canvas, show_world=False)
                viewer.canvas_changed.connect(self._bind_database_canvas)
            inspector = self._database_inspector
            inspector.bind_viewport(viewer.canvas)
            inspector.show()
            inspector.raise_()
        inspector.set_frame(frame.image_np, frame.markers_all or frame.markers,
            frame_id=f'DB原始帧 {frame.frame_id}', current_visible=False)

    def _bind_database_canvas(self, canvas):
        if self._database_inspector:
            self._database_inspector.bind_viewport(canvas)

    def restore_business_image(self):
        if self._database_inspector:
            self._database_inspector.hide()
        if self._business_marker_image:
            args, kwargs = self._business_marker_image
            self.set_marker_image(*args, **kwargs)
        elif self.inspector:
            self.inspector.set_frame(None, [], current_visible=False)


def set_presentation(workspace, mode, enabled):
    presentation = getattr(workspace, '_industrial', None)
    if presentation is None and enabled:
        presentation = IndustrialPresentation(workspace, mode)
        workspace._industrial = presentation
    if presentation:
        presentation.activate(enabled)
