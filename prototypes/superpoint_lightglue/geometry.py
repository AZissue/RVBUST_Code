"""Bounded geometry assistance and anchored multi-frame surface optimization (mm)."""
import numpy as np
from scipy.spatial import cKDTree


def transformed(points, pose):
    return points @ pose[:3, :3].T + pose[:3, 3]


def bounded(points, before, after, limit):
    return (np.isfinite(after).all() and
            np.max(np.linalg.norm(transformed(points, after)-transformed(points, before), axis=1)) <= limit)


def surface_cloud(points, voxel):
    import open3d as o3d
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(points).copy()))
    cloud = cloud.voxel_down_sample(voxel)
    if len(cloud.points) > 20000:
        cloud = cloud.uniform_down_sample(int(np.ceil(len(cloud.points)/20000)))
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel*3, max_nn=30))
    # Opposite visible sides of a thin workpiece must not be welded together.
    cloud.orient_normals_towards_camera_location(np.zeros(3))
    return cloud


def geometric_initialization(reference, moving, initial, settings):
    """Optional FPFH proposes a correction near the feature seed, never an unbounded reset."""
    if not settings.geometry_fpfh:
        return initial, ''
    from core.postprocess.fpfh_registration import DEFAULTS, solve, validate_transform
    source = transformed(moving, initial)
    voxel = settings.geometry_voxel
    params = dict(DEFAULTS, voxel_mm=voxel, normal_radius_mm=voxel*2,
                  feature_radius_mm=voxel*5, ransac_distance_mm=voxel*1.5,
                  ransac_iterations=20000, min_consensus=12,
                  eval_voxel_mm=voxel, eval_distance_mm=settings.icp_distance,
                  min_fscore=settings.icp_overlap/100)
    try:
        proposal = validate_transform(solve(reference, source, params)['transform']) @ initial
        if not bounded(moving, initial, proposal, settings.icp_max_correction):
            raise ValueError('几何初值超出最大修正量')
        def score(pose):
            distances = cKDTree(reference).query(transformed(moving, pose))[0]
            return np.mean(np.minimum(distances, settings.icp_distance)**2)
        if score(proposal) >= score(initial):
            raise ValueError('几何初值未改善固定采样误差')
        return proposal, 'FPFH 几何初值已采用。'
    except (ValueError, RuntimeError) as exc:
        return initial, f'FPFH 未采用：{exc}。'


def optimize_geometry(surfaces, poses, settings):
    """Jointly adjust overlapping ROI surfaces; fix the first pose and preserve all samples."""
    from core.pose_graph import PoseGraph
    initial = {key: np.asarray(value).copy() for key, value in poses.items()}
    if not settings.geometry_enabled or len(initial) < 2:
        return initial, '', False
    if any(len(surfaces[key]) < 30 for key in initial):
        return initial, '多帧几何未采用：工件采样不足。', False
    clouds = {key: surface_cloud(surfaces[key], settings.geometry_voxel) for key in initial}
    local = {key: np.asarray(cloud.points) for key, cloud in clouds.items()}
    normals = {key: np.asarray(cloud.normals) for key, cloud in clouds.items()}
    keys = list(initial)
    pairs = [(keys[i], keys[j]) for i in range(len(keys))
             for j in range(max(0, i-settings.geometry_neighbors), i)]
    if len(keys) > settings.geometry_neighbors+1:
        pairs.append((keys[-1], keys[0]))  # Only accepted when a real closure overlaps.
    pairs = [(a, b) for a, b in pairs if min(len(local[a]), len(local[b])) >= 30]
    if not pairs:
        return initial, '多帧几何未采用：工件采样不足。', False
    distance = settings.icp_distance

    def world(p):
        return {key: transformed(local[key], p[key]) for key in keys}

    def score(p):
        points = world(p)
        trees = {key: cKDTree(value) for key,value in points.items()}
        errors = []
        for a, b in pairs:
            for x, y in ((a, b), (b, a)):
                d = trees[y].query(points[x])[0]
                errors.append(np.mean(np.minimum(d, distance)**2))
        return float(np.sqrt(np.mean(errors)))

    current = initial
    baseline = score(initial)
    edge_count = 0
    reason = '有效重叠约束不足'
    for _ in range(settings.geometry_rounds):
        points = world(current)
        trees = {key: cKDTree(points[key]) for key in keys}
        constraints = []
        for a, b in pairs:
            d, ids = trees[b].query(points[a])
            reverse_distance, backward = trees[a].query(points[b])
            na = normals[a] @ current[a][:3, :3].T
            nb = normals[b] @ current[b][:3, :3].T
            overlap = (d < distance) & (np.sum(na*nb[ids], axis=1) > .5)
            coverage = min(np.mean(overlap), np.mean(reverse_distance < distance))
            valid = overlap & (backward[ids] == np.arange(len(d)))
            selected = np.flatnonzero(valid)
            if len(selected) < 30 or coverage < settings.icp_overlap/100:
                continue
            selected = selected[np.linspace(0, len(selected)-1, min(500, len(selected)), dtype=int)]
            constraints.append((a, b, local[a][selected], local[b][ids[selected]]))
        connected = {keys[0]}
        for _ in keys:
            for a, b, _, _ in constraints:
                if a in connected or b in connected:
                    connected.update((a, b))
        constraints = [entry for entry in constraints if entry[0] in connected and entry[1] in connected]
        if not constraints:
            break
        graph = PoseGraph()
        anchor = current[keys[0]]
        for key in connected:
            graph.add_node(key, np.linalg.inv(anchor) @ current[key])
            if key != keys[0]:
                graph.add_edge(key, keys[0], np.linalg.inv(anchor) @ current[key])
        optimized = graph.optimize_global_ba(keys[0], max_iterations=settings.icp_iterations,
                    point_constraints=constraints, robust_scale=max(.05, settings.geometry_voxel*.5))
        proposal = dict(current)
        proposal.update({key: anchor @ matrix for key, matrix in optimized.items()})
        proposal[keys[0]] = initial[keys[0]].copy()
        if any(not bounded(local[key], initial[key], proposal[key], settings.icp_max_correction)
               for key in connected):
            reason = '修正量超过允许纠偏幅度'
            break
        if score(proposal) > score(current)+1e-6:
            reason = '固定采样几何误差变差'
            break
        current = proposal
        edge_count = len(constraints)
        reason = '固定采样改善不足'
    final = score(current)
    accepted = final < baseline-1e-6
    report = (f'多帧几何{"已采用" if accepted else "未采用"}：固定首帧，{edge_count} 条几何约束，'
              f'双向固定采样截断 RMS {baseline:.4f} → {final:.4f} mm。')
    if not accepted:
        report += reason + '，保留逐帧位姿。'
    return (current if accepted else initial), report, accepted


def multiscale_icp(reference, moving, initial, settings):
    """Coarse point-to-point followed by robust point-to-plane at finer scales."""
    import open3d as o3d
    reg = o3d.pipelines.registration
    pose = initial.copy()
    full_source = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(moving).copy()))
    full_target = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(reference).copy()))

    def score(matrix):
        result = reg.evaluate_registration(full_source, full_target, settings.icp_distance, matrix)
        error = result.fitness*result.inlier_rmse**2+(1-result.fitness)*settings.icp_distance**2
        return error, result.fitness

    best = initial.copy()
    best_error, _ = score(best)
    for factor in (4, 2, 1):
        voxel = settings.icp_voxel*factor
        source = surface_cloud(moving, voxel)
        target = surface_cloud(reference, voxel)
        if min(len(source.points), len(target.points)) < 30:
            raise ValueError('多尺度 ICP 工件采样不足')
        estimators = [reg.TransformationEstimationPointToPoint()]
        if factor != 4:
            estimators.append(reg.TransformationEstimationPointToPlane(reg.HuberLoss(settings.icp_voxel)))
        for estimator in estimators:
            result = reg.registration_icp(source, target, settings.icp_distance, best, estimator,
                        reg.ICPConvergenceCriteria(max_iteration=settings.icp_iterations))
            pose = result.transformation
            error, overlap = score(pose)
            if (error < best_error and overlap >= settings.icp_overlap/100
                    and bounded(moving, initial, pose, settings.icp_max_correction)):
                best, best_error = pose.copy(), error
    return best
