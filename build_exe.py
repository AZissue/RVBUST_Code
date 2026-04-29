#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for CodedCircleRegistration_v2
使用 PyInstaller 打包为可执行程序

用法:
    python build_exe.py
"""

import os
import sys
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.resolve()
SRC_DIR = PROJECT_ROOT / "src"
OUTPUT_DIR = Path(r"D:\RVC_SRC\Releases\CodedCircleRegistration_v2")
ENTRY_SCRIPT = SRC_DIR / "main.py"

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 构建临时 spec（可直接用命令行）
PYINSTALLER = Path(r"D:\Program Files\Anaconda\envs\rvc\Scripts\pyinstaller.exe")
PYTHON = Path(r"D:\Program Files\Anaconda\envs\rvc\python.exe")

# ---------------------------------------------------------------------------
# 收集需要打包的隐藏模块和路径
# ---------------------------------------------------------------------------
hidden_imports = [
    "src.core.camera_controller",
    "src.core.frame_data",
    "src.core.marker_detector",
    "src.core.rvc_resource",
    "src.core.project_manager",
    "src.core.stitch_engine",
    "src.threads.detection_worker",
    "src.threads.preview_thread",
    "src.ui.styles",
    "src.ui.zoomable_label",
    "src.ui.overlay_loading",
    "src.utils.logging_config",
    "src.utils.ply_io",
    "PyRVC",
    "cv2",
    "numpy",
    "scipy",
    "open3d",
    "pycairo",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]

# 收集 src 下所有 .py 作为 hidden import
for py_file in SRC_DIR.rglob("*.py"):
    rel = py_file.relative_to(PROJECT_ROOT)
    module = str(rel.with_suffix("")).replace(os.sep, ".")
    if module not in hidden_imports:
        hidden_imports.append(module)

hidden_str = " ".join(f'--hidden-import "{m}"' for m in hidden_imports)

# 收集数据文件（配置文件、样式等）
data_files = []
# config 目录
config_dir = PROJECT_ROOT / "config"
if config_dir.exists():
    data_files.append(f'--add-data "{config_dir};config"')

# ---------------------------------------------------------------------------
# 构建命令
# ---------------------------------------------------------------------------
cmd_parts = [
    str(PYINSTALLER),
    "--noconfirm",
    "--onedir",                    # 单目录模式，启动快，便于更新
    f'--distpath "{OUTPUT_DIR}"',
    f'--workpath "{OUTPUT_DIR / "build"}"',
    f'--specpath "{OUTPUT_DIR}"',
    f'--name "CodedCircleRegistration"',
    "--windowed",                  # 无控制台窗口
    hidden_str,
    " ".join(data_files),
    f'"{ENTRY_SCRIPT}"',
]

cmd = " ".join(cmd_parts)

print("=" * 70)
print("  PyInstaller Build Script")
print("=" * 70)
print(f"项目目录: {PROJECT_ROOT}")
print(f"入口脚本: {ENTRY_SCRIPT}")
print(f"输出目录: {OUTPUT_DIR}")
print(f"隐藏导入: {len(hidden_imports)} 个模块")
print()
print("构建命令:")
print(cmd)
print()
print("开始构建...")
print("=" * 70)

# 执行构建
os.system(cmd)

# ---------------------------------------------------------------------------
# 构建后处理
# ---------------------------------------------------------------------------
exe_dir = OUTPUT_DIR / "CodedCircleRegistration"
if exe_dir.exists():
    # 复制 README
    readme_src = PROJECT_ROOT / "README.md"
    if readme_src.exists():
        shutil.copy(readme_src, exe_dir / "README.md")
    
    # 创建快捷启动批处理（用于调试时带控制台输出）
    bat_path = exe_dir / "调试启动.bat"
    bat_path.write_text(
        "@echo off\n"
        "echo CodedCircleRegistration_v2\n"
        "echo 如有问题，查看此窗口输出...\n"
        "cd /d \"%~dp0\"\n"
        "CodedCircleRegistration.exe\n"
        "pause\n",
        encoding="utf-8"
    )
    
    print()
    print("=" * 70)
    print("  构建完成!")
    print(f"  程序目录: {exe_dir}")
    print(f"  可执行文件: {exe_dir / 'CodedCircleRegistration.exe'}")
    print(f"  调试启动: {bat_path}")
    print("=" * 70)
else:
    print("\n[ERROR] 构建失败，未找到输出目录")
    sys.exit(1)
