"""Top-right image/marker inspector. Reusable by the workbench and replay."""
from html import escape
import numpy as np
from PySide6.QtCore import Qt, QEvent, QPointF, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
)
from ..core.marker_display import (
    GREEN, RED, YELLOW, MarkerDisplay, classify_markers, cumulative_world_markers,
)


def load_image(image):
    if isinstance(image, QImage):
        return image.copy()
    if isinstance(image, np.ndarray):
        pixels = image
        if pixels.dtype == np.uint16:
            pixels = (pixels/256).astype(np.uint8)
        pixels = np.ascontiguousarray(np.clip(pixels, 0, 255), dtype=np.uint8)
        if pixels.ndim == 2:
            return QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_Grayscale8).copy()
        if pixels.ndim == 3 and pixels.shape[2] == 3:
            return QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_BGR888).copy()
        raise ValueError('2D图像需为灰度或BGR数组')
    return QImage() if image is None else QImage(str(image))


class MarkerImage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.display = MarkerDisplay((), frozenset(), frozenset(), False)
        self.setFixedHeight(175)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#151c22'))
        if self.image.isNull():
            painter.setPen(QColor('#98a9b7'))
            painter.drawText(self.rect(), Qt.AlignCenter, '未关联当前帧2D图像')
            return
        scale = min(self.width()/self.image.width(), self.height()/self.image.height())
        width, height = self.image.width()*scale, self.image.height()*scale
        x, y = (self.width()-width)/2, (self.height()-height)/2
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(QRectF(x, y, width, height), self.image)
        painter.setRenderHint(QPainter.Antialiasing)
        for row in self.display.rows:
            px, py = x+row.xy[0]*scale, y+row.xy[1]*scale
            if not 0 <= row.xy[0] < self.image.width() or not 0 <= row.xy[1] < self.image.height():
                continue
            painter.setPen(QPen(QColor(row.color), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(px, py), 4, 4)


class WorldMarkerOverlay(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.points = []
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(viewport.rect())
        self.show()

    def set_points(self, points):
        self.points = points
        if hasattr(self.viewport, 'set_marker_annotations'):
            self.viewport.set_marker_annotations(points)
        self.update()

    def paintEvent(self, event):
        if not self.points:
            return
        view = self.viewport
        if hasattr(view, 'set_marker_annotations'):
            return  # GPU renders depth-tested rings; no GUI-thread cloud scan.
        xyz = np.asarray([point[1][0] for point in self.points])
        if not hasattr(view, 'rotation'):
            return
        camera = (xyz-view.center) @ view.rotation.matrix.T
        scale = min(view.width(), view.height())*1.65/view.extent*view.zoom
        pixels = camera[:, :2]*[scale, -scale] + [view.width()/2+view.pan[0], view.height()/2+view.pan[1]]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for (_, (_, color)), (x, y) in zip(self.points, pixels):
            if 5 <= x < self.width()-5 and 5 <= y < self.height()-5:
                painter.setPen(QPen(QColor(color), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(x, y), 5, 5)


class MarkerInspector(QFrame):
    def __init__(self, viewport, load_callback=None):
        super().__init__(viewport)
        self.viewport = viewport
        self.world_overlay = WorldMarkerOverlay(viewport)
        self.display = MarkerDisplay((), frozenset(), frozenset(), False)
        self.setObjectName('markerInspector')
        self.setStyleSheet('QFrame#markerInspector {background:#1c252d;border:1px solid #43525f;border-radius:6px;}')
        self.setFixedWidth(340)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        header = QHBoxLayout()
        self.title = QLabel('当前帧 · 2D与编码圆')
        header.addWidget(self.title, 1)
        self.collapse = QToolButton()
        self.collapse.setText('−')
        self.collapse.setCheckable(True)
        self.collapse.toggled.connect(self._collapse)
        header.addWidget(self.collapse)
        root.addLayout(header)
        self.body = QWidget()
        content = QVBoxLayout(self.body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6)
        self.image_view = MarkerImage()
        content.addWidget(self.image_view)
        self.counts = QLabel('绿 0　红 0　仅2D 0')
        content.addWidget(self.counts)
        self.pair_label = QLabel('参考帧：未指定；不显示共有红圈')
        self.pair_label.setWordWrap(True)
        content.addWidget(self.pair_label)
        self.world_counts = QLabel()
        content.addWidget(self.world_counts)
        self.ids = QLabel('尚无检测结果')
        self.ids.setWordWrap(True)
        self.ids.setMaximumHeight(67)
        content.addWidget(self.ids)
        buttons = QHBoxLayout()
        self.details_button = QPushButton('编码圆数据')
        self.details_button.clicked.connect(self.show_details)
        buttons.addWidget(self.details_button)
        if load_callback is not None:
            load = QPushButton('载入2D结果')
            load.clicked.connect(load_callback)
            buttons.addWidget(load)
        content.addLayout(buttons)
        root.addWidget(self.body)
        viewport.installEventFilter(self)
        viewport.view_changed.connect(self.world_overlay.update)
        self._position()
        self.show()
        self.raise_()

    def _collapse(self, checked):
        self.body.setVisible(not checked)
        self.collapse.setText('+' if checked else '−')
        self.adjustSize()
        self._position()

    def _position(self):
        self.setFixedWidth(max(230, min(340, self.viewport.width()-24)))
        compact = self.viewport.height() < 420
        self.image_view.setFixedHeight(max(24, min(90, self.viewport.height()-135)) if compact else 175)
        self.counts.setVisible(self.viewport.height() >= 200)
        self.ids.setVisible(not compact)
        self.pair_label.setVisible(not compact)
        self.world_counts.setVisible(not compact)
        self.body.layout().invalidate()
        self.body.layout().activate()
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()
        self.move(max(8, self.viewport.width()-self.width()-12), 12)
        self.world_overlay.setGeometry(self.viewport.rect())

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self._position()
        return False

    def bind_viewport(self, viewport):
        self.viewport.removeEventFilter(self)
        self.viewport.view_changed.disconnect(self.world_overlay.update)
        self.viewport = viewport
        self.setParent(viewport)
        self.world_overlay.setParent(viewport)
        self.world_overlay.viewport = viewport
        viewport.installEventFilter(self)
        viewport.view_changed.connect(self.world_overlay.update)
        self.world_overlay.set_points(self.world_overlay.points)
        self._position()
        self.world_overlay.show()
        self.show()
        self.raise_()

    def set_frame(self, image, markers, *, frame_id=None, reference_id=None,
                  reference_markers=None, used_codes=None, rejected_codes=(),
                  registration_accepted=None, history=(), current_visible=True):
        loaded = load_image(image)
        if reference_id is None or reference_id == frame_id:
            reference_markers = None
        self.display = classify_markers(markers, reference_markers, used_codes=used_codes,
                                        rejected_codes=rejected_codes, registration_accepted=registration_accepted)
        self.image_view.image = loaded
        self.image_view.display = self.display
        self.image_view.update()
        self.title.setText(f'当前帧 {frame_id if frame_id is not None else "—"} · 编码圆')
        self.counts.setText(f'<span style="color:{GREEN}">● 绿 {self.display.green_count}</span>　'
                            f'<span style="color:{RED}">● 红 {self.display.red_count}</span>　'
                            f'<span style="color:{YELLOW}">● 仅2D {self.display.yellow_count}</span>')
        reference_text = str(reference_id) if reference_id is not None else '未指定'
        kind = '配准内点' if used_codes is not None else '共有可配对'
        self.pair_label.setText(f'2D检出 {len(self.display.rows)} / 3D有效 {self.display.green_count+self.display.red_count}\n'
                                f'参考帧 {reference_text} · 红圈：{kind}；黄圈：无有效3D')
        parts = []
        for color, label in [(GREEN, '有效'), (RED, '共有'), (YELLOW, '仅2D')]:
            codes = [str(row.code) for row in self.display.rows if row.color == color]
            text = ' · '.join(codes[:14]) + (' …' if len(codes) > 14 else '')
            if codes:
                parts.append(f'<span style="color:{color}">{label} ID：{escape(text)}</span>')
        self.ids.setText('<br>'.join(parts) or '尚无检测结果')
        self.details_button.setEnabled(bool(self.display.rows))
        points = cumulative_world_markers(self.display, history, current_visible)
        self.world_overlay.set_points(points)
        self.world_counts.setText('累积3D标记：绿 %d / 红 %d' % (
            sum(item[1][1] == GREEN for item in points), sum(item[1][1] == RED for item in points)))
        self._position()
        self.raise_()

    def show_details(self):
        dialog = QDialog(self.window())
        dialog.setWindowTitle('当前帧编码圆数据（相机坐标 mm）')
        dialog.resize(900, 450)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(self.display.rows), 8)
        table.setHorizontalHeaderLabels(['ID', '状态', '图像X(px)', '图像Y(px)', '3D X', '3D Y', '3D Z', '说明'])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        for i, row in enumerate(self.display.rows):
            values = [row.code, row.status, *[f'{v:.2f}' for v in row.xy],
                      *([f'{v:.3f}' for v in row.xyz] if row.xyz else ['—']*3),
                      '显示颜色不代表测量精度']
            for j, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setForeground(QColor(row.color))
                table.setItem(i, j, item)
        layout.addWidget(table)
        dialog.exec()
