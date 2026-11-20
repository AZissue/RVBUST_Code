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
    icp_enabled: bool = True
    icp_after_geometry: bool = True
    icp_distance: float = 2.
    icp_voxel: float = .5
    icp_iterations: int = 50
    icp_overlap: int = 30
    icp_max_correction: float = 5.
    geometry_enabled: bool = True
    geometry_fpfh: bool = False
    geometry_voxel: float = 1.
    geometry_neighbors: int = 3
    geometry_rounds: int = 3


# Bounds also drive the corresponding controls in the recognition panel.
FEATURE_SETTING_LIMITS = {
    'image_size': (320, 2048, 64),
    'max_keypoints': (256, 4096, 128),
    'match_score': (.01, .99, .05),
    'depth_jump': (.5, 20., .5),
    'tolerance': (.1, 10., .1),
    'inlier_percent': (35, 100, 5),
    'icp_distance': (.1, 20., .1),
    'icp_voxel': (.05, 5., .05),
    'icp_iterations': (10, 200, 10),
    'icp_overlap': (10, 100, 5),
    'icp_max_correction': (.1, 20., .1),
    'geometry_voxel': (.1, 5., .1),
    'geometry_neighbors': (1, 10, 1),
    'geometry_rounds': (1, 10, 1),
}


def load_feature_settings(values):
    switches = {'icp_enabled', 'geometry_enabled', 'geometry_fpfh', 'icp_after_geometry'}
    if not isinstance(values, dict) or values.keys() - (FEATURE_SETTING_LIMITS.keys() | switches):
        raise ValueError('会话中的 2D 特征配准参数无效。')
    defaults = FeatureSettings()
    for key, value in values.items():
        if key in switches:
            if type(value) is not bool:
                raise ValueError('几何/ICP 开关必须为布尔值。')
            continue
        low, high, _ = FEATURE_SETTING_LIMITS[key]
        types = (int,) if isinstance(getattr(defaults, key), int) else (int, float)
        if type(value) not in types or not low <= value <= high:
            raise ValueError(f'会话中的 2D 特征配准参数超出范围：{key}')
    return FeatureSettings(**values)
