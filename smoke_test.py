import sys
sys.path.insert(0, r'D:\RVC_SRC\Python\CodedCircleRegistration_v2')

print("[1] Importing modules...")
from src.ui.zoomable_label import ZoomableImageLabel
from src.ui.styles import STYLESHEET
from src.core.rvc_resource import safe_destroy
from src.core.camera_controller import RVCCameraController
from src.core.marker_detector import MarkerDetector
from src.core.stitch_engine import HAS_OPEN3D
from src.threads.preview_thread import PreviewThread
from src.threads.detection_worker import DetectionParamSearchWorker
from src.utils.ply_io import save_binary_ply
print("[2] All module imports OK")

print("[3] Testing ZoomableImageLabel instantiation...")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
zl = ZoomableImageLabel()
print("[4] ZoomableImageLabel OK")

print("[5] Testing RVCCameraController...")
cam = RVCCameraController()
ok, msg = cam.initialize()
print(f"[6] Camera init: {ok}, {msg}")

print("[7] Testing MarkerDetector...")
det = MarkerDetector()
print("[8] MarkerDetector OK")

print("[9] Cleaning up...")
cam.shutdown()
print("[10] Smoke test passed")
