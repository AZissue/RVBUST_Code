"""Independent colour validation workspace. Never initializes camera SDK."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from ui_v2.postprocess.window import PostprocessWindow

class ColorValidationWindow(PostprocessWindow):
    COLOR_VALIDATION = True


def main():
    import argparse
    import json
    from PySide6.QtWidgets import QApplication, QPushButton
    from ui_v2 import MainWindowShell
    from ui_v2.backend_bridge import BackendBridge
    from core.session_project import SessionProject
    parser = argparse.ArgumentParser(description='颜色统一/原色对比/2D颜色融合原型验证')
    parser.add_argument('--session',type=Path,help='可选：已保存MCC会话目录（读取私有副本）')
    parser.add_argument('--output',type=Path,default=ROOT/'outputs'/'color_validation',help='验证副本保存目录')
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    shell = MainWindowShell()
    bridge = BackendBridge(shell); bridge.wire_all(); shell.set_backend_bridge(bridge)
    bridge.offline_preview = True; bridge.recognition.enabled = False
    workflow = {}
    mode = 'mobile_chain'
    if args.session:
        manifest = json.loads((args.session/'session.json').read_text(encoding='utf-8'))
        mode = manifest['mode']
        project, workflow = SessionProject.load(args.session,mode,args.output)
        project.saved_path = None  # Validation must never overwrite the source session.
        project.save_root = args.output.resolve()
        project.name += '_颜色验证'
        bridge.projects.install(mode,project)
    else:
        project = bridge.projects.projects[mode]
        project.save_root = args.output.resolve()
    shell.set_mode(mode,[]); shell.set_presentation('industrial'); bridge._current_mode = mode
    window = ColorValidationWindow(bridge,mode)
    window.setWindowTitle('MCC · 颜色功能原型验证（独立副本）')
    save = QPushButton('保存验证副本')
    def save_copy():
        if not window._parameter_gate(): return
        def work(): return project.save(workflow)
        window._run(work,lambda path:window._set_status('验证副本已保存：'+str(path)),kind='export')
    save.clicked.connect(save_copy)
    window.operation_bar.layout().insertWidget(0,save)
    window.destroyed.connect(app.quit)
    window.show()
    app.aboutToQuit.connect(bridge.cleanup)
    return app.exec()

if __name__ == '__main__':
    raise SystemExit(main())
