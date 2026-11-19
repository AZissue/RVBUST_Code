"""Object-ROI ICP refinement, using the project's existing quality-gated solver."""
import numpy as np

from core.feature_masks import roi_pixels
from core.postprocess.icp_registration import ICPParameters, refine_icp
from core.postprocess.session import CloudLayer
from .geometry import bounded, multiscale_icp


def evidence_preserved(pose, coarse, evidence, settings):
    source, target = evidence
    if len(source) < 6:
        return False
    def errors(matrix):
        return np.linalg.norm(source @ matrix[:3,:3].T + matrix[:3,3] - target,axis=1)
    before, after = errors(coarse), errors(pose)
    budget = max(.05, min(.5,settings.tolerance*.25), float(np.sqrt(np.mean(before**2)))*.1)
    needed = max(6, int(np.ceil(settings.inlier_percent/100*len(source))))
    return (np.sum(after <= settings.tolerance) >= needed and
            np.sqrt(np.mean(after**2)) <= np.sqrt(np.mean(before**2))+budget)


def supported_surface(points, seeds, distance):
    """Limit geometry to the depth and spatial neighbourhood of trusted 3D features."""
    from scipy.spatial import cKDTree
    if len(seeds) < 6 or len(points) == 0:
        raise ValueError('工件特征支撑点不足，跳过几何精修')
    spacing = cKDTree(seeds).query(seeds,k=2)[0][:,1]
    radius = max(distance*3, float(np.median(spacing))*3)
    near = cKDTree(seeds).query(points)[0] <= radius
    # All points are in one camera/world coordinate system at each call.
    low, high = np.min(seeds[:,2])-distance, np.max(seeds[:,2])+distance
    selected = points[near & (points[:,2]>=low) & (points[:,2]<=high)]
    if len(selected) < 30:
        raise ValueError('特征支撑范围内工件点云不足，保留特征初值')
    return selected


def feature_surface(frame, matching_roi, workpiece_roi, voxel):
    import open3d as o3d
    if matching_roi is None and workpiece_roi is None:
        raise ValueError('未设置工件或匹配 ROI，跳过几何精修；不使用全幅点云')
    # A workpiece ROI restricts geometry independently of texture matching.
    x0, y0, x1, y1 = roi_pixels(frame.image.shape, workpiece_roi if workpiece_roi is not None else matching_roi)
    if x1 <= x0 or y1 <= y0:
        raise ValueError('工件几何区域为空。')
    points = frame.grid[y0:y1, x0:x1].reshape(-1, 3)
    valid = np.isfinite(points).all(axis=1) & np.any(points != 0, axis=1)
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points[valid]))
    cloud = cloud.voxel_down_sample(voxel)
    if len(cloud.points) > 100000:
        cloud = cloud.uniform_down_sample(int(np.ceil(len(cloud.points) / 100000)))
    return np.asarray(cloud.points).copy()


def refine_feature_pose(reference, moving_points, coarse_pose, evidence, settings):
    """Return moving-sensor -> first-frame pose; optional ICP rejection retains coarse pose."""
    params = ICPParameters(settings.icp_distance, settings.icp_voxel,
                           settings.icp_iterations, settings.icp_overlap / 100)
    try:
        source, target = evidence
        moving_points = supported_surface(moving_points,source,settings.icp_distance)
        reference = CloudLayer(reference.name, supported_surface(reference.points,target,settings.icp_distance))
        moving = CloudLayer('当前工件',
            moving_points @ coarse_pose[:3, :3].T + coarse_pose[:3, 3])
        if settings.geometry_enabled:
            pose = multiscale_icp(reference.points, moving_points, coarse_pose, settings)
            correction = pose @ np.linalg.inv(coarse_pose)
            report = '特征初值约束下的 ROI 多尺度 ICP 微调。'
        else:
            refined, report = refine_icp(reference, moving, params)
            correction = np.asarray(refined.registration_transform)
            pose = correction @ coarse_pose
        # Compare a fixed ROI sample set before/after, counting unmatched points
        # at the distance limit so changing overlap cannot disguise degradation.
        import open3d as o3d
        target_cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(reference.points.copy()))
        source_cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(moving.points.copy()))
        registration = o3d.pipelines.registration
        before = registration.evaluate_registration(source_cloud, target_cloud, params.distance)
        after = registration.evaluate_registration(source_cloud, target_cloud, params.distance, correction)
        def clipped_rms(result):
            return float(np.sqrt(result.fitness * result.inlier_rmse**2
                                 + (1 - result.fitness) * params.distance**2))

        initial_error, final_error = clipped_rms(before), clipped_rms(after)
        if after.fitness < params.min_overlap:
            raise ValueError(f'工件重叠率 {after.fitness:.1%} 低于要求 {params.min_overlap:.1%}')
        if final_error >= initial_error-1e-6:
            raise ValueError(f'固定工件采样误差未改善（{initial_error:.4f} → {final_error:.4f} mm）')
        report += f' 工件重叠率 {before.fitness:.1%} → {after.fitness:.1%}。'
        report += f' 固定工件采样截断 RMS {initial_error:.4f} → {final_error:.4f} mm。'

        if not evidence_preserved(pose,coarse_pose,evidence,settings):
            raise ValueError('ICP 位姿未通过原有特征对应点检查')
        if not bounded(moving_points, coarse_pose, pose, min(settings.icp_max_correction,settings.tolerance)):
            raise ValueError('ICP 修正幅度超过最大修正量')
    except (ValueError, RuntimeError) as exc:
        return coarse_pose, f'ICP 未采用，保留特征配准位姿。{exc}', False
    return pose, report, True
