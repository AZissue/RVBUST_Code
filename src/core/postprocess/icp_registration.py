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
