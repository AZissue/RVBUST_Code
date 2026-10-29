"""Read-only millimetre cloud statistics. No database or UI dependencies."""
from time import perf_counter
import numpy as np


def finite_points(points):
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    return points[np.isfinite(points).all(axis=1)]


def sample(points, limit):
    return points[np.linspace(0, len(points)-1, min(len(points), limit), dtype=np.int64)]


def distances(query, target, *, self_query=False, chunk=16384):
    from scipy.spatial import cKDTree
    tree = cKDTree(target)
    values = []
    for start in range(0, len(query), chunk):
        d, _ = tree.query(query[start:start+chunk], k=2 if self_query else 1, workers=1)
        values.append(d[:, 1] if self_query else d)
    return np.concatenate(values) if values else np.empty(0)


def spacing(points, limit=50000):
    if limit < 1:
        raise ValueError('样本上限必须大于0')
    start = perf_counter()
    points = finite_points(points)
    report = dict(count=len(points), unit='mm', samples=min(limit, len(points)),
                  estimated=len(points) > limit, bbox=np.ptp(points, axis=0).tolist() if len(points) else [0]*3)
    if len(points) < 2:
        report.update(reason='有效点不足2个', samples=0)
    else:
        d = distances(sample(points, limit), points, self_query=True)
        p50, p90, p95 = np.percentile(d, [50, 90, 95])
        report.update(p50=float(p50), mean=float(d.mean()), p90=float(p90), p95=float(p95),
                      ratio=float(p90/p50) if p50 > 0 else None,
                      voxel=float(1.5*p50), voxel_range=[float(p50), float(2*p50)])
    report['seconds'] = perf_counter()-start
    return report


def coverage(query, target, tau, limit=50000):
    if not np.isfinite(tau) or tau <= 0:
        raise ValueError('阈值必须为正有限毫米值')
    query, target = finite_points(query), finite_points(target)
    if not len(query) or not len(target):
        return dict(reason='来源有效点为空')
    d = distances(sample(query, limit), target)
    inside = d[d <= tau]
    return dict(coverage=float(len(inside)/len(d)), samples=len(d), estimated=len(query)>limit,
                median=float(np.median(inside)) if len(inside) else None,
                rms=float(np.sqrt(np.mean(inside**2))) if len(inside) else None,
                p95=float(np.percentile(inside, 95)) if len(inside) else None)


def source_reason(records, confirmed):
    if not records:
        return '无来源信息'
    if any(row is None or row.status == '来源数据已变更，请重新拼接' for row in records):
        return '来源已删除或修订失效'
    if len(records) == 1:
        return '单来源后处理结果'
    if any(row.kind == 'raw' for row in records):
        return '未配准原始帧，无法确认坐标系一致'
    if not confirmed:
        return '无法确认坐标系一致，请确认来源结果已在同一毫米坐标系'
    return ''
