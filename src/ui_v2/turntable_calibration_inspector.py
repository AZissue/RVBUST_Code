"""Turntable snapshots adapted to the shared read-only calibration dialog."""
import copy
from PySide6.QtWidgets import QLabel
from core.turntable_calibrator import rotation_direction
from ui_common.calibration_result import CalibrationResultDialog
from .calibration_inspector import load_calibration_clouds


class TurntableCalibrationInspector(CalibrationResultDialog):
    def __init__(self, calib, snapshot, parent=None):
        self.calibration = copy.deepcopy(calib)
        snapshot = copy.deepcopy(snapshot or {})
        result = snapshot.get('result', {})
        super().__init__({('初始帧', '旋转帧'): result}, parent,
                         title='转台标定结果与误差', loading=True)
        self.error_filter.setCurrentIndex(1)
        direction = rotation_direction(calib.axis, calib.angle_rad)
        self.model_info = QLabel(f'旋转方向：{direction} · 从相机沿 +Z 看向场景（初始帧 → 旋转帧）\n'
            '两帧按小于180°的单步旋转解释；方向不等同于转台俯视方向。\n'
            '显示旋转帧按转轴模型回到初始帧的误差；未进行内点分类，质量门禁未评估。')
        self.model_info.setWordWrap(True)
        self.layout().insertWidget(0, self.model_info)
        self.viewer.set_rotation_geometry(calib.axis, calib.center)


def open_inspector(bridge):
    workspace = bridge.shell.workspace_turntable()
    if not bridge.can_change_workspace():
        bridge.shell.log('请先等待当前任务完成，再查看标定可视化。', 'warn')
        return
    if not workspace.session.is_calibrated():
        bridge.shell.log('尚无转台标定结果，请先计算转轴。', 'warn')
        return
    previous = getattr(bridge, '_turntable_calibration_inspector', None)
    if previous is not None and previous.active:
        previous.raise_()
        previous.activateWindow()
        return
    snapshot = copy.deepcopy(workspace.session.calibration_result)
    dialog = TurntableCalibrationInspector(workspace.session.calib, snapshot, bridge.shell)
    bridge._turntable_calibration_inspector = dialog
    database = bridge.frame_db.databases['turntable']
    paths = {}
    source_warnings = []
    for name, uid in zip(('初始帧', '旋转帧'), (snapshot or {}).get('source_ids', [])):
        if uid in database.records:
            saved_revision = snapshot.get('source_revisions', {}).get(uid)
            if saved_revision is not None and database.records[uid].revision != saved_revision:
                source_warnings.append(f'{name}：原始帧已被替换，不叠加已改变的点云；匹配点仍来自标定快照。')
            else:
                paths[name] = str(database.directory / 'frames' / uid / 'pointmap.ply')
    dialog.open()

    def done(result, error):
        if not dialog.active:
            return
        if error:
            dialog.set_clouds({}, ['读取标定点云失败：' + str(error)])
        else:
            clouds, warnings = result
            warnings.extend(source_warnings)
            if not snapshot:
                warnings.append('历史标定未保存两帧来源和误差明细；仅展示转轴与中心，请重新标定以生成完整可视化。')
            dialog.set_clouds(clouds, warnings)

    bridge._run_background(lambda: load_calibration_clouds(paths), done, name='calibration_inspection')
