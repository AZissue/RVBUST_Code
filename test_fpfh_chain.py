import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'src'))
from unittest.mock import patch
import numpy as np
from core.postprocess.session import CloudLayer
from core.postprocess.fpfh_registration import solve_chain,merge_chain,DEFAULTS

class ChainTests(unittest.TestCase):
    def layers(self):
        return [CloudLayer(str(i),np.array([[1.,2,3],[4,5,6]]),np.ones((2,3))*i/3,origins=((str(i),1),)) for i in range(3)]
    def test_noncommuting_pose_composition_and_preserved_points_colors(self):
        a=np.eye(4);a[:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]];a[:3,3]=[5,6,7]
        b=np.eye(4);b[:3,3]=[11,12,13]
        layers=self.layers()
        with patch('core.postprocess.fpfh_registration.solve',side_effect=[{'transform':a.tolist()},{'transform':b.tolist()}]) as solver:
            result=solve_chain(layers,DEFAULTS.copy())
        np.testing.assert_allclose(result['transforms_to_reference'][2],a@b)
        self.assertIs(solver.call_args_list[1].args[0],layers[1].points)
        output=merge_chain(layers,result)
        np.testing.assert_allclose(output.points[-2:],layers[2].points@(a@b)[:3,:3].T+(a@b)[:3,3])
        np.testing.assert_array_equal(output.colors[-2:],layers[2].colors)
        self.assertEqual(len(output.origins),3)
        self.assertEqual(set(output.parent_transforms),{'0','1','2'})
    def test_failed_edge_rejects_whole_chain_with_identity(self):
        with patch('core.postprocess.fpfh_registration.solve',side_effect=[{'transform':np.eye(4).tolist()},ValueError('no consensus')]):
            with self.assertRaisesRegex(ValueError,'第3帧失败.*2 → 1.*整批未发布'):
                solve_chain(self.layers(),DEFAULTS.copy())
        with self.assertRaises(ValueError):solve_chain(self.layers()[:1],DEFAULTS.copy())

if __name__=='__main__':unittest.main()
