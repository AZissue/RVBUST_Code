import os,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[2]/'src')]
os.environ['QT_QPA_PLATFORM']='offscreen'
import numpy as np
from prototypes.fpfh_geometry_match.algorithm import DEFAULTS,SPECS,validate,solve,merge
from core.postprocess.session import CloudLayer

class AlgorithmTests(unittest.TestCase):
    def test_known_rigid_transform_and_full_color_output(self):
        rng=np.random.default_rng(17)
        points=rng.normal(size=(1800,3))*[35,19,11]
        angle=.34;rotation=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
        target=points@rotation.T+[18,-8,6]
        p=DEFAULTS.copy();p.update(voxel_mm=3.,normal_radius_mm=8.,feature_radius_mm=20.,icp=True,icp_distance_mm=5.,min_consensus=20,min_fscore=.9)
        result=solve(target,points,p);matrix=np.asarray(result['transform'])
        self.assertLess(np.linalg.norm(matrix[:3,3]-[18,-8,6]),.4)
        self.assertLess(np.linalg.norm(matrix[:3,:3]-rotation),.02)
        a=CloudLayer('a',target,np.zeros_like(points),origins=(('a',1),));b=CloudLayer('b',points,np.ones_like(points),origins=(('b',1),))
        output=merge(a,b,result)
        self.assertEqual(len(output.points),3600);np.testing.assert_equal(output.colors[1800:],1)
        np.testing.assert_equal(b.points,points)
    def test_invalid_and_insufficient_geometry(self):
        p=DEFAULTS.copy();p['voxel_mm']=0
        with self.assertRaises(ValueError):validate(p)
        with self.assertRaises(ValueError):solve(np.zeros((30,3)),np.ones((30,3)),DEFAULTS.copy())
        p=DEFAULTS.copy();p['plane_min_fraction']=.99
        with self.assertRaises(ValueError):validate(p)
    def test_dialog_parameters_and_invalidation(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QApplication,QWidget
        from prototypes.fpfh_geometry_match.dialog import FPFHDialog
        app=QApplication.instance() or QApplication([])
        from PySide6.QtGui import QFontDatabase
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        parent=QWidget();parent.database=SimpleNamespace(records={})
        dialog=FPFHDialog(parent)
        self.assertEqual(dialog.parameters(),DEFAULTS)
        self.assertEqual(len(dialog.controls),len(SPECS))
        dialog.result={'transform':[]};dialog.confirm.setChecked(True)
        dialog.controls['voxel_mm'].setValue(6)
        self.assertIsNone(dialog.result);self.assertFalse(dialog.publish.isEnabled())
        dialog.resize(860,760);dialog.show();app.processEvents()
        output=Path('outputs/fpfh_validation');output.mkdir(parents=True,exist_ok=True)
        dialog.grab().save(str(output/'parameters.png'))
        dialog.close();parent.close()

if __name__=='__main__':unittest.main()
