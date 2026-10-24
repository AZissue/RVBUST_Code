"""Pure-numpy geometry; matches the orthographic camera model of both canvases."""
import numpy as np


def ortho_project(points, center, rotation_matrix, extent, zoom, pan, width, height):
    points = np.asarray(points, dtype=np.float64)
    rotated = (points - np.asarray(center, dtype=float)) @ np.asarray(rotation_matrix, dtype=float).T
    scale = min(width, height) * 1.65 / extent * zoom
    xy = np.column_stack((rotated[:, 0] * scale + width / 2 + pan[0],
                          -rotated[:, 1] * scale + height / 2 + pan[1]))
    return xy, rotated[:, 2]


def point_in_polygon(xy, polygon):
    xy = np.asarray(xy, dtype=np.float64)
    poly = np.asarray(polygon, dtype=np.float64)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError('xy 必须为 N×2 数组')
    if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3:
        raise ValueError('多边形至少需要 3 个顶点')
    xi = poly[:, 0]
    yi = poly[:, 1]
    xj = np.roll(xi, 1)
    yj = np.roll(yi, 1)
    dx = xj - xi
    dy = yj - yi
    inside = np.zeros(len(xy), dtype=bool)
    for begin in range(0, len(xy), 65536):
        x = xy[begin:begin + 65536, 0:1]
        y = xy[begin:begin + 65536, 1:2]
        crosses = (yi > y) != (yj > y)
        with np.errstate(divide='ignore', invalid='ignore'):
            x_intersect = dx * (y - yi) / dy + xi
        inside[begin:begin + 65536] = (crosses & (x < x_intersect)).sum(axis=1) % 2 == 1
    return inside


def polygon_crop_mask(points, polygon_xy, *, center, rotation_matrix, extent, zoom, pan, width, height):
    xy, _ = ortho_project(points, center, rotation_matrix, extent, zoom, pan, width, height)
    return point_in_polygon(xy, np.asarray(polygon_xy, dtype=float))


def voxel_downsample(points, colors=None, voxel_size=1.0):
    points = np.asarray(points, dtype=np.float64)
    if not np.isfinite(voxel_size) or voxel_size <= 0:
        raise ValueError('体素尺寸必须为正有限值（mm）')
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError('点云必须为 N×3 数组')
    keys = np.floor(points / voxel_size).astype(np.int64)
    _, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    total = len(counts)
    if total == 0:
        raise ValueError('体素下采样结果为空')
    out = np.column_stack([np.bincount(inverse, weights=points[:, axis], minlength=total)
                           for axis in range(3)]) / counts[:, None]
    out_colors = None
    if colors is not None:
        colors = np.asarray(colors, dtype=np.float64)
        out_colors = np.column_stack([np.bincount(inverse, weights=colors[:, axis], minlength=total)
                                      for axis in range(3)]) / counts[:, None]
    return out, out_colors


def random_downsample(points, colors=None, ratio=0.5, seed=None):
    points = np.asarray(points, dtype=np.float64)
    if not np.isfinite(ratio) or ratio <= 0 or ratio > 1:
        raise ValueError('抽样比例必须在 (0, 1] 之间')
    count = int(round(len(points) * ratio))
    if count < 1:
        raise ValueError('抽样结果为空，请提高保留比例')
    rng = np.random.default_rng(seed)
    indices = np.sort(rng.choice(len(points), count, replace=False))
    return points[indices], (None if colors is None else np.asarray(colors)[indices]), indices
