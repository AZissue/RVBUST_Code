import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'src'))
import numpy as np
from core.postprocess.manual_registration import landmark_transform,register_manual
from core.postprocess.icp_registration import ICPParameters
from core.postprocess.session import CloudLayer

class ManualTests(unittest.TestCase):
    def test_rotation_translation_and_merged_count(self):
        xyz=np.random.default_rng(2).uniform(10,30,(600,3))
        angle=.7
        r=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
        moving=xyz@r.T+[100,20,-50]
        a=CloudLayer('a',xyz,origins=(('a',0),));b=CloudLayer('b',moving,origins=(('b',0),))
        output,report=register_manual(a,b,xyz[:5],moving[:5],ICPParameters(1,.02,60,.8))
        self.assertEqual(len(output.points),1200)
        np.testing.assert_allclose(output.points[600:],xyz,atol=1e-6)
        self.assertIn('共有点5对',report)
        np.testing.assert_array_equal(b.points,moving)
        self.assertEqual(set(output.parent_transforms),{'a','b'})

    def test_degenerate_pairs_rejected(self):
        for a,b in (([[1,2,3]]*3,[[1,2,3]]*3),([[i,0,0] for i in range(3)],[[i,0,0] for i in range(3)]),([[1,2,3]]*2,[[1,2,3]]*2)):
            with self.assertRaises(ValueError):landmark_transform(a,b)

import test_postprocess as fixture
class ManualUiTests(unittest.TestCase):
    setUpClass=classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp=fixture.PostprocessTests.setUp
    tearDown=fixture.PostprocessTests.tearDown
    wait=fixture.PostprocessTests.wait
    finish=fixture.PostprocessTests.finish
    source=fixture.PostprocessTests.source

    def test_dialog_pairs_publish_pose_and_undo(self):
        from ui_v2.postprocess.manual_registration_dialog import ManualRegistrationDialog
        from core.postprocess.image_color_fusion import source_poses
        raw=self.db.ingest(self.source(1));self.db.records[raw].pointcloud_aligned=True
        raw2=self.db.ingest(self.source(2));self.db.records[raw2].pointcloud_aligned=True
        xyz=np.random.default_rng(7).uniform(10,30,(500,3))
        a=self.db.publish_result(fixture.cloud(xyz),[raw],source_transforms={raw:np.eye(4).tolist()})
        b=self.db.publish_result(fixture.cloud(xyz+[100,0,0]),[raw2],source_transforms={raw2:np.eye(4).tolist()})
        self.editor.load_selected([a,b]);self.finish()
        dialog=ManualRegistrationDialog([(uid,self.editor._clouds[uid]) for uid in (a,b)],self.editor)
        self.assertFalse(dialog.execute.isEnabled())
        from unittest.mock import patch
        from PySide6.QtCore import Qt,QPoint
        from PySide6.QtTest import QTest
        dialog.show();self.app.processEvents()
        with patch.object(dialog.viewers[0].canvas,'pick_pivot',return_value=xyz[0]):
            QTest.mouseClick(dialog.viewers[0].canvas,Qt.LeftButton,Qt.ShiftModifier,QPoint(100,100))
        self.assertEqual(len(dialog.pickers[0].points),1)
        dialog.reference.setCurrentIndex(1)
        self.assertEqual(len(dialog.pickers[0].points),0)
        dialog.reference.setCurrentIndex(0)
        dialog.pickers[0].points=list(xyz[:4]);dialog.pickers[1].points=list(xyz[:4]+[100,0,0]);dialog.refresh_pairs()
        self.assertTrue(dialog.execute.isEnabled())
        import tempfile
        dialog.grab().save(str(Path(tempfile.gettempdir())/'mcc_manual_dialog.png'))
        dialog.reject();dialog.deleteLater()
        self.editor.register_manual(a,xyz[:4],xyz[:4]+[100,0,0],ICPParameters(1,.02,60,.8));self.finish()
        result=self.editor._display_ids[0]
        self.assertEqual(len(self.editor._clouds[result].points),1000)
        self.assertEqual(set(self.db.records[result].source_ids),{a,b})
        np.testing.assert_allclose(source_poses(self.db,result)[raw2][1][:3,3],[-100,0,0],atol=1e-6)
        self.editor.undo();self.finish()
        self.assertEqual(set(self.editor._display_ids),{a,b})

if __name__=='__main__':unittest.main()
