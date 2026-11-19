"""Object-ROI ICP refinement, using the project's existing quality-gated solver."""
import numpy as np

from core.feature_masks import roi_pixels
from core.postprocess.icp_registration import ICPParameters, refine_icp
from core.postprocess.session import CloudLayer
from .geometry import bounded, geometric_initialization, multiscale_icp


def feature_surface(frame, matching_roi, workpiece_roi, voxel):
    import open3d as o3d
    # Geometry has its own workpiece region; texture evidence may be elsewhere.
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
        moving = CloudLayer('当前工件',
            moving_points @ coarse_pose[:3, :3].T + coarse_pose[:3, 3])
        if settings.geometry_enabled:
            seed, note = geometric_initialization(reference.points, moving_points, coarse_pose, settings)
            pose = multiscale_icp(reference.points, moving_points, seed, settings)
            correction = pose @ np.linalg.inv(coarse_pose)
            report = note + '多尺度 ICP 候选择优：粗层点到点，细层稳健点到面。'
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

        source, target = evidence
        errors = np.linalg.norm(source @ pose[:3, :3].T + pose[:3, 3] - target, axis=1)
        needed = max(6, int(np.ceil(settings.inlier_percent / 100 * len(source))))
        if not settings.geometry_enabled and int((errors <= settings.tolerance).sum()) < needed:
            raise ValueError('ICP 位姿未通过原有特征对应点检查')
        if not bounded(moving_points, coarse_pose, pose, settings.icp_max_correction):
            raise ValueError('ICP 修正幅度超过最大修正量')
    except (ValueError, RuntimeError) as exc:
        return coarse_pose, f'ICP 未采用，保留特征配准位姿。{exc}', False
    return pose, report, True
