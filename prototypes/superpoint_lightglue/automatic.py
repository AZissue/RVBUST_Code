"""Automatic feature registration for the mobile capture and stitch flow."""
from copy import deepcopy
from dataclasses import dataclass, replace

import numpy as np

from core.feature_settings import FeatureSettings
from core.feature_masks import WorkpieceMaskSettings
from core.frame_database import STALE_RESULT
from core.pcd_utils import merge_pointclouds
from core.postprocess.session import CloudLayer
from core.point_cloud_processor import PointCloudProcessor
from ui_v2.feature_recognition import FEATURE_RESULT_PREFIX

from .pipeline import PretrainedMatcher, analyze_pair, estimate_pose, frame_image, read_frame
from .matching import PixelMatchCache
from .refinement import feature_surface, refine_feature_pose

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
    stage: str = 'registration'


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
    links: tuple
    icp_reports: tuple = ()
    icp_accepted: int = 0

class FeatureStitching:
    def __init__(self, matcher=None):
        self.matcher = matcher if matcher is not None else PretrainedMatcher()
        self._pixel_cache = PixelMatchCache(self.matcher)

    def _pixels(self, database, rows, images, roi, settings, workpiece_roi, mask_settings, rotation=0):
        if self._pixel_cache.matcher is not self.matcher:
            self._pixel_cache = PixelMatchCache(self.matcher)
        return self._pixel_cache.pair(database, rows, images, roi, settings,
                                      workpiece_roi, mask_settings, rotation)

    def prepare(self, database, uid, *, roi=None, settings=FeatureSettings(),
                workpiece_roi=None, mask_settings=WorkpieceMaskSettings()):
        """Read only image files; do not load XYZ, estimate poses, or publish results."""
        with database._lock:
            rows = [r for r in database.records.values() if r.kind == 'raw'
                    and r.pointcloud_aligned is not False]
            index = next(i for i, row in enumerate(rows) if row.uid == uid)
            rows = deepcopy(rows[max(0, index-MAX_REFERENCES):index+1])
        index = len(rows) - 1
        row = rows[index]
        if index == 0:
            return (FeatureObservation(uid, row.revision, None, (),
                    '参考图像已准备，拍摄后续帧后后台匹配。', stage='matching'),)
        image = frame_image(database.directory, row)
        best = None
        for anchor in reversed(rows[max(0, index-MAX_REFERENCES):index]):
            images = (frame_image(database.directory, anchor), image)
            pixels = self._pixels(database, (anchor, row), images, roi, settings, workpiece_roi, mask_settings)
            if len(pixels[0]) < 6 and isinstance(self.matcher, PretrainedMatcher):
                for rotation in (1, 3, 2):
                    candidate = self._pixels(database, (anchor, row), images, roi, settings,
                                             workpiece_roi, mask_settings, rotation)
                    if len(candidate[0]) > len(pixels[0]):
                        pixels = candidate
            if best is None or len(pixels[0]) > len(best[1][0]):
                best = (anchor, pixels)
        anchor, pixels = best
        message = f'已缓存 {len(pixels[0])} 对 2D 匹配，点击「执行拼接」进行 3D 配准。'
        return tuple(FeatureObservation(current.uid, current.revision, reference.frame_id,
            tuple((float(x), float(y), 3) for x, y in points), message,
            reference.uid, reference.revision, stage='matching')
            for current, reference, points in ((anchor, row, pixels[0]), (row, anchor, pixels[1])))

    def append(self, database, uid, *, roi=None, settings=FeatureSettings(), workpiece_roi=None,
               mask_settings=WorkpieceMaskSettings()):
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
            return self.stitch(database, [*prior.source_ids, uid], prior=prior, roi=roi, settings=settings,
                               workpiece_roi=workpiece_roi, mask_settings=mask_settings)
        if not raw:
            return None
        return self.stitch(database, [raw[0].uid, uid], roi=roi, settings=settings,
                           workpiece_roi=workpiece_roi, mask_settings=mask_settings)

    def stitch(self, database, identifiers, *, prior=None, roi=None, settings=FeatureSettings(), workpiece_roi=None,
               mask_settings=WorkpieceMaskSettings()):
        rows = [database.records[uid] for uid in identifiers]
        if len(rows) < 2:
            raise ValueError('至少需要两帧原始数据。')
        if any(row.kind != 'raw' or row.pointcloud_aligned is False for row in rows):
            raise ValueError('请先开启「点云对应2D」并拍摄两帧对齐的原始数据。')

        surfaces = {}
        icp_reports, icp_accepted = [], 0
        if prior is None:
            first = 1
            initial = read_frame(database.directory, rows[0])
            merged = frame_cloud(initial)
            if settings.icp_enabled:
                surfaces[rows[0].uid] = feature_surface(initial,roi,workpiece_roi,settings.icp_voxel)
            poses = {rows[0].uid: np.eye(4).tolist()}
        else:
            first = len(prior.source_ids)
            _, merged = database.load_frame(prior.uid, 'cloud')
            poses = dict(prior.source_transforms)
        observations, links = {}, []
        for index in range(first, len(rows)):
            row = rows[index]
            moving = read_frame(database.directory, row)
            references = rows[max(0, index - MAX_REFERENCES):index]
            pose, shared, inliers, rms, visible, used, evidence = self._register(
                database, references, row, moving, poses, roi, settings, workpiece_roi, mask_settings)
            if settings.icp_enabled:
                for reference in references:
                    if reference.uid not in surfaces:
                        previous = read_frame(database.directory,reference)
                        local = feature_surface(previous,roi,workpiece_roi,settings.icp_voxel)
                        previous_pose = np.asarray(poses[reference.uid])
                        surfaces[reference.uid] = local @ previous_pose[:3,:3].T + previous_pose[:3,3]
                local = feature_surface(moving,roi,workpiece_roi,settings.icp_voxel)
                try:
                    target = CloudLayer('最近已拼接工件',np.vstack([surfaces[r.uid] for r in references]))
                    pose, report, accepted = refine_feature_pose(target,local,pose,evidence,settings)
                except ValueError as exc:
                    report, accepted = f'ICP 未采用，保留特征配准位姿。{exc}', False
                icp_reports.append(f'帧 {row.frame_id:03d} 工件 ROI：{report}')
                icp_accepted += int(accepted)
                surfaces[row.uid] = local @ pose[:3,:3].T + pose[:3,3]
                keep = {r.uid for r in rows[max(0, index-MAX_REFERENCES+1):index+1]}
                surfaces = {key: value for key, value in surfaces.items() if key in keep}
                if accepted:
                    visible = tuple(replace(entry,
                        message='特征初始配准分类。该帧已采用 ICP 精修，几何误差对比见运行日志。')
                        for entry in visible)
            observations.update((entry.uid, entry) for entry in visible)
            links.append((row.frame_id, visible[-1].reference_number))
            poses[row.uid] = pose.tolist()
            merge_pointclouds(merged, frame_cloud(moving).transform(pose))
        uid = database.publish_result(merged, identifiers,
            name=f'{FEATURE_RESULT_PREFIX} · {len(identifiers)} 帧', source_transforms=poses)
        return FeatureStitchResult(uid, merged, shared, inliers, rms, tuple(observations.values()), used, tuple(links), tuple(icp_reports), icp_accepted)

    def _register(self, database, references, row, moving, poses, roi, settings, workpiece_roi, mask_settings):
        threshold = settings.tolerance
        pairs = []
        for anchor in reversed(references):
            reference = read_frame(database.directory, anchor)
            frames = (reference, moving)
            images = [frame.image for frame in frames]
            pixels = self._pixels(database, (anchor, row), images, roi, settings, workpiece_roi, mask_settings)
            pair = analyze_pair(frames, (), self.matcher, threshold=threshold,
                                depth_jump=settings.depth_jump, settings=settings, pixels=pixels)
            if not pairs and pair.pose is None and isinstance(self.matcher, PretrainedMatcher):
                for rotation in (1, 3, 2):
                    pixels = self._pixels(database, (anchor, row), images, roi, settings,
                                          workpiece_roi, mask_settings, rotation)
                    retry = analyze_pair(frames, (), self.matcher, threshold=threshold,
                                         depth_jump=settings.depth_jump, settings=settings, pixels=pixels)
                    if retry.pose is not None:
                        pair = retry
                        break
            anchor_pose = np.asarray(poses[anchor.uid])
            anchor_xyz, moving_xyz = pair.xyz
            world = anchor_xyz @ anchor_pose[:3, :3].T + anchor_pose[:3, 3]
            pairs.append((anchor, pair, world))

        accepted = [entry for entry in pairs if entry[1].pose is not None]
        if not accepted:
            anchor, pair, _ = max(pairs, key=lambda item: (item[1].valid.sum(), len(item[1].valid)))
            reason = (f'帧 {row.frame_id:03d}：最近 {len(pairs)} 个机位均无法接入。{pair.reason}'
                      f'（帧 {anchor.frame_id:03d}：像素匹配 {len(pair.valid)} 对，有效深度 {pair.valid.sum()} 对）。'
                      '转角较大时请补拍与两侧都重叠的中间机位。')
            raise FeatureRegistrationError(reason, observation(row, anchor, pair, 1, pair.inliers, reason))

        # Anchor the chain at the newest accepted frame. Older, independently
        # fitted links can refine it only if they agree in the common 3D space.
        anchor, pair, _ = accepted[0]
        pose = np.asarray(poses[anchor.uid]) @ pair.pose
        ranked = [(pair.inliers, pair.errors)]
        support = [accepted[0]]
        ratio = settings.inlier_percent / 100
        for candidate in accepted[1:]:
            matches, _ = residuals(candidate, pose, threshold)
            if matches.sum() >= max(6, np.ceil(ratio * candidate[1].valid.sum())):
                support.append(candidate)

        if len(support) > 1:
            sources = np.vstack([entry.xyz[1][entry.inliers] for _, entry, _ in support])
            targets = np.vstack([world[entry.inliers] for _, entry, world in support])
            try:
                refined, _, _ = estimate_pose(sources, targets, threshold, min_ratio=ratio)
            except ValueError:
                pass
            else:
                refined_ranked = [residuals(entry, refined, threshold) for entry in support]
                if all(mask.sum() >= max(6, np.ceil(ratio * entry[1].valid.sum()))
                       for (mask, _), entry in zip(refined_ranked, support)):
                    pose, ranked = refined, refined_ranked
        mask = ranked[0][0]
        visible = (observation(anchor, row, pair, 0, mask), observation(row, anchor, pair, 1, mask))
        errors = np.concatenate([error[inliers] for inliers, error in ranked])
        shared = sum(int(entry[1].valid.sum()) for entry in support[:len(ranked)])
        evidence = (np.vstack([entry[1].xyz[1][mask] for entry,(mask,_) in zip(support,ranked)]),
                    np.vstack([entry[2][mask] for entry,(mask,_) in zip(support,ranked)]))
        return pose, shared, len(errors), float(np.sqrt(np.mean(errors**2))), visible, len(ranked), evidence


def residuals(entry, pose, threshold):
    _, pair, world = entry
    transformed = pair.xyz[1] @ pose[:3, :3].T + pose[:3, 3]
    errors = np.linalg.norm(transformed - world, axis=1)
    return pair.valid & (errors <= threshold), errors


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
