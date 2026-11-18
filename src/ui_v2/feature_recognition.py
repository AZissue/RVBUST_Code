"""Recognition mode identifier shared by the prototype's industrial UI hooks."""

from math import ceil, floor

FEATURE_RECOGNITION = 'superpoint_lightglue'

FEATURE_RESULT_PREFIX = 'SuperPoint + LightGlue 拼接'


def feature_box(shape, roi):
    height, width = shape[:2]
    if roi is None:
        return 0, 0, width, height
    left, top, right, bottom = roi
    box = (floor(left * width), floor(top * height), ceil(right * width), ceil(bottom * height))
    if min(box[2] - box[0], box[3] - box[1]) < 32:
        raise ValueError('匹配 ROI 在原图上至少需要 32 × 32 像素。')
    return box
