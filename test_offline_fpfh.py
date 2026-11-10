"""Formal offline FPFH entry, actual solve and result publication."""
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import open3d as o3d
import test_offline_stitch as offline_tests
import test_ui_frame_database as fixture
from ui_v2.postprocess.fpfh_dialog import FPFHDialog
from ui_v2.postprocess.fpfh_editor import FPFHEditor
from core.postprocess.fpfh_registration import SPECS,DEFAULTS

class FPFHOfflineTests(unittest.TestCase):
    setUpClass=classmethod(offline_tests.OfflineTests.setUpClass.__func__)
    setUp=offline_tests.OfflineTests.setUp
    def tearDown(self):
        window=getattr(self.win,'_offline_stitch_window',None)
        if window is not None:self.dispose(window)
        offline_tests.OfflineTests.tearDown(self)
    wait=offline_tests.OfflineTests.wait
    open=offline_tests.OfflineTests.open
    dispose=offline_tests.OfflineTests.dispose
    def test_separate_entry_and_existing_editor_reuse(self):
        window=self.open();bridge=window._backend_bridge
        opened=[]
        class ProbeDialog:
            def __init__(self,editor):self.editor=editor
            def exec(self):opened.append(self.editor)
            def deleteLater(self):pass
        with patch('ui_v2.postprocess.fpfh_dialog.FPFHDialog',ProbeDialog):
            window._industrial_ribbon.commands[('mobile_chain','fpfh')].click()
            self.wait(lambda:len(opened)==1)
            editor=bridge._postprocess_window
            self.assertIsInstance(editor,FPFHEditor)
            self.assertIs(editor.database,bridge.frame_db.databases['mobile_chain'])
            self.assertIsNone(getattr(bridge,'validation_root',None))
            self.assertIs(window.open_fpfh(),editor)
            self.wait(lambda:len(opened)==2)
        window.resize(1050,650);self.app.processEvents()
        folder=Path('outputs/offline_fpfh');folder.mkdir(exist_ok=True)
        window.grab().save(str(folder/'entry.png'))
        self.assertLessEqual(window.width(),1050)
        dialog=FPFHDialog(editor);dialog.show();self.app.processEvents()
        dialog.grab().save(str(folder/'parameters.png'));dialog.close()
        editor.close()
    def test_full_parameters_real_solve_and_db_publication(self):
        window=self.open();bridge=window._backend_bridge;db=bridge.frame_db.databases['mobile_chain']
        raw=[db.ingest(fixture.FrameBrowserTests.source(self,i)) for i in (1,2)]
        rng=np.random.default_rng(17);points=rng.normal(size=(1000,3))*[35,19,11]+[100,100,100]
        ids=[]
        for xyz,uid in ((points+[15,-9,6],raw[0]),(points,raw[1])):
            cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz))
            ids.append(db.publish_result(cloud,[uid]))
        editor=bridge.open_postprocess();self.wait(lambda:editor._worker is None)
        dialog=FPFHDialog(editor)
        self.assertEqual(len(dialog.controls),34)
        self.assertEqual(dialog.parameters(),DEFAULTS)
        self.assertTrue(all(control.toolTip() for control in dialog.controls.values()))
        dialog.reference.setCurrentIndex(dialog.reference.findData(ids[0]))
        dialog.moving.setCurrentIndex(dialog.moving.findData(ids[1]))
        for key,value in dict(voxel_mm=3,normal_radius_mm=8,feature_radius_mm=20,min_consensus=20).items():dialog.controls[key].setValue(value)
        dialog.controls['icp'].setChecked(True)
        dialog.analyze();self.wait(lambda:not dialog.busy)
        self.assertIsNotNone(dialog.result,dialog.report.toPlainText())
        np.testing.assert_allclose(np.asarray(dialog.result['transform'])[:3,3],[15,-9,6],atol=.4)
        again=FPFHDialog(editor);self.assertEqual(again.controls['voxel_mm'].value(),3);again.close()
        before=set(db.records);dialog.confirm.setChecked(True);dialog.publish_result()
        self.wait(lambda:editor._worker is None)
        added=set(db.records)-before;self.assertEqual(len(added),1)
        output=db.records[added.pop()];self.assertEqual(output.points,2000)
        self.assertTrue(bridge.projects.projects['mobile_chain'].dirty)
        self.assertEqual(set(output.source_ids),set(ids))
        self.assertEqual(len(db.records),len(before)+1)
        editor.close()

if __name__=='__main__':unittest.main()
