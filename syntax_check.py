"""
Code syntax test script - Check Python files without running GUI
"""
import py_compile
import sys
from pathlib import Path

def check_syntax(file_path, desc):
    """Check Python file syntax"""
    try:
        py_compile.compile(file_path, doraise=True)
        print(f"[OK] {desc}: Syntax OK")
        return True
    except py_compile.PyCompileError as e:
        print(f"[FAIL] {desc}: Syntax Error - {e}")
        return False

print("=" * 50)
print("CodedCircleRegistration_v2 Syntax Check")
print("=" * 50)

base_path = Path(r"D:\RVC_SRC\Python\CodedCircleRegistration_v2\src")

files_to_check = [
    (base_path / "app.py", "Main app.py"),
    (base_path / "ui" / "loading_dialog.py", "LoadingDialog Component"),
    (base_path / "core" / "frame_data.py", "CaptureSession Class"),
    (base_path / "core" / "project_manager.py", "ProjectManager Class"),
    (base_path / "core" / "stitch_engine.py", "Stitch Engine"),
    (base_path / "core" / "camera_controller.py", "Camera Controller"),
    (base_path / "core" / "marker_detector.py", "Marker Detector"),
]

all_ok = True
for file_path, desc in files_to_check:
    if file_path.exists():
        if not check_syntax(str(file_path), desc):
            all_ok = False
    else:
        print(f"[WARN] {desc}: File not found - {file_path}")

print("=" * 50)
if all_ok:
    print("[PASS] All files passed syntax check!")
else:
    print("[FAIL] Syntax errors found, please fix")
print("=" * 50)
