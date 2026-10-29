import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'src'))
from types import SimpleNamespace
from core.chain_stitcher import ChainStitcher

class QualityPolicyTests(unittest.TestCase):
    def test_relaxed_inlier_boundary_retains_other_gates(self):
        chain=ChainStitcher(None,None,None)
        def edge(ratio=.676,rms=.1,common=6):
            return SimpleNamespace(inlier_ratio=ratio,rms_mm=rms,common_markers=common,quality='unknown')
        observed=edge();self.assertTrue(chain._evaluate_edge(observed)[0]);self.assertEqual(observed.quality,'ok')
        self.assertTrue(chain._evaluate_edge(edge(.6))[0])
        self.assertFalse(chain._evaluate_edge(edge(.59999))[0])
        self.assertFalse(chain._evaluate_edge(edge(rms=2.01))[0])
        self.assertFalse(chain._evaluate_edge(edge(common=5))[0])
        best=edge(.95);self.assertTrue(chain._evaluate_edge(best)[0]);self.assertEqual(best.quality,'good')

if __name__=='__main__':unittest.main()
