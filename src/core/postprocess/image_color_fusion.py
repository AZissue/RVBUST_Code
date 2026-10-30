"""Recolour fixed geometry from organized, registered original RGB observations."""
import numpy as np
from scipy.spatial import cKDTree
from .session import CloudLayer
from .color_correction import _overlap


def source_poses(database, uid, path=()):
    if uid in path or uid not in database.records:
        raise ValueError('原始帧来源缺失或循环，请重新拼接')
    row = database.records[uid]
    if row.status == '来源数据已变更，请重新拼接':
        raise ValueError('来源数据已变化，请重新拼接')
    if row.registration_transform is not None:
        matrix = np.asarray(row.registration_transform, dtype=float)
        if (matrix.shape != (4,4) or not np.isfinite(matrix).all()
                or not np.allclose(matrix[3], [0,0,0,1])
                or not np.allclose(matrix[:3,:3].T @ matrix[:3,:3], np.eye(3), atol=1e-5)
                or not np.isclose(np.linalg.det(matrix[:3,:3]), 1, atol=1e-5)
                or len(row.source_ids) != 1):
            raise ValueError('ICP来源位姿无效，请重新执行精配准')
        uid_source = row.source_ids[0]
        parent = database.records.get(uid_source)
        if parent is not None and parent.kind == 'raw':
            if parent.pointcloud_aligned is not True:
                raise ValueError('原始帧未确认2D对齐，不能融合')
            poses = {uid_source: (parent.revision, np.eye(4))}
        else:
            poses = source_poses(database, uid_source, (*path, uid))
        return {key: (revision, matrix @ pose) for key, (revision, pose) in poses.items()}
    if row.source_transforms:
        if set(row.source_transforms) != set(row.source_ids):
            raise ValueError('拼接位姿与来源帧不完整，请重新拼接')
        result = {}
        for source, value in row.source_transforms.items():
            raw = database.records.get(source)
            matrix = np.asarray(value, dtype=float)
            if raw is None or raw.kind != 'raw' or raw.pointcloud_aligned is not True:
                raise ValueError('原始帧缺失或未确认2D对齐；请开启对齐重拍并重新拼接')
            if (matrix.shape != (4,4) or not np.isfinite(matrix).all() or
                    not np.allclose(matrix[3], [0,0,0,1]) or
                    not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-5) or
                    not np.isclose(np.linalg.det(matrix[:3,:3]),1,atol=1e-5)):
                raise ValueError('拼接位姿无效，请重新拼接')
            result[source] = (raw.revision, matrix)
        return result
    result = {}
    for source in row.source_ids:
        for key, pose in source_poses(database, source, (*path,uid)).items():
            if key in result and not np.allclose(result[key][1],pose[1]):
                raise ValueError('来源包含不同坐标系的拼接结果，不能直接融合')
            result[key] = pose
    if not result:
        raise ValueError('该结果未保存原始帧拼接位姿，请重新执行拼接；当前模式无法提供位姿时不能使用2D融合')
    return result


def _read(database, uid, revision, matrix):
    row = database.records.get(uid)
    if row is None or row.revision != revision:
        raise ValueError('原始帧已变化，请重新拼接')
    frame, cloud = database.load_frame(uid)
    image = frame.image_np
    points = np.asarray(cloud.points)
    if image is None or image.ndim != 3 or image.shape[2] != 3 or len(points) != image.shape[0]*image.shape[1]:
        raise ValueError('原始PNG与有序PLY不对应或不是彩色图像，不能按像素取色')
    valid = np.isfinite(points).all(axis=1) & (np.linalg.norm(points,axis=1)>1e-8)
    # RGB derives from the corresponding original pixel, never the processed PLY.
    rgb = image.reshape(-1,3)[valid,::-1].astype(float)/255.
    xyz = points[valid]@matrix[:3,:3].T + matrix[:3,3]
    pixels = np.flatnonzero(valid)
    h,w = image.shape[:2]
    border = np.minimum.reduce((pixels%w+1,w-pixels%w,pixels//w+1,h-pixels//w))
    quality = np.minimum(border/10.,1.)
    quality[(rgb.max(axis=1)>.99)|(rgb.max(axis=1)<.02)] = 0
    if not len(xyz): raise ValueError('原始帧没有有效深度')
    return xyz, rgb, quality


def fuse_image_colors(database, layer, poses, params):
    """Two passes: bounded exposure samples, then one original frame at a time."""
    samples=[]
    for uid,(revision,matrix) in poses.items():
        xyz,rgb,quality=_read(database,uid,revision,matrix)
        ids=np.flatnonzero(quality>0)
        ids=ids[np.linspace(0,len(ids)-1,min(len(ids),params.sample_limit),dtype=int)] if len(ids) else ids
        samples.append((xyz[ids].copy(),rgb[ids].copy()))
        del xyz,rgb,quality
    gains=[np.ones(3)]; raw_gains=[np.ones(3)]; matches=0
    for index,(xyz,rgb) in enumerate(samples[1:],1):
        for anchor in range(index-1,-1,-1):
            try:
                gain,report=_overlap(samples[anchor][0],xyz,samples[anchor][1],rgb,False,params)
            except ValueError:
                continue
            absolute=gain*raw_gains[anchor]
            raw_gains.append(absolute)
            gains.append(np.exp(params.strength*np.clip(np.log(absolute),-np.log(params.max_gain),np.log(params.max_gain))))
            matches+=report['matches']
            break
        else:
            raise ValueError(f'原始帧{index+1}无可靠颜色重叠，无法连接参考帧；请增加重叠或调整匹配距离')
    total=np.zeros_like(layer.points); weights=np.zeros(len(layer.points))
    for (uid,(revision,matrix)),gain in zip(poses.items(),gains):
        xyz,rgb,quality=_read(database,uid,revision,matrix)
        tree=cKDTree(xyz)
        rgb=np.clip(rgb*gain,0,1)
        rgb=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        for start in range(0,len(layer.points),params.chunk_size):
            stop=min(start+params.chunk_size,len(layer.points))
            distance,index=tree.query(layer.points[start:stop],distance_upper_bound=params.overlap_distance)
            valid=np.isfinite(distance); target=np.flatnonzero(valid)+start; ids=index[valid]
            weight=quality[ids]*np.exp(-2*(distance[valid]/params.overlap_distance)**2)
            total[target]+=rgb[ids]*weight[:,None]; weights[target]+=weight
        del tree,xyz,rgb,quality
    covered=weights>0
    if not covered.any(): raise ValueError('目标点云与原始帧没有可靠几何对应，请检查坐标系和重叠距离')
    output=layer.colors.copy()
    linear=total[covered]/weights[covered,None]
    output[covered]=np.clip(np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055),0,1)
    report=dict(status='已处理',algorithm='image_fusion',voxel_size_mm=0,mode='原始2D融合',matches=matches,frames=len(poses),
        input_points=len(layer.points),output_points=len(layer.points),
        reason=f'来自{len(poses)}帧原始2D；覆盖{covered.mean():.1%}，未覆盖点保留原色；XYZ不变。')
    return CloudLayer(layer.name+' · 原始2D融合',layer.points,output,source=layer.source,origins=layer.origins),report
