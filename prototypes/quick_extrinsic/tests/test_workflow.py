import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import open3d as o3d

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'core'))
from workflow import Workflow, DEFAULT_BOARD_SPECS, rigid_matrix, valid_markers
from core.frame_data import FrameData


def write_cloud(path, points):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    if not o3d.io.write_point_cloud(str(path), cloud):
        raise IOError(path)


def markers(points, codes=None):
    return [dict(code=c, x_3d=float(p[0]), y_3d=float(p[1]), z_3d=float(p[2]), valid_3d=True)
            for c, p in zip(range(len(points)) if codes is None else codes, points)]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.flow = Workflow(self.folder / 'output')

    def seed(self):
        rng = np.random.default_rng(4)
        points = rng.uniform(-30, 30, (15, 3)) + [0, 0, 400]
        theta = np.deg2rad(21)
        T = np.eye(4)
        T[:3, :3] = [[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]]
        T[:3, 3] = [80, -25, 12]
        local = (points - T[:3, 3]) @ T[:3, :3]
        self.flow.mode = 'coded_circle'
        self.flow.detected = {'cam0': {'markers': markers(points), 'board': None},
                              'cam1': {'markers': markers(local), 'board': None}}
        return T, points, local

    def test_transform_save_load_and_stitch_end_to_end(self):
        T, points, local = self.seed()
        self.flow.calibrate('cam0')
        np.testing.assert_allclose(self.flow.engine.get_transform('cam1', 'cam0'), T, atol=1e-9)
        path = self.folder / 'calibration.json'
        self.flow.save(path)
        loaded = Workflow(self.folder / 'loaded')
        loaded.load(path)
        for cid, pts in [('cam0', points), ('cam1', local)]:
            ply = self.folder / f'{cid}.ply'
            write_cloud(ply, np.vstack([pts, [0, 0, 0], [np.nan]*3]))
            loaded.frames['scan'][cid] = FrameData(0, cid, is_offline=True, offline_pointmap_path=str(ply))
        loaded.stitch()
        merged = np.asarray(o3d.io.read_point_cloud(loaded.last_cloud).points)
        self.assertEqual(len(merged), 30)
        np.testing.assert_allclose(merged[:15], merged[15:], atol=1e-8)

    def test_disconnected_pair_preserves_previous_calibration(self):
        self.seed()
        self.flow.calibrate('cam0')
        old = self.flow.engine
        self.flow.detected['cam2'] = {'markers': [], 'board': None}
        with self.assertRaises(ValueError):
            self.flow.calibrate('cam0')
        self.assertIs(self.flow.engine, old)

    def test_chained_overlap(self):
        T, points, local = self.seed()
        self.flow.detected['cam0']['markers'] = markers(points[:8], range(8))
        self.flow.detected['cam1']['markers'] = markers(local)
        self.flow.detected['cam2'] = {'markers': markers(local[8:] - [0, 50, 0], range(8, 15)), 'board': None}
        self.flow.calibrate('cam0')
        expected = T.copy()
        expected[:3, 3] += T[:3, :3] @ [0, 50, 0]
        np.testing.assert_allclose(self.flow.engine.get_transform('cam2', 'cam0'), expected, atol=1e-8)

    def test_invalid_matrix_and_duplicate_codes(self):
        T = np.eye(4)
        T[0, 0] = np.nan
        with self.assertRaises(ValueError):
            rigid_matrix(T)
        with self.assertRaises(ValueError):
            valid_markers(markers([[1, 2, 3], [3, 4, 5]], [1, 1]))

    def test_collinear_rejected(self):
        points = np.array([[i, 0, 300] for i in range(8)])
        self.flow.mode = 'coded_circle'
        self.flow.detected = {cid: {'markers': markers(points), 'board': None} for cid in ['cam0', 'cam1']}
        with self.assertRaises(ValueError):
            self.flow.calibrate('cam0')

    def test_board_spec_mismatch_rejected(self):
        self.seed()
        self.flow.mode = 'asymmetric_grid'
        self.flow.detected['cam0']['board'] = {'pattern_size': (11, 4)}
        self.flow.detected['cam1']['board'] = {'pattern_size': (5, 4)}
        with self.assertRaises(ValueError):
            self.flow.calibrate('cam0')

    def test_partial_scan_cannot_be_exported(self):
        self.seed()
        self.flow.calibrate('cam0')
        self.flow.frames['scan'] = {'cam0': FrameData(0, 'cam0'), 'missing': FrameData(0, 'missing')}
        with self.assertRaises(ValueError):
            self.flow.stitch()
        self.assertIsNone(self.flow.last_cloud)

    def test_board_detection_default_and_custom_sizes(self):
        specs = [*DEFAULT_BOARD_SPECS, {'name': 'custom_5x9', 'cols': 9, 'rows': 5, 'spacing_mm': 24.}]
        for spec in specs:
            with self.subTest(spec=spec['name']):
                d = 32
                w, h = spec['cols'] * d + 100, spec['rows'] * d + 100
                image = np.full((h, w, 3), 255, np.uint8)
                for j in range(spec['cols']):
                    for i in range(spec['rows']):
                        cv2.circle(image, (50+j*d, 50+i*d+int(.5*(j % 2)*d)), 7, (0, 0, 0), -1)
                yy, xx = np.mgrid[:h, :w]
                points = np.column_stack([xx.ravel()*.75, yy.ravel()*.75, np.full(w*h, 400.)])
                image_path, ply = self.folder / 'board.png', self.folder / 'board.ply'
                cv2.imwrite(str(image_path), image)
                write_cloud(ply, points)
                self.flow.load_pair('calib', 'cam0', image_path, ply)
                self.flow.detect('asymmetric_grid', specs)
                det = self.flow.detected['cam0']
                self.assertIsNotNone(det['board'])
                self.assertEqual(det['board']['pattern_name'], spec['name'])
                self.assertEqual(len(det['markers']), spec['cols']*spec['rows'])

    def test_coded_circle_real_sdk_offline_detection(self):
        # Use repository generator only for synthetic test input; production uses MCC core.
        sys.path.insert(0, str(BASE.parents[0] / 'coded_circle_ui'))
        from generator import CodedCircleParams, draw_single_coded_circle
        from core import marker_detector
        self.assertIsNotNone(marker_detector.RVC, 'Real SDK detector is required for this test')
        image = np.full((600, 800, 3), 255, np.uint8)
        params = CodedCircleParams()
        codes = [15, 29, 45, 111]
        for code, (x, y) in zip(codes, [(170, 170), (620, 170), (170, 440), (620, 440)]):
            draw_single_coded_circle(image, code, format(code, '08b'), x, y, 12., params, draw_label=False)
        yy, xx = np.mgrid[:600, :800]
        ply, png = self.folder / 'coded.ply', self.folder / 'coded.png'
        write_cloud(ply, np.column_stack([xx.ravel(), yy.ravel(), np.full(600*800, 500.)]))
        cv2.imwrite(str(png), image)
        self.flow.load_pair('calib', 'cam0', png, ply)
        self.flow.detect('coded_circle', DEFAULT_BOARD_SPECS)
        self.assertEqual({m['code'] for m in self.flow.detected['cam0']['markers']}, set(codes))

    def test_failed_capture_releases_sdk_frame(self):
        from unittest.mock import Mock
        manager = Mock()
        manager.get_connected_ids.return_value = ['cam0', 'cam1']
        frame = Mock()
        frame.save.side_effect = IOError('disk full')
        manager.capture.return_value = frame
        self.flow.manager = manager
        with self.assertRaises(IOError):
            self.flow.capture('calib')
        frame.release_rvc.assert_called_once()
        self.assertEqual(self.flow.frames['calib'], {})

    def test_all_calibrated_cameras_required_in_scan(self):
        self.seed()
        self.flow.detected['cam2'] = self.flow.detected['cam1']
        self.flow.calibrate('cam0')
        self.flow.frames['scan'] = {cid: FrameData(0, cid) for cid in ['cam0', 'cam1']}
        with self.assertRaisesRegex(ValueError, '集合'):
            self.flow.stitch()

    def test_online_serial_mismatch_rejected(self):
        from unittest.mock import Mock
        self.seed()
        self.flow.calibrate('cam0')
        self.flow.calibration_identities = {'cam0': 'SN0', 'cam1': 'SN1'}
        self.flow.manager = Mock()
        self.flow.identities = {'cam0': 'SN0', 'cam1': 'REPLACED'}
        self.flow.frames['scan'] = {cid: FrameData(0, cid) for cid in ['cam0', 'cam1']}
        with self.assertRaisesRegex(ValueError, '序列号'):
            self.flow.stitch()

    def test_capture_releases_before_next_trigger(self):
        from unittest.mock import Mock
        manager = Mock()
        manager.get_connected_ids.return_value = ['cam0', 'cam1']
        self.flow.manager = manager
        order = []
        def capture(cid, **kwargs):
            order.append(f'capture_{cid}')
            frame = Mock()
            def save(base):
                folder = self.folder / cid
                folder.mkdir()
                (folder / 'pointmap.ply').write_text('test')
                (folder / 'image.png').write_bytes(b'test')
                order.append(f'save_{cid}')
                return str(folder)
            frame.save.side_effect = save
            frame.release_rvc.side_effect = lambda: order.append(f'release_{cid}')
            return frame
        manager.capture.side_effect = capture
        with patch('workflow.FrameData.load', side_effect=lambda path: FrameData(0, Path(path).name)):
            self.flow.capture('calib')
        self.assertEqual(order, ['capture_cam0', 'save_cam0', 'release_cam0',
                                 'capture_cam1', 'save_cam1', 'release_cam1'])

    def test_detection_failure_does_not_publish_partial_group(self):
        image = np.zeros((20, 20, 3), np.uint8)
        for cid in ['cam0', 'cam1']:
            frame = FrameData(0, cid, image_np=image)
            frame.load_pointcloud_o3d = lambda: o3d.geometry.PointCloud()
            self.flow.frames['calib'][cid] = frame
        self.flow.detected = {'stale': {}}
        with self.assertRaises(ValueError):
            self.flow.detect('coded_circle', DEFAULT_BOARD_SPECS)
        self.assertEqual(self.flow.detected, {})

    def test_bad_load_preserves_previous_engine(self):
        self.seed()
        self.flow.calibrate('cam0')
        engine = self.flow.engine
        path = self.folder / 'bad.json'
        path.write_text(json.dumps({'reference_id': 'cam0', 'pairs': {'cam0|cam1': {'T': [[0]*4]*4}},
            'quick_extrinsic': {'unit': 'mm', 'direction': 'cam_to_ref'}}))
        with self.assertRaises(ValueError):
            self.flow.load(path)
        self.assertIs(self.flow.engine, engine)


if __name__ == '__main__':
    unittest.main(verbosity=2)
