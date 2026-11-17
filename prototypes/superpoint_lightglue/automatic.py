"""Automatic feature registration for the mobile capture and stitch flow."""
from dataclasses import dataclass

import numpy as np

from core.frame_database import STALE_RESULT
from core.pcd_utils import merge_pointclouds
from core.point_cloud_processor import PointCloudProcessor

from .pipeline import PretrainedMatcher, analyze_pair, read_frame

RESULT_PREFIX = 'SuperPoint + LightGlue 拼接'


@dataclass
class FeatureStitchResult:
    uid: str
    cloud: object
    shared: int
    inliers: int
    rms: float


class FeatureStitching:
    def __init__(self, matcher=None):
        self.matcher = matcher if matcher is not None else PretrainedMatcher()

    def append(self, database, uid):
        """Use the newest valid feature result as the accepted chain."""
        raw = [row for row in database.records.values()
               if row.kind == 'raw' and row.pointcloud_aligned is not False and row.uid != uid]
        candidates = [row for row in database.records.values()
                      if row.kind == 'result' and row.logical_name.startswith(RESULT_PREFIX)
                      and row.status != STALE_RESULT and uid not in row.source_ids
                      and row.source_ids and set(row.source_ids) == set(row.source_transforms)]
        prior = max(candidates, key=lambda row: (row.frame_id, row.created), default=None)
        if prior is not None:
            return self.stitch(database, [*prior.source_ids, uid], prior=prior)
        if not raw:
            return None
        reference = min(raw, key=lambda row: (row.frame_id, row.created))
        return self.stitch(database, [reference.uid, uid])

    def stitch(self, database, identifiers, *, prior=None):
        import open3d as o3d

        rows = [database.records[uid] for uid in identifiers]
        if len(rows) < 2:
            raise ValueError('至少需要两帧原始数据。')
        if any(row.kind != 'raw' or row.pointcloud_aligned is False for row in rows):
            raise ValueError('请先开启「点云对应2D」并拍摄两帧对齐的原始数据。')

        if prior is None:
            first = 0
            merged = o3d.geometry.PointCloud()
            poses = {rows[0].uid: np.eye(4).tolist()}
        else:
            first = len(prior.source_ids) - 1
            _, merged = database.load_frame(prior.uid, 'cloud')
            poses = dict(prior.source_transforms)
        reference = read_frame(database.directory, rows[first])
        if prior is None:
            merge_pointclouds(merged, frame_cloud(reference))
        for row in rows[first + 1:]:
            moving = read_frame(database.directory, row)
            pair = (reference, moving)
            boxes = [(0, 0, frame.image.shape[1], frame.image.shape[0]) for frame in pair]
            result = analyze_pair(pair, boxes, self.matcher, threshold=2., depth_jump=5.)
            if result.pose is None:
                raise ValueError(f'帧 {row.frame_id:03d}：{result.reason}'
                                 f'（像素匹配 {len(result.valid)} 对，有效深度 {result.valid.sum()} 对）')
            pose = np.asarray(poses[reference.token[0]]) @ result.pose
            poses[row.uid] = pose.tolist()
            merge_pointclouds(merged, frame_cloud(moving).transform(pose))
            reference = moving
        rms = float(np.sqrt(np.mean(result.errors[result.inliers] ** 2)))
        uid = database.publish_result(merged, identifiers,
            name=f'{RESULT_PREFIX} · {len(identifiers)} 帧', source_transforms=poses)
        return FeatureStitchResult(uid, merged, int(result.valid.sum()), int(result.inliers.sum()), rms)


def frame_cloud(frame):
    import open3d as o3d

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(frame.grid.reshape(-1, 3))
    if frame.colors is not None:
        cloud.colors = o3d.utility.Vector3dVector(frame.colors.reshape(-1, 3))
    valid, _ = PointCloudProcessor._filter_valid(cloud)
    if not len(valid.points):
        raise ValueError(f'{frame.name} 无有效点云。')
    return valid
