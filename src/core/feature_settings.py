"""Adjustable thresholds for SuperPoint and LightGlue registration."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSettings:
    image_size: int = 1024
    max_keypoints: int = 2048
    match_score: float = .10
    depth_jump: float = 5.
    tolerance: float = 2.
    inlier_percent: int = 60


# Bounds also drive the corresponding controls in the recognition panel.
FEATURE_SETTING_LIMITS = {
    'image_size': (320, 2048, 64),
    'max_keypoints': (256, 4096, 128),
    'match_score': (.01, .99, .05),
    'depth_jump': (.5, 20., .5),
    'tolerance': (.1, 10., .1),
    'inlier_percent': (35, 100, 5),
}


def load_feature_settings(values):
    if not isinstance(values, dict) or values.keys() - FEATURE_SETTING_LIMITS.keys():
        raise ValueError('会话中的 2D 特征配准参数无效。')
    defaults = FeatureSettings()
    for key, value in values.items():
        low, high, _ = FEATURE_SETTING_LIMITS[key]
        types = (int,) if isinstance(getattr(defaults, key), int) else (int, float)
        if type(value) not in types or not low <= value <= high:
            raise ValueError(f'会话中的 2D 特征配准参数超出范围：{key}')
    return FeatureSettings(**values)
