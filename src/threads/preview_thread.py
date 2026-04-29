import time
import numpy as np
from PySide6.QtCore import QThread, Signal
from ..utils.logging_config import setup_module_logger

logger = setup_module_logger(__name__)


class PreviewThread(QThread):
    """安全的实时预览线程。"""
    frame_ready = Signal(np.ndarray, list)   # image_np, markers
    error_occurred = Signal(str)

    def __init__(self, camera_controller, marker_detector, detect_interval=3):
        super().__init__()
        self.camera = camera_controller
        self.detector = marker_detector
        self.detect_interval = detect_interval
        self._running = False
        self.frame_count = 0
        self.last_markers = []

    def run(self):
        logger.info("预览线程开始运行")
        self._running = True
        self.frame_count = 0
        error_count = 0
        max_errors = 5

        while self._running and self.camera.is_connected:
            try:
                image, msg = self.camera.capture_2d()
                if image is not None:
                    error_count = 0
                    markers = []
                    if self.detector.enabled:
                        self.frame_count += 1
                        if self.frame_count % self.detect_interval == 0:
                            try:
                                markers = self.detector.detect(image)
                                self.last_markers = markers
                                logger.debug(f"检测完成，发现 {len(markers)} 个编码圆")
                            except Exception as e:
                                logger.error(f"编码圆检测失败: {e}")
                                markers = self.last_markers
                        else:
                            markers = self.last_markers
                    self.frame_ready.emit(image, markers)
                else:
                    error_count += 1
                    logger.warning(f"拍摄失败 ({error_count}/{max_errors}): {msg}")
                    if error_count >= max_errors:
                        self.error_occurred.emit(f"连续{max_errors}次拍摄失败: {msg}")
                        break
            except Exception as e:
                error_count += 1
                logger.critical(f"预览循环异常 ({error_count}/{max_errors}): {e}")
                if error_count >= max_errors:
                    self.error_occurred.emit(f"预览异常: {str(e)}")
                    break

            sleep_time = 0.05 if self.detector.enabled else 0.033
            time.sleep(sleep_time)

        logger.info("预览线程运行结束")

    def stop(self):
        logger.info("停止预览线程")
        self._running = False
        if not self.wait(2000):
            logger.warning("预览线程未能在2秒内停止，尝试终止")
            self.terminate()
            self.wait(1000)
