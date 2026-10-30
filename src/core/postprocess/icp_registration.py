"""Optional rigid refinement of two already roughly aligned clouds (millimetres)."""
from dataclasses import dataclass
import numpy as np
from .session import CloudLayer

@dataclass(frozen=True)
class ICPParameters:
    distance: float = 2.0
    voxel: float = 1.0
    iterations: int = 50
    min_overlap: float = .3

    def validate(self):
        if not np.isfinite([self.distance, self.voxel, self.min_overlap]).all():
            raise ValueError('ICP参数必须为有限数值')
        if not .001 <= self.distance <= 1000 or not .001 <= self.voxel <= 1000:
            raise ValueError('对应距离和计算体素必须在0.001～1000 mm之间')
        if not 1 <= self.iterations <= 500 or not .01 <= self.min_overlap <= 1:
            raise ValueError('迭代次数或最小重叠率超出范围')


def refine_icp(reference, moving, params):
    import open3d as o3d
    params.validate()
    def sampled(layer):
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(layer.points.copy()))
        return cloud.voxel_down_sample(params.voxel)
    target, source = sampled(reference), sampled(moving)
    if min(len(target.points), len(source.points)) < 6:
        raise ValueError('计算点数不足，请减小计算体素尺寸')
    reg = o3d.pipelines.registration
    before = reg.evaluate_registration(source, target, params.distance)
    result = reg.registration_icp(source, target, params.distance, np.eye(4),
        reg.TransformationEstimationPointToPoint(),
        reg.ICPConvergenceCriteria(max_iteration=int(params.iterations)))
    matrix = result.transformation
    if (not np.isfinite(matrix).all() or result.fitness < params.min_overlap
            or len(result.correspondence_set) < 6):
        raise ValueError(f'ICP重叠不足（{result.fitness:.1%}），请先粗配准、检查坐标系或调整对应距离；未发布结果')
    if result.fitness + 1e-6 < before.fitness or (result.fitness <= before.fitness + 1e-6 and result.inlier_rmse > before.inlier_rmse + 1e-6):
        raise ValueError('ICP未改善配准，未发布结果；请检查初始位姿和重叠区域')
    points = moving.points @ matrix[:3,:3].T + matrix[:3,3]
    output = CloudLayer(moving.name+' · ICP精配准', points, moving.colors,
        source='ICP精配准', origins=moving.origins, registration_transform=matrix.tolist())
    report = (f'ICP重叠率 {before.fitness:.1%} → {result.fitness:.1%}；'
        f'对应点RMS {before.inlier_rmse:.4f} → {result.inlier_rmse:.4f} mm；'
        f'输出 {len(points):,} 点（保持有效点数）。参考点云：{reference.name}。')
    return output, report


def refine_stitched(database, uid, reference_uid, params):
    """Rebuild a stitch from its raw frames; fix one frame and grow the reference."""
    from .image_color_fusion import source_poses
    from ..point_cloud_processor import PointCloudProcessor
    row = database.records[uid]
    if row.kind != 'result' or row.purpose == '后处理结果':
        raise ValueError('请选择原始拼接结果；裁剪/下采样后的结果不能直接按原始帧重建')
    poses = source_poses(database, uid)
    if len(poses) < 2 or reference_uid not in poses:
        raise ValueError('原始帧及位姿不足，请重新执行拼接')
    order = [reference_uid] + [key for key in poses if key != reference_uid]
    def load(key):
        revision, pose = poses[key]
        raw = database.records.get(key)
        if raw is None or raw.revision != revision:
            raise ValueError('原始帧已变化，请重新执行拼接')
        _, cloud = database.load_frame(key, 'cloud')
        cloud, _ = PointCloudProcessor._filter_valid(cloud)
        return CloudLayer(raw.logical_name,
            np.asarray(cloud.points) @ pose[:3,:3].T + pose[:3,3],
            np.asarray(cloud.colors) if cloud.has_colors() else None,
            origins=((key, revision),))
    layers = [load(reference_uid)]
    transforms = {reference_uid: poses[reference_uid][1].tolist()}
    reports = []
    pending = order[1:]
    # Retry non-overlapping frames after the reference has grown. No frame is dropped.
    while pending:
        progressed = False
        failures = []
        for key in list(pending):
            reference = CloudLayer('已精配准参考', np.vstack([layer.points for layer in layers]))
            moving = load(key)
            try:
                output, report = refine_icp(reference, moving, params)
            except ValueError as exc:
                failures.append(f'{moving.name}：{exc}')
                continue
            transforms[key] = (np.asarray(output.registration_transform) @ poses[key][1]).tolist()
            layers.append(output)
            reports.append(report)
            pending.remove(key)
            progressed = True
        if not progressed:
            raise ValueError('部分来源帧无法精配准，整批未发布。请检查重叠或调整参数。\n'+'\n'.join(failures))
    has_colors = [layer.colors is not None for layer in layers]
    if any(has_colors) and not all(has_colors):
        raise ValueError('来源帧颜色属性不一致，未发布结果；请统一原始帧颜色数据')
    merged = CloudLayer(row.logical_name+' · 来源帧ICP精修',
        np.vstack([layer.points for layer in layers]),
        np.vstack([layer.colors for layer in layers]) if all(has_colors) else None,
        source='原始帧ICP重建', origins=tuple((key, poses[key][0]) for key in order),
        source_transforms=transforms)
    return merged, f'固定参考：{database.records[reference_uid].logical_name}；重建{len(layers)}帧，保留全部{len(merged.points):,}有效点。\n'+'\n'.join(reports)
