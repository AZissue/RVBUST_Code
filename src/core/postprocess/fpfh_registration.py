"""FPFH registration. All distances and transforms use MCC millimetres."""
import time
import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree
def point_cloud(points):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=np.float64))
    return cloud


def validate_transform(matrix):
    matrix = np.asarray(matrix, dtype=np.float64)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
            or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-5)
            or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-4)
            or not np.isclose(np.linalg.det(matrix[:3, :3]), 1, atol=1e-4)):
        raise ValueError('无效的4×4刚体变换矩阵')
    return matrix


# key, default, lower, upper, purpose and tuning advice
SPECS = [
('voxel_mm',5.,.001,10000.,'特征体素mm：增大提速，减小保留细节；先试3/5/8'),
('normal_radius_mm',10.,.001,10000.,'法线半径mm：建议体素2倍；噪声大适当增大'),
('normal_nn',30,3,10000,'法线最多邻点：增大更稳定但更慢'),
('feature_radius_mm',25.,.001,10000.,'FPFH半径mm：建议体素5倍；重复结构可增大'),
('feature_nn',100,3,10000,'FPFH最多邻点：密云可增加到200'),
('backend','exact_kdtree',0,0,'搜索后端：exact_kdtree使用完整33维正交变换精确搜索；open3d用于对照'),
('mutual',True,0,0,'互近邻：减少错误对应；低重叠时可对照关闭'),
('mutual_fraction',.1,0.,1.,'互近邻不足源特征此比例时退回单向；设0禁止回退'),
('workers',4,1,64,'KD树查询线程数：CPU繁忙时减小'),
('seed',20261110,0,2147483647,'随机种子：固定便于复测；并行仍可能波动'),
('ransac_distance_mm',7.5,.001,10000.,'RANSAC对应距离mm：建议体素1.5倍；过大容易假匹配'),
('edge_ratio',.9,.001,1.,'边长一致比例：接近1更严格；噪声大可试0.85'),
('ransac_n',3,3,20,'RANSAC抽样对数：3起步；增大会显著降低采中概率'),
('ransac_iterations',100000,1,10000000,'RANSAC最大次数：低重叠可增加，耗时上升'),
('confidence',.999,.001,.999999,'RANSAC置信度：提高增加搜索时间'),
('min_consensus',3,3,1000000,'最少几何内点对：小于门禁拒绝结果；实际建议提高'),
('remove_plane',False,0,0,'去最大平面：背景占优时试开；仅影响求解，输出保留全云'),
('plane_voxel_mm',2.,.001,10000.,'平面计算体素mm：增大提速但损失小物体'),
('plane_threshold_mm',3.,.001,10000.,'平面距离mm：过大会删掉物体边缘'),
('plane_n',3,3,20,'平面抽样点数：通常3'),
('plane_iterations',1500,1,1000000,'平面RANSAC最大次数：复杂背景可增加'),
('plane_min_fraction',.15,0.,1.,'平面最小占比：低于此值拒绝去平面'),
('plane_max_fraction',.95,0.,1.,'平面最大占比：高于此值视为剩余几何不足'),
('plane_min_remaining',2048,3,10000000,'去平面最少剩余点：小目标可调低并人工核对'),
('icp',False,0,0,'启用点到点ICP：先验证粗配准，再开启'),
('icp_voxel_mm',2.,.001,10000.,'ICP计算体素mm：减小提高细节但变慢'),
('icp_distance_mm',10.,.001,10000.,'ICP距离mm：过大可能吸附错误平面'),
('icp_iterations',50,1,100000,'ICP最大迭代：30至100起步'),
('icp_relative_fitness',.000001,.000000001,.1,'ICP适应度停止变化量：减小更严格'),
('icp_relative_rmse',.000001,.000000001,.1,'ICP残差停止变化量：减小更严格'),
('eval_voxel_mm',2.,.001,10000.,'评估体素mm：对照实验保持一致'),
('eval_max_points',50000,30,10000000,'每侧评估采样上限：固定种子可复测'),
('eval_distance_mm',10.,.001,10000.,'评估内点距离mm：不能用放宽阈值证明精度改善'),
('min_fscore',0.,0.,1.,'双向覆盖F值门禁：0仅检查共识；实际按场景提高')]
DEFAULTS={k:v for k,v,*_ in SPECS}

def validate(p):
    if set(p)!=set(DEFAULTS): raise ValueError('参数键不完整或未知')
    for k,v,lo,hi,_ in SPECS:
        x=p[k]
        if isinstance(v,str):
            if x not in ('exact_kdtree','open3d'): raise ValueError('未知匹配后端')
        elif isinstance(v,bool):
            if not isinstance(x,bool): raise ValueError(k+'必须为布尔值')
        elif not np.isfinite(x) or not lo<=x<=hi or (isinstance(v,int) and int(x)!=x):
            raise ValueError(k+'参数越界')
    if p['feature_radius_mm']<=p['normal_radius_mm']: raise ValueError('FPFH半径必须大于法线半径')
    if p['plane_min_fraction']>=p['plane_max_fraction']: raise ValueError('平面占比上下限错误')

def solve(reference, moving, p):
    validate(p); started=time.perf_counter(); stages={}
    o3d.utility.random.seed(p['seed']); reg=o3d.pipelines.registration
    clouds=[]; features=[]; preprocessing=[]
    for points in (moving,reference):
        points=np.asarray(points,float)
        points=points[np.isfinite(points).all(1)&np.any(points!=0,axis=1)]
        cloud=point_cloud(points)
        if p['remove_plane']:
            cloud=cloud.voxel_down_sample(p['plane_voxel_mm'])
            if len(cloud.points)<max(p['plane_n'],30): raise ValueError('平面计算点不足')
            _, ids=cloud.segment_plane(p['plane_threshold_mm'],p['plane_n'],p['plane_iterations'])
            fraction=len(ids)/len(cloud.points); cloud=cloud.select_by_index(ids,invert=True)
            if not p['plane_min_fraction']<=fraction<=p['plane_max_fraction'] or len(cloud.points)<p['plane_min_remaining']:
                raise ValueError('去平面后几何不足或占比越界，请关闭去平面或调整参数')
            preprocessing.append(fraction)
        clouds.append(cloud)
        small=cloud.voxel_down_sample(p['voxel_mm'])
        if len(small.points)<max(30,p['ransac_n']): raise ValueError('降采样后点不足，请减小体素')
        small.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=p['normal_radius_mm'],max_nn=p['normal_nn']))
        feature=reg.compute_fpfh_feature(small,o3d.geometry.KDTreeSearchParamHybrid(radius=p['feature_radius_mm'],max_nn=p['feature_nn']))
        if not np.isfinite(np.asarray(feature.data)).all(): raise ValueError('FPFH包含无效值')
        features.append((small,feature))
    stages['preprocess_features']=time.perf_counter()-started; t=time.perf_counter()
    a,b=[np.asarray(f.data).T.copy() for _,f in features]
    if p['backend']=='exact_kdtree':
        mean=(a.sum(0)+b.sum(0))/(len(a)+len(b)); a-=mean; b-=mean
        _,basis=np.linalg.eigh(a.T@a+b.T@b); a=a@basis; b=b@basis
        _,ids=cKDTree(b).query(a,eps=0,workers=p['workers'])
        pairs=np.column_stack((np.arange(len(a)),ids))
        if p['mutual']:
            unique,inverse=np.unique(ids,return_inverse=True)
            _,back=cKDTree(a).query(b[unique],eps=0,workers=p['workers'])
            mutual=pairs[back[inverse]==np.arange(len(a))]
            if len(mutual)>=p['mutual_fraction']*len(a): pairs=mutual
    else:
        pairs=np.asarray(reg.correspondences_from_features(features[0][1],features[1][1],p['mutual'],p['mutual_fraction']))
    stages['matching']=time.perf_counter()-t; t=time.perf_counter()
    if len(pairs)<p['ransac_n']: raise ValueError('特征对应不足')
    coarse=reg.registration_ransac_based_on_correspondence(features[0][0],features[1][0],o3d.utility.Vector2iVector(pairs),p['ransac_distance_mm'],reg.TransformationEstimationPointToPoint(False),p['ransac_n'],[reg.CorrespondenceCheckerBasedOnEdgeLength(p['edge_ratio']),reg.CorrespondenceCheckerBasedOnDistance(p['ransac_distance_mm'])],reg.RANSACConvergenceCriteria(p['ransac_iterations'],p['confidence']))
    stages['ransac']=time.perf_counter()-t
    if len(coarse.correspondence_set)<p['min_consensus']: raise ValueError('RANSAC几何共识不足，拒绝发布')
    matrix=validate_transform(coarse.transformation); coarse_matrix=matrix.copy()
    if p['icp']:
        t=time.perf_counter()
        src,dst=[c.voxel_down_sample(p['icp_voxel_mm']) for c in clouds]
        fine=reg.registration_icp(src,dst,p['icp_distance_mm'],matrix,reg.TransformationEstimationPointToPoint(False),reg.ICPConvergenceCriteria(p['icp_relative_fitness'],p['icp_relative_rmse'],p['icp_iterations']))
        if len(fine.correspondence_set)<3: raise ValueError('ICP无有效共识，拒绝发布')
        matrix=validate_transform(fine.transformation); stages['icp']=time.perf_counter()-t
    t=time.perf_counter()
    rng=np.random.default_rng(p['seed']); evaluation=[]
    for cloud in clouds:
        xyz=np.asarray(cloud.voxel_down_sample(p['eval_voxel_mm']).points)
        if len(xyz)>p['eval_max_points']: xyz=xyz[rng.choice(len(xyz),p['eval_max_points'],replace=False)]
        evaluation.append(point_cloud(xyz))
    def metrics(mat):
        f=reg.evaluate_registration(*evaluation,p['eval_distance_mm'],mat)
        r=reg.evaluate_registration(evaluation[1],evaluation[0],p['eval_distance_mm'],np.linalg.inv(mat))
        return dict(forward=f.fitness,reverse=r.fitness,fscore=2*f.fitness*r.fitness/(f.fitness+r.fitness) if f.fitness+r.fitness else 0,rmse_mm=f.inlier_rmse if f.fitness else None)
    quality=metrics(matrix)
    coarse_quality=metrics(coarse_matrix)
    stages['evaluation']=time.perf_counter()-t
    if quality['fscore']<p['min_fscore']: raise ValueError('双向覆盖不足，拒绝发布')
    return dict(parameters=p.copy(),transform=matrix.tolist(),coarse_transform=coarse_matrix.tolist(),coarse_metrics=coarse_quality,metrics=quality,feature_counts=[len(c.points) for c,_ in features],feature_pairs=len(pairs),consensus=len(coarse.correspondence_set),plane_removed_fractions=preprocessing,stage_seconds=stages,total_seconds=time.perf_counter()-started,unit='mm',direction='moving_to_reference',warning='几何残差不等于真实位姿精度；对称物体可能存在多解')

def merge(reference,moving,result):
    from .session import CloudLayer
    if (reference.colors is None)!=(moving.colors is None): raise ValueError('两云颜色属性不一致，请先统一输入')
    matrix=np.asarray(result['transform'])
    reference_points=reference.points[np.any(reference.points!=0,axis=1)]
    moving_points=moving.points[np.any(moving.points!=0,axis=1)]
    colors=(np.vstack((reference.colors[np.any(reference.points!=0,axis=1)],moving.colors[np.any(moving.points!=0,axis=1)])) if reference.colors is not None else None)
    return CloudLayer(reference.name+' + '+moving.name+' · FPFH',np.vstack((reference_points,moving_points@matrix[:3,:3].T+matrix[:3,3])),colors,origins=reference.origins+moving.origins,parent_transforms={reference.origins[0][0]:np.eye(4).tolist(),moving.origins[0][0]:matrix.tolist()})


def solve_chain(layers, parameters, progress=None):
    """Adjacent-frame registration; T_i_to_first = T_previous_to_first @ T_i_to_previous."""
    validate(parameters)
    if len(layers) < 2:
        raise ValueError('链式配准至少需要两帧')
    poses = [np.eye(4)]
    edges = []
    started = time.perf_counter()
    for i in range(1, len(layers)):
        if progress:
            progress(f'FPFH链式配准 {i}/{len(layers)-1}：{layers[i].name} → {layers[i-1].name}')
        try:
            edge = solve(layers[i-1].points, layers[i].points, parameters)
        except Exception as exc:
            raise ValueError(f'链式配准在第{i+1}帧失败：{layers[i].name} → {layers[i-1].name}；{exc}。整批未发布，请检查相邻重叠或调整顺序/参数。') from exc
        poses.append(validate_transform(poses[-1] @ np.asarray(edge['transform'])))
        edges.append(dict(reference_index=i-1, moving_index=i, reference_name=layers[i-1].name,
                          moving_name=layers[i].name, **edge))
    return dict(mode='chain', parameters=parameters.copy(), frame_names=[layer.name for layer in layers],
                transforms_to_reference=[pose.tolist() for pose in poses], edges=edges,
                unit='mm', direction='each_frame_to_first', total_seconds=time.perf_counter()-started,
                warning='相邻帧链式累积，未执行闭环或全局优化；几何歧义及累计漂移仍需检查。')


def merge_chain(layers, result):
    from .session import CloudLayer
    poses=result.get('transforms_to_reference', [])
    if len(layers)<2 or len(poses)!=len(layers):
        raise ValueError('链式结果与输入帧数不一致，请重新计算')
    colored=[layer.colors is not None for layer in layers]
    if len(set(colored))!=1:
        raise ValueError('各帧颜色属性不一致，请先统一输入')
    points=[]; colors=[]; parents={}; origins=[]
    for layer,pose in zip(layers,poses):
        matrix=validate_transform(pose)
        valid=np.any(layer.points!=0,axis=1)
        points.append(layer.points[valid] @ matrix[:3,:3].T + matrix[:3,3])
        if colored[0]:colors.append(layer.colors[valid])
        if len(layer.origins)!=1 or layer.origins[0][0] in parents:
            raise ValueError('链式输入必须是互不重复的DB点云记录')
        parents[layer.origins[0][0]]=matrix.tolist()
        origins.extend(layer.origins)
    return CloudLayer(f'FPFH链式拼接 ({len(layers)}帧)', np.vstack(points),
                      np.vstack(colors) if colored[0] else None,
                      origins=tuple(origins), parent_transforms=parents)
