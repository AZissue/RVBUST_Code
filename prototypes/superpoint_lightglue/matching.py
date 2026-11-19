"""Cache immutable pixel correspondences independently of point-cloud registration."""
from threading import RLock
from weakref import WeakKeyDictionary

import numpy as np

from core.feature_masks import build_feature_mask
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
        if any(not selection.mask.any() for selection in selections):
            raise ValueError('工件掩膜没有保留任何像素，请调整明暗类型、阈值或工件框。')
        masks = [selection.mask for selection in selections]
    return boxes, masks


def matching_key(roi, settings, workpiece_roi, mask_settings):
    # Depth and registration thresholds do not change the 2D correspondences.
    return (roi, workpiece_roi, settings.image_size, settings.max_keypoints,
            settings.match_score, mask_settings)


class PixelMatchCache:
    def __init__(self, matcher):
        self.matcher = matcher
        self._databases = WeakKeyDictionary()
        self._lock = RLock()

    def pair(self, database, rows, images, roi, settings, workpiece_roi, mask_settings, rotation=0):
        identity = tuple((row.uid, row.revision) for row in rows)
        key = (str(database.directory), identity,
               matching_key(roi, settings, workpiece_roi, mask_settings), rotation)
        with self._lock:
            cache = self._databases.setdefault(database, {})
            if key not in cache:
                boxes, masks = matching_inputs(images, roi, workpiece_roi, mask_settings)
                if isinstance(self.matcher, PretrainedMatcher):
                    pixels = self.matcher.match(images, boxes, settings=settings, rotation=rotation, masks=masks)
                else:
                    pixels = self.matcher.match(images, boxes)
                if masks is not None:
                    from core.feature_masks import mask_keypoints
                    keep = mask_keypoints(masks[0], pixels[0]) & mask_keypoints(masks[1], pixels[1])
                    pixels = tuple(points[keep] for points in pixels)
                cache[key] = tuple(np.array(points, copy=True) for points in pixels)
                value = cache[key]
                # Drop old exposure revisions, keeping each session's current pixel pairs.
                revisions = {uid: row.revision for uid, row in database.records.copy().items()}
                for old in list(cache):
                    if any(revisions.get(uid) != revision for uid, revision in old[1]):
                        del cache[old]
                # Bound memory when many alternative tuning configurations are tried.
                while len(cache) > max(32, 12 * len(revisions)):
                    del cache[next(iter(cache))]
            else:
                value = cache[key]
            return value
