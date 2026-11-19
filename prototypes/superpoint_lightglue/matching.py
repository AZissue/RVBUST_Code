"""Cache immutable pixel correspondences independently of point-cloud registration."""
from threading import RLock
from weakref import WeakKeyDictionary

import numpy as np

from core.feature_masks import (WorkpieceMaskSettings, build_feature_mask,
                                enhance_workpiece_texture, mask_keypoints)
from ui_v2.feature_recognition import feature_box

from .pipeline import PretrainedMatcher


def matching_inputs(images, roi, workpiece_roi, mask_settings):
    boxes = [feature_box(image.shape, roi) for image in images]
    masks = None
    if workpiece_roi is not None or mask_settings.enabled:
        selections = [build_feature_mask(image, roi, workpiece_roi, mask_settings) for image in images]
        boxes = [selection.box for selection in selections]
        if any(min(box[2]-box[0], box[3]-box[1]) < 32 for box in boxes):
            raise ValueError('两个 ROI 的重叠区域至少需要 32 × 32 像素。')
        masks = [selection.mask for selection in selections]
    return boxes, masks


def matching_key(roi, settings, workpiece_roi, mask_settings):
    # Depth and registration thresholds do not change the 2D correspondences.
    return ('texture_augmentation_v1', roi, workpiece_roi, settings.image_size, settings.max_keypoints,
            settings.match_score, mask_settings)


class PixelMatchCache:
    def __init__(self, matcher):
        self.matcher = matcher
        self._databases = WeakKeyDictionary()
        self._lock = RLock()

    def _match(self, images, boxes, settings, rotation, masks=None):
        if isinstance(self.matcher, PretrainedMatcher):
            pixels = self.matcher.match(images, boxes, settings=settings, rotation=rotation, masks=masks)
        else:
            pixels = self.matcher.match(images, boxes)
        if masks is not None:
            keep = mask_keypoints(masks[0], pixels[0]) & mask_keypoints(masks[1], pixels[1])
            pixels = tuple(points[keep] for points in pixels)
        return tuple(np.array(points, copy=True) for points in pixels)

    def pair(self, database, rows, images, roi, settings, workpiece_roi, mask_settings, rotation=0):
        identity = tuple((row.uid, row.revision) for row in rows)
        key = (str(database.directory), identity,
               matching_key(roi, settings, workpiece_roi, mask_settings), rotation)
        baseline_key = (str(database.directory), identity,
                        matching_key(roi, settings, workpiece_roi, WorkpieceMaskSettings()), rotation)
        with self._lock:
            cache = self._databases.setdefault(database, {})
            if key not in cache:
                boxes, _ = matching_inputs(images, roi, workpiece_roi, WorkpieceMaskSettings())
                if baseline_key not in cache:
                    cache[baseline_key] = self._match(images, boxes, settings, rotation)
                pixels = cache[baseline_key]
                if mask_settings.enabled:
                    selections = [build_feature_mask(image, roi, workpiece_roi, mask_settings) for image in images]
                    if all(selection.mask.any() for selection in selections):
                        enhanced = [enhance_workpiece_texture(image, selection)
                                    for image, selection in zip(images, selections)]
                        extra = self._match(enhanced, boxes, settings, rotation,
                                            masks=[selection.mask for selection in selections])
                        pixels = combine_pixel_matches(pixels, extra)
                cache[key] = pixels
                value = cache[key]
                revisions = {uid: row.revision for uid, row in database.records.copy().items()}
                for old in list(cache):
                    if any(revisions.get(uid) != revision for uid, revision in old[1]):
                        del cache[old]
                while len(cache) > max(32, 12 * len(revisions)):
                    del cache[next(iter(cache))]
            else:
                value = cache[key]
            return value


def combine_pixel_matches(original, extra, separation=1.5):
    """Original pairs win; each added pair must have a new endpoint in both images."""
    accepted = [list(points) for points in original]
    for reference, moving in zip(*extra):
        if any(np.any(np.sum((np.asarray(points)-candidate)**2, axis=1) <= separation**2)
               for points, candidate in zip(accepted, (reference, moving)) if points):
            continue
        accepted[0].append(reference)
        accepted[1].append(moving)
    return tuple(np.asarray(points, dtype=float).reshape(-1, 2) for points in accepted)
