"""Open distributed SDK examples as text, using the system editor."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMenu, QToolButton


EXAMPLES = (
    ('点云坐标转换', 'transform_cloud.py'),
    ('标记物识别与三维坐标提取', 'recognize_markers.py'),
    ('相机采集与图像／点云保存', 'capture_rvc.py'),
    ('固定外参、标记物与 FPFH 拼接', 'stitch.py'),
    ('Python SDK 使用说明', 'README.md'),
)


def example_path(filename):
    if getattr(sys, 'frozen', False):
        root = Path(sys.executable).resolve().parent.parent
        external = root / 'PythonSDK' / filename
        if external.is_file():
            return external
        return Path(sys._MEIPASS) / 'sdk_examples' / filename
    return Path(__file__).resolve().parents[2] / 'tools' / 'customer_trial' / filename


def open_example(shell, filename):
    path = example_path(filename)
    if not path.is_file():
        shell.log(f'SDK 示例文件缺失：{path}', 'error')
        return
    editor = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32' / 'notepad.exe'
    started, _ = QProcess.startDetached(str(editor), [str(path)])
    if not started:
        shell.log(f'无法启动记事本。示例文件位于 {path}', 'error')


def make_examples_button(shell):
    button = QToolButton()
    button.setText('SDK 源码')
    button.setProperty('headerAction', True)
    button.setToolTip('在记事本中查看 Python SDK 示例源码')
    menu = QMenu(button)
    for title, filename in EXAMPLES:
        action = menu.addAction(title)
        action.triggered.connect(lambda checked=False, name=filename: open_example(shell, name))
    button.setMenu(menu)
    button.setPopupMode(QToolButton.InstantPopup)
    return button
