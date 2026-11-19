"""Object-ROI ICP refinement, using the project's existing quality-gated solver."""
import numpy as np

from core.feature_masks import roi_pixels
from core.postprocess.icp_registration import ICPParameters, refine_icp
from core.postprocess.session import CloudLayer


def feature_surface(frame, matching_roi, workpiece_roi, voxel):
    import open3d as o3d
    matching_box = roi_pixels(frame.image.shape, matching_roi)
    workpiece_box = roi_pixels(frame.image.shape, workpiece_roi)
    x0, y0 = max(matching_box[0], workpiece_box[0]), max(matching_box[1], workpiece_box[1])
    x1, y1 = min(matching_box[2], workpiece_box[2]), min(matching_box[3], workpiece_box[3])
    if x1 <= x0 or y1 <= y0:
        raise ValueError('ICP 的匹配框与工件框没有重叠。')
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
        if final_error > initial_error+1e-6 or after.fitness < params.min_overlap:
            raise ValueError('ICP 在固定工件采样上的几何误差或重叠率未通过检查')
        report += f' 固定工件采样截断 RMS {initial_error:.4f} → {final_error:.4f} mm。'

        source, target = evidence
        errors = np.linalg.norm(source @ pose[:3, :3].T + pose[:3, 3] - target, axis=1)
        needed = max(6, int(np.ceil(settings.inlier_percent / 100 * len(source))))
        if int((errors <= settings.tolerance).sum()) < needed:
            raise ValueError('ICP 位姿未通过原有特征对应点检查')
        displacement = np.linalg.norm(source @ pose[:3, :3].T + pose[:3, 3]
                                     - (source @ coarse_pose[:3, :3].T + coarse_pose[:3, 3]), axis=1)
        if displacement.max() > settings.icp_distance:
            raise ValueError('ICP 修正幅度超过最大对应距离')
    except ValueError as exc:
        return coarse_pose, f'ICP 未采用，保留特征配准位姿。{exc}', False
    return pose, report, True
