"""Robust turntable calibration and marker-chain regression, no camera."""
import sys,unittest
from pathlib import Path
import numpy as np
import open3d as o3d
sys.path.insert(0,str(Path(__file__).parent/'src'))
from core.turntable_calibrator import TurntableCalibrator,robust_rigid_transform,transform_matrix
class RobustTests(unittest.TestCase):
 def setUp(self):
  self.p=np.random.default_rng(5).normal(size=(8,3))*25
  self.T=transform_matrix(np.array([0.,0.,1.]),np.pi/2,np.array([3.,4.,5.]))
  self.q=self.p@self.T[:3,:3].T+self.T[:3,3]
 def test_outlier_does_not_tilt_axis(self):
  self.q[2]+=[40,-10,0]
  c=TurntableCalibrator();ok,msg,info=c.calibrate_from_markers(self.p,self.q)
  self.assertTrue(ok,msg);self.assertEqual(info['inlier_count'],7)
  self.assertAlmostEqual(info['angle_deg'],90,places=6)
 def test_chain_rejects_outlier_without_falling_back_to_bad_calibration(self):
  self.q[2]+=[40,-10,0]
  def markers(p):return [dict(code=i,x_3d=v[0],y_3d=v[1],z_3d=v[2]) for i,v in enumerate(p)]
  clouds=[]
  for p in (self.p,self.q):
   c=o3d.geometry.PointCloud();c.points=o3d.utility.Vector3dVector(p);clouds.append(c)
  c=TurntableCalibrator();c.set_calibration([1,0,0],[0,0,0],82,4)
  out,msg=c.stitch_pointclouds(clouds,markers=[markers(self.p),markers(self.q)])
  np.testing.assert_allclose(c.last_stitch_transforms[1],np.linalg.inv(self.T),atol=1e-8)
  self.assertIn('7/8',msg)
 def test_inconsistent_and_collinear_are_rejected(self):
  for q,p in [(np.random.default_rng(10).normal(size=(8,3))*80,self.p),(np.arange(9).reshape(3,3),np.arange(9).reshape(3,3))]:
   with self.assertRaises(ValueError):robust_rigid_transform(p,q)
if __name__=='__main__':unittest.main()
