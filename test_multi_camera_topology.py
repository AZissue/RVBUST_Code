"""Real rigid solves for star / non-star visibility, path composition and UI persistence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import json
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.calibration_engine import CalibrationEngine
from core.fixed_multi_cam_workflow import FixedMultiCamWorkflow
from core.frame_data import FrameData
from core.stitch_engine import StitchEngine
from core.multi_camera_topology import calibration_paths, quality_gate


def fixture(count=3, all_visible=False):
    rng = np.random.default_rng(19)
    world = {i: rng.uniform([-50, -50, 400], [100, 90, 600]) for i in range((count-1)*10)}
    poses, frames = {}, {}
    for i in range(count):
        transform = np.eye(4)
        transform[:3, :3] = Rotation.from_euler('xyz', [i*9, i*13, i*21], degrees=True).as_matrix()
        transform[:3, 3] = [i*100, i*37, i*-15]
        if i == 0:
            transform = np.eye(4)
        poses[f'cam{i}'] = transform
        visible = range(len(world)) if all_visible else [code for code in world if code//10 in (i-1, i)]
        markers = []
        for code in visible:
            point = (world[code] - transform[:3, 3]) @ transform[:3, :3]
            markers.append(dict(code=code, x_3d=point[0], y_3d=point[1], z_3d=point[2]))
        frames[f'cam{i}'] = FrameData(i, f'cam{i}', markers=markers, kind='calib', is_offline=True)
    return poses, frames


def workflow(frames):
    manager = Mock()
    manager.get_connected_ids.return_value = list(frames)
    processor = Mock()
    processor.process.side_effect = lambda cloud: (cloud, 'ok')
    result = FixedMultiCamWorkflow(manager, Mock(), CalibrationEngine(), StitchEngine(), processor)
    result.start_calibration('cam0')
    for frame in frames.values():
        result.add_calibration_frame(frame)
    return result


class TopologyTests(unittest.TestCase):
    def test_chain_succeeds_without_reference_visibility_and_star_fails(self):
        poses, frames = fixture(5)
        wf = workflow(frames)
        self.assertFalse(wf.calibrate()[0])
        self.assertFalse(wf.start_scanning()[0])
        wf.set_topology('chain')
        ok, message = wf.calibrate()
        self.assertTrue(ok, message)
        self.assertEqual(len(wf.calibration_engine.pair_results), 4)
        for cid, expected in poses.items():
            np.testing.assert_allclose(wf.calibration_engine.get_transform(cid, 'cam0'), expected, atol=1e-8)
        self.assertEqual(calibration_paths(wf.calibration_engine)['cam4'],
                         ['cam4', 'cam3', 'cam2', 'cam1', 'cam0'])
        self.assertTrue(wf.start_scanning()[0])

    def test_star_uses_direct_reference_pairs(self):
        poses, frames = fixture(4, all_visible=True)
        wf = workflow(frames)
        self.assertTrue(wf.calibrate()[0])
        self.assertEqual(set(wf.calibration_engine.pair_results), {('cam0', f'cam{i}') for i in range(1, 4)})
        for cid, expected in poses.items():
            np.testing.assert_allclose(wf.calibration_engine.get_transform(cid, 'cam0'), expected, atol=1e-8)

    def test_chain_can_anchor_at_middle_camera_and_invert_edges(self):
        poses, frames = fixture(4)
        wf = workflow(frames)
        wf._reference_id = 'cam2'
        wf.calibration_engine.reference_id = 'cam2'
        wf.set_topology('chain')
        self.assertTrue(wf.calibrate()[0])
        for cid in frames:
            expected = np.linalg.inv(poses['cam2']) @ poses[cid]
            np.testing.assert_allclose(wf.calibration_engine.get_transform(cid, 'cam2'), expected, atol=1e-8)

    def test_missing_camera_and_disconnected_graph_cannot_pass(self):
        _, frames = fixture(3)
        wf = workflow(frames)
        wf.set_topology('chain')
        frames['cam2'].markers = []
        self.assertFalse(wf.calibrate()[0])
        self.assertFalse(wf.start_scanning()[0])
        _, frames = fixture(3, all_visible=True)
        wf = workflow(frames)
        wf.camera_manager.get_connected_ids.return_value += ['cam3']
        self.assertFalse(wf.calibrate()[0])
        self.assertIn('cam3', wf._check_calibration_quality()[1])

    def test_chain_can_bypass_a_failed_candidate_using_only_qualified_edges(self):
        _, frames = fixture(3, all_visible=True)
        wf = workflow(frames)
        original = wf.calibration_engine.calibrate_pair
        def solve_pair(ref, cam, *args, **kwargs):
            if (ref, cam) == ('cam0', 'cam2'):
                return dict(success=False, message='模拟直接配对失败')
            return original(ref, cam, *args, **kwargs)
        with patch.object(wf.calibration_engine, 'calibrate_pair', side_effect=solve_pair):
            self.assertFalse(wf.calibrate()[0])
            wf.set_topology('chain')
            self.assertTrue(wf.calibrate()[0])
            self.assertNotIn(('cam0', 'cam2'), wf.calibration_engine.pair_results)
            self.assertEqual(calibration_paths(wf.calibration_engine)['cam2'], ['cam2', 'cam1', 'cam0'])

    def test_strategy_change_retains_inputs_and_invalidates_previous_scan(self):
        _, frames = fixture(3, all_visible=True)
        wf = workflow(frames)
        self.assertTrue(wf.calibrate()[0])
        wf.start_scanning()
        wf.add_scan_frame(FrameData(20, 'cam0'))
        wf.set_topology('chain')
        self.assertEqual(wf.frames_calib, frames)
        self.assertFalse(wf.frames_scan)
        self.assertFalse(wf.calibration_engine.pair_results)
        self.assertFalse(wf.is_calibration_locked)
        self.assertEqual(wf.get_state(), 'calibrating')

    def test_roundtrip_keeps_strategy_members_and_transform_chain(self):
        poses, frames = fixture(3)
        wf = workflow(frames)
        wf.set_topology('chain')
        self.assertTrue(wf.calibrate()[0])
        engine = CalibrationEngine()
        self.assertTrue(engine.load_from_dict(json.loads(json.dumps(wf.calibration_engine.to_dict())))[0])
        self.assertEqual(engine.topology, 'chain')
        self.assertTrue(quality_gate(engine)[0])
        np.testing.assert_allclose(engine.get_transform('cam2', 'cam0'), poses['cam2'], atol=1e-8)
        engine.required_cameras.append('missing')
        self.assertFalse(quality_gate(engine)[0])

    def test_stitch_applies_composite_transforms_and_rejects_missing_scan_frame(self):
        import open3d as o3d
        from dataclasses import replace
        poses, frames = fixture(3)
        wf = workflow(frames)
        wf.set_topology('chain')
        self.assertTrue(wf.calibrate()[0])
        wf.start_scanning()
        target = np.array([[20., 30., 500.], [40., 60., 550.]])
        for cid, frame in frames.items():
            scan = replace(frame, frame_id=20)
            def cloud(cid=cid):
                result = o3d.geometry.PointCloud()
                local = (target - poses[cid][:3, 3]) @ poses[cid][:3, :3]
                result.points = o3d.utility.Vector3dVector(local)
                return result
            scan.load_pointcloud_o3d = cloud
            wf.add_scan_frame(scan)
        ok, message, merged = wf.stitch()
        self.assertTrue(ok, message)
        np.testing.assert_allclose(np.asarray(merged.points), np.tile(target, (3, 1)), atol=1e-8)
        wf.frames_scan.pop('cam2')
        self.assertFalse(wf.stitch()[0])

    def test_bad_edge_or_nonfinite_matrix_cannot_carry_a_camera(self):
        _, frames = fixture(3)
        wf = workflow(frames)
        wf.set_topology('chain')
        wf.calibrate()
        result = wf.calibration_engine.pair_results['cam1', 'cam2']
        result['rms_mm'] = 3
        self.assertFalse(quality_gate(wf.calibration_engine)[0])
        result['rms_mm'] = .1
        result['T'][0, 0] = np.nan
        self.assertFalse(quality_gate(wf.calibration_engine)[0])

    def test_legacy_star_metadata_defaults_and_bad_entry_does_not_hide_a_camera(self):
        _, frames = fixture(3, all_visible=True)
        wf = workflow(frames)
        self.assertTrue(wf.calibrate()[0])
        saved = wf.calibration_engine.to_dict()
        saved.pop('topology')
        saved.pop('required_cameras')
        engine = CalibrationEngine()
        self.assertTrue(engine.load_from_dict(saved)[0])
        self.assertEqual(engine.topology, 'star')
        self.assertTrue(quality_gate(engine)[0])
        saved['pairs']['cam0|cam2']['T'] = [[0]]
        self.assertTrue(engine.load_from_dict(saved)[0])
        self.assertFalse(quality_gate(engine)[0])


class TopologyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_mode_entry_binding_invalidation_and_loaded_chain_paths(self):
        from ui_v2 import MainWindowShell
        from ui_v2.backend_bridge import BackendBridge
        from core.offline_session import OfflineSession
        window = MainWindowShell()
        bridge = BackendBridge(window)
        bridge.wire_all()
        window.set_mode('multi_cam', [])
        window.set_presentation('industrial')
        ws = window.workspace_multi()
        try:
            _, frames = fixture(3)
            bridge.fixed_workflow.start_calibration('cam0')
            for frame in frames.values():
                bridge.fixed_workflow.add_calibration_frame(frame)
            ws.calibration_topology_changed.emit('chain')
            self.assertEqual(bridge.calibration_engine.topology, 'chain')
            description = bridge.projects.describe('multi_cam', include_raw=False)
            self.assertEqual(description['calibration_topology'], 'chain')
            self.assertIsNone(description['calibration'])
            self.assertEqual(window._industrial_ribbon.commands['multi_cam', 'topology'].text(), '链式标定')
            self.assertTrue(bridge.fixed_workflow.calibrate()[0])
            session = OfflineSession()
            session._meta['calibration'] = bridge.calibration_engine.to_dict()
            bridge._load_fixed_session(session, {})
            self.assertEqual(ws._calibration_topology, 'chain')
            self.assertIn('cam2 → cam1 → cam0', ws._path_summary.text())
            self.assertTrue(ws._quality_passed)
            self.assertEqual(bridge.fixed_workflow.get_state(), 'scanning')
            self.assertTrue(bridge.fixed_workflow.add_scan_frame(FrameData(20, 'cam0'))[0])
            ws.calibration_topology_changed.emit('star')
            self.assertFalse(ws._quality_passed)
            self.assertFalse(ws._btn_scan_capture.isEnabled())
        finally:
            bridge.cleanup()
            window._dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
