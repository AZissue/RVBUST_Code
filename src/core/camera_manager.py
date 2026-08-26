# -*- coding: utf-8 -*-
"""
相机管理模块。

包含两部分：
  1. SingleCameraController —— 从 DualCameraFusion/src/app.py:1044-1194 原样抽取，
     干净的单相机封装（X2 优先、X1 回退），直接可用；
  2. CameraManager —— 新写的 N 相机管理器（替代 DualCameraManager），
     以 camera_id 为键管理任意数量的 SingleCameraController，
     支持软触发同步/异步拍摄，RVC SystemInit 采用引用计数管理。

注意：PyRVC 不在模块顶层 import（try/except 保护），无 SDK 环境下
所有连接/拍摄操作优雅降级（返回失败而不崩溃），便于离线开发。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple
import threading

import numpy as np

from .utils import logger, safe_destroy
from .frame_data import FrameData

try:
    import PyRVC as RVC
except ImportError:
    RVC = None  # 无 SDK 环境：连接/拍摄一律返回失败


def _decode_network_bytes(b):
    """把 GetNetworkConfig 返回的 bytes 解码为字符串（去除尾空）。"""
    if b is None:
        return ""
    try:
        s = b.decode("ascii", errors="ignore").split("\x00")[0]
        return (s or "").strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 单相机控制器（轻量封装，N 台直接实例化）
# ---------------------------------------------------------------------------
class SingleCameraController:
    """单台 RVC 相机控制器。"""

    def __init__(self, name: str):
        self.name = name
        self.camera = None
        self.device = None
        self.device_info = None
        self.camera_type = None
        self.camera_id = RVC.CameraID_Left if RVC is not None else None
        self.is_connected = False
        self.current_options = None
        self.device_index = None      # 连接的设备索引（防重复占用）
        self.sn = None                # 设备 SN（防重复占用，索引可能因枚举顺序变化）
        self.line_scan_detected = False  # 连接时检测到线扫模式（已自动改面阵）
        self._capture_lock = threading.RLock()  # 串行化 2D/3D 拍摄，避免 SDK 句柄并发冲突

    def find_devices(self) -> list:
        if RVC is None:
            return []
        opt = RVC.SystemListDeviceTypeEnum.All
        ret, devices = RVC.SystemListDevices(opt)
        return devices if devices else []

    def connect(self, device_index=0) -> Tuple[bool, str]:
        if RVC is None:
            return False, "PyRVC 未安装（无 SDK 环境）"
        devices = self.find_devices()
        if len(devices) == 0:
            return False, "未找到任何设备"
        if device_index >= len(devices):
            return False, f"索引 {device_index} 越界"

        self.device = devices[device_index]
        if not self.device.IsFirmwareMatch():
            return False, "固件不匹配"

        ret, info = self.device.GetDeviceInfo()
        if not ret:
            return False, "获取设备信息失败"
        self.device_info = info

        # 占用提示（Open 失败的常见原因）
        busy_hint = "（可能被 RVCManager / 其他程序占用，或已被本软件其他相机连接）"

        # 优先 X2
        x2_ok = False
        try:
            self.camera = RVC.X2.Create(self.device)
            if self.camera:
                ret = self.camera.Open()
                if ret and self.camera.IsOpen():
                    self.camera_type = "X2"
                    self.camera_id = RVC.CameraID_Extra if info.support_extra else RVC.CameraID_Left
                    x2_ok = True
                else:
                    safe_destroy(self.camera, RVC.X2.Destroy, "X2")
                    self.camera = None
        except Exception as e:
            logger.warning(f"{self.name} X2 失败: {e}")
            self.camera = None

        if not x2_ok:
            try:
                self.camera = RVC.X1.Create(self.device, RVC.CameraID_Left)
                if not self.camera.IsValid():
                    safe_destroy(self.camera, RVC.X1.Destroy, "X1")
                    return False, f"X1 创建失败{busy_hint}"
                ret = self.camera.Open()
                if not self.camera.IsOpen():
                    safe_destroy(self.camera, RVC.X1.Destroy, "X1")
                    return False, f"X1 打开失败{busy_hint}"
                self.camera_type = "X1"
                self.camera_id = RVC.CameraID_Left
            except Exception as e:
                return False, f"X1 失败: {e}"

        self.device_index = device_index
        self.sn = getattr(info, "sn", None)
        self._load_options()
        mode_note = self._check_capture_mode()
        self.is_connected = True
        return True, f"{info.name} ({info.sn}) [{self.camera_type}]{mode_note}"

    def _check_capture_mode(self) -> str:
        """检测相机拍摄模式（仅检测提示，不修改）。

        M 系列相机（如 M2600）的线扫模式是正常拍摄方式：无参 Capture()
        直接按相机内部参数拍摄即可。不做任何模式切换——M2600 一类并不
        支持 Normal 面阵模式，强行改写 capture_mode 反而会失败。
        FixedLineScan（连续线扫）无法用单拍 Capture()，提示用户去
        RVCManager 调整。
        返回附加提示文本。"""
        self.line_scan_detected = False
        opts = self.current_options
        if opts is None or RVC is None:
            return ""
        swing = getattr(RVC, "CaptureMode_SwingLineScan", None)
        fixed = getattr(RVC, "CaptureMode_FixedLineScan", None)
        mode = getattr(opts, "capture_mode", None)
        if fixed is not None and mode == fixed:
            self.line_scan_detected = True
            logger.warning(
                f"{self.name} 处于固定线扫模式（FixedLineScan），单拍 Capture() 不可用，"
                "如需单帧拍摄请在 RVCManager 中切换为摆动线扫/面阵模式")
            return "（固定线扫模式，单拍 Capture 不可用，请在 RVCManager 中调整模式）"
        if swing is not None and mode == swing:
            self.line_scan_detected = True
            logger.info(f"{self.name} 处于摆动线扫模式（SwingLineScan），按相机当前模式拍摄")
            return "（摆动线扫模式，按相机当前模式拍摄）"
        return ""

    def _load_options(self):
        try:
            ret, opts = self.camera.LoadCaptureOptionParameters()
            if ret:
                self.current_options = opts
        except Exception as e:
            logger.warning(f"读取参数失败: {e}")

    def disconnect(self):
        if self.camera:
            try:
                self.camera.Close()
                if self.camera_type == "X2":
                    RVC.X2.Destroy(self.camera)
                else:
                    RVC.X1.Destroy(self.camera)
            except Exception as e:
                logger.error(f"关闭异常: {e}")
            self.camera = None
        self.is_connected = False
        self.device = None
        self.device_info = None
        self.device_index = None
        self.sn = None
        self.line_scan_detected = False
        self.current_options = None

    def capture_2d(self) -> Tuple[Optional[np.ndarray], str]:
        """仅拍摄 2D 图像（Capture2D），不生成点云，用于取景预览/位置调整。

        使用相机当前保存的 2D 参数（exposure_time_2d / gain_2d 等），避免默认参数过暗。
        """
        if not self.is_connected or not self.camera:
            return None, "相机未连接"
        with self._capture_lock:
            try:
                opts = self.current_options
                if self.camera_type == "X2":
                    ret = (self.camera.Capture2D(self.camera_id, opts)
                           if opts is not None else self.camera.Capture2D(self.camera_id))
                else:
                    ret = (self.camera.Capture2D(opts)
                           if opts is not None else self.camera.Capture2D())
                if not ret:
                    return None, f"2D 预览失败: {RVC.GetLastErrorMessage()}"

                img = self.camera.GetImage(self.camera_id) if self.camera_type == "X2" else self.camera.GetImage()
                if img is None:
                    return None, "获取图像失败"

                image_np = np.array(img, copy=True)
                return image_np, "success"
            except Exception as e:
                logger.error(f"2D 预览异常: {e}")
                return None, f"异常: {e}"

    def capture_3d(self, options=None) -> Tuple[Optional[np.ndarray], Optional['RVC.PointMap'], Optional['RVC.Image'], str]:
        if not self.is_connected or not self.camera:
            return None, None, None, "相机未连接"
        with self._capture_lock:
            try:
                # 默认用无参 Capture()：直接按相机内部参数拍摄（SDK 推荐方式，
                # 兼容 M 系列线扫模式）；仅当显式传入参数时才 Capture(opts)
                if options is not None:
                    ret = self.camera.Capture(options)
                else:
                    ret = self.camera.Capture()
                if not ret:
                    return None, None, None, f"拍摄失败: {RVC.GetLastErrorMessage()}"

                img = self.camera.GetImage(self.camera_id) if self.camera_type == "X2" else self.camera.GetImage()
                pm = self.camera.GetPointMap()
                if img is None or pm is None:
                    return None, None, None, "获取图像/点云失败"

                image_np = np.array(img, copy=True)
                return image_np, pm.Clone(), img.Clone(), "success"
            except Exception as e:
                logger.error(f"拍摄异常: {e}")
                return None, None, None, f"异常: {e}"

    def get_capture_options(self):
        if not self.is_connected:
            return False, None
        if self.current_options is not None:
            return True, self.current_options
        try:
            ret, opts = self.camera.LoadCaptureOptionParameters()
            if ret:
                self.current_options = opts
            return ret, opts
        except Exception:
            return False, None

    def set_capture_options(self, options) -> bool:
        if not self.is_connected:
            return False
        try:
            ret = self.camera.SaveCaptureOptionParameters(options)
            if ret:
                self.current_options = options
            return ret
        except Exception as e:
            logger.error(f"保存参数失败: {e}")
            return False

    def build_options(self, exp2d, exp3d, gain2d, gain3d, brightness):
        """构建 CaptureOptions。

        注意三点（实机踩坑记录）：
        1. 曝光时间字段在 PyRVC 绑定中是 **int**（传 float 会报
           "incompatible function arguments: arg0: int"），必须取整；
        2. 基于相机当前参数修改（"先 Load 再改"），避免默认构造把
           其他已调好的参数全部重置；
        3. X1 相机必须用 X1_CaptureOptions（X2 类型会报错）。
        """
        base = self.current_options
        if base is None:
            if RVC is None:
                raise RuntimeError("PyRVC 未安装")
            base = (RVC.X1_CaptureOptions() if self.camera_type == "X1"
                    else RVC.X2_CaptureOptions())
        opts = base
        opts.exposure_time_2d = int(round(exp2d))
        opts.exposure_time_3d = int(round(exp3d))
        opts.gain_2d = float(gain2d)
        opts.gain_3d = float(gain3d)
        opts.projector_brightness = int(round(brightness))
        return opts


# ---------------------------------------------------------------------------
# N 相机管理器（替代 DualCameraManager）
# ---------------------------------------------------------------------------
class CameraManager:
    """管理任意数量相机，提供统一操作接口。

    以 camera_id（任意字符串）为键维护 SingleCameraController 字典；
    RVC SystemInit / SystemShutdown 采用类级引用计数，多个 CameraManager
    实例共存时只初始化/关闭一次 SDK。
    """

    _sys_init_count = 0  # 类级引用计数

    def __init__(self):
        self._cameras: Dict[str, SingleCameraController] = {}
        self._frame_counter = 0  # 全局帧号（每次 capture_all 递增）

    # ------------------------------------------------------------------
    # RVC 系统初始化（引用计数）
    # ------------------------------------------------------------------
    def initialize(self) -> Tuple[bool, str]:
        """初始化 RVC 系统（引用计数 +1，首个实例真正调用 SystemInit）。"""
        if RVC is None:
            return False, "PyRVC 未安装（无 SDK 环境）"
        if CameraManager._sys_init_count == 0:
            try:
                RVC.SystemInit()
            except Exception as e:
                return False, f"初始化失败: {e}"
        CameraManager._sys_init_count += 1
        logger.info(f"RVC SystemInit 引用计数: {CameraManager._sys_init_count}")
        return True, "RVC 系统初始化成功"

    def shutdown(self):
        """关闭 RVC 系统（引用计数 -1，归零时真正调用 SystemShutdown）。"""
        self.disconnect_all()
        if CameraManager._sys_init_count > 0:
            CameraManager._sys_init_count -= 1
            logger.info(f"RVC SystemInit 引用计数: {CameraManager._sys_init_count}")
            if CameraManager._sys_init_count == 0 and RVC is not None:
                try:
                    RVC.SystemShutdown()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 设备枚举（供网络配置等功能使用）
    # ------------------------------------------------------------------
    def find_devices(self) -> list:
        """枚举所有 RVC 设备（USB + GigE）。无 SDK 环境返回空列表。"""
        if RVC is None:
            return []
        try:
            ret, devices = RVC.SystemListDevices(RVC.SystemListDeviceTypeEnum.All)
            return devices if devices else []
        except Exception as e:
            logger.warning(f"枚举设备失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 相机增删
    # ------------------------------------------------------------------
    def add_camera(self, camera_id: str) -> bool:
        """添加一台相机（仅注册，不连接）。已存在返回 False。"""
        if camera_id in self._cameras:
            logger.warning(f"相机 {camera_id} 已存在")
            return False
        self._cameras[camera_id] = SingleCameraController(camera_id)
        return True

    def remove_camera(self, camera_id: str):
        """移除一台相机（先断开连接）。不存在则静默忽略。"""
        cam = self._cameras.pop(camera_id, None)
        if cam is not None:
            cam.disconnect()

    @property
    def camera_ids(self) -> List[str]:
        return list(self._cameras.keys())

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------
    def is_device_index_connected(self, device_index: int,
                                  exclude_id: str = None) -> Optional[str]:
        """检查设备索引是否已被某台相机连接，返回占用它的 camera_id 或 None。"""
        for cid, cam in self._cameras.items():
            if cid == exclude_id:
                continue
            if cam.is_connected and cam.device_index == device_index:
                return cid
        return None

    def find_by_sn(self, sn: str, exclude_id: str = None) -> Optional[str]:
        """按 SN 查找已连接的相机，返回 camera_id 或 None。"""
        if not sn:
            return None
        for cid, cam in self._cameras.items():
            if cid == exclude_id:
                continue
            if cam.is_connected and cam.sn and cam.sn == sn:
                return cid
        return None

    def connect(self, camera_id: str, device_index: int) -> Tuple[bool, str]:
        """连接指定相机到指定设备索引（防重复占用：索引 + SN 双重检查）。"""
        cam = self._cameras.get(camera_id)
        if cam is None:
            return False, f"相机 {camera_id} 未注册（先 add_camera）"
        # 前置检查：同一设备索引不能被两台相机占用
        holder = self.is_device_index_connected(device_index, exclude_id=camera_id)
        if holder is not None:
            return False, f"设备 [{device_index}] 已被相机 {holder} 连接，不能重复占用"
        try:
            ok, msg = cam.connect(device_index)
        except Exception as e:
            logger.error(f"连接 {camera_id} 异常: {e}")
            return False, f"异常: {e}"
        # 后置检查：SN 去重（设备索引可能因枚举顺序变化而错位）
        if ok:
            holder = self.find_by_sn(cam.sn, exclude_id=camera_id)
            if holder is not None:
                cam.disconnect()
                return False, (f"设备 SN {cam.sn} 已被相机 {holder} 连接，"
                               "同一台物理相机不能重复添加")
        return ok, msg

    def connect_all(self, device_indices: Dict[str, int]) -> Tuple[bool, str]:
        """按 {camera_id: device_index} 批量连接；任一失败则全部回滚。"""
        msgs = []
        connected = []
        for camera_id, idx in device_indices.items():
            ok, msg = self.connect(camera_id, idx)
            msgs.append(f"{camera_id}: {msg}")
            if not ok:
                for cid in connected:
                    self._cameras[cid].disconnect()
                return False, " | ".join(msgs)
            connected.append(camera_id)
        return True, " | ".join(msgs)

    def is_connected(self, camera_id: str) -> bool:
        cam = self._cameras.get(camera_id)
        return cam is not None and cam.is_connected

    def get_connected_ids(self) -> List[str]:
        """返回当前已连接的 camera_id 列表（按注册顺序）。"""
        return [cid for cid, cam in self._cameras.items() if cam.is_connected]

    def disconnect_all(self):
        """断开所有相机。"""
        for cam in self._cameras.values():
            cam.disconnect()

    def clear(self):
        """断开并移除所有已注册相机，恢复到初始空状态。"""
        self.disconnect_all()
        self._cameras.clear()

    # ------------------------------------------------------------------
    # 网口相机网络配置
    # ------------------------------------------------------------------
    def find_gige_devices(self) -> list:
        """仅枚举 GigE 网口相机。无 SDK 环境返回空列表。"""
        if RVC is None:
            return []
        try:
            ret, devices = RVC.SystemListDevices(RVC.SystemListDeviceTypeEnum.GigE)
            return devices if devices else []
        except Exception as e:
            logger.warning(f"枚举 GigE 设备失败: {e}")
            return []

    def get_device_network_config(self, device_index: int,
                                  network_device=RVC.NetworkDevice.NetworkDevice_LightMachine
                                  if RVC is not None else None) -> Tuple[bool, dict, str]:
        """获取指定 GigE 设备的网络配置。

        Returns:
            (success, config_dict, message)
            config_dict 含: type('DHCP'/'STATIC'), ip, netmask, gateway, status(0=OK...)
        """
        if RVC is None:
            return False, {}, "PyRVC 未安装"
        devices = self.find_gige_devices()
        if device_index >= len(devices):
            return False, {}, f"GigE 设备索引 {device_index} 越界"
        dev = devices[device_index]
        try:
            net_type, ip_b, nm_b, gw_b, status = dev.GetNetworkConfig(network_device)
            ip = _decode_network_bytes(ip_b)
            nm = _decode_network_bytes(nm_b)
            gw = _decode_network_bytes(gw_b)
            cfg = {
                'type': 'STATIC' if net_type == RVC.NetworkType.NetworkType_STATIC else 'DHCP',
                'ip': ip,
                'netmask': nm,
                'gateway': gw,
                'status': int(status),
            }
            return True, cfg, "获取成功"
        except Exception as e:
            return False, {}, f"获取网络配置失败: {e}"

    def auto_configure_network(self, device_indices: Optional[List[int]] = None
                               ) -> List[Tuple[int, bool, str]]:
        """对指定设备一键自动配置 IP（仅 GigE 设备生效，USB 设备自动跳过）。

        Args:
            device_indices: find_devices() 返回的索引列表（可能包含 USB + GigE 混合）；
                            None 或空列表表示所有 GigE 设备。

        Returns:
            结果列表，每项为 (device_index, success, message)。
        """
        if RVC is None:
            return [(-1, False, "PyRVC 未安装")]

        # 枚举所有设备，建立 GigE 设备索引映射
        all_devices = self.find_devices()
        gige_devices = self.find_gige_devices()
        if not gige_devices:
            return [(-1, False, "未找到 GigE 设备")]

        # 构建 all_devices 索引 → gige_devices 索引的映射（通过 SN 匹配）
        gige_sn_to_idx = {}
        for gidx, dev in enumerate(gige_devices):
            try:
                ok, info = dev.GetDeviceInfo()
                if ok:
                    gige_sn_to_idx[getattr(info, 'sn', '')] = gidx
            except Exception:
                pass

        all_sn_to_gige_idx = {}
        for aidx, dev in enumerate(all_devices):
            try:
                ok, info = dev.GetDeviceInfo()
                if ok:
                    sn = getattr(info, 'sn', '')
                    if sn in gige_sn_to_idx:
                        all_sn_to_gige_idx[aidx] = gige_sn_to_idx[sn]
            except Exception:
                pass

        # 确定要处理的目标（all_devices 索引）
        if device_indices:
            targets = device_indices
        else:
            targets = list(all_sn_to_gige_idx.keys())

        results: List[Tuple[int, bool, str]] = []
        for aidx in targets:
            if aidx < 0 or aidx >= len(all_devices):
                results.append((aidx, False, f"索引 {aidx} 越界"))
                continue
            gidx = all_sn_to_gige_idx.get(aidx)
            if gidx is None:
                # USB 设备或其他非 GigE 设备，跳过并提示
                try:
                    ok, info = all_devices[aidx].GetDeviceInfo()
                    name = getattr(info, 'name', '?') if ok else '?'
                    sn = getattr(info, 'sn', '?') if ok else '?'
                except Exception:
                    name, sn = '?', '?'
                results.append((aidx, False, f"{name} (SN:{sn}) 非 GigE 设备，跳过 IP 配置"))
                continue

            dev = gige_devices[gidx]
            try:
                ok, info = dev.GetDeviceInfo()
                sn = getattr(info, 'sn', '?') if ok else '?'
            except Exception:
                sn = '?'
            try:
                ret = dev.AutoConfigureNetwork()
                if ret == 0:
                    results.append((aidx, True, f"SN:{sn} 自动配置 IP 成功"))
                else:
                    err = RVC.GetLastErrorMessage() if hasattr(RVC, 'GetLastErrorMessage') else ""
                    results.append((aidx, False, f"SN:{sn} 自动配置 IP 失败 (code={ret}) {err}"))
            except Exception as e:
                results.append((aidx, False, f"SN:{sn} 自动配置异常: {e}"))
        return results

    # ------------------------------------------------------------------
    # 拍摄（软触发）
    # ------------------------------------------------------------------
    def capture_2d_preview(self, camera_id: str) -> Optional[FrameData]:
        """仅获取 2D 预览图像，不拍摄点云。成功返回 FrameData（无 pointmap），失败 None。"""
        cam = self._cameras.get(camera_id)
        if cam is None or not cam.is_connected:
            logger.warning(f"capture_2d_preview: 相机 {camera_id} 未连接")
            return None
        img, msg = cam.capture_2d()
        if img is None:
            logger.error(f"capture_2d_preview {camera_id} 失败: {msg}")
            return None
        return FrameData(frame_id=self._frame_counter, camera_name=camera_id,
                         image_np=img, pointmap=None, rvc_image=None)

    def capture(self, camera_id: str, options=None,
                frame_id: Optional[int] = None) -> Optional[FrameData]:
        """软触发单拍指定相机，成功返回 FrameData，失败返回 None。

        frame_id 为 None 时自动递增全局帧号；capture_all 会显式传入同一帧号，
        保证同步拍摄时各相机 frame_id 一致。
        """
        cam = self._cameras.get(camera_id)
        if cam is None or not cam.is_connected:
            logger.warning(f"capture: 相机 {camera_id} 未连接")
            return None
        if frame_id is None:
            self._frame_counter += 1
            frame_id = self._frame_counter
        img, pm, rvc_img, msg = cam.capture_3d(options)
        if img is None:
            logger.error(f"capture {camera_id} 失败: {msg}")
            return None
        return FrameData(frame_id=frame_id, camera_name=camera_id,
                         image_np=img, pointmap=pm, rvc_image=rvc_img)

    def capture_all(self, camera_ids: Optional[List[str]] = None,
                    sync: bool = True, options=None) -> Dict[str, FrameData]:
        """拍摄多台相机，返回 {camera_id: FrameData}（仅含成功的相机）。

        sync=True ：使用线程并发调用各相机的软触发，尽量缩小触发时间差；
                    真正的零时差需要硬件同步触发（RVC 外触发）。
        sync=False：串行拍摄，一台拍完再拍下一台。
        """
        if camera_ids is None:
            camera_ids = self.get_connected_ids()
        if not camera_ids:
            return {}

        self._frame_counter += 1
        current_id = self._frame_counter
        raw_results: Dict[str, Optional[FrameData]] = {}

        if sync and len(camera_ids) > 1:
            logger.info(
                f"[sync-capture] frame_id={current_id} 启动并发拍摄，"
                f"相机数={len(camera_ids)}, workers={len(camera_ids)}"
            )

            def _capture_one(cid: str) -> Tuple[str, Optional[FrameData]]:
                thread_info = f"{threading.current_thread().name}({threading.get_ident()})"
                logger.info(f"[sync-capture] frame_id={current_id} 线程 {thread_info} 开始触发 {cid}")
                frame = self.capture(cid, options=options, frame_id=current_id)
                elapsed = "ok" if frame is not None else "failed"
                logger.info(
                    f"[sync-capture] frame_id={current_id} 线程 {thread_info} "
                    f"完成 {cid}: {elapsed}"
                )
                return cid, frame

            with ThreadPoolExecutor(max_workers=len(camera_ids)) as executor:
                for cid, frame in executor.map(_capture_one, camera_ids):
                    raw_results[cid] = frame
        else:
            for cid in camera_ids:
                frame = self.capture(cid, options=options, frame_id=current_id)
                raw_results[cid] = frame

        return {cid: frame for cid, frame in raw_results.items() if frame is not None}

    # ------------------------------------------------------------------
    # 参数
    # ------------------------------------------------------------------
    def set_options(self, camera_id: str, options) -> bool:
        """设置指定相机的拍摄参数。"""
        cam = self._cameras.get(camera_id)
        if cam is None:
            return False
        return cam.set_capture_options(options)

    def set_all_options(self, options_dict: Dict[str, object]) -> bool:
        """按 {camera_id: options} 批量设置参数，全部成功返回 True。"""
        ok = True
        for cid, opts in options_dict.items():
            ok = self.set_options(cid, opts) and ok
        return ok

    def get_options(self, camera_id: str):
        """获取指定相机的拍摄参数，返回 (bool, options)。"""
        cam = self._cameras.get(camera_id)
        if cam is None:
            return False, None
        return cam.get_capture_options()
