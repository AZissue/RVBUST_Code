import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'src'))
import numpy as np
from core.postprocess.session import CloudLayer
from core.postprocess.icp_registration import ICPParameters, refine_icp

class ICPTests(unittest.TestCase):
    def test_refinement_preserves_full_geometry_color_and_input(self):
        rng=np.random.default_rng(42)
        xyz=rng.uniform([10,10,10],[30,25,20],(2500,3))
        rgb=rng.random((len(xyz),3))
        ref=CloudLayer('fixed',xyz)
        moving=CloudLayer('moving',xyz+[.15,-.1,.08],rgb,origins=(('source',0),))
        original=moving.points.copy()
        out,report=refine_icp(ref,moving,ICPParameters(1,.05,80,.8))
        np.testing.assert_allclose(out.points,xyz,atol=1e-6)
        np.testing.assert_array_equal(out.colors,rgb)
        np.testing.assert_array_equal(moving.points,original)
        self.assertEqual(out.origins,moving.origins)
        self.assertEqual(len(out.points),len(xyz))
        self.assertIn('RMS',report)
        np.testing.assert_allclose(np.array(out.registration_transform)[:3,3],[-.15,.1,-.08],atol=1e-6)

    def test_no_overlap_and_invalid_parameters_rejected(self):
        rng=np.random.default_rng(4); xyz=rng.random((100,3))+10
        a=CloudLayer('a',xyz); b=CloudLayer('b',xyz+100)
        with self.assertRaisesRegex(ValueError,'重叠不足'):refine_icp(a,b,ICPParameters(.2,.01))
        for params in (ICPParameters(distance=float('nan')),ICPParameters(voxel=0),ICPParameters(iterations=0)):
            with self.assertRaises(ValueError):refine_icp(a,b,params)

import test_postprocess as fixture
class ICPUiTests(unittest.TestCase):
    setUpClass=classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp=fixture.PostprocessTests.setUp
    tearDown=fixture.PostprocessTests.tearDown
    wait=fixture.PostprocessTests.wait
    finish=fixture.PostprocessTests.finish
    source=fixture.PostprocessTests.source

    def test_entry_publishes_persistent_transform_and_undo(self):
        from core.frame_database import FrameDatabase
        from core.postprocess.image_color_fusion import source_poses
        from ui_v2.postprocess.icp_dialog import ICPDialog
        raw=self.db.ingest(self.source(1))
        xyz=np.random.default_rng(13).uniform(10,30,(1000,3))
        fixed=self.db.publish_result(fixture.cloud(xyz),[raw])
        moving=self.db.publish_result(fixture.cloud(xyz+[.1,0,0]),[raw],source_transforms={raw:np.eye(4).tolist()})
        self.db.records[raw].pointcloud_aligned=True
        self.editor.load_selected([fixed,moving]);self.finish()
        self.assertTrue(self.editor.actions['icp'].isEnabled())
        dialog=ICPDialog([(fixed,'fixed'),(moving,'moving')],self.editor)
        self.assertEqual(dialog.parameters()[0],fixed);dialog.reject()
        self.editor.register_icp(fixed,ICPParameters(1,.02,60,.8));self.finish()
        result=self.editor._display_ids[0]
        self.assertNotEqual(result,moving)
        np.testing.assert_allclose(self.editor._clouds[result].points,xyz,atol=1e-6)
        self.assertEqual(self.db.records[result].source_ids,[moving])
        self.assertIn('对应点RMS',self.editor.status.text())
        opened=FrameDatabase(self.db.mode);opened.open_project(self.db.directory/'index.json')
        np.testing.assert_allclose(source_poses(opened,result)[raw][1][:3,3],[-.1,0,0],atol=1e-6)
        self.editor.undo();self.finish()
        self.assertEqual(set(self.editor._display_ids),{fixed,moving})

    def test_failed_icp_does_not_publish_and_shows_advice(self):
        from unittest.mock import patch
        raw=self.db.ingest(self.source(1))
        xyz=np.random.default_rng(9).random((100,3))+10
        a=self.db.publish_result(fixture.cloud(xyz),[raw])
        b=self.db.publish_result(fixture.cloud(xyz+100),[raw])
        self.editor.load_selected([a,b]);self.finish()
        before=set(self.db.records)
        with patch('ui_v2.postprocess.window.QMessageBox.warning') as warning:
            self.editor.register_icp(a,ICPParameters(.1,.01));self.wait(lambda: self.editor._worker is None)
            self.assertTrue(warning.called)
            self.assertIn('粗配准',warning.call_args.args[-1])
        self.assertEqual(set(self.db.records),before)
        self.assertFalse(self.editor._undo)

if __name__=='__main__':unittest.main()
