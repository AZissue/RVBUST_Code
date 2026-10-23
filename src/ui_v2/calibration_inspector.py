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
    def __init__(self, pairs, parent=None):
        super().__init__(pairs, parent, title='标定结果与误差',
                         rms_limit_mm=2., min_inlier_ratio=.5, loading=True)
