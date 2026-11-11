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


    def test_transform_and_organized_marker_recognition(self):
        import json
        import numpy as np
        import open3d as o3d
        from make_demo import generate
        from recognize_markers import recognize
        from transform_cloud import transform_cloud

        with TemporaryDirectory() as folder:
            root = Path(folder)
            demo = generate(root / 'demo').parent
            matrix = json.loads((demo / 'cam1_to_cam0.json').read_text(encoding='utf-8'))
            target = root / 'transformed.ply'
            self.assertEqual(transform_cloud(demo / 'cam1.ply', matrix, target), 1000)
            transformed = o3d.io.read_point_cloud(str(target))
            reference = o3d.io.read_point_cloud(str(demo / 'cam0.ply'))
            np.testing.assert_allclose(transformed.points, reference.points, atol=1e-9)
            np.testing.assert_array_equal(transformed.colors, reference.colors)
            report = recognize(demo / 'board.png', demo / 'board.ply', 'asymmetric_grid')
            self.assertEqual(report['valid_3d'], 77)
            self.assertTrue(all(abs(marker['z_3d'] - 500.) < .01 for marker in report['markers']))
            with self.assertRaisesRegex(ValueError, '逐像素'):
                recognize(demo / 'board.png', demo / 'cam0.ply', 'asymmetric_grid')


if __name__ == '__main__':
    unittest.main()
