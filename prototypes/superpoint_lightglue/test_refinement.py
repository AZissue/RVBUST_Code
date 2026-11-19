"""ICP should refine object geometry while preserving sensor-frame data and pose direction."""
import unittest

import numpy as np

from core.feature_settings import FeatureSettings
from .refinement import feature_surface, refine_feature_pose
from .pipeline import AlignedFrame


class FeatureICPTests(unittest.TestCase):
    def test_roi_surface_excludes_background_and_recovers_known_pose(self):
        from dataclasses import replace
        from core.postprocess.session import CloudLayer

        y, x = np.indices((64, 64))
        grid = np.stack((x*.5, y*.5, 400+2*np.sin(x*.2)+np.cos(y*.25)),axis=-1)
        frame = AlignedFrame(np.zeros((64,64,3),np.uint8),grid,None,'object',('a',1))
        points = feature_surface(frame, (.1,.1,.9,.9),(.25,.25,.75,.75),.25)
        self.assertLess(len(points), 64*64)
        self.assertTrue(np.all(points[:,0]>=8))
        self.assertTrue(np.all(points[:,0]<24))
        source = points.copy()
        shifted_pose = np.eye(4)
        shifted_pose[:3,3]=[.15,-.1,.25]
        settings=replace(FeatureSettings(),icp_enabled=True,icp_voxel=.25,icp_distance=1.)
        # Sparse feature constraints refer to the same physical points.
        target=CloudLayer('reference',source)
        matrix, report, accepted = refine_feature_pose(
            target,source,shifted_pose,(source,source),settings)
        self.assertTrue(accepted,report)
        self.assertLess(np.linalg.norm(matrix[:3,3]), .1)
        np.testing.assert_array_equal(source,points)
        np.testing.assert_allclose(shifted_pose[:3,3],[.15,-.1,.25])

    def test_stitch_applies_icp_to_full_points_and_saved_source_pose(self):
        from dataclasses import replace
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import open3d as o3d
        from core.frame_data import FrameData
        from core.frame_database import FrameDatabase
        from .automatic import FeatureStitching

        class BiasedPixels:
            def match(self,images,boxes):
                pixels=np.array([[x,y] for y in (8,20,32) for x in (8,20,32)],dtype=float)
                return pixels,pixels+[.25,-.15]
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            db=FrameDatabase('mobile_chain')
            db.directory=root/'db'
            y,x=np.indices((48,48))
            ids=[]
            hashes={}
            for number in (1,2):
                grid=np.stack((x+2*(number-1),y,400+2*np.sin(x*.2)+np.cos(y*.3)),axis=-1)
                cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(grid.reshape(-1,3)))
                cloud.colors=o3d.utility.Vector3dVector(np.tile([.2,.4,.6],(x.size,1)))
                path=root/f'{number}.ply'
                self.assertTrue(o3d.io.write_point_cloud(str(path),cloud))
                uid=db.ingest(FrameData(number,'cam0',image_np=np.full(x.shape,100,np.uint8),
                    offline_pointmap_path=str(path),pointcloud_aligned=True))
                ids.append(uid)
                hashes[uid]=(db.directory/'frames'/uid/'pointmap.ply').read_bytes()
            service=FeatureStitching(BiasedPixels())
            base=service.stitch(db,ids,settings=replace(FeatureSettings(),icp_enabled=False))
            result=service.stitch(db,ids,settings=replace(FeatureSettings(),icp_distance=1.))
            initial=np.asarray(db.records[base.uid].source_transforms[ids[1]])
            final=np.asarray(db.records[result.uid].source_transforms[ids[1]])
            self.assertEqual(result.icp_accepted,1,result.icp_reports)
            self.assertLess(np.linalg.norm(final[:3,3]-[-2,0,0]),
                            np.linalg.norm(initial[:3,3]-[-2,0,0]))
            self.assertEqual(len(result.cloud.points),2*x.size)
            self.assertTrue(result.cloud.has_colors())
            np.testing.assert_allclose(np.asarray(result.cloud.colors),[.2,.4,.6]*np.ones((2*x.size,3)),
                                       atol=1/255)
            for uid in ids:
                self.assertEqual((db.directory/'frames'/uid/'pointmap.ply').read_bytes(),hashes[uid])
            np.testing.assert_array_equal(db.records[result.uid].source_transforms[ids[0]],np.eye(4))

    def test_icp_cannot_override_inconsistent_feature_evidence(self):
        from dataclasses import replace
        from core.postprocess.session import CloudLayer
        source=np.random.default_rng(5).uniform(-5,5,(2500,3))
        coarse=np.eye(4)
        coarse[:3,3]=[.15,-.1,.08]
        evidence=(source,source+coarse[:3,3])
        matrix,report,accepted=refine_feature_pose(
            CloudLayer('fixed',source),source,coarse,evidence,
            replace(FeatureSettings(),icp_voxel=.05,icp_distance=1.,tolerance=.01))
        self.assertFalse(accepted)
        self.assertIn('原有特征',report)
        np.testing.assert_array_equal(matrix,coarse)

    def test_no_overlap_retains_coarse_pose(self):
        from dataclasses import replace
        from core.postprocess.session import CloudLayer
        points=np.random.default_rng(4).uniform(-5,5,(100,3))
        initial=np.eye(4)
        initial[:3,3]=[100,0,0]
        settings=replace(FeatureSettings(),icp_enabled=True)
        matrix, report, accepted = refine_feature_pose(
            CloudLayer('reference',points),points,initial,(points,points+[100,0,0]),settings)
        self.assertFalse(accepted)
        np.testing.assert_array_equal(matrix,initial)
        self.assertIn('保留特征配准',report)
