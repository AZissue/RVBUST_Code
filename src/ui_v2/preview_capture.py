"""Common serialized SDK preview acquisition, independent of workspace widgets."""
import time
from PySide6.QtCore import QThread, Signal
from core.utils import logger

class PreviewCaptureThread(QThread):
    """Serialized SDK reads for continuous single-camera or one-round card preview.

    Only QImage/raw frame data crosses threads; QPixmap construction stays on GUI.
    Stop prevents further reads and late delivery; the owner joins on shutdown.
    SDK capture_2d_preview retains the global acquisition lock for 3D interlocks.
    """

    camera_frame_ready = Signal(str, object)
    frame_ready = Signal(object)  # detached QImage

    def __init__(self, camera_manager, camera_id: str,
                 interval_ms: int = 200, parent=None, *, single_pass=False):
        super().__init__(parent)
        self._camera_manager = camera_manager
        self._camera_ids = (camera_id,) if isinstance(camera_id, str) else tuple(camera_id)
        self._single_pass = single_pass
        self._interval_ms = interval_ms
        self._stop_flag = False
        self._task_name = 'preview_capture'
        self._must_finish = False

    def run(self):
        while not self._stop_flag:
            t0 = time.perf_counter()
            for camera_id in self._camera_ids:
                if self._stop_flag:
                    break
                try:
                    frame = self._camera_manager.capture_2d_preview(camera_id)
                    if self._stop_flag:
                        break
                    if frame is not None and frame.image_np is not None:
                        self.camera_frame_ready.emit(camera_id, frame)
                        if not self._single_pass:
                            # QImage has no GUI-thread ownership requirement.
                            from ui_common.image_canvas import load_image
                            self.frame_ready.emit(load_image(frame.image_np))
                except Exception as exc:
                    logger.warning(f"实时取景采集异常 ({camera_id}): {exc}")
            if self._single_pass:
                break
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.msleep(max(10, int(self._interval_ms - elapsed_ms)))

    def request_stop(self):
        """Signal cancellation without blocking the GUI thread."""
        self._stop_flag = True

    def stop(self):
        """Stop scheduling without blocking GUI; the owner retains and joins the thread."""
        self.request_stop()
