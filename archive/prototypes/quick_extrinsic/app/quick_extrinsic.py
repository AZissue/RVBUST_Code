"""Run with the MCC rvc environment. No SDK initialization until Connect."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / 'core'))
from workflow import Workflow, DEFAULT_BOARD_SPECS, draw_overlay

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QPlainTextEdit, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QFileDialog,
    QMessageBox, QSplitter, QCheckBox, QScrollArea)


class Job(QThread):
    result = Signal(bool, str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.result.emit(True, str(self.action()))
        except Exception:
            self.result.emit(False, traceback.format_exc())


class Window(QWidget):
    def __init__(self, output):
        super().__init__()
        self.flow = Workflow(output)
        self.job = None
        self.setWindowTitle('临时多相机外参标定与拼接 · MCC 核心 · mm')
        self.resize(1400, 900)
        layout = QVBoxLayout(self)
        self.controls = QWidget()
        form = QVBoxLayout(self.controls)
        row = QHBoxLayout()
        self.indices = QLineEdit('0,1')
        self.indices.setMaximumWidth(120)
        row.addWidget(QLabel('设备索引'))
        row.addWidget(self.indices)
        self.button(row, '枚举设备', self.enumerate)
        self.button(row, '连接', self.connect)
        self.button(row, '断开', lambda: self.run(self.flow.disconnect))
        row.addWidget(QLabel('参考相机'))
        self.reference = QComboBox()
        self.reference.setMinimumWidth(100)
        row.addWidget(self.reference)
        self.button(row, '载入外参', self.load)
        self.button(row, '保存外参', self.save)
        self.button(row, '清空帧列表', lambda: self.run(self.flow.clear_frames))
        row.addStretch()
        form.addLayout(row)

        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem('编码圆', 'coded_circle')
        self.mode.addItem('非对称圆标定板（多规格自动尝试）', 'asymmetric_grid')
        row.addWidget(self.mode)
        self.n = QSpinBox()
        self.n.setRange(3, 32)
        self.n.setValue(8)
        self.r1 = self.number(1.01, 20, 2)
        self.r2 = self.number(1.02, 30, 3)
        for label, widget in [('N', self.n), ('r1/r0', self.r1), ('r2/r0', self.r2)]:
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        form.addLayout(row)

        self.specs = QPlainTextEdit(json.dumps(DEFAULT_BOARD_SPECS, ensure_ascii=False))
        self.specs.setMaximumHeight(65)
        self.specs.setToolTip('JSON 数组，cols/rows 沿用 MCC 规格定义。核心会从深度自动估计实际间距。')
        form.addWidget(QLabel('非对称圆板规格 JSON（支持自定义行列和尺寸，spacing_mm 单位 mm）'))
        form.addWidget(self.specs)
        row = QHBoxLayout()
        self.threshold = self.number(.01, 100, 2)
        self.max_rms = self.number(.01, 100, 2)
        self.ratio = self.number(.1, 1, .6)
        self.voxel = self.number(0, 100, 0)
        for label, widget in [('RANSAC mm', self.threshold), ('最大RMS mm', self.max_rms),
                              ('最小内点率', self.ratio), ('导出体素 mm（0关闭）', self.voxel)]:
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        form.addLayout(row)
        self.confirm = QCheckBox('已核对各视角同码圆心/圆板编号对应同一物理位置，标定物在本组采集期间保持静止')
        form.addWidget(self.confirm)
        row = QHBoxLayout()
        self.button(row, '① 采集标定帧', lambda: self.capture('calib'))
        self.button(row, '离线标定帧', lambda: self.offline('calib'))
        self.button(row, '② 检测并显示', self.detect)
        self.button(row, '③ 计算外参', self.calibrate)
        self.button(row, '④ 采集扫描帧', lambda: self.capture('scan'))
        self.button(row, '离线扫描帧', lambda: self.offline('scan'))
        self.button(row, '⑤ 拼接并导出', self.stitch)
        self.button(row, '查看拼接3D', self.view)
        form.addLayout(row)
        layout.addWidget(self.controls)
        layout.addWidget(QLabel('固定相机流程：保持相机位置不变；采集标定 → 检测/核对编号 → 外参 → 移走标定物放入工件 → 采集扫描 → 拼接。'))
        splitter = QSplitter(Qt.Horizontal)
        self.images = QTabWidget()
        splitter.addWidget(self.images)
        right = QTabWidget()
        self.markers = QTableWidget(0, 7)
        self.markers.setHorizontalHeaderLabels(['相机', '编号', '像素x', '像素y', 'X mm', 'Y mm', 'Z mm'])
        self.transforms = QPlainTextEdit()
        self.transforms.setReadOnly(True)
        right.addTab(self.markers, '圆心坐标（红色=无有效深度）')
        right.addTab(self.transforms, '外参与误差 / cam→ref / mm')
        splitter.addWidget(right)
        splitter.setSizes([760, 570])
        layout.addWidget(splitter, 1)
        self.log = QPlainTextEdit(f'输出目录: {self.flow.output}\n设备连接时加载相机已保存参数；离线 PLY 必须为 mm，有序点云与图像逐像素对齐。')
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)

    @staticmethod
    def number(low, high, value):
        box = QDoubleSpinBox()
        box.setDecimals(3)
        box.setRange(low, high)
        box.setValue(value)
        return box

    def button(self, row, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        row.addWidget(button)

    def run(self, action):
        if self.job is not None:
            return
        self.controls.setEnabled(False)
        self.log.appendPlainText('处理中…')
        self.job = Job(action, self)
        self.job.result.connect(self.completed)
        self.job.finished.connect(self.finished)
        self.job.start()

    def completed(self, ok, message):
        self.log.appendPlainText(message)
        if ok:
            self.refresh()
        else:
            QMessageBox.warning(self, '操作未完成', message.splitlines()[-1])

    def finished(self):
        job, self.job = self.job, None
        job.deleteLater()
        self.controls.setEnabled(True)

    def enumerate(self):
        def action():
            if self.flow.manager:
                devices = self.flow.manager.find_devices()
            else:
                from core.camera_manager import CameraManager
                manager = CameraManager()
                ok, message = manager.initialize()
                if not ok:
                    raise RuntimeError(message)
                try:
                    devices = manager.find_devices()
                    return self.describe(devices)
                finally:
                    manager.shutdown()
            return self.describe(devices)
        self.run(action)

    @staticmethod
    def describe(devices):
        lines = []
        for i, device in enumerate(devices):
            ok, info = device.GetDeviceInfo()
            lines.append(f'[{i}] {info.name} / SN {info.sn}' if ok else f'[{i}] 信息读取失败')
        return '\n'.join(lines) or '未发现设备'

    def connect(self):
        try:
            indices = [int(i.strip()) for i in self.indices.text().split(',')]
        except ValueError:
            QMessageBox.warning(self, '索引错误', '请输入例如 0,1,2')
            return
        self.run(lambda: self.flow.connect(indices))

    def capture(self, kind):
        self.confirm.setChecked(False)
        self.run(lambda: self.flow.capture(kind))

    def offline(self, kind):
        from PySide6.QtWidgets import QInputDialog
        cid, ok = QInputDialog.getText(self, '离线相机ID', '必须与外参ID一致，例如 cam0')
        if not ok or not cid:
            return
        image, _ = QFileDialog.getOpenFileName(self, '选择图像', '', 'Image (*.png *.bmp *.jpg *.tif *.tiff)')
        if not image:
            return
        ply, _ = QFileDialog.getOpenFileName(self, '选择对应的 mm 有序点云', '', 'PLY (*.ply)')
        if ply:
            self.confirm.setChecked(False)
            self.run(lambda: self.flow.load_pair(kind, cid, image, ply))

    def detect(self):
        try:
            specs = json.loads(self.specs.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, '规格 JSON 错误', str(exc))
            return
        args = (self.mode.currentData(), specs, self.n.value(), self.r1.value(), self.r2.value())
        self.confirm.setChecked(False)
        self.run(lambda: self.flow.detect(*args))

    def calibrate(self):
        if not self.confirm.isChecked():
            QMessageBox.warning(self, '请先核对对应点', '检查叠图中的编号对应同一物理圆心，再勾选确认。对称排列可能有180°编号歧义。')
            return
        args = (self.reference.currentText(), self.threshold.value(), self.max_rms.value(), self.ratio.value())
        self.run(lambda: self.flow.calibrate(*args))

    def stitch(self):
        voxel = self.voxel.value()
        self.run(lambda: self.flow.stitch(voxel))

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存外参', str(self.flow.output / 'extrinsics.json'), 'JSON (*.json)')
        if path:
            self.run(lambda: self.flow.save(path))

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, '载入本工具外参', '', 'JSON (*.json)')
        if path:
            self.run(lambda: self.flow.load(path))

    def view(self):
        if not self.flow.last_cloud:
            QMessageBox.information(self, '尚无结果', '请先完成拼接')
            return
        subprocess.Popen([sys.executable, str(HERE), '--view', self.flow.last_cloud])

    def refresh(self):
        selected = self.reference.currentText()
        ids = list(dict.fromkeys([*self.flow.identities, *self.flow.frames['calib'], *self.flow.frames['scan']]))
        self.reference.clear()
        self.reference.addItems(ids)
        if self.flow.engine.reference_id in ids:
            self.reference.setCurrentText(self.flow.engine.reference_id)
        elif selected in ids:
            self.reference.setCurrentText(selected)
        while self.images.count():
            widget = self.images.widget(0)
            self.images.removeTab(0)
            widget.deleteLater()
        self.markers.setRowCount(0)
        for kind, frames in self.flow.frames.items():
            for cid, frame in frames.items():
                if frame.image_np is None:
                    continue
                image = draw_overlay(frame.image_np, frame.markers_all or [])
                h, w = image.shape[:2]
                qimage = QImage(image.data, w, h, image.strides[0], QImage.Format_BGR888).copy()
                label = QLabel()
                label.setAlignment(Qt.AlignCenter)
                label.setPixmap(QPixmap.fromImage(qimage).scaled(1000, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                scroll = QScrollArea()
                scroll.setWidget(label)
                self.images.addTab(scroll, f'{cid} / {kind} {frame.board_pattern_name or ""}')
                if kind != 'calib':
                    continue
                for marker in frame.markers_all or []:
                    row = self.markers.rowCount()
                    self.markers.insertRow(row)
                    values = [cid, marker['code'], marker.get('x_2d', marker.get('x')),
                              marker.get('y_2d', marker.get('y')),
                              *[marker.get(k) for k in ('x_3d', 'y_3d', 'z_3d')]]
                    for col, value in enumerate(values):
                        item = QTableWidgetItem(f'{value:.3f}' if isinstance(value, float) else str(value))
                        if not marker.get('valid_3d', True):
                            item.setForeground(Qt.red)
                        self.markers.setItem(row, col, item)
        self.markers.resizeColumnsToContents()
        engine = self.flow.engine
        lines = [f'参考相机: {engine.reference_id}\n方向 p_ref = T @ p_cam；平移单位 mm']
        for (a, b), result in engine.pair_results.items():
            lines.append(f'\n{b}→{a}: RMS {result["rms_mm"]:.5f} mm / 全量 {result.get("rms_all_mm", 0):.5f} mm / 内点率 {result["inlier_ratio"]:.1%}')
        for cid in ids:
            if cid == engine.reference_id:
                continue
            try:
                T = engine.get_transform(cid, engine.reference_id)
                lines.append(f'\n{cid}→{engine.reference_id}\n' + '\n'.join('  '.join(f'{x: .7f}' for x in row) for row in T))
            except Exception:
                pass
        self.transforms.setPlainText('\n'.join(lines))

    def closeEvent(self, event):
        if self.job is not None:
            event.ignore()
            self.log.appendPlainText('请等待当前操作完成后关闭，避免中断设备采集/保存。')
            return
        self.flow.disconnect()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description='MCC 临时多相机外参标定与拼接工具')
    parser.add_argument('--output', default=str(HERE.parents[1] / 'outputs'))
    parser.add_argument('--view', help='在独立进程查看 PLY')
    parser.add_argument('--smoke', action='store_true', help='离屏构造窗口并退出，不初始化SDK')
    args = parser.parse_args()
    if args.view:
        import open3d as o3d
        cloud = o3d.io.read_point_cloud(args.view)
        if len(cloud.points) > 500000:
            cloud = cloud.uniform_down_sample(max(1, (len(cloud.points) + 499999) // 500000))
        o3d.visualization.draw_geometries([cloud], window_name='拼接结果 / mm')
        return
    app = QApplication(sys.argv[:1])
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 9))
    window = Window(args.output)
    window.show()
    if args.smoke:
        app.processEvents()
        window.grab().save(str(window.flow.output / 'ui_smoke.png'))
        window.close()
        return
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
