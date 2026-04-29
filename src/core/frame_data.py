"""帧数据封装模块 —— 统一管理一帧的所有资源。"""
from typing import List, Optional
import numpy as np
import PyRVC as RVC

from .rvc_resource import safe_destroy


class CaptureSession:
    """
    封装单帧捕获的所有数据与资源生命周期：
      - 2D 图像 (numpy)
      - RVC PointMap
      - RVC Image
      - 检测到的编码圆 markers
    """

    def __init__(
        self,
        frame_id: int,
        image_np: Optional[np.ndarray] = None,
        pointmap: Optional[RVC.PointMap] = None,
        rvc_image: Optional[RVC.Image] = None,
        markers: Optional[List[dict]] = None,
    ):
        self.frame_id = frame_id
        self.image_np = image_np
        self.pointmap = pointmap
        self.rvc_image = rvc_image
        self.markers = markers or []

    @property
    def marker_count(self) -> int:
        return len(self.markers)

    @property
    def has_pointcloud(self) -> bool:
        return self.pointmap is not None and self.rvc_image is not None

    def release(self) -> None:
        """安全释放 RVC 资源，并清空引用。"""
        safe_destroy(self.pointmap, RVC.PointMap.Destroy, "PointMap")
        safe_destroy(self.rvc_image, RVC.Image.Destroy, "Image")
        self.pointmap = None
        self.rvc_image = None
        self.image_np = None
        self.markers = []

    def __repr__(self) -> str:
        return (
            f"CaptureSession(id={self.frame_id}, "
            f"markers={self.marker_count}, "
            f"has_pc={self.has_pointcloud})"
        )
