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
            self.assertEqual(pages.scene_host.width(),pages.content.width())
            self.assertLess(pages.image_host.width(),pages.scene_host.width())
            self.assertGreater(pages.image_host.x(),pages.content.width()/2)
            self.assertLessEqual(pages.image_host.y(),12)
            self.assertTrue(pages.content.rect().contains(pages.image_host.geometry()))
            self.win.resize(1200,760);self.app.processEvents()
            self.assertTrue(pages.content.rect().contains(pages.image_host.geometry()))
            self.assertEqual(pages.scene_host.width(),pages.content.width())
            pages.set_view('2d');self.app.processEvents()
            self.assertFalse(pages.scene_host.isVisible());self.assertTrue(pages.image_host.isVisible())
            self.assertEqual(pages.image_host.geometry(),pages.content.rect())
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

    def test_preview_toolbar_routes_four_modes_and_mirrors_permissions(self):
        from unittest.mock import patch
        for mode in ('multi_cam','mobile_chain','turntable','robot_stitch'):
            self.win.set_mode(mode,[])
            self.win.set_presentation('industrial')
            p=self.win._stack.currentWidget()._industrial
            source=p._preview_action.source
            button=p.view_pages.preview_button
            source.setEnabled(False)
            self.assertFalse(button.isEnabled())
            with patch.object(source,'click') as click:
                button.click()
                click.assert_not_called()
                source.setEnabled(True)
                self.assertTrue(button.isEnabled())
                button.click()
                click.assert_called_once()
                self.assertEqual(p.view_pages.current_view(),'2d')
            if source.isCheckable():
                source.blockSignals(True)
                source.setChecked(True)
                source.blockSignals(False)
                p._preview_action.sync()
                self.assertEqual(button.text(),'停止2D预览')

    def test_marker_details_label_is_generic_for_both_marker_types(self):
        self.win.set_mode('mobile_chain',[])
        inspector=self.win.workspace_mobile()._industrial.inspector
        self.assertEqual(inspector.details_button.text(),'标记物数据')
        for marker_type in ('coded_circle','asymmetric_grid'):
            inspector.set_frame(None,[],marker_type=marker_type)
            self.assertEqual(inspector.details_button.text(),'标记物数据')

    def test_robot_preview_uses_2d_only_and_restores_after_failure(self):
        from unittest.mock import Mock
        from core.frame_data import FrameData
        import numpy as np
        self.win.set_mode('robot_stitch',[])
        ws=self.win.workspace_robot()
        manager=Mock()
        manager.get_connected_ids.return_value=['cam0']
        ws.workflow.camera_manager=manager
        ws.set_devices([object()])
        ws.set_background_runner(Mock())
        before=ws.workflow.get_frame_count()
        for error in (None,'模拟失败'):
            ws._refresh_actions()
            ws._industrial.view_pages.preview_button.click()
            self.assertTrue(ws._busy)
            self.assertFalse(ws.btn_preview_2d.isEnabled())
            work,done=ws._background_runner.call_args.args
            frame=FrameData(99,'cam0',image_np=np.zeros((10,12,3),np.uint8))
            manager.capture_2d_preview.return_value=frame
            self.assertIs(work(),frame)
            done(frame if error is None else None,error)
            self.assertFalse(ws._busy)
            self.assertTrue(ws.btn_preview_2d.isEnabled())
            self.assertEqual(ws.workflow.get_frame_count(),before)
        manager.capture.assert_not_called()

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
