"""Immutable file-pair analysis and complete-cloud merge; no device SDK."""
from pathlib import Path
import cv2
import numpy as np
from .circles import CircleParameters,detect_circles
from .matching import MatchParameters,match_geometry
from core.postprocess.session import CloudLayer


def read_frame(directory,record,params):
    import open3d as o3d
    if record.kind!='raw':
        raise ValueError('请选择两帧原始图像+有序点云，拼接结果不能做逐像素圆心定位')
    folder=Path(directory)/'frames'/record.uid
    image=cv2.imdecode(np.fromfile(folder/'image.png',np.uint8),cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError('原始2D图像无法读取')
    cloud=o3d.io.read_point_cloud(str(folder/'pointmap.ply'),remove_nan_points=False,remove_infinite_points=False)
    points=np.asarray(cloud.points)
    dots=detect_circles(image,points,params)
    valid=np.isfinite(points).all(axis=1)&np.any(points!=0,axis=1)
    if not valid.any():
        raise ValueError('原始点云没有有效点')
    layer=CloudLayer(record.logical_name,points[valid],np.asarray(cloud.colors)[valid] if cloud.has_colors() else None,
                     origins=((record.uid,record.revision),))
    return dict(image=image,dots=dots,valid_dots=[dot for dot in dots if dot['valid_3d']],layer=layer)


def analyze_pair(directory,reference,moving,circle_params=CircleParameters(),match_params=MatchParameters()):
    if reference.uid==moving.uid:
        raise ValueError('参考帧和移动帧不能相同')
    frames=[read_frame(directory,row,circle_params) for row in (reference,moving)]
    result=dict(frames=frames,match=None,error='')
    try:
        centres=[np.asarray([dot['xyz'] for dot in frame['valid_dots']]).reshape(-1,3) for frame in frames]
        result['match']=match_geometry(*centres,match_params)
    except ValueError as exc:
        result['error']=str(exc)
    return result


def merged_layer(analysis):
    match=analysis['match']
    if match is None:
        raise ValueError('尚未得到唯一有效的三角形匹配')
    a,b=[frame['layer'] for frame in analysis['frames']]
    if (a.colors is None)!=(b.colors is None):
        raise ValueError('两帧颜色属性不一致，不能补造颜色后合并')
    transform=match['transform']
    return CloudLayer(a.name+' + '+b.name+' · 圆点三角匹配',
        np.vstack([a.points,b.points@transform[:3,:3].T+transform[:3,3]]),
        np.vstack([a.colors,b.colors]) if a.colors is not None else None,
        source='普通圆点三角形匹配',origins=a.origins+b.origins,
        parent_transforms={a.origins[0][0]:np.eye(4).tolist(),b.origins[0][0]:transform.tolist()})
