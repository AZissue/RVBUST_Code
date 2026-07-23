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

from typing import Dict, List, Optional, Tuple

import numpy as np

from .utils import logger, safe_destroy
from .frame_data import FrameData

try:
    import PyRVC as RVC
except ImportError:
    RVC = None  # 无 SDK 环境：连接/拍摄一律返回失败


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

    def capture(self, camera_id: str, options=None) -> Optional[FrameData]:
        """软触发单拍指定相机，成功返回 FrameData，失败返回 None。"""
        cam = self._cameras.get(camera_id)
        if cam is None or not cam.is_connected:
            logger.warning(f"capture: 相机 {camera_id} 未连接")
            return None
        img, pm, rvc_img, msg = cam.capture_3d(options)
        if img is None:
            logger.error(f"capture {camera_id} 失败: {msg}")
            return None
        return FrameData(frame_id=self._frame_counter, camera_name=camera_id,
                         image_np=img, pointmap=pm, rvc_image=rvc_img)

    def capture_all(self, camera_ids: Optional[List[str]] = None,
                    sync: bool = True) -> Dict[str, FrameData]:
        """拍摄多台相机，返回 {camera_id: FrameData}（仅含成功的相机）。

        sync=True ：尽量同时触发——循环快速依次软触发（RVC 软触发本身是
                    异步的，依次触发的时间差在毫秒级）；
        sync=False：串行拍摄（一台拍完再拍下一台）。
        当前实现两者均为快速循环触发，接口预留以便未来接入硬件同步。
        """
        if camera_ids is None:
            camera_ids = self.get_connected_ids()
        self._frame_counter += 1
        frames: Dict[str, FrameData] = {}
        for cid in camera_ids:
            frame = self.capture(cid)
            if frame is not None:
                frames[cid] = frame
        return frames

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
