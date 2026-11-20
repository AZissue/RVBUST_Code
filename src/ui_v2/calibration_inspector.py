"""Production adapter: async file loading stays outside the shared dialog."""
from pathlib import Path
import numpy as np
from ui_common.calibration_result import (CalibrationResultDialog, ResidualChart,
                                          residual_rows, REFERENCE_COLOR, CAMERA_COLOR)


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


class CalibrationInspector(CalibrationResultDialog):
    """Multi-camera compatibility entry with the workflow's pair gate."""
    def __init__(self, pairs, parent=None, *, topology='star', paths=None, report=None):
        super().__init__(pairs, parent, title='标定结果与误差',
                         rms_limit_mm=2., min_inlier_ratio=.5, loading=True)
        from PySide6.QtWidgets import QLabel
        description = ('链式标定 · 合格共视连接树；误差为每条配对边的局部拟合误差，'
                       '沿路径可能累积，未执行全局优化。' if topology == 'chain' else
                       '星型标定 · 每路直接对齐参考相机。')
        if topology == 'joint':
            report = report or {}
            description = '多相机联合标定 · 固定参考系，使用全部合格共视约束。\n' + report.get('message', '')
            if report.get('error'):
                description += '\n未通过全局门禁：' + report['error']
                description += '\n下方仅显示逐对局部测量，不能用于整体拼接。'
            elif 'final_rms_mm' in report:
                description += (f"\n全局三维内点 RMS：{report['initial_rms_mm']:.3f} → "
                                f"{report['final_rms_mm']:.3f} mm；{report['constraint_count']} 条约束。")
                description += '\n下方矩阵和误差使用最终联合位姿；内点分类沿用原始配对。'
                local = [value['local_rms_mm'] for value in pairs.values() if 'local_rms_mm' in value]
                if local:
                    description += f' 原逐对局部 RMS 范围 {min(local):.3f}–{max(local):.3f} mm。'
            description += '\n共视连通路径（联合结果由全部约束共同决定）：'
        routes = '\n'.join(' → '.join(path) for path in (paths or {}).values() if len(path) > 1)
        label = QLabel(description + ('\n' + routes if routes else ''))
        label.setWordWrap(True)
        self.layout().insertWidget(0, label)
