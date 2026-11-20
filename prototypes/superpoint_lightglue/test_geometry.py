"""Dense geometry must correct joint layering without changing the anchor or source samples."""
from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch
import numpy as np
from core.feature_settings import FeatureSettings
from .geometry import optimize_geometry, geometric_initialization, multiscale_icp


class GeometryAssistanceTests(TestCase):
    def test_order_settings_are_backward_compatible_and_validated(self):
        from core.feature_settings import load_feature_settings
        self.assertTrue(load_feature_settings({}).icp_after_geometry)
        self.assertFalse(load_feature_settings({'icp_after_geometry':False}).icp_after_geometry)
        with self.assertRaises(ValueError):
            load_feature_settings({'icp_after_geometry':1})
    def test_finer_scale_cannot_overwrite_better_coarse_candidate(self):
        from types import SimpleNamespace
        points=np.random.default_rng(3).uniform(-5,5,(2000,3))+[0,0,400]
        initial=np.eye(4); initial[2,3]=.2
        bad=np.eye(4); bad[2,3]=1.5
        with patch('open3d.pipelines.registration.registration_icp',side_effect=[
                SimpleNamespace(transformation=matrix) for matrix in (np.eye(4),bad,bad,bad,bad)]):
            result=multiscale_icp(points,points,initial,FeatureSettings())
        np.testing.assert_array_equal(result,np.eye(4))

    def test_excessive_joint_correction_is_rejected(self):
        points=np.random.default_rng(3).uniform(-5,5,(1200,3))+[0,0,400]
        initial={'a':np.eye(4),'b':np.eye(4)}
        initial['b'][2,3]=.2
        bad=np.eye(4); bad[0,3]=30
        with patch('core.pose_graph.PoseGraph.optimize_global_ba',return_value={'a':np.eye(4),'b':bad}):
            result,report,accepted=optimize_geometry({'a':points,'b':points},initial,FeatureSettings())
        self.assertFalse(accepted,report)
        np.testing.assert_array_equal(result['b'],initial['b'])

    def test_missing_surface_retains_poses(self):
        poses={'a':np.eye(4),'b':np.eye(4)}
        result,report,accepted=optimize_geometry({'a':np.empty((0,3)),'b':np.empty((0,3))},
                                                poses,FeatureSettings())
        self.assertFalse(accepted)
        self.assertIn('采样不足',report)
        np.testing.assert_array_equal(result['b'],poses['b'])

    def test_opposite_surfaces_are_not_collapsed(self):
        x,y=np.meshgrid(np.linspace(-10,10,32),np.linspace(-10,10,32))
        a=np.column_stack((x.ravel(),y.ravel(),np.full(x.size,400.)))
        # Camera views the underside of the same thin sheet in the other frame.
        b=np.column_stack((x.ravel(),-y.ravel(),np.full(x.size,400.)))
        flipped=np.diag([1.,-1.,-1.,1.]); flipped[2,3]=800.5
        poses={'a':np.eye(4),'b':flipped}
        result,report,accepted=optimize_geometry({'a':a,'b':b},poses,FeatureSettings())
        self.assertFalse(accepted,report)
        np.testing.assert_array_equal(result['b'],flipped)

    def test_multi_frame_geometry_reduces_drift_and_keeps_first_pose(self):
        rng=np.random.default_rng(8)
        x=rng.uniform(-20,20,1800)
        y=rng.uniform(-15,15,1800)
        shape=np.column_stack((x,y,400+2*np.sin(x*.25)+np.cos(y*.3)))
        surfaces={}
        poses={}
        for i in range(4):
            uid=str(i)
            physical=np.array([i*.2,0,0])
            surfaces[uid]=shape-physical
            pose=np.eye(4)
            pose[:3,3]=physical+[0,0,i*.2]
            poses[uid]=pose
        before={key:matrix.copy() for key,matrix in poses.items()}
        original={key:points.copy() for key,points in surfaces.items()}
        settings=replace(FeatureSettings(),geometry_enabled=True,geometry_voxel=.5,
                         icp_voxel=.25,icp_distance=1.,icp_max_correction=3.)
        refined,report,accepted=optimize_geometry(surfaces,poses,settings)
        self.assertTrue(accepted,report)
        self.assertLess(abs(refined['3'][2,3]),abs(poses['3'][2,3])*.5)
        np.testing.assert_array_equal(refined['0'],poses['0'])
        for key in poses:
            np.testing.assert_array_equal(poses[key],before[key])
            np.testing.assert_array_equal(surfaces[key],original[key])

    def test_unbounded_fpfh_proposal_is_rejected(self):
        points=np.random.default_rng(2).uniform(-10,10,(100,3))+[0,0,400]
        initial=np.eye(4)
        bad=np.eye(4)
        bad[:3,3]=[100,0,0]
        settings=replace(FeatureSettings(),geometry_fpfh=True)
        with patch('core.postprocess.fpfh_registration.solve',return_value={'transform':bad.tolist()}):
            pose,report=geometric_initialization(points,points,initial,settings)
        np.testing.assert_array_equal(pose,initial)
        self.assertIn('未采用',report)
