"""No SDK or Qt imports: all prototype geometry is in millimetres."""
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np


@dataclass
class CloudLayer:
    name: str
    points: np.ndarray
    colors: np.ndarray | None = None
    visible: bool = True
    source: str = '演示合成数据'
    source_points: int | None = None

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
        if not len(self.points):
            raise ValueError('点云不含有效点')


@dataclass
class PostProcessSession:
    layers: list = field(default_factory=list)
    sequence: int = 0
    UNDO_LIMIT: int = 8
    _undo: list = field(default_factory=list)

    def snapshot(self):
        self._undo.append(list(self.layers))
        self._undo = self._undo[-self.UNDO_LIMIT:]

    @property
    def can_undo(self):
        return bool(self._undo)

    def undo(self):
        if not self._undo:
            return False
        self.layers = self._undo.pop()
        return True


def demo_cloud(index=0, spacing=0.8):
    """Bent sheet specimen + platform. Synthetic visual data, no measurement claim."""
    step = max(0.5, float(spacing))
    x, y = np.meshgrid(np.arange(-95, 95, step), np.arange(-55, 55, step))
    z = 18 + 26 * np.exp(-((x / 62) ** 2)) + 8 * np.sin(y / 28)
    keep = ~((x > 48) & (y > 18))
    sheet = np.column_stack((x[keep], y[keep], z[keep]))
    rng = np.random.default_rng(42 + index)
    sheet += rng.normal(0, 0.06, sheet.shape)
    colors = np.tile([0.66, 0.81, 0.91], (len(sheet), 1))
    bx, by = np.meshgrid(np.arange(-145, 145, step * 3), np.arange(-100, 100, step * 3))
    base = np.column_stack((bx.ravel(), by.ravel(), np.zeros(bx.size)))
    base_colors = np.tile([0.43, 0.49, 0.49], (len(base), 1))
    return CloudLayer(f'演示点云 {index + 1:02d}', np.vstack((sheet, base)),
                      np.vstack((colors, base_colors)))


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
    if not o3d.io.write_point_cloud(str(path), cloud):
        raise OSError('点云写入失败')
    return len(cloud.points)
