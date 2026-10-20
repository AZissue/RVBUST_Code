"""Parallel industrial/classic presentation uses the exact production action ports."""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import numpy as np
import open3d as o3d

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0, str(Path(__file__).parent/'src'))
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QFontDatabase, QPixmap
from PySide6.QtTest import QSignalSpy
from ui_v2 import MainWindowShell, LauncherDialog, GLOBAL_QSS
from ui_v2.bindings import MULTI_ACTIONS, MOBILE_ACTIONS, SHELL_ACTIONS, connect_actions
from ui_v2.widgets.device_table import DeviceInfo
from ui_v2.contracts import PointCloudView


class IndustrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        cls.app.setStyleSheet(GLOBAL_QSS)

    def setUp(self):
        self.win=MainWindowShell()

    def tearDown(self):
        self.win._dirty=False
        self.win.close(); self.win.deleteLater(); self.app.processEvents()

    def test_six_entries_keep_business_modes_and_restore_presentation(self):
        dlg=LauncherDialog()
        self.assertEqual(len(dlg._industrial_cards),3)
        spy=QSignalSpy(dlg.connect_requested)
        for mode in dlg.MODE_NAMES:
            dlg._industrial_cards[mode].clicked.emit()
            self.assertEqual(dlg.selected_mode(),mode)
            self.assertEqual(dlg.selected_presentation(),'industrial')
            devices=[DeviceInfo(serial='a',checked=True,backend_ref=0)]
            if mode=='multi_cam':devices.append(DeviceInfo(serial='b',checked=True,backend_ref=1))
            dlg.set_devices(devices); dlg._btn_connect.click()
            self.assertEqual(spy.at(spy.count()-1)[0],mode)
            dlg.restore_state(mode,devices,'industrial')
            self.assertTrue(dlg._industrial_cards[mode].is_checked())
        dlg.deleteLater()

    def test_all_action_ports_survive_relayout_without_reconnection(self):
        original=[self.win.workspace_multi(), self.win.workspace_mobile(), self.win.workspace_turntable()]
        controller=SimpleNamespace()
        for actions in (MULTI_ACTIONS,MOBILE_ACTIONS,SHELL_ACTIONS):
            for _, slot in actions:setattr(controller,slot,Mock())
        for view,actions in [(original[0],MULTI_ACTIONS),(original[1],MOBILE_ACTIONS),(self.win,SHELL_ACTIONS)]:
            connect_actions(view,controller,actions)
        args={'capture_requested':(True,), 'detect_requested':('coded_circle',),
              'batch_scan_requested':(2,), 'reference_changed':('cam0',),'step_back_requested':(0,),
              'card_preview_toggled':('cam0',True), 'card_capture_requested':('cam0',),
              'card_detect_requested':('cam0',), 'preview_toggled':(True,),
              'recapture_requested':(0,), 'delete_station_requested':(0,), 'station_selected':(0,)}
        for mode in LauncherDialog.MODE_NAMES:
            self.win.set_mode(mode,[])
            for _ in range(2):
                self.win.set_presentation('industrial')
                self.win.set_presentation('classic')
            self.win.set_presentation('industrial')
        self.assertEqual(original,[self.win.workspace_multi(),self.win.workspace_mobile(),self.win.workspace_turntable()])
        for view,actions in [(original[0],MULTI_ACTIONS),(original[1],MOBILE_ACTIONS),(self.win,SHELL_ACTIONS)]:
            for signal, slot in actions:
                handler=getattr(controller,slot)
                handler.reset_mock()
                getattr(view,signal).emit(*args.get(signal,()))
                handler.assert_called_once_with(*args.get(signal,()))

    def test_real_buttons_and_gate_evaluation_turntable_session_survive(self):
        win=self.win
        win.set_mode('multi_cam',[DeviceInfo(serial='A',backend_ref=0),DeviceInfo(serial='B',backend_ref=1)])
        multi=win.workspace_multi()
        capture=QSignalSpy(multi.capture_requested)
        button=multi._btn_capture
        win.set_presentation('industrial')
        button.click();self.assertEqual(capture.count(),1)
        self.assertFalse(multi._btn_scan_capture.isEnabled())
        multi.on_calibrate_done([],90,True);multi.set_state('calibrated')
        self.assertTrue(multi._btn_scan_capture.isEnabled())
        multi.set_state('locked')
        win.set_mode('multi_cam',win._devices,preserve_state=True)
        self.assertEqual(multi.current_state(),'locked')
        win.set_presentation('classic')
        self.assertIs(button,multi._btn_capture)
        self.assertEqual(multi.current_state(),'locked')
        win.set_mode('mobile_chain',[]);win.set_presentation('industrial')
        mobile=win.workspace_mobile()
        mobile.on_evaluation_done(8,.9,.2,'ok','继续移动',backend_ref='station_1')
        self.assertEqual(mobile.get_station_id(1),'station_1')
        mobile.on_evaluation_done(0,0,None,'fail','重拍')
        self.assertEqual(mobile._station_count,1)
        win.set_presentation('classic')
        self.assertEqual(mobile._station_count,1)
        win.set_mode('turntable',[])
        turn=win.workspace_turntable();session=turn.session
        win.set_presentation('industrial')
        self.assertIs(turn.session,session)
        self.assertFalse(turn.btn_auto_capture.isEnabled())
        save=QSignalSpy(win.save_session_requested)
        turn.save_session_requested.emit()
        self.assertEqual(save.count(),1)

    def test_display_points_data_contract_and_docked_logs(self):
        win=self.win
        win.set_mode('mobile_chain',[])
        viewer=win.workspace_mobile().viewer()
        cloud=o3d.geometry.PointCloud()
        points=np.array([[0.,0.,0.],[1.,2.,3.],[4.,5.,6.]])
        cloud.points=o3d.utility.Vector3dVector(points)
        viewer.set_pointcloud_merged(cloud)
        win.set_presentation('industrial')
        renderer=viewer.viewer()
        self.assertIsInstance(renderer,PointCloudView)
        self.assertIs(renderer._merged,cloud)
        np.testing.assert_array_equal(np.asarray(cloud.points),points)
        self.assertEqual(renderer.canvas.total_points,3)
        win.resize(1400,900);win.show();self.app.processEvents()
        win._btn_log.setChecked(True);self.app.processEvents()
        self.assertIs(win._log_panel.parentWidget(),win._content_split)
        self.assertLessEqual(win._log_panel.height(),380)
        win.set_presentation('classic');self.app.processEvents()
        self.assertIs(viewer._merged,cloud)
        self.assertIs(win._log_panel.parentWidget(),win)

    def test_mobile_turntable_collapsed_controls_and_persistent_footer_evaluation(self):
        win = self.win
        win.resize(1600, 950)
        win.show()
        for mode in ('mobile_chain', 'turntable'):
            win.set_mode(mode, [])
            win.set_presentation('industrial')
            p = win._stack.currentWidget()._industrial
            self.assertTrue(p.sidebar.isHidden())
            p.legacy_toggle.click()
            self.assertFalse(p.sidebar.isHidden())
            p.legacy_toggle.click()
            p.maximize(True)
            p.maximize(False)
            self.assertTrue(p.sidebar.isHidden())
        win.set_mode('mobile_chain', [])
        ws = win.workspace_mobile()
        ws.on_evaluation_done(12, .85, .24, 'ok', '继续移动')
        self.app.processEvents()
        self.assertFalse(ws._eval_card.isVisible())
        self.assertFalse(ws._stats_label.isVisible())
        self.assertTrue(win._st_quality.isVisible())
        self.assertIn('本步误差 0.24mm', win._st_quality.full_text)
        self.assertIn('已接 1 机位', win._st_quality.full_text)
        win.log('最新日志', 'info')
        self.assertIn('本步误差 0.24mm', win._st_quality.full_text)
        ws.on_evaluation_done(2, .1, None, 'fail', '请重拍')
        self.assertIn('请重拍', win._st_quality.toolTip())
        self.assertIn('已接 1 机位', win._st_quality.full_text)
        ws.reset_session()
        self.assertIn('已接 0 机位', win._st_quality.full_text)
        self.assertIn('本步误差 —', win._st_quality.full_text)
        win.set_presentation('classic')
        self.app.processEvents()
        self.assertFalse(win._st_quality.isVisible())
        self.assertTrue(ws._eval_card.isVisible())
        win.set_mode('turntable', [])
        win.set_presentation('industrial')
        self.assertFalse(win._st_quality.isVisible())

    def test_marker_inspector_live_preview_and_failed_pair(self):
        win=self.win
        win.set_mode('mobile_chain',[]);win.set_presentation('industrial')
        live=win.workspace_mobile().live_view()
        frame=SimpleNamespace(image_np=np.zeros((100,100),np.uint8), markers_all=[],
                              markers=[dict(code=1,x_2d=20,y_2d=20,x_3d=1,y_3d=2,z_3d=3,valid_3d=True)])
        presentation=win.workspace_mobile()._industrial
        reference=SimpleNamespace(image_np=frame.image_np, markers_all=[],markers=frame.markers)
        live.set_marker_context(frame,reference,None)
        self.assertEqual(presentation.inspector.display.red_count,1)
        live.set_marker_context(frame,reference,False)
        self.assertEqual(presentation.inspector.display.red_count,0)
        self.assertEqual(presentation.inspector.display.green_count,1)
        live.set_frame(None)
        self.assertEqual(len(presentation.inspector.display.rows),0)

    def test_presentation_only_switch_keeps_connection_data_and_dirty_state(self):
        win=self.win
        devices=[DeviceInfo(serial='ACTIVE',backend_ref=0,checked=True)]
        win.set_mode('mobile_chain',devices)
        win._dirty=True
        win._confirm_discard=Mock(side_effect=AssertionError('Layout switch must not discard'))
        class Dialog(LauncherDialog):
            def exec(dialog):
                dialog._set_mode('mobile_chain','industrial')
                dialog.connect_requested.emit('mobile_chain',devices)
                return QDialog.Accepted
        win._launcher_factory=Dialog
        reconnect=Mock(side_effect=AssertionError('Layout switch must not reconnect'))
        bridge=SimpleNamespace(can_change_workspace=lambda:True,
            enumerate_devices=lambda:devices,get_ordered_devices=lambda value:value,
            _on_device_manager_reopened=reconnect)
        win.set_backend_bridge(bridge)
        before=win.workspace_mobile()
        win.open_device_manager()
        self.assertIs(win.workspace_mobile(),before)
        self.assertEqual(win.current_presentation(),'industrial')
        self.assertTrue(win._dirty)
        reconnect.assert_not_called()

    def test_multicam_marker_colors_and_per_camera_controls(self):
        from core.frame_data import FrameData
        from ui_common.industrial_scene.marker_display import GREEN, RED, YELLOW
        win=self.win
        win.set_mode('multi_cam',[DeviceInfo(serial='A',backend_ref=0),DeviceInfo(serial='B',backend_ref=1)])
        win.set_presentation('industrial')
        ws=win.workspace_multi()
        marker=dict(code=1,x_2d=20,y_2d=20,x_3d=1,y_3d=2,z_3d=3,valid_3d=True)
        first=FrameData(frame_id=1,camera_name='cam0',image_np=np.zeros((80,80),np.uint8),is_offline=True)
        second=FrameData(frame_id=1,camera_name='cam1',image_np=first.image_np,is_offline=True)
        first.markers=[marker]
        second.markers=[marker,dict(marker,code=2),dict(marker,code=3,valid_3d=False)]
        ws.camera_grid().set_frame('cam0',first)
        ws.camera_grid().set_frame('cam1',second)
        ws.on_detect_done({'cam0':1,'cam1':2})
        card=ws.camera_grid().card('cam1')
        self.assertEqual([m['display_color'] for m in card._thumb._markers],[RED,GREEN,YELLOW])
        self.assertFalse(card._btn_capture.isHidden())
        ws.on_calibrate_done([],0,False);ws.set_state('calibrated')
        self.assertNotIn(RED,[m['display_color'] for m in card._thumb._markers])


if __name__=='__main__':unittest.main(verbosity=2)
