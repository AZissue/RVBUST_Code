import unittest
from unittest.mock import Mock,patch
import test_ui_frame_database as fixture
from core.frame_database import STALE_RESULT

class RetakeTests(fixture.FrameBrowserTests):
    def setUp(self):
        super().setUp()
        self.bridge._current_mode='multi_cam'
        self.bridge.offline_preview=False

    def test_selected_calibration_retake_replaces_pair(self):
        frame=self.source(1)
        uid=self.db.ingest(frame,purpose='标定数据')
        self.bridge.fixed_workflow.frames_calib['cam0']=frame
        self.browser.tree.setCurrentItem(self.browser._items[uid])
        self.wait(lambda:not self.bridge._workers)
        self.bridge.camera_manager.get_connected_ids=Mock(return_value=['cam0'])
        replacement=self.source(9)
        def capture(camera):
            return self.bridge.frame_db.capture(replacement)
        self.bridge.camera_manager.capture=Mock(side_effect=capture)
        self.bridge.stitching.recapture_selected()
        self.wait(lambda:not self.bridge._workers)
        self.assertEqual(list(self.db.records),[uid])
        self.assertEqual(self.db.records[uid].revision,1)
        self.assertEqual(self.db.records[uid].frame_id,1)
        self.assertEqual(self.db.records[uid].purpose,'标定数据')
        self.assertEqual(self.bridge.fixed_workflow.frames_calib['cam0'].database_id,uid)
        self.assertFalse(self.bridge.fixed_workflow.is_calibration_locked)

    def test_failed_retake_keeps_old_record(self):
        uid=self.db.ingest(self.source(1))
        self.browser.tree.setCurrentItem(self.browser._items[uid])
        self.wait(lambda:not self.bridge._workers)
        self.bridge.camera_manager.get_connected_ids=Mock(return_value=['cam0'])
        self.bridge.camera_manager.capture=Mock(return_value=None)
        with patch('ui_v2.explicit_stitching.QMessageBox.warning') as warning:
            self.bridge.stitching.recapture_selected();self.wait(lambda:not self.bridge._workers)
            self.assertTrue(warning.called)
        self.assertEqual(self.db.records[uid].revision,0)
        self.assertEqual(len(self.db.records),1)

    def test_scan_retake_invalidates_result_without_adding_frame(self):
        frame=self.source(1)
        uid=self.db.ingest(frame,purpose='扫描数据')
        result=self.db.publish_result(frame.load_pointcloud_o3d(),[uid])
        self.bridge.fixed_workflow.frames_scan['cam0']=frame
        self.browser.tree.setCurrentItem(self.browser._items[uid]);self.wait(lambda:not self.bridge._workers)
        self.bridge.camera_manager.get_connected_ids=Mock(return_value=['cam0'])
        self.bridge.camera_manager.capture=Mock(side_effect=lambda camera:self.bridge.frame_db.capture(self.source(8)))
        self.bridge.stitching.recapture_selected();self.wait(lambda:not self.bridge._workers)
        self.assertEqual(len(self.db.records),2)
        self.assertEqual(self.db.records[uid].revision,1)
        self.assertEqual(self.db.records[result].status,STALE_RESULT)
        self.assertEqual(self.bridge.fixed_workflow.frames_scan['cam0'].database_id,uid)

    def test_turntable_retake_updates_calibration_slot(self):
        from ui_v2.widgets.device_table import DeviceInfo
        self.win.set_mode('turntable',[DeviceInfo(serial='MOCK',backend_ref=0)])
        self.bridge._current_mode='turntable'
        db=self.bridge.frame_db.databases['turntable']
        browser=self.bridge.frame_db.browsers['turntable']
        uid=db.ingest(self.source(1),purpose='转台标定 frame0')
        browser.tree.setCurrentItem(browser._items[uid]);self.wait(lambda:not self.bridge._workers)
        self.bridge.camera_manager.get_connected_ids=Mock(return_value=['cam0'])
        self.bridge.camera_manager.capture=Mock(side_effect=lambda camera:self.bridge.frame_db.capture(self.source(8)))
        self.bridge.stitching.recapture_selected();self.wait(lambda:not self.bridge._workers)
        ws=self.win.workspace_turntable()
        self.assertEqual(list(db.records),[uid])
        self.assertEqual(db.records[uid].revision,1)
        self.assertEqual(ws.current_frame0.database_id,uid)
        self.assertEqual(ws.session.frame0.database_id,uid)
        self.assertFalse(ws.session.calibrated)

    def test_project_labels_do_not_repeat_across_sessions(self):
        self.db.project_title='project'
        first=self.db.ingest(self.source(1),purpose='标定数据')
        self.db.begin_session('second')
        second=self.db.ingest(self.source(2),purpose='标定数据')
        self.browser.refresh()
        self.assertEqual(self.browser._items[first].text(0),'标定帧 001 · cam0')
        self.assertEqual(self.browser._items[second].text(0),'标定帧 002 · cam0')

if __name__=='__main__':unittest.main()
