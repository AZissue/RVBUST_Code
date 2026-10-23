"""Plain-data capture settings; SDK objects stay inside the camera service."""
import math

FIELDS = ('exposure_time_2d', 'exposure_time_3d', 'gain_2d', 'gain_3d',
          'projector_brightness')


def _load(controller):
    if not controller.is_connected:
        raise RuntimeError('相机已断开，请重新连接')
    ok, options = controller.camera.LoadCaptureOptionParameters()
    if not ok or options is None:
        raise RuntimeError('读取相机拍摄参数失败')
    ranges = {}
    for method, fields in (
            ('GetExposureTimeRange', FIELDS[:2]), ('GetGainRange', FIELDS[2:4])):
        ok, low, high = getattr(controller.camera, method)()
        if not ok or not all(math.isfinite(x) for x in (low, high)) or low > high:
            raise RuntimeError('无法获取相机参数范围，请检查连接或使用参数调试')
        for field in fields:
            ranges[field] = (low, high)
    ranges['projector_brightness'] = (0, 255)
    return options, ranges


def _snapshot(controller, options, ranges):
    return {'values': {key: getattr(options, key) for key in FIELDS},
            'ranges': ranges, 'camera_type': controller.camera_type,
            'hdr': int(getattr(options, 'hdr_exposure_times', 0))}


def read(controller):
    # Same order as capture_2d/3d; shared across all cameras and preview threads.
    from .utils import rvc_sdk_lock
    with rvc_sdk_lock, controller._capture_lock:
        options, ranges = _load(controller)
        snapshot = _snapshot(controller, options, ranges)
        controller.current_options = options
        return snapshot


def apply(controller, values):
    from .utils import rvc_sdk_lock
    with rvc_sdk_lock, controller._capture_lock:
        # Always reload a separate SDK options object. Failed writes must not
        # mutate current_options, and untouched HDR/filter/ROI settings survive.
        options, ranges = _load(controller)
        if set(values) != set(FIELDS):
            raise ValueError('拍摄参数不完整，请重新读取')
        for field in FIELDS:
            value = float(values[field])
            low, high = ranges[field]
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{field} 超出相机允许范围 [{low}, {high}]')
            if field not in ('gain_2d', 'gain_3d'):
                if not value.is_integer():
                    raise ValueError('曝光时间和投影亮度必须为整数')
                value = int(value)
            setattr(options, field, value)
        if not controller.camera.SaveCaptureOptionParameters(options):
            raise RuntimeError('相机拒绝参数，请检查曝光范围、HDR模式或使用参数调试')
        controller.current_options = options
        return _snapshot(controller, options, ranges)
