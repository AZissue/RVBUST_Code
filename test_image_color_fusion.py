import tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/"src"))
from pathlib import Path
import numpy as np
import open3d as o3d
from core.frame_data import FrameData
from core.frame_database import FrameDatabase
from core.postprocess.session import CloudLayer
from core.postprocess.color_correction import ColorParameters
from core.postprocess.image_color_fusion import source_poses,fuse_image_colors

class FusionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=FrameDatabase('mobile_chain',self.temp.name)
        self.xyz=np.array([[x,y,100] for y in range(20) for x in range(20)],float)
        self.ids=[]
        for i,factor in enumerate((1.,.7)):
            path=Path(self.temp.name)/f'raw{i}.ply'
            cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(self.xyz))
            o3d.io.write_point_cloud(str(path),cloud,write_ascii=True)
            frame=FrameData(i,'cam0',image_np=(np.tile(np.array([40,80,120]),(20,20,1)) * (1+np.arange(20)[None,:,None]/20.) * factor).astype(np.uint8),
                is_offline=True,offline_pointmap_path=str(path),pointcloud_aligned=True)
            self.ids.append(self.db.ingest(frame))
        self.cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(self.xyz[::2]))
        self.cloud.colors=o3d.utility.Vector3dVector(np.tile([.1,.1,.1],(len(self.cloud.points),1)))
        self.uid=self.db.publish_result(self.cloud,self.ids,source_transforms={uid:np.eye(4).tolist() for uid in self.ids})
        self.layer=CloudLayer('test',np.asarray(self.cloud.points),np.asarray(self.cloud.colors),origins=((self.uid,0),))
        self.params=ColorParameters(algorithm='image_fusion',strength=1,max_gain=2,overlap_distance=.1)

    def test_original_pixels_exposure_fusion_preserves_xyz_and_input(self):
        poses=source_poses(self.db,self.uid)
        out,report=fuse_image_colors(self.db,self.layer,poses,self.params)
        np.testing.assert_array_equal(out.points,self.layer.points)
        np.testing.assert_allclose(out.colors,self.db.load_frame(self.ids[0])[0].image_np.reshape(-1,3)[::2,::-1]/255.,atol=.01)
        np.testing.assert_allclose(self.layer.colors,.1)
        self.assertEqual(report['frames'],2)
        child=self.db.publish_result(self.cloud,[self.uid],postprocess=True)
        self.assertEqual(set(source_poses(self.db,child)),set(self.ids))
        other=FrameDatabase('mobile_chain');other.open_project(self.db.directory/'index.json')
        self.assertEqual(set(source_poses(other,child)),set(self.ids))

    def test_missing_pose_unaligned_and_invalid_transform_are_rejected(self):
        self.db.records[self.uid].source_transforms={}
        with self.assertRaisesRegex(ValueError,'位姿'):source_poses(self.db,self.uid)
        self.db.records[self.uid].source_transforms={uid:np.eye(4).tolist() for uid in self.ids}
        self.db.records[self.ids[0]].pointcloud_aligned=False
        with self.assertRaisesRegex(ValueError,'对齐'):source_poses(self.db,self.uid)
        self.db.records[self.ids[0]].pointcloud_aligned=True
        self.db.records[self.uid].source_transforms[self.ids[0]][0][0]=2
        with self.assertRaisesRegex(ValueError,'位姿无效'):source_poses(self.db,self.uid)

    def test_nonidentity_pose_is_used_and_far_targets_keep_original_color(self):
        uid=self.ids[1]
        xyz=self.xyz-np.array([10.,0,0])
        o3d.io.write_point_cloud(str(self.db.directory/'frames'/uid/'pointmap.ply'),o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz)))
        self.db.records[self.uid].source_transforms[uid][0][3]=10.
        output,_=fuse_image_colors(self.db,self.layer,source_poses(self.db,self.uid),self.params)
        np.testing.assert_array_equal(output.points,self.layer.points)
        self.assertGreater(output.colors.mean(),.1)
        far=CloudLayer('far',self.layer.points+10000,self.layer.colors)
        with self.assertRaisesRegex(ValueError,'没有可靠几何对应'):
            fuse_image_colors(self.db,far,source_poses(self.db,self.uid),self.params)

    def test_missing_pixel_correspondence_is_rejected(self):
        import cv2
        cv2.imwrite(str(self.db.directory/'frames'/self.ids[0]/'image.png'),np.zeros((3,3,3),np.uint8))
        with self.assertRaisesRegex(ValueError,'不对应'):
            fuse_image_colors(self.db,self.layer,source_poses(self.db,self.uid),self.params)

import test_postprocess as ui_fixture
class FusionUiTests(unittest.TestCase):
    setUpClass=classmethod(ui_fixture.PostprocessTests.setUpClass.__func__)
    setUp=ui_fixture.PostprocessTests.setUp
    tearDown=ui_fixture.PostprocessTests.tearDown
    wait=ui_fixture.PostprocessTests.wait
    finish=ui_fixture.PostprocessTests.finish
    source=ui_fixture.PostprocessTests.source

    def test_robot_publisher_persists_full_identity_and_pose(self):
        from unittest.mock import Mock
        from test_robot_session import RobotSessionTests
        from ui_v2.widgets.device_table import DeviceInfo
        workspace,project=RobotSessionTests.robot(self)
        frame=self.source(7);frame.pointcloud_aligned=True
        self.bridge.camera_manager.get_connected_ids=Mock(return_value=['cam0'])
        self.bridge.camera_manager.capture=Mock(side_effect=lambda camera:self.bridge.frame_db.capture(frame))
        workspace.set_devices([DeviceInfo(serial='A',backend_ref=0)])
        workspace.on_capture()
        self.wait(lambda: workspace.workflow.get_frame_count()==1 and not self.bridge._workers)
        workspace.workflow.handeye.validated=True
        self.bridge._on_robot_publish()
        self.wait(lambda: not self.bridge._workers)
        result=next(row for row in project.database.records.values() if row.kind=='result')
        self.assertEqual(len(result.uid),32)
        self.assertIn(frame.database_id,result.source_transforms)
        np.testing.assert_allclose(result.source_transforms[frame.database_id],workspace.workflow.transforms[0])

    def test_existing_color_entry_publishes_and_undoes_image_fusion(self):
        seed=FusionTests();seed.setUp()
        self.addCleanup(seed.doCleanups)
        ids=[]
        for uid in seed.ids:
            frame,_=seed.db.load_frame(uid)
            frame.database_id=None
            ids.append(self.db.ingest(frame))
        uid=self.db.publish_result(seed.cloud,ids,source_transforms={x:np.eye(4).tolist() for x in ids})
        self.editor.load_selected([uid]);self.finish()
        self.editor._color_state.update(algorithm='image_fusion')
        dialog=self.editor.create_color_dialog()
        self.assertEqual(dialog.parameters()['algorithm'],'image_fusion')
        self.assertFalse(dialog.voxel_size.isEnabled());dialog.reject()
        self.editor.correct_colors(seed.params);self.finish()
        result=self.editor._display_ids[0]
        self.assertNotEqual(result,uid)
        self.assertEqual(self.db.records[result].source_ids,[uid])
        np.testing.assert_array_equal(self.editor._clouds[result].points,seed.layer.points)
        self.assertEqual(self.editor._last_color_report[0]['algorithm'],'image_fusion')
        self.editor.undo();self.finish()
        self.assertEqual(self.editor._display_ids,[uid])

if __name__=='__main__':unittest.main()
