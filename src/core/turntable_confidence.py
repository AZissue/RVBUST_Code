"""Advisory two-frame diagnostics, never a fixed-axis acceptance certificate.

All distances are mm. Distance is measured from the reference marker centroid
to the axis line, so changing the arbitrary point along that line changes no check.
"""
import numpy as np

DEFAULT_LIMITS = dict(small_angle_deg=5., axial_shift_mm=1.,
                      center_distance_mm=1000., center_scale_ratio=10.)


def assess(axis, angle_rad, center, *, translation=None, reference_points=None, limits=None):
    limits = dict(DEFAULT_LIMITS, **(limits or {}))
    if any(not np.isfinite(value) or value <= 0 for value in limits.values()):
        raise ValueError('可信度提示阈值必须为有限正数')
    axis, center = np.asarray(axis, dtype=float), np.asarray(center, dtype=float)
    axis_ok = axis.shape == (3,) and np.isfinite(axis).all() and np.linalg.norm(axis) > 1e-9
    if axis_ok:
        axis = axis / np.linalg.norm(axis)
    angle = abs(float(np.degrees(angle_rad))) if np.isfinite(angle_rad) else None
    shift = None
    if translation is not None and axis_ok:
        translation = np.asarray(translation, dtype=float)
        if translation.shape == (3,) and np.isfinite(translation).all():
            shift = abs(float(np.dot(axis, translation)))
    distance, scale = None, None
    if reference_points is not None and axis_ok and center.shape == (3,) and np.isfinite(center).all():
        points = np.asarray(reference_points, dtype=float)
        if points.ndim == 2 and points.shape[1] == 3 and len(points) >= 3 and np.isfinite(points).all():
            centroid = points.mean(axis=0)
            offset = centroid - center
            distance = float(np.linalg.norm(offset-axis*np.dot(offset, axis)))
            scale = float(np.sqrt(np.mean(np.sum((points-centroid)**2, axis=1))))
    distance_limit = max(limits['center_distance_mm'], limits['center_scale_ratio'] * (scale or 0.))
    checks = []
    for key, label, value, limit, unit, small, reason in (
            ('small_angle', '小角度', angle, limits['small_angle_deg'], '°', True,
             '两帧转角过小，会放大轴心估计误差，建议增大转角后复核'),
            ('axial_shift', '轴向位移', shift, limits['axial_shift_mm'], 'mm', False,
             '刚体平移在转轴方向的分量较大，不符合固定轴纯旋转；也可能受深度噪声影响'),
            ('center_distance', '轴心距离', distance, distance_limit, 'mm', False,
             '标记重心到轴线距离较大，可能出现远轴心解释平移；请结合平台尺寸复核')):
        flagged = value is not None and (value < limit-1e-9 if small else value > limit+1e-9)
        state = 'unassessed' if value is None else 'warning' if flagged else 'clear'
        measurement = '未评估（缺少原始刚体平移）' if value is None and key == 'axial_shift' else '未评估（缺少标记位置或有效参数）' if value is None else f'{value:.3f} {unit}，提示阈值 {"<" if small else ">"} {limit:.3f} {unit}'
        checks.append(dict(key=key, label=label, value=value, limit=limit, unit=unit,
                           state=state, text=f'{label}：{measurement}' + (f'；{reason}' if flagged else '')))
    state = 'warning' if any(c['state'] == 'warning' for c in checks) else 'partial' if any(c['state'] == 'unassessed' for c in checks) else 'clear'
    summary = {'warning': '需复核', 'partial': '资料不全，部分未评估', 'clear': '未触发三项初筛提示'}[state]
    return dict(state=state, summary=summary, checks=checks, limits=limits, marker_scale_mm=scale)


def report_for(calibration, snapshot=None):
    report = getattr(calibration, 'confidence', None) or (snapshot or {}).get('confidence')
    if isinstance(report, dict) and isinstance(report.get('checks'), list):
        return report
    details = (snapshot or {}).get('result', {}).get('details', [])
    points = [row['pt_ref'] for row in details if isinstance(row, dict) and 'pt_ref' in row]
    return assess(calibration.axis, calibration.angle_rad, calibration.center,
                  translation=calibration.t_init, reference_points=points or None)
