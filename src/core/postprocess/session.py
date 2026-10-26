"""No SDK or Qt imports: all editing geometry is in millimetres."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np


@dataclass
class CloudLayer:
    name: str
    points: np.ndarray
    colors: np.ndarray | None = None
    visible: bool = True
    source: str = '点云数据'

    origins: tuple = ()  # (DB UID, geometry revision) provenance

    def __post_init__(self):
        pts = np.asarray(self.points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 3:
            raise ValueError('点云必须为 N×3 数组')
        valid = np.isfinite(pts).all(axis=1)
        if self.colors is not None:
            colors = np.asarray(self.colors, dtype=float)
            if colors.shape != pts.shape or not np.isfinite(colors).all():
                raise ValueError('颜色必须与点数一致且为有限值')
            self.colors = np.clip(colors[valid], 0, 1).copy()
        self.points = pts[valid].copy()
        self.points.setflags(write=False)
        if self.colors is not None:
            self.colors.setflags(write=False)
        if not len(self.points):
            raise ValueError('点云不含有效点')

    def has_colors(self):
        """Read-only XYZ/RGB geometry interface accepted by IndustrialViewer."""
        return self.colors is not None


def read_cloud(path, unit='mm'):
    import open3d as o3d
    cloud = o3d.io.read_point_cloud(str(path))
    points = np.asarray(cloud.points)
    if unit not in ('mm', 'm'):
        raise ValueError('请选择 mm 或 m')
    if unit == 'm':
        points = points * 1000
    return CloudLayer(Path(path).stem, points,
                      np.asarray(cloud.colors) if cloud.has_colors() else None,
                      source=str(Path(path).resolve()))


def write_cloud(path, layers):
    import open3d as o3d
    visible = [layer for layer in layers if layer.visible]
    if not visible:
        raise ValueError('没有可见点云可以导出')
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.vstack([layer.points for layer in visible]))
    cloud.colors = o3d.utility.Vector3dVector(np.vstack([
        layer.colors if layer.colors is not None else np.tile([0.66, 0.81, 0.91], (len(layer.points), 1))
        for layer in visible]))
    from core.utils import write_point_cloud_atomic
    if not write_point_cloud_atomic(str(path), cloud):
        raise OSError('点云写入失败')
    return len(cloud.points)
