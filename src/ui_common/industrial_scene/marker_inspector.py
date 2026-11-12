"""Top-right image/marker inspector. Reusable by the workbench and replay."""
from html import escape
import numpy as np
from PySide6.QtCore import Qt, QEvent, QPointF, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QPolygonF
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
)
from .marker_display import (
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
        self.match_triangle = ()
        self.setFixedHeight(175)
        self.zoom = 1.0
        self.pan = QPointF()
        self._drag = None

    def wheelEvent(self,event):
        self.zoom=max(.2,min(20,self.zoom*(1.15 if event.angleDelta().y()>0 else 1/1.15)))
        self.update();event.accept()

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self._drag=event.position()

    def mouseMoveEvent(self,event):
        if self._drag is not None:
            self.pan+=event.position()-self._drag;self._drag=event.position();self.update()

    def mouseReleaseEvent(self,event):self._drag=None
    def mouseDoubleClickEvent(self,event):
        self.zoom=1.;self.pan=QPointF();self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#1c1c1c'))
        if self.image.isNull():
            painter.setPen(QColor('#aaaaaa'))
            painter.drawText(self.rect(), Qt.AlignCenter, '未关联当前帧2D图像')
            return
        scale = min(self.width()/self.image.width(), self.height()/self.image.height())*self.zoom
        width, height = self.image.width()*scale, self.image.height()*scale
        x, y = (self.width()-width)/2+self.pan.x(), (self.height()-height)/2+self.pan.y()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(QRectF(x, y, width, height), self.image)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.match_triangle:
            painter.setPen(QPen(QColor(YELLOW), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(QPolygonF([QPointF(x+px*scale, y+py*scale) for px, py in self.match_triangle]))
        for row in self.display.rows:
            px, py = x+row.xy[0]*scale, y+row.xy[1]*scale
            if not 0 <= row.xy[0] < self.image.width() or not 0 <= row.xy[1] < self.image.height():
                continue
            painter.setPen(QPen(QColor(row.color), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(px, py), 4, 4)
            if row.marker.get('marker_type') == 'unencoded_circle':
                painter.drawText(QPointF(px+6, py-6), str(row.code))


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
    def __init__(self, viewport, load_callback=None, *, show_world=True):
        super().__init__(viewport)
        self.viewport = viewport
        self.show_world = show_world
        self.world_overlay = WorldMarkerOverlay(viewport)
        self.display = MarkerDisplay((), frozenset(), frozenset(), False)
        self.setObjectName('markerInspector')
        self.setStyleSheet('QFrame#markerInspector {background:#242424;border:1px solid #505050;border-radius:6px;}')
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
        self.details_button = QPushButton('标记物数据')
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

    def set_embedded(self,enabled):
        self.embedded=enabled
        if enabled:
            self.setMinimumSize(0,0);self.setMaximumSize(16777215,16777215)
            self.collapse.hide();self.body.show()
            self.image_view.setMinimumHeight(120);self.image_view.setMaximumHeight(16777215)
            self.body.layout().setStretch(0,1)
            self.layout().setStretch(1,1)
        self._position()

    def _position(self):
        if getattr(self,'embedded',False):
            self.world_overlay.setGeometry(self.viewport.rect())
            return
        self.setFixedWidth(max(230, min(340, self.viewport.width()-24)))
        compact = self.viewport.height() < 420
        self.image_view.setFixedHeight(max(24, min(90, self.viewport.height()-135)) if compact else 175)
        self.counts.setVisible(self.viewport.height() >= 200)
        self.ids.setVisible(not compact)
        self.pair_label.setVisible(not compact)
        self.world_counts.setVisible(not compact and self.show_world)
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
        if not getattr(self,'embedded',False):
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
                  registration_accepted=None, history=(), current_visible=True,
                  recognition_state='', recognition_message='', marker_type='', match_triangle=()):
        loaded = load_image(image)
        if reference_id is None or reference_id == frame_id:
            reference_markers = None
        self.display = classify_markers(markers, reference_markers, used_codes=used_codes,
                                        rejected_codes=rejected_codes, registration_accepted=registration_accepted)
        self.image_view.image = loaded
        self.image_view.display = self.display
        self.image_view.match_triangle = match_triangle
        self.image_view.update()
        self.is_board = marker_type in ('asymmetric_grid', 'calib_board')
        unencoded = marker_type == 'unencoded_circle' or any(
            row.marker.get('marker_type') == 'unencoded_circle' for row in self.display.rows)
        self.marker_name = '普通圆点 / 圆环' if unencoded else '非对称圆板' if self.is_board else '编码圆'
        self.details_button.setText('标记物数据')
        self.title.setText(f'当前帧 {frame_id if frame_id is not None else "—"} · {self.marker_name}')
        self.counts.setText(f'<span style="color:{GREEN}">● 绿 {self.display.green_count}</span>　'
                            f'<span style="color:{RED}">● 红 {self.display.red_count}</span>　'
                            f'<span style="color:{YELLOW}">● 仅2D {self.display.yellow_count}</span>')
        reference_text = str(reference_id) if reference_id is not None else '未指定'
        kind = '配准内点' if used_codes is not None else '共有可配对'
        self.pair_label.setText(f'2D检出 {len(self.display.rows)} / 3D有效 {self.display.green_count+self.display.red_count}\n'
                                f'参考帧 {reference_text} · 红圈：{kind}；黄圈：无有效3D')
        if self.is_board:
            self.pair_label.setText(
                f'标定板圆心：2D检出 {len(self.display.rows)} / 3D有效 '
                f'{self.display.green_count+self.display.red_count}\n'
                '序号为网格圆心索引；黄圈表示无有效3D。')
        elif unencoded:
            description = '虚线：配准圆心三角形' if match_triangle else '序号对应当前帧圆心'
            self.pair_label.setText(f'2D检出 {len(self.display.rows)} / 3D有效 '
                                    f'{self.display.green_count}\n{description}；黄圈：无有效3D')
        parts = []
        for color, label in [(GREEN, '有效'), (RED, '共有'), (YELLOW, '仅2D')]:
            codes = [str(row.code) for row in self.display.rows if row.color == color]
            text = ' · '.join(codes[:14]) + (' …' if len(codes) > 14 else '')
            if codes:
                parts.append(f'<span style="color:{color}">{label} {"圆心序号" if self.is_board or unencoded else "ID"}：{escape(text)}</span>')
        self.ids.setText('<br>'.join(parts) or '尚无检测结果')
        diagnosis = {'running': '正在后台识别…', 'error': '识别失败：' + recognition_message}.get(
            recognition_state, recognition_message)
        if diagnosis:
            self.ids.setText(escape(diagnosis) + ('<br>' + '<br>'.join(parts) if parts else ''))
        self.ids.setToolTip(diagnosis)
        self.details_button.setEnabled(bool(self.display.rows))
        points = cumulative_world_markers(self.display, history, current_visible)
        self.world_overlay.set_points(points)
        self.world_counts.setText('累积3D标记：绿 %d / 红 %d' % (
            sum(item[1][1] == GREEN for item in points), sum(item[1][1] == RED for item in points)))
        self._position()
        self.raise_()

    def show_details(self):
        dialog = QDialog(self.window())
        dialog.setWindowTitle('当前帧' + self.marker_name + '数据（相机坐标 mm）')
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
