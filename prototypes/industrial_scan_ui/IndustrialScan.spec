# Build on the target OS/architecture; no private interpreter or SDK path.
from pathlib import Path
import sys
root = Path(SPECPATH).resolve()
repo = root.parents[1]
a = Analysis(
    [str(root / 'run.py')],
    pathex=[str(repo / 'src'), str(root.parent)],
    binaries=[], datas=[],
    hiddenimports=['industrial_scan_ui.app.gpu_canvas', 'OpenGL.platform.win32',
                   'OpenGL.arrays.numpymodule', 'OpenGL.GL.shaders'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['ui', 'PyQt5', 'PyQt6', 'torch', 'tensorflow', 'IPython', 'jupyter'],
    noarchive=False,
)
# Qt's Windows build imports the OS ICU API (unversioned symbols). A developer
# PATH can contain a different icuuc.dll with version-suffixed exports, which
# PyInstaller may accidentally collect. Do not shadow the Windows system DLL.
if sys.platform == 'win32':
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() != 'icuuc.dll']
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MCC-Scan-Prototype',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MCC-Scan-Prototype')
