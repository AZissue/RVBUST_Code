import traceback
import numpy as np
import cv2
import PyRVC as RVC
from ..utils.logging_config import setup_module_logger

logger = setup_module_logger(__name__)


class MarkerDetector:
    def __init__(self):
        self.marker_type = RVC.CodedCircleMarkerType()
        self.marker_type.N = 8
        self.marker_type.r1_to_r0_ratio = 2.0
        self.marker_type.r2_to_r0_ratio = 3.0
        self.enabled = True

    def set_params(self, n, r1_ratio, r2_ratio):
        self.marker_type.N = n
        self.marker_type.r1_to_r0_ratio = r1_ratio
        self.marker_type.r2_to_r0_ratio = r2_ratio
        logger.info(f"检测参数更新: N={n}, r1/r0={r1_ratio:.3f}, r2/r0={r2_ratio:.3f}")

    def detect(self, image: np.ndarray):
        if image is None:
            return []
        try:
            img_for_detection = self._preprocess_image(image)
            markers = RVC.DetectCodedCircleMarker(img_for_detection, self.marker_type)
            results = [
                {
                    'code': int(marker.code),
                    'x': float(marker.x),
                    'y': float(marker.y),
                    'center': (int(marker.x), int(marker.y))
                }
                for marker in markers
            ]
            logger.debug(f"检测完成，发现 {len(results)} 个编码圆")
            return results
        except Exception as e:
            logger.error(f"检测异常: {e}")
            logger.error(traceback.format_exc())
            return []

    def _preprocess_image(self, image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 3 and image.shape[2] == 3:
            return np.ascontiguousarray(image).copy()
        elif len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif len(image.shape) == 3 and image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        else:
            return np.ascontiguousarray(image).copy()
