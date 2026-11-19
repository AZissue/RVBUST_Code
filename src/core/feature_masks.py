"""Binary focus regions and guided grayscale enhancement in sensor coordinates."""
from dataclasses import dataclass
from math import ceil, floor

import cv2
import numpy as np


@dataclass(frozen=True)
class WorkpieceMaskSettings:
    enabled: bool = False
    polarity: str = 'bright'
    threshold: int = -1


@dataclass
class WorkpieceMask:
    mask: np.ndarray
    box: tuple
    threshold: float | None


def load_mask_settings(values):
    defaults = WorkpieceMaskSettings()
    if (not isinstance(values, dict) or values.keys() - vars(defaults).keys()
            or type(values.get('enabled', defaults.enabled)) is not bool
            or values.get('polarity', defaults.polarity) not in ('bright', 'dark')
            or type(values.get('threshold', defaults.threshold)) is not int
            or not -1 <= values.get('threshold', defaults.threshold) <= 255):
        raise ValueError('二值化掩膜参数无效。')
    return WorkpieceMaskSettings(**values)


def roi_pixels(shape, roi):
    height, width = shape[:2]
    if roi is None:
        return 0, 0, width, height
    return floor(roi[0]*width), floor(roi[1]*height), ceil(roi[2]*width), ceil(roi[3]*height)


def build_feature_mask(image, matching_roi, workpiece_roi, settings):
    """Threshold only the intersection, without modifying the image used by the model."""
    a = roi_pixels(image.shape, matching_roi)
    b = roi_pixels(image.shape, workpiece_roi)
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        raise ValueError('匹配框与工件框没有重叠，请重新框选。')
    box = (x0, y0, x1, y1)
    mask = np.zeros(image.shape[:2], dtype=bool)
    threshold = None
    if settings.enabled:
        crop = image[y0:y1, x0:x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        operation = cv2.THRESH_BINARY_INV if settings.polarity == 'dark' else cv2.THRESH_BINARY
        if settings.threshold == -1:
            operation |= cv2.THRESH_OTSU
        threshold, binary = cv2.threshold(gray, max(0, settings.threshold), 255, operation)
        mask[y0:y1, x0:x1] = binary > 0
    else:
        mask[y0:y1, x0:x1] = True
    return WorkpieceMask(mask, box, threshold)


def mask_keypoints(mask, points):
    """Evaluate a mask at original pixel coordinates, rejecting out-of-frame points."""
    points = np.asarray(points)
    keep = np.zeros(len(points), dtype=bool)
    finite = np.isfinite(points).all(axis=1)
    indices = np.flatnonzero(finite)
    xy = np.floor(points[finite]).astype(int)
    h, w = mask.shape
    inside = (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
    keep[indices[inside]] = mask[xy[inside, 1], xy[inside, 0]]
    return keep


def enhance_workpiece_texture(image, selection):
    """Blend local grayscale contrast enhancement into a softly feathered focus mask."""
    x0, y0, x1, y1 = selection.box
    crop = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    enhanced = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(gray)
    weight = cv2.GaussianBlur(selection.mask[y0:y1, x0:x1].astype(np.float32), (0, 0), 2.)
    blended = np.rint(gray.astype(np.float32) + weight*(enhanced.astype(np.float32)-gray))
    blended = np.clip(blended, 0, 255).astype(np.uint8)
    result = image.copy()
    result[y0:y1, x0:x1] = cv2.cvtColor(blended, cv2.COLOR_GRAY2BGR) if crop.ndim == 3 else blended
    return result
