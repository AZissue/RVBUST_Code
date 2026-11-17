"""Industrial dialog for image ROI selection and 2D/3D match review."""
from copy import deepcopy

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ui_common.image_preview import AspectRatioLabel, numpy_to_qpixmap
from ui_v2.dialogs import localize_buttons

from .pipeline import analyze_pair, frame_image, read_frame


class RegionPreview(AspectRatioLabel):
    region_changed = Signal()

    def __init__(self):
        super().__init__()
        self.region = None
        self._anchor = None
        self._drag = None
        self.setMinimumSize(260, 230)
        self.setAccessibleName('拖动选择工件图像区域')
        self.setCursor(Qt.CrossCursor)

    def reset(self, image=None):
        self.region = self._anchor = self._drag = None
        self.clear_image()
        if image is not None:
            self.setPixmap(numpy_to_qpixmap(image))

    def _image_rect(self):
        w, h = self._pixmap.width(), self._pixmap.height()
        scale = min(self.width() / w, self.height() / h)
        w, h = int(w * scale), int(h * scale)
        return QRectF((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def _normalized(self, position):
        r = self._image_rect()
        return QPointF(np.clip((position.x() - r.x()) / r.width(), 0, 1),
                       np.clip((position.y() - r.y()) / r.height(), 0, 1))

    def pixel_box(self):
        if self.region is None:
            return None
        w, h = self._pixmap.width(), self._pixmap.height()
        r = self.region
        return (int(r.left() * w), int(r.top() * h),
                int(np.ceil(r.right() * w)), int(np.ceil(r.bottom() * h)))

    def mousePressEvent(self, event):
        if (event.button() == Qt.LeftButton and self._pixmap is not None
                and self._image_rect().contains(event.position())):
            self._anchor = self._normalized(event.position())
            self._drag = QRectF(self._anchor, self._anchor)
            self.update()

    def mouseMoveEvent(self, event):
        if self._anchor is not None:
            self._drag = QRectF(self._anchor, self._normalized(event.position())).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._anchor is None or event.button() != Qt.LeftButton:
            return
        self.region = QRectF(self._anchor, self._normalized(event.position())).normalized()
        self._anchor = self._drag = None
        x0, y0, x1, y1 = self.pixel_box()
        if min(x1 - x0, y1 - y0) < 32:
            self.region = None
        self.update()
        self.region_changed.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        region = self._drag if self._drag is not None else self.region
        if region is None or self._pixmap is None:
            return
        r = self._image_rect()
        painter = QPainter(self)
        painter.setPen(QPen(QColor('#56c9ff'), 2))
        painter.drawRect(QRectF(r.x() + region.x() * r.width(), r.y() + region.y() * r.height(),
                                region.width() * r.width(), region.height() * r.height()))
        painter.end()


class FeatureMatchDialog(QDialog):
    def __init__(self, editor, matcher):
        super().__init__(editor)
        self.editor = editor
        self.matcher = matcher
        self.snapshot = None
        self.rms = None
        self._busy = False
        self.setWindowTitle('SuperPoint + LightGlue · 2D 特征拼接')
        screen = self.screen().availableGeometry()
        self.resize(min(1080, screen.width() - 32), min(760, screen.height() - 48))
        layout = QVBoxLayout(self)
        note = QLabel('分别拖框选中两帧中的同一工件，尽量避开标记物、静止背景和台面。拼接结果保留两帧选区内的有效点。')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        layout.addLayout(form)
        self.combos = (QComboBox(), QComboBox())
        self.views = (RegionPreview(), RegionPreview())
        rows = sorted(editor.eligible_frames(), key=lambda row: (row.created, row.frame_id, row.uid))
        picked = [uid for uid in editor.source_browser.selected_ids() if any(row.uid == uid for row in rows)]
        if len(picked) < 2:
            picked.extend(row.uid for row in rows if row.uid not in picked)
        for side, (label, combo) in enumerate(zip(('固定参考帧', '待变换移动帧'), self.combos)):
            for row in rows:
                combo.addItem(f'{row.logical_name} · {row.uid[:6]}', row.uid)
            combo.setCurrentIndex(combo.findData(picked[side]))
            combo.currentIndexChanged.connect(lambda _index, side=side: self.load_preview(side))
            form.addRow(label, combo)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(.1, 20)
        self.threshold.setValue(2)
        self.threshold.setSuffix(' mm')
        self.depth_jump = QDoubleSpinBox()
        self.depth_jump.setRange(.1, 40)
        self.depth_jump.setValue(5)
        self.depth_jump.setSuffix(' mm')
        for label, control in (('3D 内点距离', self.threshold), ('邻域最大深度差', self.depth_jump)):
            control.valueChanged.connect(self.invalidate)
            form.addRow(label, control)
        previews = QHBoxLayout()
        layout.addLayout(previews, 1)
        for view in self.views:
            view.region_changed.connect(self.invalidate)
            previews.addWidget(view, 1)
        self.calculate = QPushButton('匹配像素并计算 3D 变换')
        self.calculate.clicked.connect(self.analyze)
        layout.addWidget(self.calculate)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(140)
        layout.addWidget(self.report)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        localize_buttons(buttons)
        self.publish = buttons.button(QDialogButtonBox.Ok)
        self.publish.setText('确认并生成拼接结果')
        self.cancel = buttons.button(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for side in range(2):
            self.load_preview(side)

    def load_preview(self, side):
        self.invalidate()
        view = self.views[side]
        view.reset()
        try:
            record = self.editor.database.records[self.combos[side].currentData()]
            view.reset(frame_image(self.editor.directory, record))
        except (OSError, ValueError, KeyError) as exc:
            self.report.setPlainText(f'无法显示原始图像 · {exc}')
        self.refresh()

    def invalidate(self, *_):
        self.snapshot = None
        for view in self.views:
            view.clear_markers()
        self.report.setPlainText('请框选两帧中的工件，然后计算匹配。')
        self.refresh()

    def refresh(self):
        busy = self._busy
        for control in (*self.combos, *self.views, self.threshold, self.depth_jump, self.cancel):
            control.setEnabled(not busy)
        different = self.combos[0].currentData() != self.combos[1].currentData()
        self.calculate.setEnabled(not busy and different and all(v.pixel_box() for v in self.views))
        self.publish.setEnabled(not busy and self.snapshot is not None)

    def analyze(self):
        editor = self.editor
        if not self.calculate.isEnabled() or not editor._parameter_gate():
            return
        directory = editor.directory
        rows = [deepcopy(editor.database.records[combo.currentData()]) for combo in self.combos]
        tokens = tuple((row.uid, row.revision) for row in rows)
        boxes = tuple(view.pixel_box() for view in self.views)
        threshold, depth_jump = self.threshold.value(), self.depth_jump.value()
        self.invalidate()
        self._busy = True
        self.refresh()
        self.report.setPlainText('正在加载预训练权重、匹配像素、读取点图并求解刚体变换…')

        def work():
            with editor.database._lock:
                editor._validate_source(directory, tokens)
                frames = [read_frame(directory, row) for row in rows]
            result = analyze_pair(frames, boxes, self.matcher, threshold, depth_jump)
            with editor.database._lock:
                editor._validate_source(directory, tokens)
            return result

        def finished(result=None, error=None):
            def release():
                if editor._worker is not None:
                    QTimer.singleShot(10, release)
                    return
                self._busy = False
                self.refresh()

            try:
                if error is not None:
                    self.report.setPlainText(f'计算失败 · {error}')
                else:
                    self.show_result(result, directory, tokens, boxes)
            finally:
                QTimer.singleShot(0, release)

        if not editor._run(work, finished, kind='probe', on_error=lambda error: finished(error=error)):
            self._busy = False
            self.report.setPlainText('工作区正在处理另一项任务，请稍后重试。')
            self.refresh()

    def show_result(self, result, directory, tokens, boxes):
        # Label all 3D inliers first. Subsample rejects solely for readable overlays.
        kept = np.flatnonzero(result.inliers)
        rejected = np.flatnonzero(~result.inliers)
        displayed = np.r_[kept[:80], rejected[::max(1, int(np.ceil(len(rejected) / 35)))][:35]]
        for view, pixels in zip(self.views, result.pixels):
            w, h = view._pixmap.width(), view._pixmap.height()
            view.set_markers([
                dict(x=pixels[i, 0] / w, y=pixels[i, 1] / h, code=str(i+1),
                     display_color=('#55ee88' if result.inliers[i] else
                                    '#ffcc55' if result.valid[i] else '#ff7777'))
                for i in displayed
            ])
        report = (f'2D 匹配 {len(result.valid)} 对 · 连续深度 {result.valid.sum()} 对 · '
                  f'3D 内点 {result.inliers.sum()} 对\n同号表示同一对。绿 = 内点，黄 = 3D 外点，红 = 深度不连续或无效。')
        if result.pose is None:
            self.report.setPlainText(report + '\n' + result.reason)
            return
        self.rms = float(np.sqrt(np.mean(result.errors[result.inliers] ** 2)))
        self.snapshot = (directory, tokens, boxes, result.pose)
        self.report.setPlainText(report + f'\n内点 RMS {self.rms:.3f} mm · 移动 → 参考（平移 mm）\n'
                                 + np.array2string(result.pose, precision=5, suppress_small=True))
        self.report.verticalScrollBar().setValue(0)

    def accept(self):
        if self.publish.isEnabled():
            super().accept()

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
