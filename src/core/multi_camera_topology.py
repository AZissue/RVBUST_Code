"""Fixed-camera star / shared-marker graph calibration, in millimetres."""
from itertools import combinations
from collections import deque
import numpy as np


def qualified(result):
    try:
        transform = np.asarray(result['T'], dtype=float)
        rms, ratio = float(result['rms_mm']), float(result['inlier_ratio'])
        return (bool(result.get('success')) and transform.shape == (4, 4)
                and np.isfinite(transform).all() and abs(np.linalg.det(transform)) > 1e-12
                and np.isfinite([rms, ratio]).all() and 0 <= rms <= 2 and .5 <= ratio <= 1)
    except (KeyError, TypeError, ValueError, np.linalg.LinAlgError):
        return False


def calibration_paths(engine):
    """Only qualified edges may carry a camera to the reference coordinate frame."""
    adjacency = {}
    for (a, b), result in engine.pair_results.items():
        if qualified(result):
            adjacency.setdefault(a, []).append(b)
            adjacency.setdefault(b, []).append(a)
    reference = engine.reference_id
    paths = {reference: [reference]} if reference else {}
    queue = deque(paths)
    while queue:
        node = queue.popleft()
        for neighbor in sorted(adjacency.get(node, [])):
            if neighbor not in paths:
                paths[neighbor] = [neighbor] + paths[node]
                queue.append(neighbor)
    return paths


def quality_gate(engine, required=()):
    if not engine.pair_results:
        return False, '无合格标定配对，请检查共视标记和逐对误差'
    for (ref, cam), result in engine.pair_results.items():
        if not qualified(result):
            return False, f'{cam}→{ref} 未通过配对门禁（RMS ≤ 2 mm，内点率 ≥ 50%）'
    cameras = (set(required) | set(getattr(engine, 'required_cameras', []))
               | {cid for pair in engine.pair_results for cid in pair})
    if len(cameras) < 2 or engine.reference_id not in cameras:
        return False, '至少需要两台相机及有效参考相机'
    paths = calibration_paths(engine)
    missing = sorted(cameras - paths.keys())
    if missing:
        return False, '无法通过合格配对连接到参考相机：' + '、'.join(missing)
    if getattr(engine, 'topology', 'star') == 'star':
        missing = [cid for cid in sorted(cameras) if cid != engine.reference_id
                   and (engine.reference_id, cid) not in engine.pair_results
                   and (cid, engine.reference_id) not in engine.pair_results]
        if missing:
            return False, '星型标定缺少与参考相机直接共视的配对：' + '、'.join(missing)
    for cid in cameras:
        try:
            transform = engine.get_transform(cid, engine.reference_id)
            if not np.isfinite(transform).all():
                raise ValueError('复合矩阵非有限值')
        except (ValueError, KeyError, np.linalg.LinAlgError) as exc:
            return False, f'{cid} 外参路径无效：{exc}'
    maximum = max(float(result['rms_mm']) for result in engine.pair_results.values())
    minimum = min(float(result['inlier_ratio']) for result in engine.pair_results.values())
    return True, f'{len(cameras)} 台相机全部可达，最大 RMS {maximum:.3f}mm，最小内点率 {minimum:.1%}'


def solve(engine, frames, reference, topology, required):
    """Chain mode chooses a deterministic minimum-RMS spanning tree of good edges.

    No chain-wide precision claim or bundle adjustment: residuals belong to each
    measured edge. Missing / bad candidate edges are diagnostics, never transforms.
    """
    if topology not in ('star', 'chain'):
        raise ValueError('未知标定方式')
    engine.pair_results.clear()
    engine.reference_id = reference
    engine.topology = topology
    engine.required_cameras = sorted(set(required) | set(frames))
    diagnostics, candidates = [], []
    pairs = ([(reference, cid) for cid in sorted(frames) if cid != reference]
             if topology == 'star' else list(combinations(sorted(frames), 2)))
    for ref, cam in pairs:
        if ref not in frames or not frames[ref].markers or not frames[cam].markers:
            diagnostics.append(f'{cam}→{ref}：缺少标记')
            continue
        result = engine.calibrate_pair(ref, cam, frames[ref].markers, frames[cam].markers,
                                       ransac_threshold=2.0)
        if qualified(result):
            candidates.append(((ref, cam), result))
        else:
            diagnostics.append(f'{cam}→{ref}：' + result.get('message', '配对质量未达标'))
    # calibrate_pair writes into the engine; replace these trial results atomically
    # at the end so failed trials / older calibrations cannot be used for stitching.
    if topology == 'chain':
        connected, chosen = {reference}, {}
        candidates.sort(key=lambda item: (item[1]['rms_mm'], -item[1]['inlier_ratio'], item[0]))
        while True:
            edge = next((item for item in candidates
                         if (item[0][0] in connected) != (item[0][1] in connected)), None)
            if edge is None:
                break
            key, result = edge
            chosen[key] = result
            connected.update(key)
        engine.pair_results = chosen
    else:
        engine.pair_results = dict(candidates)
    engine.reference_id = reference
    return diagnostics
