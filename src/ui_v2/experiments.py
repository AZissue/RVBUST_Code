"""Integrated validation sessions using production UI, workflows and task delivery."""
import copy
import shutil
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from core.session_project import SessionProject, PROJECT_ROOT

OUTPUT = PROJECT_ROOT / 'outputs' / 'experiments'
FEATURES = (
    ('color', '颜色统一 / 原色对比 / 原始2D融合', None),
    ('fpfh', 'FPFH + 几何特征匹配 / 参数调试', None),
    ('geometry', '几何后处理 / 框选 / 下采样 / ICP', None),
    ('circle_triangle', '普通圆点识别 / 三角形几何匹配拼接', None),
    ('multi_cam', '固定多相机外参及拼接', 'multi_cam'),
    ('robot_stitch', '机器人手眼变换与戳点验证', 'robot_stitch'),
)


def clone_project(source):
    """Copy live data, including unsaved results, without saving the source."""
    project = SessionProject(source.mode, source.name + '_实验副本', OUTPUT)
    try:
        with source.database._lock:
            if source.database.directory.exists():
                shutil.copytree(source.database.directory, project.database.directory)
            db = project.database
            db.records = copy.deepcopy(source.database.records)
            db.removed = copy.deepcopy(source.database.removed)
            db.sessions = copy.deepcopy(source.database.sessions)
            db.session_id = source.database.session_id
            db._save_index()
        return project
    except Exception:
        project.dispose()
        raise


class ExperimentHub(QDialog):
    def __init__(self, bridge):
        super().__init__(bridge.shell)
        self.bridge = bridge
        self.setWindowTitle('MCC · 实验功能')
        self.setWindowModality(Qt.WindowModal)
        self.resize(580, 390)
        layout = QVBoxLayout(self)
        text = QLabel('使用正式工作区和操作流程，读取当前内存中的数据副本（包含未保存结果）。\n'
            '颜色及几何处理复制当前模式；其他功能复制对应模式。\n'
            '验证副本仅手动保存到 outputs/experiments；不会覆盖源会话。\n'
            '本版为离线验证，不连接设备；实机采集请使用主工作区。')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.buttons = {}
        for key, title, mode in FEATURES:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, k=key, m=mode: self.launch(k, m))
            self.buttons[key] = button
            layout.addWidget(button)
        self.status = QLabel('颜色效果、真实精度与大数据性能需要人工验收。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._preparing = False

    def closeEvent(self, event):
        if self._preparing:
            event.ignore()
        else:
            super().closeEvent(event)

    def launch(self, feature, mode=None):
        if self._preparing or not self.bridge.can_change_workspace():
            return
        previous = getattr(self.bridge, '_validation_shell', None)
        if previous is not None:
            previous.raise_()
            previous.activateWindow()
            return
        mode = mode or self.bridge.shell.current_mode()
        # Capture workflow metadata on the UI thread; disk copy runs in background.
        try:
            workflow = copy.deepcopy(self.bridge.projects.describe(mode, True))
        except Exception as exc:
            self.status.setText('读取当前工作流失败：' + str(exc))
            return
        source = self.bridge.projects.projects[mode]
        browser = self.bridge.frame_db.browsers.get(mode)
        ids = ([uid for uid, _ in browser.checked_components('cloud')] or browser.selected_ids()) if browser else []
        self._preparing = True
        for button in self.buttons.values():
            button.setEnabled(False)
        self.status.setText('正在创建验证副本，请稍候…')
        def done(project, error):
            self._preparing = False
            for button in self.buttons.values():
                button.setEnabled(True)
            if error:
                self.status.setText('创建失败：' + str(error))
                return
            try:
                shell = open_validation(self.bridge, project, workflow, feature, ids)
            except Exception as exc:
                project.dispose()
                self.status.setText('打开失败：' + str(exc))
                return
            self.bridge._validation_shell = shell
            self.hide()
        self.bridge._run_background(lambda: clone_project(source), done,
                                    must_finish=True, name='project_experiment_copy')


def open_validation(owner, project, workflow, feature, identifiers):
    from .main_window import MainWindowShell
    from .backend_bridge import BackendBridge
    from .postprocess.window import PostprocessWindow

    class ValidationShell(MainWindowShell):
        def open_device_manager(self):
            self.log('验证副本只做离线操作；请返回主工作区连接设备。', 'warn')

        def open_param_debug(self):
            self.log('验证副本不连接设备。', 'warn')

        def closeEvent(self, event):
            editor = getattr(self._backend_bridge, '_postprocess_window', None)
            if editor is not None and not editor._closed:
                editor.close()
                if not editor._closed:
                    event.ignore()
                    return
            super().closeEvent(event)
            if event.isAccepted():
                if self._backend_bridge is not None:
                    self._backend_bridge.cleanup()
                owner._validation_shell = None

    shell = ValidationShell(owner.shell)
    shell.setWindowFlags(Qt.Window)
    shell.setWindowModality(Qt.WindowModal)
    shell.setAttribute(Qt.WA_DeleteOnClose, True)
    bridge = None
    try:
        bridge = BackendBridge(shell)
        bridge.wire_all()
        bridge.validation_color = feature == 'color'
        bridge.validation_root = OUTPUT
        bridge.offline_preview = True
        shell._offline_preview = True
        bridge.recognition.enabled = False
        shell.set_backend_bridge(bridge)
        for item in bridge.projects.projects.values():
            item.save_root = OUTPUT
        empty_robot = project.mode == 'robot_stitch' and not workflow.get('handeye')
        prepared = None if empty_robot else bridge.projects.prepare_loaded(project, workflow)
        old = bridge.projects.projects[project.mode]
        bridge.projects.install(project.mode, project)
        old.dispose()
        bridge._current_mode = project.mode
        shell.set_mode(project.mode, [])
        shell.set_presentation('industrial')
        if not empty_robot:
            bridge.projects.apply_loaded(project.mode, workflow, prepared)
        # Every presentation refresh retains the visible validation identity.
        shell.setWindowTitle('MCC · 实验验证副本 · ' + project.name)
        from PySide6.QtWidgets import QLabel
        banner = QLabel('实验验证副本 · 离线 · 保存到 outputs/experiments · 源会话不变')
        banner.setStyleSheet('background:#573d20;color:#ffe1a6;padding:8px;')
        shell.centralWidget().layout().insertWidget(0, banner)
        shell.show()
        if feature in ('color', 'geometry', 'circle_triangle', 'fpfh'):
            class ValidationEditor(PostprocessWindow):
                COLOR_VALIDATION = feature == 'color'
            if feature == 'fpfh':
                from prototypes.fpfh_geometry_match.editor import FPFHEditor
                ValidationEditor = FPFHEditor
            editor = ValidationEditor(bridge, project.mode)
            bridge._postprocess_window = editor
            editor.setWindowTitle('MCC · 实验副本后处理 · ' + project.name)
            editor.show()
            ids = [uid for uid in identifiers if uid in project.database.records]
            if not ids:
                ids = [row.uid for row in project.database.records.values()
                       if row.kind == 'result' and not row.intermediate_of][-1:]
            if feature == 'circle_triangle':
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, editor.open_circle_match)
            elif ids:
                editor.load_selected(ids, auto_intermediates=True)
        shell.log('验证副本已打开；关闭后返回原工作区。需要保留结果时请点击保存会话。', 'info')
        return shell
    except Exception:
        if bridge is not None:
            bridge.cleanup()
        shell._backend_bridge = None
        shell._dirty = False
        shell.close()
        shell.deleteLater()
        raise
