"""Offline architecture/contract regressions for replaceable MCC presentations.

Run directly with the rvc Python. No SDK initialization, enumeration or camera I/O.
"""
from __future__ import annotations
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QObject, Signal, QEventLoop, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from ui_common.image_preview import AspectRatioLabel
from ui_common.point_cloud_viewer import EmbeddedPointCloudViewer
from ui_common.worker_thread import WorkerThread
from ui_common.appearance import ImagePreviewAppearance, ViewerAppearance
from ui_common import icons as file_icons, symbols
from ui_v2.composition import UiComposition, WorkspaceFactories
from ui_v2.components import UiComponents
from ui_v2.contracts import PointCloudView, ImagePreview
from ui_v2.bindings import MULTI_ACTIONS, MOBILE_ACTIONS, SHELL_ACTIONS, connect_actions
from ui_v2.workspaces import MultiCamWorkspace, MobileChainWorkspace, TurntableWorkspace


class UiArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        symbols.set_icon_provider(None)
        self.app.processEvents()

    def test_no_legacy_imports_in_production_or_common_layer(self):
        for folder in ("ui_v2", "ui_common"):
            for path in (ROOT / "src" / folder).rglob("*.py"):
                for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    names = ([n.module or ""] if isinstance(n, ast.ImportFrom) else
                             [a.name for a in n.names] if isinstance(n, ast.Import) else [])
                    for name in names:
                        self.assertNotIn(name.split(".")[0], ("ui",), str(path))
                        self.assertFalse(name.startswith("src.ui."), str(path))
                        if folder == "ui_common":
                            self.assertNotEqual(name.split(".")[0], "ui_v2", str(path))

    def test_production_imports_and_views_work_when_legacy_package_is_blocked(self):
        code = r"""
import importlib.abc, sys
sys.path.insert(0, sys.argv[1])
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'ui' or fullname.startswith('ui.'):
            raise ImportError('Legacy UI is forbidden: ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
from PySide6.QtWidgets import QApplication
app = QApplication([])
from ui_v2 import UiComposition
from ui_v2.backend_bridge import BackendBridge
composition = UiComposition()
composition.configure(app)
launcher = composition.create_launcher()
shell = composition.create_shell()
for mode in ('multi_cam', 'mobile_chain', 'turntable'):
    shell.set_mode(mode, [])
assert not any(n == 'ui' or n.startswith('ui.') for n in sys.modules)
print('NO_LEGACY_RUNTIME_IMPORTS')
"""
        result = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT / "src")],
                                capture_output=True, text=True, encoding="utf-8", timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NO_LEGACY_RUNTIME_IMPORTS", result.stdout)

    def test_legacy_source_package_is_removed(self):
        self.assertFalse((ROOT / 'src' / 'ui').exists())

    def test_repository_has_no_legacy_imports(self):
        for path in [ROOT / 'main.py', *ROOT.glob('test_*.py'),
                     *(ROOT / 'src').rglob('*.py'), *(ROOT / 'tools').rglob('*.py'),
                     *(ROOT / 'prototypes').rglob('*.py')]:
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                names = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                         [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                for name in names:
                    self.assertFalse(name == 'ui' or name.startswith('ui.') or
                                     name == 'src.ui' or name.startswith('src.ui.'), str(path))

    def test_default_components_honor_public_ports(self):
        preview = UiComponents().create_preview()
        panel = UiComponents().create_viewer()
        self.assertIsInstance(preview, ImagePreview)
        self.assertIsInstance(panel.viewer(), PointCloudView)
        panel.set_pointcloud("cam0", None)
        panel.set_reference("cam0")
        panel.clear_highlight()
        panel.clear_all()
        panel.deleteLater()
        preview.deleteLater()

    def test_renderer_can_be_replaced_without_inheriting_existing_viewer(self):
        class NewRenderer(QWidget):
            status_changed = Signal(str)
            collapse_toggled = Signal(bool)
            maximize_toggled = Signal(bool)

        renderer = NewRenderer()
        for name in PointCloudView.__annotations__:
            self.assertTrue(hasattr(renderer, name))
        for name, value in PointCloudView.__dict__.items():
            if not name.startswith('_') and callable(value):
                setattr(renderer, name, Mock())
        panel = UiComponents(point_cloud_view_factory=lambda **kw: renderer).create_viewer()
        data = object()
        panel.set_pointcloud_merged(data)
        renderer.set_pointcloud_merged.assert_called_once_with(data)
        messages = []
        panel.viewer_message.connect(messages.append)
        renderer.status_changed.emit('new renderer')
        self.assertEqual(messages, ['new renderer'])
        panel.deleteLater()

    def test_v2_bridge_restores_offline_frames_without_sdk_or_legacy_window(self):
        import numpy as np
        from core.frame_data import FrameData
        from core.camera_manager import CameraManager
        from ui_v2.backend_bridge import BackendBridge
        win = UiComposition().create_shell()
        with patch.object(CameraManager, 'initialize', return_value=(False, 'offline test')):
            bridge = BackendBridge(win)
        try:
            bridge.wire_all()
            frames = {cid: [FrameData(frame_id=1, camera_name=cid,
                                      image_np=np.zeros((16, 16, 3), dtype=np.uint8),
                                      is_offline=True)] for cid in ('cam0', 'cam1')}
            bridge._load_fixed_session(SimpleNamespace(get_meta=lambda key: None), frames)
            ws = win.workspace_multi()
            self.assertEqual(ws.current_state(), 'captured')
            self.assertEqual(bridge.fixed_workflow.reference_id, 'cam0')
            for cid in frames:
                self.assertIsNotNone(ws.camera_grid().card(cid))
            self.assertFalse(any(n == 'ui' or n.startswith('ui.') for n in sys.modules))
        finally:
            bridge.cleanup()
            win.deleteLater()

    def test_component_replacement_reaches_all_four_workspaces(self):
        previews, renderers = [], []
        class NewPreview(AspectRatioLabel):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                previews.append(self)
        class NewRenderer(EmbeddedPointCloudViewer):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                renderers.append(self)
        components = UiComponents(NewPreview, NewRenderer)
        win = UiComposition(components=components).create_shell()
        win.workspace_multi().reset_camera_grid(["cam0", "cam1"])
        self.assertEqual(len(renderers), 4)
        self.assertEqual(len(previews), 5)  # B + C + robot + two A camera cards
        marker = object()
        for renderer in renderers:
            recorder = Mock()
            renderer.set_pointcloud_merged = recorder
        win.workspace_multi().viewer().set_pointcloud_merged(marker)
        win.workspace_mobile().viewer().set_pointcloud_merged(marker)
        win.workspace_turntable().viewer.set_pointcloud_merged(marker)
        win.workspace_robot().viewer().set_pointcloud_merged(marker)
        for renderer in renderers:
            renderer.set_pointcloud_merged.assert_called_once_with(marker)
        win.deleteLater()

    def test_new_workspace_layout_keeps_controller_bindings_once(self):
        from ui_v2.backend_bridge import BackendBridge
        class ReworkedMulti(MultiCamWorkspace): pass
        class ReworkedMobile(MobileChainWorkspace): pass
        class ReworkedTurntable(TurntableWorkspace): pass
        composition = UiComposition(workspaces=WorkspaceFactories(
            ReworkedMulti, ReworkedMobile, ReworkedTurntable))
        win = composition.create_shell()
        self.assertIsInstance(win.workspace_mobile(), ReworkedMobile)
        # Initialize QObject only: wiring never needs to initialize the SDK.
        bridge = BackendBridge.__new__(BackendBridge)
        QObject.__init__(bridge)
        bridge.shell = win
        bridge._on_device_manager_reopened = Mock()
        bridge._run_background = Mock()
        groups = [(win.workspace_multi(), MULTI_ACTIONS),
                  (win.workspace_mobile(), MOBILE_ACTIONS), (win, SHELL_ACTIONS)]
        for view, actions in groups:
            for signal_name, handler in actions:
                setattr(bridge, handler, Mock())
        bridge.wire_all()
        bridge.wire_all()
        args = {"capture_requested": (True,), "detect_requested": ("coded_circle",),
                "batch_scan_requested": (2,), "reference_changed": ("cam0",),
                "step_back_requested": (0,), "card_preview_toggled": ("cam0", True),
                "card_capture_requested": ("cam0",), "card_detect_requested": ("cam0",),
                "preview_toggled": (True,), "recapture_requested": (1,),
                "delete_station_requested": (1,), "station_selected": (1,)}
        for view, actions in groups:
            for signal_name, handler in actions:
                values = args.get(signal_name, ())
                getattr(view, signal_name).emit(*values)
                getattr(bridge, handler).assert_called_once_with(*values)
        self.assertIs(win.workspace_turntable()._background_runner, bridge._run_background)
        win.deleteLater()

    def test_incomplete_view_rejected_before_partial_connection(self):
        class View(QObject):
            good = Signal()
        view = View()
        recorder = Mock()
        with self.assertRaisesRegex(TypeError, "missing"):
            connect_actions(view, SimpleNamespace(handle=recorder),
                            (("good", "handle"), ("missing", "handle")))
        view.good.emit()
        recorder.assert_not_called()

    def test_preview_control_port_emits_user_intent_without_button_access(self):
        view = MobileChainWorkspace()
        received = []
        view.preview_toggled.connect(received.append)
        view.set_preview_enabled(True)
        view.set_preview_enabled(True)
        view.set_preview_enabled(False)
        self.assertFalse(view.is_preview_enabled())
        self.assertEqual(received, [True, False])
        view.deleteLater()

    def test_skin_changes_common_preview_and_renderer_chrome(self):
        components = UiComponents(
            partial(AspectRatioLabel, appearance=ImagePreviewAppearance(background="#102030")),
            partial(EmbeddedPointCloudViewer, appearance=ViewerAppearance(accent="#abcdef")))
        preview = components.create_preview()
        panel = components.create_viewer()
        self.assertIn("#102030", preview.styleSheet())
        toolbars = [w for w in panel.findChildren(QWidget) if "#abcdef" in w.styleSheet()]
        self.assertTrue(toolbars)
        preview.deleteLater()
        panel.deleteLater()

    def test_icon_pack_changes_both_v2_and_shared_viewer_and_resets_cache(self):
        def pack(name, color, size):
            if name not in ("camera", "view_axes"):
                return None
            pm = QPixmap(size, size)
            pm.fill(QColor("#ff00ff"))
            return pm
        symbols.set_icon_provider(pack)
        self.assertEqual(symbols.pixmap("camera").toImage().pixelColor(0, 0).name(), "#ff00ff")
        self.assertEqual(file_icons.get_icon("view_axes").pixmap(16,16).toImage().pixelColor(0,0).name(), "#ff00ff")
        self.assertFalse(symbols.pixmap("save").isNull())  # partial-pack fallback
        symbols.set_icon_provider(None)
        self.assertNotEqual(symbols.pixmap("camera").toImage().pixelColor(0,0).name(), "#ff00ff")

    def test_directory_icon_pack_has_fallback_and_filename_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            pm = QPixmap(16,16); pm.fill(QColor("#12ab34"))
            self.assertTrue(pm.save(str(Path(directory)/"capture.png")))
            provider = symbols.DirectoryIconProvider(directory, {"camera":"capture.png"})
            symbols.set_icon_provider(provider)
            self.assertEqual(symbols.pixmap("camera").toImage().pixelColor(0,0).name(), "#12ab34")
            self.assertFalse(symbols.pixmap("save").isNull())
            with self.assertRaises(ValueError):
                provider("../outside", "#fff", 16)

    def test_launcher_factory_is_reused_for_device_manager(self):
        from ui_v2.launcher_dialog import LauncherDialog
        from PySide6.QtWidgets import QDialog
        parents = []
        class RedesignedLauncher(LauncherDialog):
            def __init__(self, parent=None):
                parents.append(parent)
                super().__init__(parent)
            def exec(self):
                return QDialog.Rejected
        composition = UiComposition(launcher_factory=RedesignedLauncher)
        launcher = composition.create_launcher()
        win = composition.create_shell()
        win.open_device_manager()
        self.assertEqual(parents, [None, win])
        launcher.deleteLater()
        win.deleteLater()

    def test_incomplete_renderers_and_previews_fail_at_factory_boundary(self):
        from PySide6.QtWidgets import QLabel
        with self.assertRaisesRegex(TypeError, "ImagePreview"):
            UiComponents(image_preview_factory=lambda **kw: QLabel()).create_preview()
        with self.assertRaisesRegex(TypeError, "PointCloudView"):
            UiComponents(point_cloud_view_factory=lambda **kw: QLabel()).create_viewer()

    def test_worker_result_and_thread_exit_remain_distinct(self):
        # The actual QThread result delivery/lifetime contract is preserved.
        for func, expected, error in ((lambda: 7, 7, None),
                                      (lambda: (_ for _ in ()).throw(ValueError("fail")), None, ValueError)):
            worker = WorkerThread(func)
            results = []
            loop = QEventLoop()
            worker.result_ready.connect(lambda result, exc: results.append((result, exc)))
            worker.finished.connect(loop.quit)
            timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit)
            timer.start(3000); worker.start(); loop.exec(); worker.wait(3000)
            self.assertFalse(worker.isRunning())
            self.assertEqual(len(results),1)
            self.assertEqual(results[0][0], expected)
            if error:
                self.assertIsInstance(results[0][1],error)
            else:
                self.assertIsNone(results[0][1])
            worker.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
