import numpy as np
from PySide6.QtCore import QThread, Signal
from ..utils.logging_config import setup_module_logger

logger = setup_module_logger(__name__)


class DetectionParamSearchWorker(QThread):
    """在后台线程中执行编码圆参数穷举搜索，避免阻塞 GUI。"""
    result_found = Signal(int, float, float, int, str)   # n, r1, r2, count, message
    search_finished = Signal(bool, str)                  # found_any, summary

    def __init__(self, detector, image: np.ndarray, parent=None):
        super().__init__(parent)
        self.detector = detector
        self.image = image
        self._running = True

    def run(self):
        logger.info("开始异步参数搜索")
        found_any = False
        original_n = self.detector.marker_type.N
        original_r1 = self.detector.marker_type.r1_to_r0_ratio
        original_r2 = self.detector.marker_type.r2_to_r0_ratio

        try:
            for test_n in [8, 12, 15]:
                for test_r1 in [1.5, 2.0, 2.5]:
                    for test_r2 in [2.5, 3.0, 3.5]:
                        if not self._running:
                            break
                        try:
                            self.detector.set_params(test_n, test_r1, test_r2)
                            markers = self.detector.detect(self.image)
                            if markers:
                                count = len(markers)
                                msg = f"N={test_n}, r1={test_r1}, r2={test_r2}: {count} 个"
                                logger.info(f"参数搜索命中: {msg}")
                                self.result_found.emit(test_n, test_r1, test_r2, count, msg)
                                found_any = True
                        except Exception:
                            pass
                    if not self._running:
                        break
                if not self._running:
                    break
        finally:
            # 恢复原始参数
            try:
                self.detector.set_params(original_n, original_r1, original_r2)
            except Exception as e:
                logger.warning(f"恢复检测参数失败: {e}")

        summary = "找到可用参数组合" if found_any else "未找到任何能检测到编码圆的参数组合"
        self.search_finished.emit(found_any, summary)
        logger.info(f"参数搜索结束: {summary}")

    def cancel(self):
        self._running = False
        self.wait(1000)
