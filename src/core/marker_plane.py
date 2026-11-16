"""Filter an organized source cloud using its measured marker plane (mm)."""
from itertools import combinations

import numpy as np


def fit_marker_plane(markers, clearance_mm, *, bottom_height_mm=None, radius_mm=None):
    """Return a serializable filter for the camera-facing side of the marker plane."""
    if not np.isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError('标记物平面过滤高度必须为非负有限值')
    if bottom_height_mm is not None and not (
            0 <= bottom_height_mm < clearance_mm and radius_mm is not None
            and np.isfinite(radius_mm) and radius_mm > 0):
        raise ValueError('底边最低高度须低于主体保留高度，补点半径须大于零')
    xyz = np.asarray([[row.get(key, np.nan) for key in ('x_3d', 'y_3d', 'z_3d')]
                      for row in markers if row.get('valid_3d', True)], dtype=float).reshape(-1, 3)
    points = np.unique(xyz[np.isfinite(xyz).all(axis=1) & (xyz != 0).any(axis=1)], axis=0)
    if len(points) < 4:
        raise ValueError('标记物平面需要至少 4 个有效且分散的三维圆心')

    # Try a robust consensus first. Cap seed count for dense calibration boards.
    seeds = points[np.linspace(0, len(points) - 1, min(len(points), 16), dtype=int)]
    triples = seeds[np.asarray(list(combinations(range(len(seeds)), 3)))]
    normals = np.cross(triples[:, 1] - triples[:, 0], triples[:, 2] - triples[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    usable = lengths > 1.0
    if not np.any(usable):
        raise ValueError('标记物圆心近似共线，无法确定平面')
    normals = normals[usable] / lengths[usable, None]
    origins = triples[usable, 0]
    residuals = np.abs(points @ normals.T - np.einsum('ij,ij->i', origins, normals))
    inliers = residuals <= 1.0
    best = np.argmax(inliers.sum(axis=0))
    support = points[inliers[:, best]]
    if len(support) < max(4, np.ceil(.8 * len(points))):
        raise ValueError('标记物圆心未形成可靠的共面分布')
    center = support.mean(axis=0)
    _, spread, basis = np.linalg.svd(support - center, full_matrices=False)
    normal = basis[-1]
    if spread[1] / np.sqrt(len(support)) < 2.0 or spread[1] < .03 * spread[0]:
        raise ValueError('标记物在平面上分布过窄，无法可靠确定方向')
    if np.max(np.abs((support - center) @ normal)) > 1.0:
        raise ValueError('标记物平面拟合残差超限')
    offset = float(-center @ normal)
    if abs(offset) <= 1.0:
        raise ValueError('相机近似位于标记物平面，无法判定工件侧')
    if offset < 0:
        normal, offset = -normal, -offset
    plane = [*normal.tolist(), offset - clearance_mm]
    if bottom_height_mm is None:
        return plane
    return dict(plane=plane, bottom_band_mm=clearance_mm - bottom_height_mm, radius_mm=radius_mm)


def filter_source_cloud(cloud, plane):
    """Return the selected cloud and valid input count, preserving attributes."""
    points = np.asarray(cloud.points)
    valid = np.isfinite(points).all(axis=1) & (points != 0).any(axis=1)
    count = int(np.count_nonzero(valid))
    coefficients = np.asarray(plane.get('plane') if isinstance(plane, dict) else plane, dtype=float)
    if (coefficients.shape != (4,) or not np.isfinite(coefficients).all()
            or not np.isclose(np.linalg.norm(coefficients[:3]), 1.0)):
        raise ValueError('保存的标记物平面参数无效')
    with np.errstate(invalid='ignore'):
        height = np.einsum('ij,j->i', points, coefficients[:3]) + coefficients[3]
    keep = valid & (height > 0)
    if not np.any(keep):
        raise ValueError('标记物平面以上没有有效点，请降低过滤高度或关闭过滤')
    if isinstance(plane, dict):
        band, radius = (float(plane.get(key, np.nan)) for key in ('bottom_band_mm', 'radius_mm'))
        if not (np.isfinite([band, radius]).all() and band > 0 and radius > 0):
            raise ValueError('保存的底边过滤参数无效')
        candidates = np.flatnonzero(valid & ~keep & (height > -band))
        if candidates.size:
            from scipy.spatial import cKDTree

            # Query only the retained main cloud. Restored points never seed further restoration.
            distances, _ = cKDTree(points[keep]).query(
                points[candidates], distance_upper_bound=np.nextafter(radius, np.inf))
            keep[candidates] = distances <= radius
    return cloud.select_by_index(np.flatnonzero(keep)), count
