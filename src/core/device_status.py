"""Read-only discovery status. No SDK initialization or network writes here."""
from dataclasses import dataclass
from ipaddress import IPv4Interface
from .utils import rvc_sdk_lock


@dataclass
class DeviceStatus:
    model: str = ""
    serial: str = ""
    ip: str = ""
    status: str = "unknown"
    detail: str = "状态未知"
    online: bool = True
    backend_ref: int = 0


def text(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "").strip().strip("\x00")


def subnet_status(ip, mask, interfaces):
    """Mutual IPv4 reachability over active host interfaces; /0 is indeterminate.

    Different masks are allowed only if both peers see each other as local.
    No routing inference from gateways; no active interfaces means unknown.
    """
    def parse(address, netmask):
        result = IPv4Interface(f"{text(address)}/{text(netmask)}")
        if result.network.prefixlen == 0 or result.ip.is_unspecified or result.ip.is_multicast or result.ip.is_loopback:
            raise ValueError("不可用 IPv4 地址/掩码")
        if result.network.prefixlen < 31 and result.ip in (result.network.network_address, result.network.broadcast_address):
            raise ValueError("网络/广播地址")
        return result
    try:
        camera = parse(ip, mask)
    except ValueError as exc:
        return "unknown", f"相机网络配置无效：{exc}"
    hosts = []
    for address, netmask in interfaces:
        try:
            hosts.append(parse(address, netmask))
        except ValueError:
            continue
    if not hosts:
        return "unknown", "未取得有效的活动主机 IPv4 网卡地址/掩码"
    for host in hosts:
        if camera.ip in host.network and host.ip in camera.network and camera.ip != host.ip:
            return "same", f"相机 {camera}；主机 {host}"
    return "subnet_mismatch", f"相机 {camera}；活动主机网卡：" + ", ".join(map(str, hosts))


def host_interfaces():
    """Read OS adapter addresses only (QtNetwork, no SDK)."""
    from PySide6.QtNetwork import QNetworkInterface, QAbstractSocket
    result = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if not flags & QNetworkInterface.IsUp or not flags & QNetworkInterface.IsRunning or flags & QNetworkInterface.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            if entry.ip().protocol() == QAbstractSocket.IPv4Protocol:
                result.append((entry.ip().toString(), entry.netmask().toString()))
    return result


def explicit_busy(message):
    """Only SDK-confirmed occupancy literals; never inferred from generic failures.

    The literals below come from the installed SDK: RVC.dll carries the
    RVC::ErrorCode message table "Camera is occupied!" plus the per-handle
    "X1 is already open!" / "X2 is already open!" messages that
    RVC::GetLastErrorMessage returns. "UsbPort is Busy, {}" is a host-port
    message, not a camera state, so it stays unknown. "possibly busy",
    "Open failed" and timeouts must never become occupied.
    """
    return text(message).lower().strip().rstrip(".!。") in {
        "camera is occupied", "x1 is already open", "x2 is already open",
        "device is busy", "device is occupied", "device is already opened by another process",
        "设备被占用", "相机被占用",
    }


def probe(sdk, device, info):
    if not device.IsFirmwareMatch():
        return "unknown", "固件不匹配；未打开设备"
    errors = []
    busy = False
    for kind in ("X2", "X1"):
        api = getattr(sdk, kind)
        camera = None
        success = False
        cleanup_errors = []
        try:
            camera = api.Create(device) if kind == "X2" else api.Create(device, sdk.CameraID_Left)
            if camera is None or not camera.IsValid():
                raise RuntimeError("创建无效句柄")
            opened = camera.Open()
            if opened and camera.IsOpen():
                ok, current = device.GetDeviceInfo()
                if not ok or text(current.sn) != text(info.sn) or text(current.name) != text(info.name):
                    # Do not fall back to opening a potentially different device.
                    return "unknown", "打开后设备身份不一致，请刷新"
                success = True
            else:
                message = text(sdk.GetLastErrorMessage())
                busy = busy or explicit_busy(message)
                errors.append(f"{kind}: {message or '打开失败（SDK未给出原因）'}")
        except Exception as exc:
            errors.append(f"{kind}: {exc}")
        finally:
            if camera is not None:
                try:
                    camera.Close()
                except Exception as exc:
                    cleanup_errors.append(f"Close: {exc}")
                try:
                    api.Destroy(camera)
                except Exception as exc:
                    cleanup_errors.append(f"Destroy: {exc}")
        if cleanup_errors:
            return "unknown", "探测资源释放失败；" + "; ".join(errors + cleanup_errors)
        if success:
            return "idle", f"{kind} 打开/身份检查成功，探测句柄已关闭销毁"
    return ("busy" if busy else "unknown"), "; ".join(errors)


def network_status(code, ip, mask, interfaces, sdk):
    """Decode the status output, NOT GetNetworkConfig's C++ return code.

    Installed RVC.h (and generated SDK documentation) define 0 OK, 1
    Not_Reachable, 2 In_Use, 3 Conflict. The Python example swaps 2/3.
    Prefer named SDK constants if a future Python binding exposes them.
    """
    names = ('OK', 'Not_Reachable', 'In_Use', 'Conflict')
    values = {}
    enum = getattr(sdk, 'NetworkDeviceStatus_', None)
    for fallback, name in enumerate(names):
        symbol = 'NetworkDeviceStatus_' + name
        value = getattr(sdk, symbol, None)
        if value is None and enum is not None:
            value = getattr(enum, symbol, None)
        values[name] = int(value) if value is not None else fallback
    code = int(code)
    name = next((name for name, value in values.items() if value == code), 'Unknown')
    prefix = f'GetNetworkConfig: {name} ({code})'
    if name == 'In_Use':
        return 'busy', prefix + '；SDK 报告设备被占用，未打开相机'
    if name == 'Conflict':
        return 'ip_conflict', prefix + '；SDK 报告网络地址冲突，未打开相机'
    if name == 'Unknown':
        return 'unknown', prefix + '；无法识别的网络设备状态'
    state, detail = subnet_status(ip, mask, interfaces)
    if state != 'same':
        return state, prefix + '；' + detail
    if name == 'Not_Reachable':
        return 'unreachable', prefix + '；设备不可达（不能据此判定断电或离线）'
    return 'idle', prefix + '；网络状态正常，未打开验证采集能力'


def poll_devices(manager, sdk, interfaces, *, probe_open=True):
    """One synchronous generation under SDK lock; failures remain individual rows."""
    rows = []
    with rvc_sdk_lock:
        devices = manager.find_devices()
        for index, device in enumerate(devices):
            row = DeviceStatus(backend_ref=index)
            rows.append(row)
            try:
                ok, info = device.GetDeviceInfo()
                if info is not None:
                    row.model, row.serial = text(info.name), text(info.sn)
                if not ok:
                    raise RuntimeError("GetDeviceInfo 失败")
                own_by_sn = manager.find_by_sn(row.serial) if row.serial else None
                own_by_index = None if own_by_sn else manager.is_device_index_connected(index)
                own = own_by_sn or own_by_index
                if own:
                    basis = "SN" if own_by_sn else f"索引 {index}"
                    row.status = "connected"
                    row.detail = f"本程序已连接（识别依据：{basis}）；不重复打开探测"
                    # Read network metadata without opening another camera handle.
                # DeviceInfo.port is a descriptive string; type is the PortType enum.
                is_gige = info.type == sdk.PortType.PortType_GIGE
                if is_gige:
                    _, ip, mask, gateway, code = device.GetNetworkConfig(sdk.NetworkDevice.NetworkDevice_LightMachine)
                    row.ip = text(ip)
                    if own:
                        row.detail += f"；IP {row.ip}；网络状态原始值 {code}"
                        continue
                    row.status, row.detail = network_status(code, ip, mask, interfaces, sdk)
                    continue  # GigE status never requires Create/Open/Close.
                if own:
                    continue
                if not row.serial:
                    raise RuntimeError("缺少序列号，无法核验打开后的身份")
                if probe_open:
                    row.status, row.detail = probe(sdk, device, info)
                else:
                    row.status = "unknown"
                    row.detail = "已枚举；暂未探测空闲/占用状态（已停用打开相机轮询）"
            except Exception as exc:
                if row.status != "connected":
                    row.status = "unknown"
                row.detail = f"查询失败：{exc}"
    return rows
