"""Formal offline import, ownership, persistence and close gates; no devices."""
import tempfile,time,threading
from pathlib import Path
from unittest.mock import patch
import unittest
import cv2
import numpy as np
import test_ui_frame_database as fixture
from test_frame_database import PLY
from core.offline_pairs import collect_frame_pairs,OfflinePairLoader
from core.session_project import DEFAULT_SESSIONS,SessionProject
from core.camera_manager import CameraManager
from ui_v2.launcher_dialog import LauncherDialog

class OfflineTests(unittest.TestCase):
    setUpClass=classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp=fixture.FrameBrowserTests.setUp
    tearDown=fixture.FrameBrowserTests.tearDown
    wait=fixture.FrameBrowserTests.wait
    def open(self):
        with patch.object(CameraManager,'initialize',side_effect=AssertionError('SDK forbidden')):
            window=self.win.open_offline_stitch()
        self.addCleanup(self.dispose,window)
        return window
    def dispose(self,window):
        from shiboken6 import isValid
        if isValid(window):
            bridge=window._backend_bridge
            self.wait(lambda: not bridge._workers)
            for p in bridge.projects.projects.values():p.dirty=False
            window.close()
    def pair(self,root,name='1',shape=(2,2)):
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        (root/(name+'.ply')).write_bytes(PLY)
        cv2.imwrite(str(root/(name+'.png')),np.zeros((*shape,3),np.uint8))
    def test_formal_entrance_and_no_prototype_runtime_dependency(self):
        window=self.open();b=window._backend_bridge
        self.assertIsNone(getattr(b,'validation_root',None))
        log=window._log_panel.toPlainText()
        self.assertIn('已进入「离线拼接」工作区（本地文件 · mm）',log)
        self.assertNotIn('已进入「单相机移动拼接」',log)
        window.set_presentation('industrial')
        self.assertIn('离线拼接',window.windowTitle())
        self.assertEqual(window._st_mode.text(),'离线拼接')
        self.assertEqual(self.win.workspace_name('mobile_chain'),'单相机移动拼接')
        self.assertEqual(b.projects.projects['mobile_chain'].save_root,DEFAULT_SESSIONS)
        self.assertTrue(window._industrial_ribbon.offline_button.isHidden())
        window._industrial_ribbon.update_status()
        self.assertEqual(window._industrial_ribbon.mode_label.text(),'离线拼接')
        self.assertEqual(window._industrial_ribbon.badge.text(),'本地文件 · mm')
        window.resize(1050,650);self.app.processEvents()
        Path('outputs/offline_promotion').mkdir(exist_ok=True)
        window.grab().save('outputs/offline_promotion/formal_1050.png')
        self.assertLessEqual(window.width(),1050)
        self.assertNotIn('mobile_chain',[key for key,_,_ in __import__('ui_v2.experiments',fromlist=['FEATURES']).FEATURES])
        dialog=LauncherDialog();calls=[]
        dialog.offline_stitch_requested.connect(lambda:calls.append(1))
        dialog._btn_offline_stitch.click();self.assertEqual(calls,[1])
        dialog.set_busy(True);self.assertFalse(dialog._btn_offline_stitch.isEnabled())
        dialog.close();dialog.deleteLater()
        for module in ('src/core/offline_pairs.py','src/ui_v2/offline_stitch.py'):
            self.assertNotIn('prototypes',Path(module).read_text(encoding='utf-8'))
    def test_import_partial_failure_save_reload_and_source_ownership(self):
        window=self.open();bridge=window._backend_bridge;db=bridge.frame_db.databases['mobile_chain']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.pair(root,'2');self.pair(root,'10');self.pair(root,'bad',(1,1))
            originals={p.name:p.read_bytes() for p in root.iterdir()}
            window.load_directory(root);self.wait(lambda:not bridge._workers)
            self.assertEqual([r.logical_name for r in db.records.values()],['2','10'])
            self.assertTrue(bridge.projects.projects['mobile_chain'].dirty)
            for p in root.iterdir():self.assertEqual(p.read_bytes(),originals[p.name])
            project=bridge.projects.projects['mobile_chain'];project.save_root=root/'saved'
            saved=project.save(bridge.projects.describe('mobile_chain',True))
            for p in list(root.glob('*.ply'))+list(root.glob('*.png')):p.unlink()
            loaded,metadata=SessionProject.load(saved,'mobile_chain')
            try:
                self.assertEqual(len(loaded.database.records),2)
                frame,cloud=loaded.database.load_frame(next(iter(loaded.database.records)))
                self.assertEqual(frame.image_np.shape,(2,2,3));self.assertEqual(len(cloud.points),4)
            finally:loaded.dispose()
            bridge.projects.open(saved,'mobile_chain');self.wait(lambda:not bridge._workers)
            self.assertEqual(len(bridge.frame_db.databases['mobile_chain'].records),2)
            self.assertIsNone(getattr(bridge,'validation_root',None))
    def test_pair_order_ambiguity_alignment_and_recursion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('10','2','1'):self.pair(root,name)
            self.pair(root/'nested')
            self.assertEqual([p.name for p in collect_frame_pairs(root,False)],['1','2','10'])
            self.assertEqual(len(collect_frame_pairs(root)),4)
            cv2.imwrite(str(root/'1.jpg'),np.zeros((2,2,3),np.uint8))
            with self.assertRaisesRegex(ValueError,'歧义'):collect_frame_pairs(root)
            (root/'1.jpg').unlink();self.pair(root,'1',(1,1))
            with self.assertRaisesRegex(ValueError,'分辨率'):OfflinePairLoader().load_pair(collect_frame_pairs(root)[0])
    def test_direct_startup_without_sdk_and_process_exits_on_close(self):
        import subprocess,sys
        code = """
import sys
sys.path.insert(0,'src')
sys.argv=['main.py','--offline-stitch']
import main
from PySide6.QtCore import QTimer
from unittest.mock import patch
from core.camera_manager import CameraManager
from ui_v2.composition import UiComposition
seen=[]
class Composition(UiComposition):
    def configure(self,app):
        super().configure(app)
        def check():
            windows=[w for w in app.topLevelWidgets() if type(w).__name__=='OfflineStitchWindow']
            if not windows:
                app.quit();return
            window=windows[0]
            seen.append(window.isVisible() and not window._backend_bridge._sdk_initialized)
            window.close()
        QTimer.singleShot(1500,check)
with patch.object(CameraManager,'initialize',side_effect=AssertionError('SDK forbidden')):
    result=main.main(composition=Composition())
assert result==0 and seen==[True],(result,seen)
"""
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=40)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_busy_import_blocks_close_and_new_import(self):
        window=self.open();bridge=window._backend_bridge;release=threading.Event()
        with patch.object(window.workflow,'load_directory',side_effect=lambda *a,**k:(release.wait(3) and [])):
            try:
                first=window.load_directory(self.temp.name)
                self.assertEqual(len(bridge._workers),1)
                self.assertIsNone(window.load_directory(self.temp.name))
                self.assertFalse(window.close())
            finally:release.set()
            self.wait(lambda:not bridge._workers)
        self.assertFalse(bridge.frame_db.databases['mobile_chain'].records)

if __name__=='__main__':unittest.main()
