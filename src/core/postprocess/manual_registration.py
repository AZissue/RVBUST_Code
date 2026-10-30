"""Rigid landmark initialization followed by ICP; immutable merged output."""
import numpy as np
from .session import CloudLayer
from .icp_registration import refine_icp


def landmark_transform(reference, moving):
    a, b = np.asarray(reference, float), np.asarray(moving, float)
    if a.shape != b.shape or a.ndim != 2 or a.shape[1] != 3 or len(a) < 3:
        raise ValueError('请按相同顺序选取至少3对共有点')
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('共有点包含无效坐标')
    ac, bc = a-a.mean(0), b-b.mean(0)
    for points in (ac, bc):
        singular = np.linalg.svd(points, compute_uv=False)
        if singular[0] < 1e-8 or singular[1] < singular[0]*1e-4:
            raise ValueError('共有点重复或近似共线，请选取分散且不共线的点')
    u, _, vt = np.linalg.svd(bc.T @ ac)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    transform = np.eye(4)
    transform[:3,:3] = rotation
    transform[:3,3] = a.mean(0)-rotation @ b.mean(0)
    residual = b @ rotation.T + transform[:3,3] - a
    return transform, float(np.sqrt(np.mean(np.sum(residual**2,axis=1))))


def register_manual(reference, moving, reference_points, moving_points, params):
    initial, rms = landmark_transform(reference_points, moving_points)
    rough = CloudLayer(moving.name, moving.points @ initial[:3,:3].T+initial[:3,3],
                       moving.colors, origins=moving.origins)
    aligned, report = refine_icp(reference, rough, params)
    matrix = np.asarray(aligned.registration_transform) @ initial
    if (reference.colors is None) != (moving.colors is None):
        raise ValueError('两项颜色属性不一致，请使用同类点云，避免补造颜色')
    output = CloudLayer(reference.name+' + '+moving.name+' · 手动配准ICP',
        np.vstack([reference.points, aligned.points]),
        np.vstack([reference.colors, aligned.colors]) if reference.colors is not None else None,
        origins=reference.origins+moving.origins,
        parent_transforms={reference.origins[0][0]:np.eye(4).tolist(), moving.origins[0][0]:matrix.tolist()})
    return output, f'共有点{len(reference_points)}对，初始RMS {rms:.4f} mm；'+report
