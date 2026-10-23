"""Turntable calibration properties and non-destructive 3D annotations."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QLayout


class TurntableCalibrationPanel(QGroupBox):
    def __init__(self, workspace):
        super().__init__('转台标定数据')
        self.workspace = workspace
        self._geometry = None
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.setContentsMargins(10, 18, 10, 8)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignTop)
        self.status = QLabel('未标定')
        self.status.setMaximumHeight(self.status.sizeHint().height())
        layout.addWidget(self.status)
        self.visualize = QToolButton()
        self.visualize.setText('标定结果可视化')
        self.visualize.setToolTip('查看两帧标定点云、转轴模型对齐误差、旋转轴与中心')
        self.visualize.clicked.connect(workspace.calibration_visualization_requested)
        layout.addWidget(self.visualize)
        self.values = QLabel('旋转轴：—\n旋转中心 / mm：—\n单步角度：—\n旋转方向：—\n360°步数：—')
        self.values.setTextFormat(Qt.PlainText)
        self.values.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.values.setWordWrap(True)
        self.values.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.values.setToolTip('相机坐标系，单位mm。旋转中心是轴上一点；沿轴方向不唯一，新标定选择标记重心高度附近的轴点。\n旋转方向从相机沿 +Z 看向场景判断，图像 X 向右、Y 向下；两帧求解按小于180°的单步旋转解释，不代表从转台上方观察的方向。')
        layout.addWidget(self.values)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet('color:#edb566;')
        layout.addWidget(self.warning)
        actions = QHBoxLayout()
        self.show_geometry = QCheckBox('显示旋转轴与中心')
        self.show_geometry.setChecked(True)
        self.show_geometry.toggled.connect(self._update_geometry)
        actions.addWidget(self.show_geometry)
        self.locate = QToolButton()
        self.locate.setText('定位轴心')
        self.locate.clicked.connect(self._locate)
        actions.addWidget(self.locate)
        layout.addLayout(actions)
        workspace.calibration_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        session = self.workspace.session
        self._geometry = None
        warning = ''
        if not session.is_calibrated():
            self.status.setText('未标定 · 拍摄两帧后计算转台')
            self.values.setText('旋转轴：—\n旋转中心 / mm：—\n单步角度：—\n旋转方向：—\n360°步数：—')
        else:
            calib = session.calib
            axis, center = np.asarray(calib.axis), np.asarray(calib.center)
            angle = float(np.degrees(calib.angle_rad))
            vector = lambda values: '[' + ', '.join(f'{value:.6g}' for value in values) + ']' if values.shape == (3,) else '无效'
            from core.turntable_calibrator import rotation_direction
            self.values.setText(f'旋转轴：{vector(axis)}\n旋转中心 / mm：{vector(center)}\n单步角度：{angle:.4f}°\n旋转方向：{rotation_direction(axis, calib.angle_rad)}\n观察方向：相机沿 +Z 看向场景（初始帧 → 旋转帧）\n360°步数：{calib.step_count}')
            valid = (axis.shape == (3,) and center.shape == (3,) and np.isfinite(axis).all() and
                     np.isfinite(center).all() and np.linalg.norm(axis) > 1e-9 and np.linalg.norm(center) < 1e9)
            if valid:
                self._geometry = (axis.copy(), center.copy())
            else:
                warning = '轴心数值异常，已暂停标定图形显示，请重新标定。'
            if valid and abs(angle) < 1.:
                warning = '两帧转角过小，轴心可能不稳定；请增大转角后重新标定。'
            self.status.setText('已标定 · 建议复核' if warning else '已标定 · 相机坐标系')
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.show_geometry.setEnabled(self._geometry is not None)
        self.locate.setEnabled(self._geometry is not None)
        self.visualize.setEnabled(self._geometry is not None)
        self._update_geometry()

    def _update_geometry(self):
        geometry = self._geometry if self.show_geometry.isChecked() else None
        self.workspace.viewer.set_rotation_geometry(*(geometry or (None, None)))

    def _locate(self):
        if self._geometry is None:
            return
        canvas = getattr(self.workspace.viewer.viewer(), 'canvas', None)
        if canvas is not None:
            canvas.center = self._geometry[1].copy()
            canvas.pan[:] = 0
            canvas.zoom = 1.
            canvas._notify_view_changed()
