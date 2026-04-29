import sys
sys.path.insert(0, r'D:\RVC_SRC\Python\CodedCircleRegistration_v2')

print("[A] Creating QApplication...")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
app = QApplication.instance() or QApplication(sys.argv)
print("[B] QApplication OK")

print("[C] Importing MainWindow...")
from src.app import MainWindow
print("[D] MainWindow import OK")

print("[E] Instantiating MainWindow (no show/exec)...")
win = MainWindow()
print("[F] MainWindow instantiated OK")

# Check some internal state
print(f"[G] Camera connected? {win.camera.is_connected}")
print(f"[H] Detector enabled? {win.detector.enabled}")
print(f"[I] Has Open3D? {__import__('src.core.stitch_engine', fromlist=['HAS_OPEN3D']).HAS_OPEN3D}")

print("[J] All smoke tests passed. If GUI crashes, it's likely after app.exec() / display related.")
