"""Plain-data capture settings; SDK objects stay inside the camera service."""
import math

FIELDS = ('exposure_time_2d', 'exposure_time_3d', 'gain_2d', 'gain_3d',
          'projector_brightness')
BOOL_FIELDS = ('use_projector_capturing_2d_image', 'correspond2d')
FLOAT_FIELDS = ('gain_2d', 'gain_3d', 'gamma_2d')


def _choices(controller, options):
    from .camera_manager import RVC
    choices = {}
    info = controller.device_info
    for field, mask_name, names in (
            ('capture_mode', 'support_capture_mode', (
                ('CaptureMode_Normal', '标准模式'), ('CaptureMode_Fast', '快速模式'),
                ('CaptureMode_Ultra', '高精度模式'),
                ('CaptureMode_AntiInterReflection', '抗互反射模式'),
                ('CaptureMode_SwingLineScan', '摆动线扫'))),
            ('projector_color', 'support_color', (
                ('ProjectorColor_Blue', '蓝色'), ('ProjectorColor_Red', '红色'),
                ('ProjectorColor_Green', '绿色'), ('ProjectorColor_White', '白色')))):
        if not hasattr(options, field):
            continue
        current = int(getattr(options, field))
        mask = int(getattr(info, mask_name, 0))
        items = [(label, int(getattr(RVC, name))) for name, label in names
                 if RVC is not None and hasattr(RVC, name)
                 and (mask & int(getattr(RVC, name)) or current == int(getattr(RVC, name)))]
        if current not in [value for _, value in items]:
            items.insert(0, ('当前模式' if field == 'capture_mode' else '当前颜色', current))
        choices[field] = items
    return choices


LINE_EXPOSURE = 'line_scanner_exposure_time_us'


def _line_scan(options):
    from .camera_manager import RVC
    return RVC is not None and getattr(options, 'capture_mode', None) in (
        getattr(RVC, 'CaptureMode_SwingLineScan', object()),
        getattr(RVC, 'CaptureMode_FixedLineScan', object()))


def _ranges(controller, options):
    ranges = {}
    for method, fields in (
            ('GetExposureTimeRange', FIELDS[:2]), ('GetGainRange', FIELDS[2:4])):
        ok, low, high = getattr(controller.camera, method)()
        if not ok or not all(math.isfinite(x) for x in (low, high)) or low > high:
            raise RuntimeError('无法获取相机参数范围，请检查连接或使用参数调试')
        for field in fields:
            ranges[field] = (low, high)
    ranges['projector_brightness'] = (0, 240)
    if hasattr(options, 'gamma_2d'):
        ok, low, high = controller.camera.GetGammaRange()
        if ok and all(math.isfinite(x) for x in (low, high)) and low <= high:
            ranges['gamma_2d'] = (low, high)
    if _line_scan(options):
        ranges.pop('exposure_time_3d', None)
        if hasattr(options, LINE_EXPOSURE):
            # RVC.h exposes no line-exposure range query. This is an integer
            # input bound, NOT a claimed device range; SDK validates the value.
            ranges[LINE_EXPOSURE] = getattr(controller, '_line_exposure_range', (1, 2147483647))
    return ranges


def _load(controller):
    if not controller.is_connected:
        raise RuntimeError('相机已断开，请重新连接')
    ok, options = controller.camera.LoadCaptureOptionParameters()
    if not ok or options is None:
        raise RuntimeError('读取相机拍摄参数失败')
    return options, _ranges(controller, options), _choices(controller, options)


def _snapshot(controller, options, ranges, choices):
    keys = set(ranges) | set(choices) | {key for key in BOOL_FIELDS if hasattr(options, key)}
    return {'values': {key: (int(getattr(options, key)) if key in choices else getattr(options, key)) for key in keys},
            'ranges': ranges, 'camera_type': controller.camera_type,
            'hdr': int(getattr(options, 'hdr_exposure_times', 0)), 'choices': choices,
            'unqueried_ranges': [LINE_EXPOSURE] if LINE_EXPOSURE in ranges and not hasattr(controller, '_line_exposure_range') else []}


def read(controller):
    # Same order as capture_2d/3d; shared across all cameras and preview threads.
    from .utils import rvc_sdk_lock
    with rvc_sdk_lock, controller._capture_lock:
        options, ranges, choices = _load(controller)
        snapshot = _snapshot(controller, options, ranges, choices)
        controller.current_options = options
        controller._check_capture_mode()
        return snapshot


def apply(controller, values):
    from .utils import rvc_sdk_lock
    with rvc_sdk_lock, controller._capture_lock:
        # Always reload a separate SDK options object. Failed writes must not
        # mutate current_options, and untouched HDR/filter/ROI settings survive.
        options, ranges, choices = _load(controller)
        snapshot = _snapshot(controller, options, ranges, choices)
        if set(values) != set(snapshot['values']):
            raise ValueError('拍摄参数不完整，请重新读取')
        for field in values:
            if field in BOOL_FIELDS:
                if type(values[field]) is not bool:
                    raise ValueError('开关参数必须为是或否')
                setattr(options, field, values[field])
                continue
            if field in choices:
                if values[field] not in [value for _, value in choices[field]]:
                    raise ValueError('相机不支持所选模式或颜色')
                setattr(options, field, type(getattr(options, field))(values[field]))
                continue
            value = float(values[field])
            low, high = ranges[field]
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{field} 超出相机允许范围 [{low}, {high}]')
            if field not in FLOAT_FIELDS:
                if not value.is_integer():
                    raise ValueError('曝光时间和投影亮度必须为整数')
                value = int(value)
            setattr(options, field, value)
        if not controller.camera.SaveCaptureOptionParameters(options):
            from .camera_manager import RVC
            detail = str(RVC.GetLastErrorMessage()) if RVC is not None else ''
            # Learn explicit device bounds when this SDK reports them on failure.
            import re
            match = re.search(r'line_scanner_exposure_time_us[^\[]*\[\s*(\d+)\s*,\s*(\d+)\s*\]', detail)
            if match and int(match[1]) <= int(match[2]):
                controller._line_exposure_range = (int(match[1]), int(match[2]))
            raise RuntimeError('相机拒绝参数：' + (detail or '请检查曝光范围、HDR模式或使用参数调试'))
        controller.current_options = options
        controller._check_capture_mode()
        return _snapshot(controller, options, _ranges(controller, options), _choices(controller, options))
