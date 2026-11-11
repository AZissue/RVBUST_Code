import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))


class TrialExamples(unittest.TestCase):
    def test_three_modes_and_common_coordinate_system(self):
        import numpy as np
        import open3d as o3d
        from make_demo import generate
        from stitch import run

        with TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = generate(root / 'input')
            for mode in ('fixed', 'markers', 'fpfh'):
                target = root / mode
                report = run(mode, manifest, target)
                self.assertEqual(report['points'], 3000)
                self.assertTrue((target / 'report.json').is_file())
                xyz = np.asarray(o3d.io.read_point_cloud(str(target / 'merged.ply')).points)
                np.testing.assert_allclose(xyz[:1000], xyz[-1000:], atol=.6)
                with self.assertRaises(FileExistsError):
                    run(mode, manifest, target)


if __name__ == '__main__':
    unittest.main()
