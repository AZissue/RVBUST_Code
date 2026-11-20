"""Fixed-reference joint fitting of measured 3D marker correspondences, in mm.

Pair transforms remain local measurements. Final node poses are stored separately
so a direct pair cannot override a globally optimized transform query.
"""
import numpy as np
from copy import deepcopy
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def rigid(value):
    try:
        value = np.asarray(value, dtype=float)
    except (ValueError, TypeError):
        return False
    return (value.shape == (4, 4) and np.isfinite(value).all()
            and np.allclose(value[3], [0, 0, 0, 1], atol=1e-8)
            and np.allclose(value[:3, :3].T @ value[:3, :3], np.eye(3), atol=1e-6)
            and np.isclose(np.linalg.det(value[:3, :3]), 1., atol=1e-6))


def constraints(pairs):
    result = []
    for (a, b), pair in sorted(pairs.items()):
        rows = [row for row in pair.get('details', []) if row.get('is_inlier')]
        if len(rows) < 3:
            raise ValueError(f'{b}→{a} 缺少原始三维内点约束')
        pa = np.asarray([row['pt_ref'] for row in rows], dtype=float)
        pb = np.asarray([row['pt_cam'] for row in rows], dtype=float)
        if (pa.shape != (len(rows), 3) or pb.shape != pa.shape
                or not np.isfinite(pa).all() or not np.isfinite(pb).all()
                or min(np.linalg.matrix_rank(pa-pa.mean(axis=0)),
                       np.linalg.matrix_rank(pb-pb.mean(axis=0))) < 2):
            raise ValueError(f'{b}→{a} 三维约束无效或共线')
        result.append((a, b, pa, pb))
    return result


def errors(poses, observations):
    return [(a, b, (pa @ poses[a][:3, :3].T + poses[a][:3, 3])
             - (pb @ poses[b][:3, :3].T + poses[b][:3, 3]))
            for a, b, pa, pb in observations]


def statistics(poses, observations):
    distances = [np.linalg.norm(delta, axis=1) for _, _, delta in errors(poses, observations)]
    return float(np.sqrt(np.mean(np.concatenate(distances)**2)))


def initial_poses(pairs, reference):
    """Prim initialization only; every measured edge still enters joint fitting."""
    poses, routes = {reference: np.eye(4)}, {reference: [reference]}
    ranked = sorted(pairs.items(), key=lambda item: (item[1]['rms_mm'],
                    -item[1]['inlier_ratio'], item[0]))
    while True:
        edge = next(((key, row) for key, row in ranked
                     if (key[0] in poses) != (key[1] in poses)), None)
        if edge is None:
            break
        (a, b), row = edge
        if a in poses:
            poses[b] = poses[a] @ row['T']
            routes[b] = [b] + routes[a]
        else:
            poses[a] = poses[b] @ np.linalg.inv(row['T'])
            routes[a] = [a] + routes[b]
    return poses, routes


def fit(pairs, reference, required):
    initial, routes = initial_poses(pairs, reference)
    missing = sorted(set(required) - initial.keys())
    if missing:
        raise ValueError('共视约束无法连接到参考相机：' + '、'.join(missing))
    observations = constraints(pairs)
    initial_rms = statistics(initial, observations)
    nodes = sorted(set(initial) - {reference})

    def unpack(x):
        poses = {reference: np.eye(4)}
        for i, cid in enumerate(nodes):
            pose = np.eye(4)
            pose[:3, :3] = Rotation.from_rotvec(x[i*6:i*6+3]).as_matrix()
            pose[:3, 3] = x[i*6+3:i*6+6]
            poses[cid] = pose
        return poses

    x0 = np.concatenate([np.r_[Rotation.from_matrix(initial[cid][:3, :3]).as_rotvec(),
                                initial[cid][:3, 3]] for cid in nodes])

    def residual(x):
        return np.concatenate([delta.ravel() for _, _, delta in errors(unpack(x), observations)])

    def cost(values):
        # Same soft-L1 objective used by the solver (f_scale=.5 mm).
        return float(np.sum(np.sqrt(1 + (values / .5)**2) - 1))

    poses, optimized, message = initial, False, ''
    try:
        result = least_squares(residual, x0, method='trf', loss='soft_l1',
                               f_scale=.5, max_nfev=300, x_scale='jac')
        if not result.success:
            raise ValueError('联合求解未收敛：' + str(result.message))
        proposed = unpack(result.x)
        if (not all(rigid(pose) for pose in proposed.values())
                or not np.isfinite(result.fun).all()
                or cost(residual(result.x)) > cost(residual(x0)) + 1e-8):
            raise ValueError('联合求解位姿无效或稳健代价恶化')
        poses, optimized = proposed, True
        message = '已使用全部合格共视约束联合优化'
    except Exception as exc:
        message = '联合优化未采用，回退共视树初值：' + str(exc)
    report = dict(optimized=optimized, message=message, constraint_count=len(pairs),
        initial_rms_mm=initial_rms, final_rms_mm=statistics(poses, observations),
        initial_paths=routes)
    return poses, report


def validate(engine):
    """Recompute final-coordinate residual gates; never trust saved report metrics."""
    if getattr(engine, 'joint_report', {}).get('error'):
        return False, engine.joint_report['error']
    poses = getattr(engine, 'global_poses', {})
    cameras = set(engine.required_cameras) | {cid for edge in engine.pair_results for cid in edge}
    if set(poses) != cameras or not all(rigid(pose) for pose in poses.values()):
        return False, '联合外参节点缺失或位姿不是有效刚体变换'
    if engine.reference_id not in poses or not np.allclose(poses[engine.reference_id], np.eye(4), atol=1e-8):
        return False, '联合外参参考坐标系未固定'
    try:
        observations = constraints(engine.pair_results)
        for a, b, delta in errors(poses, observations):
            distance = np.linalg.norm(delta, axis=1)
            rms = float(np.sqrt(np.mean(distance**2)))
            ratio = float(np.sum(distance < 2.) / engine.pair_results[a, b]['total_pairs'])
            if not np.isfinite([rms, ratio]).all() or rms > 2. or ratio < .5:
                return False, f'共视约束 {b}→{a} 全局不一致（RMS {rms:.3f}mm，内点率 {ratio:.1%}）'
        value = statistics(poses, observations)
    except (KeyError, TypeError, ValueError, ZeroDivisionError, np.linalg.LinAlgError) as exc:
        return False, '联合三维约束无效：' + str(exc)
    return True, f'全局三维内点 RMS {value:.3f}mm，{len(observations)} 条共视约束'


def inspection_pairs(engine):
    """Display the actual final transforms without overwriting pair measurements."""
    pairs = {key: deepcopy(row) for key, row in engine.pair_results.items() if row.get('success')}
    if not engine.global_poses or engine.joint_report.get('error'):
        return pairs
    for (a, b), pair in pairs.items():
        transform = engine.get_transform(b, a)
        pair['local_rms_mm'] = pair['rms_mm']
        pair['T'] = transform
        for row in pair['details']:
            moved = np.asarray(row['pt_cam']) @ transform[:3, :3].T + transform[:3, 3]
            row['pt_cam_transformed'] = moved.tolist()
            row['error_mm'] = float(np.linalg.norm(moved - row['pt_ref']))
            # Keep the original local classification to show the same observations
            # before/after optimization rather than hide difficult points.
        distances = np.asarray([row['error_mm'] for row in pair['details']])
        inliers = np.asarray([row['is_inlier'] for row in pair['details']], dtype=bool)
        selected = distances[inliers]
        pair.update(rms_mm=float(np.sqrt(np.mean(selected**2))), mean_mm=float(selected.mean()),
                    min_mm=float(selected.min()), max_mm=float(selected.max()),
                    rms_all_mm=float(np.sqrt(np.mean(distances**2))))
    return pairs
