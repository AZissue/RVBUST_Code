# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 项目根目录
ROOT = os.path.dirname(os.path.abspath(SPEC))
RVC_RUNTIME = r"D:\Program Files\RVBUST\RVC\RVCSDK\runtime"

# 收集 PySide6 数据文件（插件、翻译等）
pyside6_datas = collect_data_files('PySide6')

# 收集 open3d 数据文件
open3d_datas = collect_data_files('open3d')

# 收集所有子模块
hidden_imports = []
hidden_imports += collect_submodules('PySide6')
hidden_imports += collect_submodules('open3d')
hidden_imports += collect_submodules('cv2')
hidden_imports += collect_submodules('numpy')
hidden_imports += collect_submodules('scipy')
hidden_imports += collect_submodules('OpenGL')

# RVC 运行时 DLL
rvc_binaries = []
if os.path.isdir(RVC_RUNTIME):
    for f in os.listdir(RVC_RUNTIME):
        if f.lower().endswith(('.dll', '.ax', '.ini')):
            rvc_binaries.append((os.path.join(RVC_RUNTIME, f), '.'))

a = Analysis(
    ['main.py'],
    pathex=[ROOT, os.path.join(ROOT, 'src')],
    binaries=rvc_binaries,
    datas=[
        ('assets/icons', 'assets/icons'),
    ] + pyside6_datas + open3d_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'pandas', 'tkinter', 'PyQt5', 'PyQt6',
        'IPython', 'jupyter', 'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MultiCameraCalibration',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台窗口（GUI 应用）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MultiCameraCalibration',
)
