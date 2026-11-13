"""Shared launcher for standalone MCC prototypes using the industrial UI."""
import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox

from core.session_project import SessionProject
from ui_v2.backend_bridge import BackendBridge
from ui_v2.composition import UiComposition
from ui_v2.main_window import MainWindowShell


def load_session(path, mode=None):
    path = Path(path)
    if path.is_file() and path.name == 'session.json':
        path = path.parent
    if mode is None:
        mode = json.loads((path / 'session.json').read_text(encoding='utf-8'))['mode']
    project, workflow = SessionProject.load(path, mode)
    project.saved_path = None
    project.uid = uuid4().hex
    return project, workflow


class OfflineBridge(BackendBridge):
    def _ensure_sdk(self):
        self.shell.log('原型工作区仅加载离线数据。', 'warn')
        return False


class OfflineWorkspace(MainWindowShell):
    def __init__(self, project, workflow, *, key, title, editor_type=None, output=None):
        super().__init__()
        self._editor_type = editor_type
        self._offline_preview = True
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        bridge = OfflineBridge(self)
        self.set_backend_bridge(bridge)
        try:
            self._configure(bridge, project, workflow, key, title, output)
        except Exception:
            bridge.cleanup()
            self.deleteLater()
            raise

    def _configure(self, bridge, project, workflow, key, title, output):
        bridge.wire_all()
        bridge.offline_preview = True
        bridge.recognition.enabled = False
        bridge.validation_root = Path(output).resolve() if output else ROOT / 'outputs' / 'experiments' / key
        for draft in bridge.projects.projects.values():
            draft.save_root = bridge.validation_root
        mode = project.mode
        prepared = bridge.projects.prepare_loaded(project, workflow)
        previous = bridge.projects.projects[mode]
        bridge.projects.install(mode, project)
        previous.dispose()
        bridge._current_mode = mode
        bridge.projects.loading.add(mode)
        try:
            self.set_mode(mode, [])
            self.set_presentation('industrial')
            bridge.projects.apply_loaded(mode, workflow, prepared)
            bridge.projects.prepare(mode)
        finally:
            bridge.projects.loading.discard(mode)
        bridge.projects.update(mode)
        self.setWindowTitle(f'MCC · {title} · {project.name}')
        banner = QLabel(f'{title} · 离线会话 · 保存目录 {bridge.validation_root}')
        banner.setTextFormat(Qt.PlainText)
        banner.setWordWrap(True)
        banner.setStyleSheet('background:#573d20;color:#ffe1a6;padding:8px;')
        self.centralWidget().layout().insertWidget(0, banner)
        ribbon = self._industrial_ribbon
        ribbon.offline_button.hide()
        self._btn_devices.hide()
        unavailable = ['select', 'devices', 'disconnect', 'parameters', 'manage', 'recapture']
        if mode != 'robot_stitch':
            unavailable += ['capture', 'preview', 'scan_preview', 'scan', 'batch', 'frame0', 'frame1', 'auto']
        for action in unavailable:
            button = ribbon.commands.get((mode, action))
            if button is not None:
                button.hide()
        self.resize(1440, 900)

    def open_device_manager(self):
        self.log('原型工作区仅加载离线数据。', 'info')

    def open_param_debug(self):
        self.log('原型工作区仅加载离线数据。', 'info')

    def postprocess_editor_type(self):
        return self._editor_type or super().postprocess_editor_type()

    def closeEvent(self, event):
        bridge = self._backend_bridge
        editor = getattr(bridge, '_postprocess_window', None)
        if editor is not None and not editor._closed and not editor.close():
            event.ignore()
            return
        super().closeEvent(event)
        if event.isAccepted():
            bridge.cleanup()


def launch(*, key, title, mode=None, editor_type=None):
    parser = argparse.ArgumentParser(description=title)
    parser.add_argument('--session', type=Path, help='已保存的 MCC 会话目录或 session.json')
    parser.add_argument('--output', type=Path, help='实验会话保存目录')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('MultiCameraCalibration')
    UiComposition().configure(app)
    path = args.session
    if path is None:
        selected, _ = QFileDialog.getOpenFileName(
            None, '选择 MCC 离线会话', str(ROOT / 'sessions'), 'MCC 会话 (session.json)')
        if not selected:
            return 0
        path = Path(selected)
    project = None
    try:
        project, workflow = load_session(path, mode)
        window = OfflineWorkspace(project, workflow, key=key, title=title, editor_type=editor_type,
                                  output=args.output)
    except Exception as exc:
        if project is not None:
            project.dispose()
        print(f'打开离线会话失败：{exc}', file=sys.stderr)
        if args.session is None:
            QMessageBox.critical(None, '打开离线会话失败', str(exc))
        return 1
    window.show()
    if editor_type is not None:
        window._backend_bridge.open_postprocess(auto_intermediates=False)
    return app.exec()
