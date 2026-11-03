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

    def test_rebuild_rejects_missing_pose_and_disconnected_frames(self):
        from test_image_color_fusion import FusionTests
        from core.postprocess.icp_registration import refine_stitched
        seed=FusionTests();seed.setUp();self.addCleanup(seed.doCleanups)
        row=seed.db.records[seed.uid]
        before=set(seed.db.records)
        row.source_transforms[seed.ids[1]][0][3]=1000
        with self.assertRaisesRegex(ValueError,'整批未发布'):
            refine_stitched(seed.db,seed.uid,seed.ids[0],ICPParameters(.2,.1))
        self.assertEqual(set(seed.db.records),before)
        row.source_transforms={}
        with self.assertRaisesRegex(ValueError,'位姿'):
            refine_stitched(seed.db,seed.uid,seed.ids[0],ICPParameters())

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

    def test_automatic_intermediate_failure_does_not_block_window(self):
        ids=[self.db.ingest(self.source(n)) for n in (1,2)]
        uid=self.db.publish_result(fixture.cloud([[1,2,3]]),ids,
            source_transforms={key:np.eye(4).tolist() for key in ids})
        self.editor.load_selected([uid],auto_intermediates=True)
        self.wait(lambda:self.editor._worker is None and '自动补齐中间帧失败' in self.editor.status.text())
        self.assertEqual(len(self.db.records),3)
        self.assertTrue(self.editor.actions['intermediate'].isEnabled())

    def test_opening_result_automatically_populates_intermediates(self):
        ids=[self.db.ingest(self.source(n)) for n in (1,2)]
        for key in ids: self.db.records[key].pointcloud_aligned=True
        uid=self.db.publish_result(fixture.cloud([[1,2,3],[4,5,6]]),ids,
            source_transforms={key:np.eye(4).tolist() for key in ids})
        self.editor.load_selected([uid],auto_intermediates=True)
        self.wait(lambda:self.editor._worker is None and len([row for row in self.db.records.values() if row.intermediate_of==uid])==2)
        self.assertEqual(len(self.editor._display_ids),2)
        self.assertTrue(self.editor.actions['icp'].isEnabled())
        count=len(self.db.records)
        self.editor.load_selected([uid],auto_intermediates=True)
        self.wait(lambda:self.editor._worker is None and len(self.editor._display_ids)==2)
        self.assertEqual(len(self.db.records),count)

    def test_extract_intermediates_and_probe_context(self):
        from core.postprocess.image_color_fusion import source_poses
        from ui_v2.postprocess.icp_dialog import ICPDialog
        from PySide6.QtWidgets import QLabel,QPushButton
        raw=[self.db.ingest(self.source(n)) for n in (1,2)]
        poses={key:np.eye(4).tolist() for key in raw}
        poses[raw[1]][0][3]=10
        for key in raw: self.db.records[key].pointcloud_aligned=True
        parent=self.db.publish_result(fixture.cloud([[1,2,3],[11,2,3]]),raw,source_transforms=poses)
        self.editor.load_selected([parent]);self.finish()
        self.editor.extract_intermediates();self.finish()
        outputs=list(self.editor._display_ids)
        self.assertEqual(len(outputs),2)
        for uid,key in zip(outputs,raw):
            row=self.db.records[uid]
            self.assertEqual(row.intermediate_of,parent)
            self.assertEqual(row.source_ids,[key])
            leaf=self.editor.source_browser._items[uid]
            self.assertEqual(leaf.childCount(),0)
            self.assertEqual(leaf.parent().text(0),'配准中间数据')
            self.assertEqual(leaf.parent().childCount(),2)
            self.assertEqual(leaf.parent().parent().data(0,256),parent)
            self.assertEqual(leaf.data(0,258),'cloud')
            np.testing.assert_allclose(source_poses(self.db,uid)[key][1],poses[key])
            from core.point_cloud_processor import PointCloudProcessor
            original=PointCloudProcessor._filter_valid(self.db.load_frame(key,'cloud')[1])[0]
            expected=np.asarray(original.points)+np.asarray(poses[key])[:3,3]
            np.testing.assert_allclose(self.editor._clouds[uid].points,expected)
        from core.frame_database import FrameDatabase
        reopened=FrameDatabase(self.db.mode);reopened.open_project(self.db.directory/'index.json')
        self.assertEqual(reopened.records[outputs[0]].intermediate_of,parent)
        count=len(self.db.records)
        self.editor.load_selected([parent]);self.finish();self.editor.extract_intermediates();self.finish()
        self.assertEqual(len(self.db.records),count)
        self.editor._probe_report=(self.editor._probe_key(),dict(spacing=dict(p50=.2,p90=.3,p95=.4,voxel=.3),tau=.6))
        dialog=ICPDialog([(uid,self.db.records[uid].logical_name) for uid in outputs],self.editor)
        self.assertFalse(any('探针' in label.text() for label in dialog.findChildren(QLabel)))
        self.assertFalse(any('采用探针' in button.text() for button in dialog.findChildren(QPushButton)))
        self.assertAlmostEqual(dialog.distance.value(),2)
        self.assertAlmostEqual(dialog.voxel.value(),1)
        dialog.reject()
        self.db._invalidate_results([parent])
        from core.frame_database import STALE_RESULT
        self.assertTrue(all(self.db.records[uid].status == STALE_RESULT for uid in outputs))

    def test_single_stitch_rebuild_preserves_raws_and_publishes_poses(self):
        from core.postprocess.image_color_fusion import source_poses
        from core.frame_database import FrameDatabase
        rng=np.random.default_rng(28)
        xyz=rng.uniform(10,30,(800,3))
        ids=[]
        for n in (1,2,3):
            frame=self.source(n)
            frame.pointcloud_aligned=True
            import open3d as o3d
            o3d.io.write_point_cloud(frame.offline_pointmap_path,fixture.cloud(xyz))
            ids.append(self.db.ingest(frame))
        poses={key:np.eye(4).tolist() for key in ids}
        poses[ids[1]][0][3]=.1
        poses[ids[2]][1][3]=-.1
        stitched=self.db.publish_result(fixture.cloud(np.vstack([xyz,xyz+[.1,0,0],xyz+[0,-.1,0]])),ids,source_transforms=poses)
        self.editor.load_selected([stitched]);self.finish()
        self.assertTrue(self.editor.actions['icp'].isEnabled())
        self.editor.register_stitched_icp(ids[0],ICPParameters(1,.02,60,.8));self.finish()
        result=self.editor._display_ids[0]
        self.assertNotEqual(result,stitched)
        self.assertEqual(set(self.db.records[result].source_ids),set(ids))
        self.assertEqual(len(self.editor._clouds[result].points),2400)
        for block in np.split(self.editor._clouds[result].points,3):
            np.testing.assert_allclose(block,xyz,atol=1e-5)
        opened=FrameDatabase(self.db.mode);opened.open_project(self.db.directory/'index.json')
        for _,pose in source_poses(opened,result).values():
            np.testing.assert_allclose(pose,np.eye(4),atol=1e-5)
        self.assertEqual(self.db.records[stitched].source_transforms,poses)
        self.editor.undo();self.finish()
        self.assertEqual(self.editor._display_ids,[stitched])

if __name__=='__main__':unittest.main()
