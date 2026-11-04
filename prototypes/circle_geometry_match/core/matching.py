"""Shape-matcher registry: triangle seeds, one-to-one 3D consensus, no scale fitting."""
from dataclasses import dataclass
from itertools import combinations,permutations
import numpy as np
from scipy.spatial import cKDTree
from core.postprocess.manual_registration import landmark_transform

@dataclass(frozen=True)
class MatchParameters:
    edge_tolerance: float = 1.
    relative_tolerance: float = .01
    point_tolerance: float = 2.
    min_matches: int = 3
    min_edge: float = 5.
    max_hypotheses: int = 5000

    def validate(self):
        values=[self.edge_tolerance,self.relative_tolerance,self.point_tolerance,self.min_edge]
        if not np.isfinite(values).all() or not .001<=self.edge_tolerance<=100 or not 0<=self.relative_tolerance<=.1:
            raise ValueError('三角形边长容差无效')
        if not .001<=self.point_tolerance<=100 or not .001<=self.min_edge<=10000:
            raise ValueError('匹配距离或最短边无效')
        if not 3<=self.min_matches<=24 or not 1<=self.max_hypotheses<=50000:
            raise ValueError('最少匹配数或候选上限无效')


def _triangles(points,params):
    rows=[];descriptors=[]
    for ids in combinations(range(len(points)),3):
        tri=points[list(ids)]
        edges=np.linalg.norm(tri[[0,0,1]]-tri[[1,2,2]],axis=1)
        if edges.min()<params.min_edge:
            continue
        if np.linalg.norm(np.cross(tri[1]-tri[0],tri[2]-tri[0]))/(edges.max()**2)<.03:
            continue
        rows.append(ids);descriptors.append(np.sort(edges))
    return rows,np.asarray(descriptors)


def _pairs(reference,moving,transform,tolerance):
    transformed=moving@transform[:3,:3].T+transform[:3,3]
    # At most24 centres: enforce an optimal one-to-one assignment with dummy misses.
    from scipy.optimize import linear_sum_assignment
    distances=np.linalg.norm(transformed[:,None,:]-reference[None,:,:],axis=2)
    cost=np.where(distances<=tolerance,distances/(tolerance*100),1e6)
    cost=np.c_[cost,np.ones((len(moving),len(moving)))]
    mi,ri=linear_sum_assignment(cost)
    valid=(ri<len(reference))
    mi,ri=mi[valid],ri[valid]
    return np.column_stack((ri,mi)).astype(int)


def match_triangles(reference,moving,params=MatchParameters()):
    params.validate()
    reference=np.asarray(reference,float);moving=np.asarray(moving,float)
    for points in (reference,moving):
        if points.ndim!=2 or points.shape[1]!=3 or not 3<=len(points)<=24 or not np.isfinite(points).all():
            raise ValueError('每帧需要3–24个具有有效3D的圆心')
        distances=np.linalg.norm(points[:,None,:]-points[None,:,:],axis=2)+np.eye(len(points))*1e20
        if distances.min()<1e-6:
            raise ValueError('圆心重复，不能匹配')
    rt,rd=_triangles(reference,params);mt,md=_triangles(moving,params)
    if not rt or not mt:
        raise ValueError('没有有效三角形：圆心过近、近共线或分布退化')
    tree=cKDTree(rd)
    candidates={};hypotheses=0
    for moving_ids,descriptor in zip(mt,md):
        tolerance=params.edge_tolerance+params.relative_tolerance*descriptor.max()
        for index in tree.query_ball_point(descriptor,np.sqrt(3)*tolerance):
            if np.any(np.abs(rd[index]-descriptor)>tolerance):
                continue
            a=reference[list(rt[index])]
            a_edges=np.linalg.norm(a[:,None,:]-a[None,:,:],axis=2)
            for ordered in permutations(moving_ids):
                b=moving[list(ordered)]
                if np.max(np.abs(a_edges-np.linalg.norm(b[:,None,:]-b[None,:,:],axis=2)))>tolerance:
                    continue
                hypotheses+=1
                if hypotheses>params.max_hypotheses:
                    raise ValueError('三角形候选过多，无法完成歧义检查；请减少圆点或收紧边长容差')
                transform,_=landmark_transform(a,b)
                pairs=_pairs(reference,moving,transform,params.point_tolerance)
                if len(pairs)<params.min_matches:
                    continue
                try:
                    transform,rms=landmark_transform(reference[pairs[:,0]],moving[pairs[:,1]])
                    pairs=_pairs(reference,moving,transform,params.point_tolerance)
                    if len(pairs)<params.min_matches:
                        continue
                    transform,rms=landmark_transform(reference[pairs[:,0]],moving[pairs[:,1]])
                except ValueError:
                    continue
                errors=np.linalg.norm(moving[pairs[:,1]]@transform[:3,:3].T+transform[:3,3]-reference[pairs[:,0]],axis=1)
                if errors.max()>params.point_tolerance:
                    continue
                key=tuple(map(tuple,pairs.tolist()))
                old=candidates.get(key)
                if old is None or rms<old['rms']:
                    candidates[key]=dict(transform=transform,pairs=pairs,rms=rms,errors=errors)
    ranked=sorted(candidates.values(),key=lambda result:(-len(result['pairs']),result['rms']))
    if not ranked:
        raise ValueError('没有足够一致的圆心匹配，请检查共同圆点、单位和容差')
    best=ranked[0]
    if any(len(other['pairs'])==len(best['pairs']) and other['rms']<=max(best['rms']+.1,best['rms']*1.2) for other in ranked[1:]):
        raise ValueError('存在多个同等可信匹配（等边/等腰三角形或重复图案）；请增加不对称圆点，不能唯一确定拼接')
    triangle=max(combinations(range(len(best['pairs'])),3), key=lambda ids: np.linalg.norm(np.cross(
        reference[best['pairs'][ids[1],0]]-reference[best['pairs'][ids[0],0]],
        reference[best['pairs'][ids[2],0]]-reference[best['pairs'][ids[0],0]])))
    return dict(**best,hypotheses=hypotheses,shape='triangle',triangle_pairs=best['pairs'][list(triangle)])

# Future polygon strategies share this callable contract and result structure.
MATCHERS={'triangle':match_triangles}

def match_geometry(reference,moving,params=MatchParameters(),shape='triangle'):
    if shape not in MATCHERS:
        raise ValueError('当前只实现三角形匹配')
    return MATCHERS[shape](reference,moving,params)
