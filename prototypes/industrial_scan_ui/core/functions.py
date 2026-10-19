"""Function registration is independent from widgets and device SDKs."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class FunctionSpec:
    key: str
    title: str
    description: str
    icon: str
    minimum_cameras: int
    maximum_cameras: int
    default_cameras: int
    factory: Callable


class FunctionRegistry:
    def __init__(self):
        self._entries = {}

    def register(self, spec):
        if not isinstance(spec, FunctionSpec) or not spec.key or not callable(spec.factory):
            raise ValueError('功能需要唯一标识、说明和工作区工厂')
        if spec.key in self._entries:
            raise ValueError('功能已注册：'+spec.key)
        if not 0 <= spec.minimum_cameras <= spec.default_cameras <= spec.maximum_cameras:
            raise ValueError('相机数量配置不合法')
        self._entries[spec.key] = spec

    def entries(self):
        return tuple(self._entries.values())

    def get(self, key):
        if key not in self._entries:
            raise ValueError('未注册的功能：'+str(key))
        return self._entries[key]

    def create(self, key, *, camera_count=None, **kwargs):
        spec = self.get(key)
        count = spec.default_cameras if camera_count is None else camera_count
        if type(count) is not int or not spec.minimum_cameras <= count <= spec.maximum_cameras:
            raise ValueError('该功能的相机数量不合法')
        return spec.factory(camera_count=count, **kwargs)


def default_registry():
    from ..app.workspaces import MultiCameraWorkbench, MobileWorkbench, TurntableWorkbench
    registry = FunctionRegistry()
    for spec in (
        FunctionSpec('multi_cam', '多相机外参标定', '同时查看多路2D画面，设置参考相机，计算外参后进行固定工位拼接。', 'camera_multi', 2, 16, 4, MultiCameraWorkbench),
        FunctionSpec('mobile_chain', '单相机移动链式拼接', '单相机逐帧扫描；大3D视区、右上角当前帧2D、帧质量评估与底部日志。', 'chain', 1, 1, 1, MobileWorkbench),
        FunctionSpec('turntable', '转台拼接', '左侧完成frame0/frame1转台标定，再按步进设置采集与拼接。', 'loop', 1, 1, 1, TurntableWorkbench),
    ):
        registry.register(spec)
    return registry
