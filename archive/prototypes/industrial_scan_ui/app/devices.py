"""Optional RVC connection adapter. Import/initialize SDK only on explicit refresh."""
from ui_v2.widgets.device_table import DeviceInfo


class DeviceService:
    def __init__(self):
        self.manager = None
        self.connected = []

    def _manager(self):
        if self.manager is None:
            from core.camera_manager import CameraManager
            manager = CameraManager()
            ok, message = manager.initialize()
            if not ok:
                raise RuntimeError(message)
            self.manager = manager
        return self.manager

    def enumerate(self):
        result = []
        for index, device in enumerate(self._manager().find_devices()):
            ok, info = device.GetDeviceInfo()
            if ok:
                result.append(DeviceInfo(model=info.name, serial=info.sn,
                                         ip=getattr(info, 'ip', ''), backend_ref=index))
        return result

    def connect(self, devices):
        if not devices or any(not d.online or not d.serial for d in devices):
            raise ValueError('请选择具有有效序列号的在线相机')
        serials = [d.serial for d in devices]
        if len(set(serials)) != len(serials):
            raise ValueError('同一台相机不能重复连接')
        if serials == [d.serial for d in self.connected]:
            return list(self.connected)
        manager = self._manager()
        # Resolve by stable serial immediately before opening, never trust a stale row index.
        available = {d.serial: d for d in self.enumerate()}
        if any(sn not in available for sn in serials):
            raise RuntimeError('设备列表已变化，请刷新后重新选择')
        manager.clear()
        self.connected = []
        selected = [available[sn] for sn in serials]
        indices = {}
        for i, device in enumerate(selected):
            cid = f'cam{i+1}'
            manager.add_camera(cid)
            indices[cid] = device.backend_ref
        ok, message = manager.connect_all(indices)
        if not ok:
            manager.clear()
            raise RuntimeError(message)
        # Check real controller identity as SDK enumeration may change while opening.
        if any(manager.find_by_sn(sn) != cid for cid, sn in zip(indices, serials)):
            manager.clear()
            raise RuntimeError('设备序列号发生变化，请刷新后重试')
        self.connected = selected
        return list(selected)

    def close(self):
        if self.manager is not None:
            self.manager.shutdown()
            self.manager = None
        self.connected = []

    def capture_previews(self):
        if not self.connected or self.manager is None:
            raise RuntimeError('尚未连接相机')
        return {f'cam{i+1}': self.manager.capture_2d_preview(f'cam{i+1}')
                for i in range(len(self.connected))}
