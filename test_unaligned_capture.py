import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from pathlib import Path
import test_ui_frame_database as fixture
from test_frame_database import PLY
from core.frame_database import FrameDatabase
from core import frame_recognition

class AlignmentTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    source = fixture.FrameBrowserTests.source
    wait = fixture.FrameBrowserTests.wait

    def test_capture_snapshots_alignment_only_for_swing_mode(self):
        import numpy as np
        from core.camera_manager import SingleCameraController
        class Image:
            def __array__(self, dtype=None): return np.zeros((2,2,3),dtype=np.uint8)
            def Clone(self): return self
        sdk = SimpleNamespace(CameraID_Left=0, CaptureMode_SwingLineScan=7)
        with patch('core.camera_manager.RVC', sdk):
            camera = SingleCameraController('test')
            camera.is_connected = True
            camera.camera = Mock()
            camera.camera.Capture.return_value = True
            camera.camera.GetImage.return_value = Image()
            for mode, correspond, expected in ((7,False,False),(7,True,True),(0,False,True)):
                camera.current_options = SimpleNamespace(capture_mode=mode,correspond2d=correspond)
                self.assertEqual(camera.capture_3d()[-1], 'success')
                self.assertIs(camera.last_pointcloud_aligned,expected)

    def test_raw_save_uses_geometry_and_roundtrips_alignment(self):
        frame = self.source()
        frame.pointcloud_aligned = False
        frame.pointmap = Mock()
        frame.rvc_image = object()
        def save(path, *args):
            Path(path).write_bytes(PLY)
            return True
        frame.pointmap.Save.side_effect = save
        sdk = SimpleNamespace(PointMapUnitEnum=SimpleNamespace(Millimeter=1))
        with patch('core.frame_database._import_rvc', return_value=sdk):
            uid = self.db.ingest(frame)
        frame.pointmap.SaveWithImage.assert_not_called()
        reloaded = FrameDatabase(self.db.mode)
        reloaded.open_project(self.db.directory/"index.json")
        self.assertIs(reloaded.records[uid].pointcloud_aligned, False)
        loaded, cloud = self.db.load_frame(uid)
        self.assertIs(loaded.pointcloud_aligned, False)
        self.assertEqual(len(cloud.points), 4)
        result = frame_recognition.detect(loaded, dict(marker_type='coded_circle', circle=[8,2,3], boards=[], gamma=1))
        self.assertEqual(result['markers'], [])
        self.assertIn('重拍', result['message'])

    def test_yellow_tree_warning_and_retake_clear(self):
        frame = self.source();frame.pointcloud_aligned = False
        uid = self.db.ingest(frame)
        self.browser.refresh()
        item = self.browser._items[uid]
        self.assertIn('!', item.text(0))
        self.assertEqual(item.foreground(0).color().name(), '#ffc44d')
        self.browser._alignment_clicked(item,0)
        self.assertIn('不能参与拼接', self.browser._alignment_notice.text())
        self.assertIn('重拍当前', self.browser._alignment_notice.informativeText())
        self.browser._alignment_notice.close()
        replacement = self.source(2);replacement.pointcloud_aligned = True
        self.db.replace_capture(uid,replacement)
        self.browser.refresh()
        self.assertNotIn('!',self.browser._items[uid].text(0))
        self.assertIs(self.db.records[uid].pointcloud_aligned,True)

    def test_stitch_rejects_unaligned_and_keeps_sources(self):
        self.win.set_mode('mobile_chain',[]);self.bridge._current_mode='mobile_chain'
        self.db = self.bridge.frame_db.databases['mobile_chain']
        for i in (1,2):
            f=self.source(i);f.pointcloud_aligned=False;self.db.ingest(f)
        self.bridge.stitching.execute()
        self.assertIn('未与2D对齐',self.win._stitch_failure_dialog.text())
        self.assertEqual(len(self.db.records),2)
        self.win._stitch_failure_dialog.close()

if __name__=='__main__':unittest.main()

