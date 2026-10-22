"""Read-only inspection of actual calibration frames and correspondence residuals."""
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ui_common.industrial_viewer import IndustrialViewer


REFERENCE_COLOR = (0.18, 0.78, 0.91)
CAMERA_COLOR = (1.0, 0.61, 0.25)


def load_calibration_clouds(paths, limit=120_000):
    """Run on a worker; cap display copies without touching original frame data."""
    clouds, warnings = {}, []
    for cid, path in paths.items():
        try:
            if path and Path(path).is_file():
                import open3d as o3d
                cloud = o3d.io.read_point_cloud(str(path))
            else:
                cloud = None
            if cloud is None:
                warnings.append(f'{cid}：缺少标定点云')
                continue
            points = np.asarray(cloud.points)
            points = points[np.isfinite(points).all(axis=1) & (np.linalg.norm(points, axis=1) > 1e-5)]
            if not len(points):
                warnings.append(f'{cid}：标定点云为空')
                continue
            stride = max(1, int(np.ceil(len(points) / limit)))
            clouds[cid] = points[::stride].copy()
        except Exception as exc:
            warnings.append(f'{cid}：{exc}')
    return clouds, warnings


def residual_rows(result):
    """Keep saved per-point classification; never invent it for older sessions."""
    rows = []
    for item in result.get('details', []):
        ref = np.asarray(item.get('pt_ref', []), dtype=float)
        cam = np.asarray(item.get('pt_cam_transformed', []), dtype=float)
        if ref.shape != (3,) or cam.shape != (3,) or not np.isfinite([ref, cam]).all():
            continue
        delta = cam - ref
        rows.append((item.get('code', '—'), ref, cam, delta,
                     float(np.linalg.norm(delta)), item.get('is_inlier')))
    return sorted(rows, key=lambda row: row[4], reverse=True)


class ResidualChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.setMinimumHeight(120)
        self.setToolTip('按误差降序排列；橙色为内点，红色为离群点，灰色为分类未知。')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#252525'))
        painter.setPen(QColor('#c9c9c9'))
        if not self.rows:
            painter.drawText(self.rect(), Qt.AlignCenter, '此标定结果未保存逐点误差')
            return
        peak = max(max(row[4] for row in self.rows), 0.001)
        painter.drawText(10, 20, f'匹配点误差 / mm    最大 {peak:.3f}')
        width = max(1, self.width() - 24) / len(self.rows)
        height = max(1, self.height() - 44)
        for index, row in enumerate(self.rows):
            color = '#ff6767' if row[5] is False else '#f9ac55' if row[5] is True else '#aaaaaa'
            bar_height = max(1, row[4] / peak * height)
            painter.fillRect(QRectF(12 + index * width, self.height() - 10 - bar_height,
                                    max(1, width - 2), bar_height), QColor(color))


class CalibrationInspector(QDialog):
    """Window-modal snapshot prevents capture/reset from invalidating source frames."""
    def __init__(self, pairs, parent=None):
        super().__init__(parent)
        self.setWindowTitle('标定结果可视化')
        self.setObjectName('calibrationInspector')
        self.setStyleSheet('QDialog#calibrationInspector {background:#292929;}'
                          'QDialog#calibrationInspector QTableWidget {background:#242424;}'
                          'QDialog#calibrationInspector QHeaderView::section {background:#343434;}'
                          'QDialog#calibrationInspector QWidget#inspectorDetails {background:#292929;}'
                          'QDialog#calibrationInspector QLabel {background:transparent;}'
                          'QDialog#calibrationInspector QComboBox {background:#292929;}')
        self.setWindowModality(Qt.WindowModal)
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.pairs = pairs
        self.clouds = {}
        self.warnings = []
        self.active = True
        self._loading = True
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel('相机配对'))
        self.pair_choice = QComboBox()
        for ref, cam in pairs:
            self.pair_choice.addItem(f'{cam} → {ref}', (ref, cam))
        header.addWidget(self.pair_choice)
        self.view_choice = QComboBox()
        self.view_choice.addItems(['标定点云重合', '匹配圆心重合'])
        header.addWidget(self.view_choice)
        self.show_reference = QCheckBox('参考相机')
        self.show_camera = QCheckBox('待标定相机')
        for check in (self.show_reference, self.show_camera):
            check.setChecked(True)
            header.addWidget(check)
        header.addStretch()
        fit = QPushButton('适配视图')
        header.addWidget(fit)
        root.addLayout(header)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)
        self.viewer = IndustrialViewer()
        self.viewer.toolbar.hide()
        splitter.addWidget(self.viewer)
        right = QWidget()
        right.setObjectName('inspectorDetails')
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        error_header = QHBoxLayout()
        error_header.addWidget(QLabel('误差明细'), 1)
        self.error_filter = QComboBox()
        self.error_filter.addItems(['仅内点', '全部匹配点', '仅离群点'])
        error_header.addWidget(self.error_filter)
        right_layout.addLayout(error_header)
        self.chart = ResidualChart()
        right_layout.addWidget(self.chart)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['编号', 'ΔX', 'ΔY', 'ΔZ', '误差(mm)', '分类'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        right_layout.addWidget(self.table, 1)
        note = QLabel('Δ = 变换后的待标定相机圆心 − 参考圆心（mm）。\n'
                      'RMS / 内点率为标定拟合指标，不代表点云表面距离；离群点不计入内点 RMS。')
        note.setWordWrap(True)
        right_layout.addWidget(note)
        splitter.addWidget(right)
        splitter.setSizes([730, 420])
        self.status = QLabel('正在读取标定点云…')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        footer = QHBoxLayout()
        legend = QLabel('<span style="color:#2ec7e8">● 参考相机</span>　'
                        '<span style="color:#ff9c40">● 待标定相机（已应用外参）</span>')
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
        self.refresh()

    def _finish(self, *_):
        self.active = False
        self.viewer.shutdown()

    def set_clouds(self, clouds, warnings=()):
        if not self.active:
            return
        self._loading = False
        self.clouds = clouds
        self.warnings = list(warnings)
        self.refresh()

    def refresh(self, *_):
        pair = self.pair_choice.currentData()
        if pair is None:
            return
        ref, cam = pair
        result = self.pairs[pair]
        all_rows = residual_rows(result)
        selection = self.error_filter.currentIndex()
        rows = [row for row in all_rows if selection == 1 or
                (selection == 0 and row[5] is True) or (selection == 2 and row[5] is False)]
        self.chart.rows = rows
        self.chart.update()
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            kind = '离群点' if row[5] is False else '内点' if row[5] is True else '未知'
            values = [str(row[0]), *(f'{value:.3f}' for value in row[3]), f'{row[4]:.3f}', kind]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if row[5] is False:
                    item.setForeground(QColor('#ff6767'))
                self.table.setItem(index, column, item)
        rms = result.get('rms_mm', 0)
        ratio = result.get('inlier_ratio', 0)
        passed = rms <= 2.0 and ratio >= .5
        all_rms = result.get('rms_all_mm')
        all_text = f'    全量 RMS {all_rms:.3f} mm' if all_rms is not None else ''
        self.summary.setText(f'{cam} → {ref}    内点 RMS {rms:.3f} mm    内点率 {ratio:.1%}'
                             f'{all_text}    配对门禁：{"通过" if passed else "未通过"}')
        self.viewer.clear_all()
        if self.view_choice.currentIndex() == 1:
            points_ref = np.array([row[1] for row in rows]).reshape(-1, 3)
            points_cam = np.array([row[2] for row in rows]).reshape(-1, 3)
            self.viewer.set_point_size(5)
        else:
            points_ref = self.clouds.get(ref, np.empty((0, 3)))
            points_cam = self.clouds.get(cam, np.empty((0, 3)))
            transform = np.asarray(result['T'], dtype=float)
            points_cam = points_cam @ transform[:3, :3].T + transform[:3, 3]
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
        message = '正在读取标定点云…' if self._loading else '标定帧显示已抽样；坐标与误差单位均为 mm。'
        if not self._loading and missing:
            message += ' 缺少点云：' + '、'.join(missing) + '；可切换查看匹配圆心。'
        if not all_rows:
            message += ' 此结果没有逐点明细，无法展示匹配点误差。'
        elif not rows:
            message += ' 当前筛选没有匹配点；可选择“全部匹配点”查看。'
        if self.warnings:
            message += '\n' + '\n'.join(self.warnings)
        self.status.setText(message)
