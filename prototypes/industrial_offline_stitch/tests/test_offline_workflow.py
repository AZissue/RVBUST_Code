"""Offline pairing and real ChainStitcher workflow tests."""
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np
import open3d as o3d

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))

from offline_workflow import OfflineWorkflow, collect_frame_pairs

WORLD_MARKERS = np.array([
    [0., 0., 0.], [100., 0., 0.], [200., 0., 0.],
    [0., 100., 0.], [100., 100., 0.], [200., 100., 0.],
])
OBJECT_POINTS = np.vstack([
    np.array([[x, y, z] for x in range(0, 100, 20)
              for y in range(0, 60, 20) for z in (0, 20)], dtype=float),
    np.column_stack([np.full(28, 50.), np.full(28, 60.), np.arange(28) * 2.]),
]) + 500


def world_points():
    return np.vstack([OBJECT_POINTS, WORLD_MARKERS])


def make_dataset(root, count=2):
    root = Path(root)
    markers_by_name = {}
    for index in range(count):
        transform = np.eye(4)
        transform[:3, 3] = [index * 5., index * -3., index * 10.]
        points = (transform[:3, :3] @ world_points().T + transform[:3, 3:4]).T
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
        ply = root / f'{index + 1}.ply'
        o3d.io.write_point_cloud(str(ply), cloud)
        cv2.imwrite(str(root / f'{index + 1}.png'), np.zeros((8, 8, 3), np.uint8))
        markers = []
        for code, point in enumerate(points[-6:], 1):
            markers.append(dict(code=code, u=float(code), v=float(code + 1),
                x_2d=float(code), y_2d=float(code + 1),
                x_3d=float(point[0]), y_3d=float(point[1]), z_3d=float(point[2]),
                valid_3d=True))
        markers_by_name[ply.name] = markers
    return markers_by_name


def write_pair(root, stem='1'):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.array([[1., 2., 3.]])))
    o3d.io.write_point_cloud(str(root / f'{stem}.ply'), cloud)
    cv2.imwrite(str(root / f'{stem}.png'), np.zeros((1, 1, 3), np.uint8))


class StaticDetector:
    def __init__(self, markers):
        self.markers = markers

    def detect_3d(self, image, pointmap=None, rvc_image=None, offline_ply_path=None,
                  include_invalid=True):
        return self.markers.get(Path(offline_ply_path).name, [])


class OfflineWorkflowTests(unittest.TestCase):
    def test_collect_pairs_with_suffixes_and_recursion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            make_dataset(root)
            (root / '2_color.png').write_bytes((root / '2.png').read_bytes())
            (root / '2_depth.ply').write_bytes((root / '2.ply').read_bytes())
            (root / '2.png').unlink()
            (root / '2.ply').unlink()
            nested = root / 'nested'
            write_pair(nested, '3')
            pairs = collect_frame_pairs(str(root), recursive=True)
            self.assertEqual(len(pairs), 3)
            self.assertEqual(len(collect_frame_pairs(str(root), recursive=False)), 2)
            self.assertEqual(collect_frame_pairs(str(root / 'missing')), [])

    def test_recursive_pairs_stay_in_directory_and_names_are_unique(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_pair(root, '1')
            write_pair(root / 'nested', '1')
            write_pair(root / 'only_cloud', '2')
            (root / 'only_cloud' / '2.png').unlink(missing_ok=True)
            pairs = collect_frame_pairs(str(root), recursive=True)
            self.assertEqual(len(pairs), 2)
            self.assertEqual(len({pair.name for pair in pairs}), 2)
            self.assertTrue(all(Path(pair.image_path).parent == Path(pair.ply_path).parent
                for pair in pairs))

    def test_ambiguous_image_candidates_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_pair(root, '1')
            cv2.imwrite(str(root / '1.jpg'), np.zeros((1, 1, 3), np.uint8))
            with self.assertRaisesRegex(ValueError, '歧义'):
                collect_frame_pairs(str(root))

    def test_real_chain_stitch_coordinates_and_atomic_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markers = make_dataset(root)
            workflow = OfflineWorkflow(detector=StaticDetector(markers))
            pairs = workflow.load_directory(str(root))
            result = workflow.stitch(pairs)
            self.assertTrue(result.ok, result.message)
            self.assertEqual(result.report['n_nodes'], 2)
            self.assertEqual(result.report['n_edges'], 1)
            actual = np.asarray(result.cloud.points)
            expected = np.vstack([world_points(), world_points()])
            valid = np.isfinite(actual).all(axis=1) & (np.linalg.norm(actual, axis=1) > 1e-5)
            actual = actual[valid]
            expected = expected[np.linalg.norm(expected, axis=1) > 1e-5]
            actual = actual[np.lexsort(actual.T[::-1])]
            expected = expected[np.lexsort(expected.T[::-1])]
            np.testing.assert_allclose(actual, expected, atol=1e-3)
            target = root / 'merged.ply'
            workflow.export(str(target))
            self.assertTrue(target.is_file())
            self.assertEqual(len(o3d.io.read_point_cloud(str(target)).points),
                len(result.cloud.points))

    def test_export_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markers = make_dataset(root)
            workflow = OfflineWorkflow(detector=StaticDetector(markers))
            self.assertTrue(workflow.stitch(workflow.load_directory(str(root))).ok)
            target = root / '1.ply'
            before = target.read_bytes()
            with self.assertRaisesRegex(ValueError, '原始输入'):
                workflow.export(str(target))
            self.assertEqual(target.read_bytes(), before)

    def test_failed_frame_blocks_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markers = make_dataset(root)
            markers['2.ply'] = []
            workflow = OfflineWorkflow(detector=StaticDetector(markers))
            result = workflow.stitch(workflow.load_directory(str(root)))
            self.assertFalse(result.ok)
            self.assertIn('2', result.message)
            with self.assertRaisesRegex(RuntimeError, '拼接结果不可用'):
                workflow.export(str(root / 'invalid.ply'))

    def test_new_round_failure_invalidates_previous_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markers = make_dataset(root)
            workflow = OfflineWorkflow(detector=StaticDetector(markers))
            pairs = workflow.load_directory(str(root))
            self.assertTrue(workflow.stitch(pairs).ok)

            def fail_merge():
                raise RuntimeError('merge failed')

            original_new_chain = workflow._new_chain

            def inject_failure():
                original_new_chain()
                workflow.chain.get_merged_pointcloud = fail_merge

            workflow._new_chain = inject_failure
            with self.assertRaisesRegex(RuntimeError, 'merge failed'):
                workflow.stitch(pairs)
            self.assertIsNone(workflow.last_result)
            with self.assertRaisesRegex(RuntimeError, '拼接结果不可用'):
                workflow.export(str(root / 'stale.ply'))

    def test_invalid_3d_markers_still_allow_preview_but_not_stitch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markers = make_dataset(root)
            markers['2.ply'] = [dict(marker, valid_3d=False) for marker in markers['2.ply']]
            workflow = OfflineWorkflow(detector=StaticDetector(markers))
            pairs = workflow.load_directory(str(root))
            frame = workflow.load_pair(pairs[1])
            self.assertEqual(frame.markers, [])
            self.assertFalse(workflow.stitch(pairs).ok)

    def test_unorganized_or_mismatched_cloud_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markers = make_dataset(root)
            o3d.io.write_point_cloud(str(root / '1.ply'), o3d.geometry.PointCloud(
                o3d.utility.Vector3dVector(np.array([[1., 2., 3.]]))))
            workflow = OfflineWorkflow(detector=StaticDetector(markers))
            pair = workflow.load_directory(str(root))[0]
            with self.assertRaisesRegex(ValueError, '分辨率|有组织'):
                workflow.load_pair(pair)

    def test_stool_fixture_replays_saved_markers(self):
        class ForbiddenDetector:
            def detect_3d(self, *args, **kwargs):
                raise AssertionError('凳子已有标记，不应重新检测')

        workflow = OfflineWorkflow(detector=ForbiddenDetector())
        pairs = workflow.load_stool()
        self.assertEqual(len(pairs), 2)
        result = workflow.stitch(pairs)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.report['n_nodes'], 2)


if __name__ == '__main__':
    unittest.main()
