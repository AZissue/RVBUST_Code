"""
RVC X2 3D 相机管理器。
负责设备生命周期管理、2D 预览流（QTimer 驱动）、完整 3D 采集。
"""

import os
import shutil
import tempfile

import numpy as np
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

import PyRVC as RVC


class CameraManager(QObject):
    """
    RVC X2 相机管理器。
    通过 QTimer 实现 30fps 的 2D 预览流，
    通过 Capture() 接口实现完整的 3D 结构光扫描。
    """

    # ── 信号定义 ──
    preview_frame_ready = pyqtSignal(np.ndarray)
    # 参数: png_path, ply_path, downsampled_point_cloud_np_array
    capture_complete = pyqtSignal(str, str, np.ndarray)
    camera_error = pyqtSignal(str)
    camera_connected = pyqtSignal()
    camera_disconnected = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._x2 = None                    # RVC X2 相机实例句柄
        self._camera_id = None             # 使用的相机 ID（Left 或 Extra）
        self._device_info = None           # 设备信息结构体
        self._capture_opts = None          # X2 采集参数配置
        self._preview_timer = QTimer(self) # 预览定时器
        self._preview_timer.timeout.connect(self._on_preview_tick)
        self._intrinsic_matrix = None      # 3×3 相机内参矩阵
        self._intrinsic_distortion = None  # 5 元素畸变系数 [k1,k2,p1,p2,k3]
        self._is_connected = False         # 相机连接状态标志
        self._preview_fps = 30             # 预览帧率

    # ── 生命周期 ──────────────────────────────────────────

    def init(self):
        """
        初始化 RVC 系统并打开第一个可用设备（旧接口，兼容保留）。
        新代码应使用 init_with_device() 传入指定设备。
        """
        try:
            RVC.SystemInit()
        except Exception as e:
            self.camera_error.emit(f"RVC 系统初始化失败: {e}")
            return False

        ret, devices = RVC.SystemListDevices(RVC.SystemListDeviceTypeEnum.All)
        if len(devices) == 0:
            self.camera_error.emit("未找到任何相机设备")
            RVC.SystemShutdown()
            return False

        return self.init_with_device(devices[0])

    def init_with_device(self, device):
        """
        使用指定的设备对象初始化相机连接。
        设备对象来自 RVC.SystemListDevices() 的返回列表。
        """
        try:
            # 检查固件版本是否匹配
            if not device.IsFirmwareMatch():
                self.camera_error.emit("相机固件版本不匹配，请用 RVCManager 升级固件")
                RVC.SystemShutdown()
                return False

            # 创建 X2 相机实例
            self._x2 = RVC.X2.Create(device)
            # 打开相机通信通道
            if not self._x2.Open():
                self.camera_error.emit("打开相机失败，请检查连接")
                RVC.X2.Destroy(self._x2)
                self._x2 = None
                RVC.SystemShutdown()
                return False

            # 获取设备信息（名称、序列号等）
            ret, info = device.GetDeviceInfo()
            self._device_info = info

            # 选择主相机 ID：如果设备支持 Extra 彩色相机则使用，否则用 Left
            self._camera_id = RVC.CameraID_Left
            if info.support_extra:
                self._camera_id = RVC.CameraID_Extra

            # 从设备加载已保存的采集参数
            ok, opts = self._x2.LoadCaptureOptionParameters()
            self._capture_opts = opts if ok else RVC.X2_CaptureOptions()

            # 缓存相机内参和畸变系数（用于标定板检测等场景）
            ok, mat, dist = self._x2.GetIntrinsicParameters(self._camera_id)
            if ok:
                self._intrinsic_matrix = list(mat)
                self._intrinsic_distortion = list(dist)

            self._is_connected = True
            self.camera_connected.emit()
            return True

        except Exception as e:
            self.camera_error.emit(f"相机连接异常: {e}")
            return False

    def shutdown(self):
        """
        安全关闭相机并释放资源。
        先停止预览流 → 关闭相机 → 销毁实例 → 关闭 RVC 系统。
        """
        self.stop_preview()
        if self._x2 is not None:
            if self._x2.IsOpen():
                self._x2.Close()
            RVC.X2.Destroy(self._x2)
            self._x2 = None
        RVC.SystemShutdown()
        self._is_connected = False
        self.camera_disconnected.emit()

    def is_connected(self):
        """返回相机是否处于连接状态"""
        return self._is_connected

    # ── 相机信息 ────────────────────────────────────────

    def get_device_name(self):
        """返回已连接设备的名称和序列号"""
        if self._device_info:
            return f"{self._device_info.name} - {self._device_info.sn}"
        return ""

    def get_intrinsics(self):
        """返回相机内参矩阵(9)和畸变系数(5)"""
        return self._intrinsic_matrix, self._intrinsic_distortion

    # ── 预览流 ────────────────────────────────────────────

    def start_preview(self):
        """
        启动 2D 实时预览流。
        通过 QTimer 每 ~33ms（30fps）触发一次 Capture2D 采集。
        Capture2D 只读取 RGB 传感器，不发射结构光，速度快。
        """
        if not self._is_connected:
            return
        # 按帧率计算定时器间隔（毫秒）
        self._preview_timer.start(1000 // self._preview_fps)

    def stop_preview(self):
        """停止预览流定时器"""
        self._preview_timer.stop()

    def _on_preview_tick(self):
        """
        预览定时器回调函数。
        每次 tick 执行一次快速 2D 采集，将图像转为 numpy 数组并通过信号发出。
        """
        try:
            if not self._x2 or not self._x2.IsOpen():
                return
            # 执行快速 2D 采集（不发射结构光，仅读 RGB）
            ok = self._x2.Capture2D(self._camera_id, self._capture_opts)
            if not ok:
                return
            # 获取采集到的图像
            img = self._x2.GetImage(self._camera_id)
            if img is None or not img.IsValid():
                return
            # 通过 numpy buffer protocol 零拷贝获取图像数据
            np_img = np.array(img, copy=False)
            self.preview_frame_ready.emit(np_img)
        except Exception as e:
            self.camera_error.emit(f"预览失败: {e}")

    # ── 完整 3D 采集 ──────────────────────────────────────

    def capture_full_frame(self, save_dir, index):
        """
        执行完整 3D 结构光扫描采集。
        1. 暂停预览流
        2. 触发 Capture（结构光投影 + 3D 重建），耗时约 1-2 秒
        3. 保存 PNG 图像和 PLY 点云到 save_dir/{index}.png|ply
        4. 通过 numpy buffer protocol 读取点云数据
        5. 恢复预览流

        返回 (png_path, ply_path, point_cloud_np) 或 None（失败时）。
        """
        if not self._is_connected:
            self.camera_error.emit("相机未连接")
            return None

        # 先停止预览，避免 Capture 期间被定时器中断
        self.stop_preview()

        try:
            # 触发完整的 3D 结构光扫描（投影仪投光 → 相机多帧拍摄 → 点云重建）
            ok = self._x2.Capture(self._capture_opts)
            if not ok:
                self.camera_error.emit(f"3D采集失败: {RVC.GetLastErrorMessage()}")
                self.start_preview()
                return None

            # 确保输出目录存在
            os.makedirs(save_dir, exist_ok=True)

            # 保存 PNG 图像（通过临时文件解决中文路径兼容问题）
            img = self._x2.GetImage(self._camera_id)
            png_path = os.path.join(save_dir, f"{index}.png")
            if not self._save_image_safe(img, png_path):
                self.camera_error.emit("PNG 图像保存失败")
                self.start_preview()
                return None

            # 保存 PLY 点云文件（毫米单位，二进制格式以减小体积）
            pm = self._x2.GetPointMap()
            ply_path = os.path.join(save_dir, f"{index}.ply")
            if not pm.Save(ply_path, RVC.PointMapUnitEnum.Millimeter, True):
                self.camera_error.emit("PLY 点云保存失败")
                self.start_preview()
                return None

            # 将点云转换为 numpy 数组用于 3D 显示
            # pm 是 (H, W, 3) 的张量，reshape 为 (N, 3)
            pm_np = np.array(pm, copy=False).reshape(-1, 3)
            # 过滤掉无效点（全零坐标表示无数据区域）
            valid = (pm_np[:, 2] != 0) | (pm_np[:, 1] != 0) | (pm_np[:, 0] != 0)
            pm_np = pm_np[valid].astype(np.float32)

        except Exception as e:
            self.camera_error.emit(f"采集过程异常: {e}")
            self.start_preview()
            return None

        # 恢复预览流
        self.start_preview()
        self.capture_complete.emit(png_path, ply_path, pm_np)
        return png_path, ply_path, pm_np

    # ── 辅助函数 ──────────────────────────────────────────

    @staticmethod
    def _save_image_safe(img, save_path):
        """
        安全保存图像文件。
        PyRVC 的 SaveImage 在中文路径下可能静默失败，
        因此先保存到项目 data/tmp/ 下的临时文件（同项目驱动器内），
        再用 os.replace 原子移动到目标路径。
        """
        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        # 临时文件目录统一放在项目 data/tmp/ 下
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmp_dir = os.path.join(project_root, "data", "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="rvc_", dir=tmp_dir)
        os.close(fd)
        try:
            if not img.SaveImage(tmp):
                return False
            os.replace(tmp, save_path)
            return True
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ── 参数设置 ──────────────────────────────────────────

    def set_exposure_2d(self, value_ms):
        """设置 2D 曝光时间（毫秒），影响图像亮度"""
        if self._capture_opts:
            self._capture_opts.exposure_time_2d = int(value_ms)

    def set_exposure_3d(self, value_ms):
        """设置 3D 结构光曝光时间（毫秒），影响点云质量"""
        if self._capture_opts:
            self._capture_opts.exposure_time_3d = int(value_ms)

    def set_gain_2d(self, value):
        """设置 2D 传感器增益（模拟信号放大倍数）"""
        if self._capture_opts:
            self._capture_opts.gain_2d = float(value)

    def set_gain_3d(self, value):
        """设置 3D 结构光传感器增益"""
        if self._capture_opts:
            self._capture_opts.gain_3d = float(value)

    def set_gamma_2d(self, value):
        """设置 2D Gamma 校正值，调整图像非线性亮度曲线"""
        if self._capture_opts:
            self._capture_opts.gamma_2d = float(value)

    def get_settings(self):
        """返回当前相机的采集参数（字典格式）"""
        if not self._capture_opts:
            return {}
        return {
            "exposure_time_2d": self._capture_opts.exposure_time_2d,
            "exposure_time_3d": self._capture_opts.exposure_time_3d,
            "gain_2d": self._capture_opts.gain_2d,
            "gain_3d": self._capture_opts.gain_3d,
            "gamma_2d": self._capture_opts.gamma_2d,
            "gamma_3d": self._capture_opts.gamma_3d,
        }
