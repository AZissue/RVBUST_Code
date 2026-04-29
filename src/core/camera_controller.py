import threading
import traceback
import numpy as np
import PyRVC as RVC
from ..utils.logging_config import setup_module_logger
from .rvc_resource import safe_destroy

logger = setup_module_logger(__name__)


class RVCCameraController:
    """线程安全的 RVC 相机控制器。"""

    def __init__(self):
        self._lock = threading.RLock()
        self.camera = None
        self.device = None
        self.camera_id = RVC.CameraID_Left
        self.is_connected = False
        self.current_image = None        # np.ndarray (deep copy)
        self.current_rvc_image = None    # RVC.Image (caller must destroy via this controller)
        self.current_pointmap = None     # RVC.PointMap
        self.device_info = None
        self.camera_type = None
        self.current_options = None

    def initialize(self):
        try:
            RVC.SystemInit()
            logger.info("RVC系统初始化成功")
            return True, "RVC系统初始化成功"
        except Exception as e:
            logger.error(f"初始化失败: {e}")
            return False, f"初始化失败: {str(e)}"

    def shutdown(self):
        with self._lock:
            if self.is_connected:
                self.disconnect()
        try:
            RVC.SystemShutdown()
            logger.info("RVC系统关闭成功")
        except Exception as e:
            logger.warning(f"RVC系统关闭异常: {e}")

    def find_devices(self):
        opt = RVC.SystemListDeviceTypeEnum.All
        ret, devices = RVC.SystemListDevices(opt)
        if ret and len(devices) > 0:
            logger.info(f"找到 {len(devices)} 个设备")
            return devices
        logger.warning("未找到任何设备")
        return []

    def connect(self, device_index=0):
        with self._lock:
            devices = self.find_devices()
            if len(devices) == 0:
                return False, "未找到任何RVC相机设备"
            if device_index >= len(devices):
                return False, f"设备索引 {device_index} 超出范围"

            self.device = devices[device_index]
            if not self.device.IsFirmwareMatch():
                return False, "固件版本不匹配，请使用RVCManager升级固件"

            ret, info = self.device.GetDeviceInfo()
            if not ret:
                return False, "获取设备信息失败"

            self.device_info = info
            x2_success = False

            # 优先尝试 X2
            try:
                self.camera = RVC.X2.Create(self.device)
                if self.camera is not None:
                    ret = self.camera.Open()
                    if ret and self.camera.IsOpen():
                        self.camera_type = "X2"
                        self.camera_id = RVC.CameraID_Extra if info.support_extra else RVC.CameraID_Left
                        x2_success = True
                    else:
                        safe_destroy(self.camera, RVC.X2.Destroy, "X2")
                        self.camera = None
            except Exception as e:
                logger.warning(f"X2接口异常: {e}")
                safe_destroy(self.camera, RVC.X2.Destroy, "X2")
                self.camera = None

            # X2 失败则回退 X1
            if not x2_success:
                try:
                    self.camera = RVC.X1.Create(self.device, RVC.CameraID_Left)
                    if not self.camera.IsValid():
                        safe_destroy(self.camera, RVC.X1.Destroy, "X1")
                        self.camera = None
                        return False, "创建X1相机失败"
                    ret = self.camera.Open()
                    if not self.camera.IsOpen():
                        safe_destroy(self.camera, RVC.X1.Destroy, "X1")
                        self.camera = None
                        return False, "打开X1相机失败"
                    self.camera_type = "X1"
                    self.camera_id = RVC.CameraID_Left
                except Exception as e:
                    safe_destroy(self.camera, RVC.X1.Destroy, "X1")
                    self.camera = None
                    return False, f"X1相机失败: {e}"

            self._load_and_log_capture_parameters()
            self.is_connected = True
            msg = f"{info.name} ({info.sn}) [{self.camera_type}]"
            logger.info(f"相机连接成功: {msg}")
            return True, msg

    def _load_and_log_capture_parameters(self):
        try:
            ret, opts = self.camera.LoadCaptureOptionParameters()
            if not ret:
                return
            self.current_options = opts
            logger.info(
                f"相机参数 | 2D曝光:{opts.exposure_time_2d}ms 增益:{opts.gain_2d} | "
                f"3D曝光:{opts.exposure_time_3d}ms 增益:{opts.gain_3d} | 亮度:{opts.projector_brightness}"
            )
        except Exception as e:
            logger.warning(f"读取相机参数失败: {e}")

    def get_capture_options(self):
        """读取当前相机的拍摄参数，返回 (bool, options) 或 (False, None)。"""
        with self._lock:
            if not self.is_connected or not self.camera:
                return False, None
            if self.current_options is not None:
                return True, self.current_options
            try:
                ret, opts = self.camera.LoadCaptureOptionParameters()
                if ret:
                    self.current_options = opts
                return ret, opts
            except Exception as e:
                logger.warning(f"读取相机参数失败: {e}")
                return False, None

    def set_capture_options(self, options):
        """保存拍摄参数到相机。"""
        with self._lock:
            if not self.is_connected or not self.camera:
                return False
            try:
                ret = self.camera.SaveCaptureOptionParameters(options)
                if ret:
                    self.current_options = options
                return ret
            except Exception as e:
                logger.error(f"保存相机参数失败: {e}")
                return False

    def disconnect(self):
        with self._lock:
            if self.camera:
                try:
                    self.camera.Close()
                    if self.camera_type == "X2":
                        RVC.X2.Destroy(self.camera)
                    else:
                        RVC.X1.Destroy(self.camera)
                except Exception as e:
                    logger.error(f"相机关闭异常: {e}")
                self.camera = None

            safe_destroy(self.current_rvc_image, RVC.Image.Destroy, "Image")
            safe_destroy(self.current_pointmap, RVC.PointMap.Destroy, "PointMap")

            self.is_connected = False
            self.current_image = None
            self.current_rvc_image = None
            self.current_pointmap = None
            self.device_info = None
            self.camera_type = None
            self.current_options = None
            logger.info("断开连接完成")
            return True

    def capture_3d(self, options=None):
        """3D拍摄。返回 (image_np, pm_clone, rvc_img_clone, msg)。

        调用者负责释放返回的 pm_clone 和 rvc_img_clone（或转交 stitch_engine 管理）。
        """
        with self._lock:
            if not self.is_connected or not self.camera:
                return None, None, None, "相机未连接"

            try:
                opts = options if options is not None else self.current_options
                if opts is not None:
                    ret = self.camera.Capture(opts)
                else:
                    ret = self.camera.Capture()

                if not ret:
                    error_msg = RVC.GetLastErrorMessage()
                    logger.error(f"拍摄失败: {error_msg}")
                    return None, None, None, f"拍摄失败: {error_msg}"

                img = self.camera.GetImage(self.camera_id) if self.camera_type == "X2" else self.camera.GetImage()
                pm = self.camera.GetPointMap()
                if img is None or pm is None:
                    return None, None, None, "获取图像或点云失败"

                # 深拷贝 numpy 图像，释放对 RVC buffer 的引用
                image_np = np.array(img, copy=True)

                # 清理旧的内部引用
                safe_destroy(self.current_pointmap, RVC.PointMap.Destroy, "PointMap")
                safe_destroy(self.current_rvc_image, RVC.Image.Destroy, "Image")

                # 保存新的内部引用（供后续 SaveWithImage 等使用）
                self.current_pointmap = pm.Clone()
                self.current_rvc_image = img.Clone()
                self.current_image = image_np

                # 同时返回 clone 给调用者（调用者生命周期独立）
                return image_np, self.current_pointmap.Clone(), self.current_rvc_image.Clone(), "success"
            except Exception as e:
                logger.critical(f"3D拍摄异常: {e}")
                logger.critical(traceback.format_exc())
                return None, None, None, f"3D拍摄异常: {e}"

    def capture_2d(self, options=None):
        """2D拍摄。返回深拷贝的 numpy 图像 (image_np, msg)。"""
        with self._lock:
            if not self.is_connected or not self.camera:
                return None, "相机未连接"

            try:
                opts = options if options is not None else self.current_options
                if self.camera_type == "X2":
                    if opts is not None:
                        ret = self.camera.Capture2D(self.camera_id, opts)
                    else:
                        ret = self.camera.Capture2D(self.camera_id)
                    img = self.camera.GetImage(self.camera_id)
                else:
                    if opts is not None:
                        ret = self.camera.Capture2D(opts)
                    else:
                        ret = self.camera.Capture2D()
                    img = self.camera.GetImage()

                if not ret or img is None:
                    return None, "2D拍摄失败"

                image_np = np.array(img, copy=True)
                return image_np, "success"
            except Exception as e:
                logger.critical(f"2D拍摄异常: {e}")
                logger.critical(traceback.format_exc())
                return None, f"2D拍摄异常: {e}"
