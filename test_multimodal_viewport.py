import unittest
import test_ui_frame_database as fixture
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from ui_common.multimodal_viewport import MultimodalViewport

class ViewportTests(unittest.TestCase):
    setUpClass=classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp=fixture.FrameBrowserTests.setUp
    tearDown=fixture.FrameBrowserTests.tearDown
    wait=fixture.FrameBrowserTests.wait
    source=fixture.FrameBrowserTests.source

    def test_four_modes_share_persistent_viewports(self):
        for mode in ('multi_cam','mobile_chain','turntable','robot_stitch'):
            self.win.set_mode(mode,[]);self.win.set_presentation('industrial');self.app.processEvents()
            presentation=self.win._stack.currentWidget()._industrial
            pages=presentation.view_pages
            self.assertIsInstance(pages,MultimodalViewport)
            scene,image=pages.scene,pages.image
            viewer=presentation.workspace.viewer if mode=='turntable' else presentation.workspace._viewer
            canvas=viewer.viewer().canvas
            canvas.zoom=2.3
            pages.set_view('joint');self.app.processEvents()
            self.assertTrue(pages.scene_host.isVisible());self.assertTrue(pages.image_host.isVisible())
            pages.set_view('2d');self.app.processEvents()
            self.assertFalse(pages.scene_host.isVisible());self.assertTrue(pages.image_host.isVisible())
            pages.set_view('3d');self.app.processEvents()
            self.assertTrue(pages.scene_host.isVisible());self.assertFalse(pages.image_host.isVisible())
            self.assertIs(pages.scene,scene);self.assertIs(pages.image,image)
            self.assertIs(viewer.viewer().canvas,canvas)
            self.assertAlmostEqual(canvas.zoom,2.3)
            import tempfile
            from pathlib import Path
            pages.set_view('joint');self.app.processEvents()
            self.win.grab().save(str(Path(tempfile.gettempdir())/f'mcc_views_{mode}.png'))
            self.assertFalse(presentation.viewport.isVisible())

    def test_switch_to_2d_lazily_loads_image_without_reloading_cloud(self):
        from unittest.mock import patch
        from core.frame_data import FrameData
        self.bridge._current_mode='multi_cam'
        uid=self.db.ingest(self.source(1))
        self.bridge.frame_db.select('multi_cam',uid,'cloud');self.wait(lambda:not self.bridge._workers)
        ws=self.win.workspace_multi();pages=ws._industrial.view_pages
        original=ws.viewer()._database_cloud
        with patch.object(FrameData,'load_pointcloud_o3d',side_effect=AssertionError('page switch reloaded cloud')):
            pages.set_view('2d');self.wait(lambda:not self.bridge._workers)
        self.assertEqual(pages.current_view(),'2d')
        self.assertIs(ws.viewer()._database_cloud,original)
        self.assertIsNotNone(ws.camera_grid()._database_card.current_frame().image_np)

    def test_db_image_and_cloud_select_views_check_keeps_view(self):
        self.bridge._current_mode='multi_cam'
        uid=self.db.ingest(self.source(1))
        pages=self.win.workspace_multi()._industrial.view_pages
        self.bridge.frame_db.select('multi_cam',uid,'image');self.wait(lambda:not self.bridge._workers)
        self.assertEqual(pages.current_view(),'2d')
        pages.set_view('joint')
        self.browser.set_component_checked(uid,'cloud',True)
        self.wait(lambda:not self.bridge.frame_db.overlay._running)
        self.assertEqual(pages.current_view(),'joint')
        self.bridge.frame_db.select('multi_cam',uid,'cloud');self.wait(lambda:not self.bridge._workers)
        self.assertEqual(pages.current_view(),'3d')

if __name__=='__main__':unittest.main()
