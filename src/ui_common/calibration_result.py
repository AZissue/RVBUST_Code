"""Reusable read-only calibration result dialog; no SDK, workflow or file I/O.

pairs maps (reference_id, source_id) to plain result snapshots. T maps source
coordinates to reference coordinates; details contain pt_ref and already
transformed pt_cam_transformed, both in mm. Missing metrics stay unknown.
"""
import copy
import math
import numpy as np
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QTabWidget, QToolTip)
from .industrial_viewer import IndustrialViewer

REFERENCE_COLOR = (0.18, 0.78, 0.91)
CAMERA_COLOR = (1.0, 0.61, 0.25)


def residual_rows(result):
    """Keep saved per-point classification; never invent it for older sessions."""
    rows = []
    for item in result.get('details', []) or ():
        if not isinstance(item, dict):
            continue
        try:
            ref = np.asarray(item.get('pt_ref', []), dtype=float)
            cam = np.asarray(item.get('pt_cam_transformed', []), dtype=float)
        except (TypeError, ValueError):
            continue
        if ref.shape != (3,) or cam.shape != (3,) or not np.isfinite([ref, cam]).all():
            continue
        with np.errstate(over='ignore', invalid='ignore'):
            delta = cam - ref
        error = math.hypot(*delta)
        if not math.isfinite(error):
            continue
        rows.append((item.get('code', '—'), ref, cam, delta,
                     error, bool(item['is_inlier'])
                     if isinstance(item.get('is_inlier'), (bool, np.bool_)) else None))
    return sorted(rows, key=lambda row: row[4], reverse=True)


def finite_metric(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def valid_transform(value):
    try:
        value = np.asarray(value, dtype=float)
        if value.shape == (4, 4) and np.isfinite(value).all() and np.allclose(value[3], [0, 0, 0, 1]):
            return value
    except (TypeError, ValueError):
        pass
    return None


class ResidualChart(QWidget):
    point_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.selected_index = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self.setToolTip('按误差降序排列；橙色为内点，红色为离群点，灰色为分类未知。')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#252525'))
        painter.setPen(QColor('#c9c9c9'))
        if not self.rows:
            painter.drawText(self.rect(), Qt.AlignCenter, '此标定结果未保存逐点误差')
            return
        peak = max(row[4] for row in self.rows)
        scale_peak = max(peak, .001)
        painter.drawText(10, 20, f'匹配点误差 / mm    最大 {peak:.3f}')
        width = max(1, self.width() - 24) / len(self.rows)
        height = max(1, self.height() - 44)
        for index, row in enumerate(self.rows):
            color = '#ff6767' if row[5] is False else '#f9ac55' if row[5] is True else '#aaaaaa'
            bar_height = max(1, row[4] / scale_peak * height)
            painter.fillRect(QRectF(12 + index * width, self.height() - 10 - bar_height,
                                    max(1, width - 2), bar_height), QColor(color))

            if index == self.selected_index:
                painter.setPen(QColor('#ffffff'))
                painter.drawRect(QRectF(12 + index * width, self.height() - 10 - bar_height,
                                        max(1, width - 2), bar_height))

    def _index_at(self, event):
        x = event.position().x()
        if not self.rows or not 12 <= x < self.width() - 12:
            return -1
        return min(len(self.rows) - 1, int((x - 12) / max(1, self.width() - 24) * len(self.rows)))

    def mousePressEvent(self, event):
        index = self._index_at(event)
        if event.button() == Qt.LeftButton and index >= 0:
            self.point_selected.emit(index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        index = self._index_at(event)
        if index >= 0:
            row = self.rows[index]
            QToolTip.showText(event.globalPosition().toPoint(), f'编号 {row[0]} · 误差 {row[4]:.4f} mm', self)
        super().mouseMoveEvent(event)


class CalibrationResultDialog(QDialog):
    """Owned snapshots and optional clouds; reusable with arbitrary data-pair IDs."""
    def __init__(self, pairs, parent=None, *, title='标定结果与误差',
                 rms_limit_mm=None, min_inlier_ratio=None, loading=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName('calibrationInspector')
        self.setStyleSheet('QDialog#calibrationInspector {background:#292929;}'
                          'QDialog#calibrationInspector QTableWidget {background:#242424;font-size:12px;}'
                          'QDialog#calibrationInspector QHeaderView::section {background:#343434;font-size:11px;padding:4px;}'
                          'QDialog#calibrationInspector QWidget#inspectorDetails {background:#292929;}'
                          'QDialog#calibrationInspector QLabel {background:transparent;}'
                          'QDialog#calibrationInspector QComboBox {background:#292929;}')
        self.setWindowModality(Qt.WindowModal)
        self.resize(980, 660)
        self.setMinimumSize(760, 520)
        self.pairs = copy.deepcopy(pairs)
        self.clouds = {}
        self.warnings = []
        self.active = True
        self._loading = loading
        self.rms_limit_mm = rms_limit_mm
        self.min_inlier_ratio = min_inlier_ratio
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel('数据配对'))
        self.pair_choice = QComboBox()
        for ref, cam in pairs:
            self.pair_choice.addItem(f'{cam} → {ref}', (ref, cam))
        header.addWidget(self.pair_choice)
        self.view_choice = QComboBox()
        self.view_choice.addItems(['标定点云重合', '匹配圆心重合'])
        view_bar = QHBoxLayout()
        view_bar.addWidget(self.view_choice)
        self.show_reference = QCheckBox('参考数据')
        self.show_camera = QCheckBox('待对齐数据')
        for check in (self.show_reference, self.show_camera):
            check.setChecked(True)
            view_bar.addWidget(check)
        header.addStretch()
        fit = QPushButton('适配视图')
        header.addWidget(fit)
        root.addLayout(header)
        view_bar.addStretch()
        root.addLayout(view_bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.PlainText)
        root.addWidget(self.summary)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)
        self.viewer = IndustrialViewer()
        self.viewer.toolbar.hide()
        self.viewer.display_actions['marker_centers'].setChecked(True)
        splitter.addWidget(self.viewer)
        right = QWidget()
        right.setObjectName('inspectorDetails')
        right.setMinimumWidth(340)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        error_header = QHBoxLayout()
        error_header.addWidget(QLabel('误差明细'), 1)
        self.error_filter = QComboBox()
        self.error_filter.addItems(['仅内点', '全部匹配点', '仅离群点'])
        error_header.addWidget(self.error_filter)
        detail_tabs = QTabWidget()
        right_layout.addWidget(detail_tabs)
        errors = QWidget()
        error_layout = QVBoxLayout(errors)
        error_layout.setContentsMargins(0, 0, 0, 0)
        detail_tabs.addTab(errors, '逐点误差')
        error_layout.addLayout(error_header)
        self.chart = ResidualChart()
        error_layout.addWidget(self.chart)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['编号', 'ΔX', 'ΔY', 'ΔZ', '误差(mm)', '分类'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        error_layout.addWidget(self.table, 1)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._select_row)
        self.chart.point_selected.connect(self.table.selectRow)
        self.matrix = QTableWidget(4, 4)
        self.matrix.setEditTriggers(QTableWidget.NoEditTriggers)
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        matrix_page = QWidget()
        matrix_layout = QVBoxLayout(matrix_page)
        self.matrix_title = QLabel()
        self.matrix_title.setWordWrap(True)
        self.matrix_title.setTextFormat(Qt.PlainText)
        matrix_layout.addWidget(self.matrix_title)
        matrix_layout.addWidget(self.matrix)
        matrix_layout.addStretch()
        detail_tabs.addTab(matrix_page, '变换矩阵')
        self.point_summary = QLabel()
        self.point_summary.setWordWrap(True)
        right_layout.addWidget(self.point_summary)
        note = QLabel('Δ = 变换后的源数据对应点 − 参考点（mm）。\n'
                      'RMS / 内点率为标定拟合指标，不代表点云表面距离；离群点不计入内点 RMS。')
        note.setWordWrap(True)
        right_layout.addWidget(note)
        splitter.addWidget(right)
        splitter.setSizes([560, 380])
        self.status = QLabel('正在读取标定点云…')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        root.addWidget(self.status)
        footer = QHBoxLayout()
        legend = QLabel('<span style="color:#2ec7e8">● 参考数据</span>　'
                        '<span style="color:#ff9c40">● 待对齐数据（已应用变换）</span>')
        footer.addWidget(legend)
        footer.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        root.addLayout(footer)
        self.pair_choice.currentIndexChanged.connect(self.refresh)
        self.view_choice.currentIndexChanged.connect(self.refresh)
        self.error_filter.currentIndexChanged.connect(self.refresh)
        self.show_reference.toggled.connect(self.refresh)
        self.show_camera.toggled.connect(self.refresh)
        fit.clicked.connect(self.viewer.reset_view)
        self.finished.connect(self._finish)
        self.finished.connect(self.deleteLater)
        if not loading:
            self.view_choice.setCurrentIndex(1)
            self.error_filter.setCurrentIndex(1)
        self.refresh()

    def _finish(self, *_):
        self.active = False
        self.viewer.shutdown()

    def set_clouds(self, clouds, warnings=()):
        if not self.active:
            return
        self._loading = False
        # Own display copies; callers may release or change their source arrays.
        self.clouds = {}
        for key, value in clouds.items():
            points = np.asarray(value, dtype=float)
            if points.ndim == 2 and points.shape[1] == 3:
                points = points[np.isfinite(points).all(axis=1)]
                self.clouds[key] = points[::max(1, int(np.ceil(len(points) / 120_000)))].copy()
        self.warnings = list(warnings)
        self.refresh()

    def refresh(self, *_):
        pair = self.pair_choice.currentData()
        if pair is None:
            self.summary.setText('暂无标定结果')
            self.status.setText('请先计算标定结果，再打开此窗口。')
            return
        ref, cam = pair
        result = self.pairs[pair]
        all_rows = residual_rows(result)
        selection = self.error_filter.currentIndex()
        rows = [row for row in all_rows if selection == 1 or
                (selection == 0 and row[5] is True) or (selection == 2 and row[5] is False)]
        self.chart.rows = rows
        self.chart.update()
        self.table.clearSelection()
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            kind = '离群点' if row[5] is False else '内点' if row[5] is True else '未知'
            values = [str(row[0]), *(f'{value:.3f}' for value in row[3]), f'{row[4]:.3f}', kind]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if row[5] is False:
                    item.setForeground(QColor('#ff6767'))
                self.table.setItem(index, column, item)
        rms, ratio = finite_metric(result.get('rms_mm')), finite_metric(result.get('inlier_ratio'))
        if ratio is not None and ratio > 1:
            ratio = None
        all_rms = finite_metric(result.get('rms_all_mm'))
        rms_text = f'{rms:.3f} mm' if rms is not None else '—'
        ratio_text = f'{ratio:.1%}' if ratio is not None else '—'
        gate = '未评估'
        if self.rms_limit_mm is not None and self.min_inlier_ratio is not None and rms is not None and ratio is not None:
            gate = '通过' if result.get('success') is not False and rms <= self.rms_limit_mm and ratio >= self.min_inlier_ratio else '未通过'
        self.summary.setText(f'{cam} → {ref}    内点 RMS {rms_text}    内点率 {ratio_text}'
                             + (f'    全量 RMS {all_rms:.3f} mm' if all_rms is not None else '')
                             + ('    标定失败' if result.get('success') is False else '')
                             + f'    配对门禁：{gate}')
        self.point_summary.setText(f'当前显示 {len(rows)} / {len(all_rows)} 个匹配点'
                                  + (f' · 均值 {np.mean([row[4] for row in rows]):.3f} mm'
                                     f' · 最大 {max(row[4] for row in rows):.3f} mm' if rows else ''))
        self.matrix_title.setText(f'T：{cam} → {ref}\n平移单位 mm；p参考 = R × p源 + t')
        transform = valid_transform(result.get('T'))
        for i in range(4):
            for j in range(4):
                self.matrix.setItem(i, j, QTableWidgetItem(f'{transform[i, j]:.6g}' if transform is not None else '—'))
        self._visible_rows = rows
        self.chart.selected_index = -1
        self.viewer.clear_all()
        if self.view_choice.currentIndex() == 1:
            points_ref = np.array([row[1] for row in rows]).reshape(-1, 3)
            points_cam = np.array([row[2] for row in rows]).reshape(-1, 3)
            self.viewer.set_point_size(5)
        else:
            points_ref = self.clouds.get(ref, np.empty((0, 3)))
            points_cam = self.clouds.get(cam, np.empty((0, 3)))
            points_cam = (points_cam @ transform[:3, :3].T + transform[:3, 3]
                          if transform is not None else np.empty((0, 3)))
            self.viewer.set_point_size(2)
        # Owned, bounded display geometries only: original acquisition clouds stay untouched.
        import open3d as o3d
        for cid, points, color, visible in (
                (ref, points_ref, REFERENCE_COLOR, self.show_reference.isChecked()),
                (cam, points_cam, CAMERA_COLOR, self.show_camera.isChecked())):
            if visible and len(points):
                cloud = o3d.geometry.PointCloud()
                cloud.points = o3d.utility.Vector3dVector(points)
                cloud.paint_uniform_color(color)
                self.viewer.set_pointcloud(cid, cloud)
        self.viewer.reset_view()
        missing = [cid for cid in (ref, cam) if cid not in self.clouds]
        message = ('正在读取标定点云…' if self._loading else
                   '匹配圆心来自已保存结果；坐标与误差单位均为 mm。' if self.view_choice.currentIndex() == 1 else
                   '标定帧显示已抽样；坐标与误差单位均为 mm。')
        if not self._loading and missing and self.view_choice.currentIndex() == 0:
            message += ' 缺少点云：' + '、'.join(map(str, missing)) + '；可切换查看匹配圆心。'
        if not all_rows:
            message += ' 此结果没有逐点明细，无法展示匹配点误差。'
        elif not rows:
            message += ' 当前筛选没有匹配点；可选择“全部匹配点”查看。'
        if transform is None:
            message += ' 缺少有效变换矩阵，未显示源点云变换；匹配点使用已保存的坐标。'
        if self.warnings:
            message += '\n' + '\n'.join(self.warnings)
        self.status.setText(message)

    def _select_row(self):
        index = self.table.currentRow() if self.table.selectedItems() else -1
        self.chart.selected_index = index
        self.chart.update()
        rows = getattr(self, '_visible_rows', [])
        markers = []
        if 0 <= index < len(rows):
            row = rows[index]
            markers = [(f'参考 {row[0]}', (row[1], '#2ec7e8')),
                       (f'变换后 {row[0]}', (row[2], '#ff9c40'))]
        self.viewer.set_cloud_markers(markers)
