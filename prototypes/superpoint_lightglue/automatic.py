"""Automatic feature registration for the mobile capture and stitch flow."""
from dataclasses import dataclass

import numpy as np

from core.frame_database import STALE_RESULT
from core.pcd_utils import merge_pointclouds
from core.point_cloud_processor import PointCloudProcessor
from ui_v2.feature_recognition import FEATURE_RESULT_PREFIX

from .pipeline import PretrainedMatcher, analyze_pair, estimate_pose, read_frame

MAX_REFERENCES = 3


@dataclass
class FeatureObservation:
    uid: str
    revision: int
    reference_number: int | None
    points: tuple
    message: str = ''
    reference_uid: str | None = None
    reference_revision: int | None = None


class FeatureRegistrationError(ValueError):
    def __init__(self, message, observation):
        super().__init__(message)
        self.observation = observation


@dataclass
class FeatureStitchResult:
    uid: str
    cloud: object
    shared: int
    inliers: int
    rms: float
    observations: tuple
    references: int


class FeatureStitching:
    def __init__(self, matcher=None):
        self.matcher = matcher if matcher is not None else PretrainedMatcher()

    def append(self, database, uid):
        """Use the newest valid feature result as the accepted chain."""
        records = database.records.copy()
        raw = []
        for row in records.values():
            if row.uid == uid:
                break
            if row.kind == 'raw' and row.pointcloud_aligned is not False:
                raw.append(row)
        earlier = {row.uid for row in raw}
        candidates = [row for row in records.values()
                      if row.kind == 'result' and row.logical_name.startswith(FEATURE_RESULT_PREFIX)
                      and row.status != STALE_RESULT and earlier.issuperset(row.source_ids)
                      and row.source_ids and set(row.source_ids) == set(row.source_transforms)]
        prior = candidates[-1] if candidates else None
        if prior is not None:
            return self.stitch(database, [*prior.source_ids, uid], prior=prior)
        if not raw:
            return None
        return self.stitch(database, [raw[0].uid, uid])

    def stitch(self, database, identifiers, *, prior=None):
        rows = [database.records[uid] for uid in identifiers]
        if len(rows) < 2:
            raise ValueError('至少需要两帧原始数据。')
        if any(row.kind != 'raw' or row.pointcloud_aligned is False for row in rows):
            raise ValueError('请先开启「点云对应2D」并拍摄两帧对齐的原始数据。')

        if prior is None:
            first = 1
            merged = frame_cloud(read_frame(database.directory, rows[0]))
            poses = {rows[0].uid: np.eye(4).tolist()}
        else:
            first = len(prior.source_ids)
            _, merged = database.load_frame(prior.uid, 'cloud')
            poses = dict(prior.source_transforms)
        observations = {}
        for index in range(first, len(rows)):
            row = rows[index]
            moving = read_frame(database.directory, row)
            references = rows[max(0, index - MAX_REFERENCES):index]
            pose, shared, inliers, rms, visible, used = self._register(
                database.directory, references, row, moving, poses)
            observations.update((entry.uid, entry) for entry in visible)
            poses[row.uid] = pose.tolist()
            merge_pointclouds(merged, frame_cloud(moving).transform(pose))
        uid = database.publish_result(merged, identifiers,
            name=f'{FEATURE_RESULT_PREFIX} · {len(identifiers)} 帧', source_transforms=poses)
        return FeatureStitchResult(uid, merged, shared, inliers, rms, tuple(observations.values()), used)

    def _register(self, directory, references, row, moving, poses):
        threshold = 2.
        pairs, moving_support, world_support = [], [], []
        for anchor in reversed(references):
            reference = read_frame(directory, anchor)
            frames = (reference, moving)
            boxes = [(0, 0, frame.image.shape[1], frame.image.shape[0]) for frame in frames]
            pair = analyze_pair(frames, boxes, self.matcher, threshold=threshold, depth_jump=5.)
            anchor_pose = np.asarray(poses[anchor.uid])
            anchor_xyz, moving_xyz = pair.xyz
            world = anchor_xyz @ anchor_pose[:3, :3].T + anchor_pose[:3, 3]
            pairs.append((anchor, pair, world))
            if pair.pose is not None:
                moving_support.append(moving_xyz[pair.inliers])
                world_support.append(world[pair.inliers])
        if not moving_support:
            anchor, pair, _ = max(pairs, key=lambda item: (item[1].valid.sum(), len(item[1].valid)))
            reason = (f'帧 {row.frame_id:03d}：{pair.reason}'
                      f'（像素匹配 {len(pair.valid)} 对，有效深度 {pair.valid.sum()} 对）')
            raise FeatureRegistrationError(reason, observation(row, anchor, pair, 1, pair.inliers, reason))
        if len(moving_support) == 1:
            anchor, pair, _ = next(item for item in pairs if item[1].pose is not None)
            pose = np.asarray(poses[anchor.uid]) @ pair.pose
            visible = (observation(anchor, row, pair, 0, pair.inliers),
                       observation(row, anchor, pair, 1, pair.inliers))
            rms = float(np.sqrt(np.mean(np.square(pair.errors[pair.inliers]))))
            return pose, int(pair.valid.sum()), int(pair.inliers.sum()), rms, visible, 1
        try:
            pose, _, _ = estimate_pose(np.vstack(moving_support), np.vstack(world_support), threshold)
        except ValueError as exc:
            anchor, pair, _ = max(pairs, key=lambda item: item[1].inliers.sum())
            reason = f'帧 {row.frame_id:03d}：多个参考机位的 3D 约束不一致（{exc}）'
            raise FeatureRegistrationError(reason, observation(row, anchor, pair, 1, np.zeros_like(pair.valid), reason)) from exc

        ranked, errors, used = [], [], 0
        for anchor, pair, world in pairs:
            if pair.pose is None:
                continue
            delta = pair.xyz[1] @ pose[:3, :3].T + pose[:3, 3] - world
            error = np.linalg.norm(delta, axis=1)
            mask = pair.valid & (error <= threshold)
            ranked.append((anchor, pair, mask))
            errors.extend(error[mask])
            used += int(mask.sum() >= 6)
        anchor, pair, mask = max(ranked, key=lambda item: item[2].sum())
        visible = (observation(anchor, row, pair, 0, mask), observation(row, anchor, pair, 1, mask))
        shared = sum(int(pair.valid.sum()) for _, pair, _ in pairs if pair.pose is not None)
        rms = float(np.sqrt(np.mean(np.square(errors))))
        return pose, shared, len(errors), rms, visible, used


def observation(row, reference, pair, side, inliers, message=''):
    points = tuple((float(x), float(y), 2 if keep else 1 if valid else 0)
                   for (x, y), valid, keep in zip(pair.pixels[side], pair.valid, inliers))
    return FeatureObservation(row.uid, row.revision, reference.frame_id, points, message,
                              reference.uid, reference.revision)


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
