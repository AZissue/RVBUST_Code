"""Four-frame layering regression, millimeter marker observations, no camera I/O."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.camera_manager import CameraManager
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine
from core.mobile_chain_workflow import MobileChainWorkflow
from core.frame_data import FrameData
from core.pose_graph import PoseGraph

# Measured XYZ from the 2026-10-21 reproduction; no raw captures required.
OBSERVATIONS = [[(111, 19.95066433048807, -44.619800542715005, 326.0268514895566),
  (23, -25.05744017197266, 19.818880185755727, 304.0978528520878),
  (37, 51.482794956930036, 20.67303422281502, 319.9803687373403),
  (13, 38.57194621524701, 18.005489930001374, 317.7341902583307)],
 [(23, -25.059252912972962, 19.81717540514052, 304.1012258786009),
  (37, 51.48499996307976, 20.67054034931124, 319.99361250569746),
  (111, 19.950348151029907, -44.620757432173235, 326.0180796319154),
  (13, 38.567973702470425, 18.005663745024307, 317.7339795756154)],
 [(13, 38.57094530858558, 18.003310341850806, 317.7322111595804),
  (37, 51.483735474721186, 20.67028958517939, 319.97834541144834),
  (111, 19.950452432138846, -44.623586034727595, 326.02460447562083),
  (23, -25.060349928274555, 19.815817292038673, 304.0991176370592)],
 [(37, 13.294130680818569, 23.218399391849402, 329.9981247905216),
  (3, -60.51037413125991, 21.82361364666855, 304.45029175095794),
  (13, 0.8080489714737098, 20.451781733646186, 326.1066878348879),
  (111, -18.452321074872543, -42.20671822058296, 332.513059992898)]]


def fixture():
    wf = MobileChainWorkflow(CameraManager(), MarkerDetector(), CalibrationEngine(), StitchEngine())
    wf.start_chaining()
    surface = np.array([[x, y, 320.] for x in (-70., 0., 70.) for y in (-50., 0., 50.)])
    source = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(surface))
    for index, observations in enumerate(OBSERVATIONS, 1):
        markers = [dict(code=c, x_3d=x, y_3d=y, z_3d=z, valid_3d=True) for c, x, y, z in observations]
        frame = FrameData(index, f'station_{index}', markers=markers, markers_all=markers, is_offline=True)
        frame.load_pointcloud_o3d = lambda: source
        ok, message, _ = wf._chain_stitcher.add_frame(frame, detect_markers=False)
        assert ok, message
    return wf, source


def measured_rms(chain, poses):
    errors = []
    for edge in chain.edges:
        _, ref, cam = chain.calibration_engine._match_markers(
            chain.nodes[edge.to_id].markers, chain.nodes[edge.from_id].markers)
        keep = np.linalg.norm(cam @ edge.T[:3, :3].T + edge.T[:3, 3] - ref, axis=1) < 2.
        a, b = poses[edge.from_id], poses[edge.to_id]
        delta = (cam @ a[:3, :3].T + a[:3, 3]) - (ref @ b[:3, :3].T + b[:3, 3])
        errors.extend(np.sum(delta[keep] ** 2, axis=1))
    return float(np.sqrt(np.mean(errors)))


class MobileGlobalAlignmentTests(unittest.TestCase):
    def test_global_fit_and_merged_geometry_do_not_degrade(self):
        wf, source = fixture()
        chain = wf._chain_stitcher
        chain.add_cross_frame_constraints()
        initial = measured_rms(chain, {sid: n.T_world for sid, n in chain.nodes.items()})
        raw = np.asarray(source.points).copy()
        cloud_before = np.asarray(chain.get_merged_pointcloud().points).copy()
        ok, message, before, after = wf.optimize_global()
        self.assertTrue(ok, message)
        final = measured_rms(chain, {sid: n.T_world for sid, n in chain.nodes.items()})
        self.assertLess(final, .01)
        self.assertLessEqual(final, initial + 1e-8)
        self.assertAlmostEqual(before, initial, places=9)
        self.assertAlmostEqual(after, final, places=9)
        self.assertAlmostEqual(wf.get_error_report()['global_marker_rms_mm'], final, places=9)
        np.testing.assert_array_equal(chain.nodes['station_1'].T_world, np.eye(4))
        merged = np.asarray(chain.get_merged_pointcloud().points)
        self.assertLess(float(np.max(np.linalg.norm(merged-cloud_before, axis=1))), .05)
        np.testing.assert_array_equal(np.asarray(source.points), raw)

    def test_bad_or_nonfinite_optimizer_keeps_original_geometry(self):
        for invalid in (False, True):
            with self.subTest(nonfinite=invalid):
                wf, _ = fixture()
                chain = wf._chain_stitcher
                before = {sid: n.T_world.copy() for sid, n in chain.nodes.items()}
                bad = {sid: pose.copy() for sid, pose in before.items()}
                if invalid:
                    bad['station_2'][0, 0] = np.nan
                else:
                    bad['station_2'][:3, :3] = PoseGraph._se3_exp(np.array([0., .03, 0., 0., 0., 0.]))[:3, :3]
                cloud = np.asarray(chain.get_merged_pointcloud().points).copy()
                with patch.object(chain.pose_graph, 'optimize_global_ba', return_value=bad):
                    ok, message, rms_before, rms_after = wf.optimize_global()
                self.assertTrue(ok, message)
                self.assertIn('保留', message)
                self.assertAlmostEqual(rms_before, rms_after)
                for sid, node in chain.nodes.items():
                    np.testing.assert_array_equal(node.T_world, before[sid])
                np.testing.assert_array_equal(np.asarray(chain.get_merged_pointcloud().points), cloud)

    def test_small_rotation_roundtrip_preserves_finite_difference(self):
        vector = np.array([1e-8, -2e-8, 3e-8, 1., 2., 3.])
        np.testing.assert_allclose(PoseGraph._se3_log(PoseGraph._se3_exp(vector)), vector, atol=1e-14)

    def test_pose_only_session_can_export_report_without_marker_xyz(self):
        wf, _ = fixture()
        for node in wf._chain_stitcher.nodes.values():
            node.markers = []
        self.assertNotIn('global_marker_rms_mm', wf.get_error_report())
        self.assertFalse(wf.optimize_global()[0])

    def test_global_objective_does_not_restore_rejected_marker(self):
        wf = MobileChainWorkflow(CameraManager(), MarkerDetector(), CalibrationEngine(), StitchEngine())
        wf.start_chaining()
        xyz = np.random.default_rng(61).normal(size=(8, 3)) * 30 + [0, 0, 320]
        for index in range(3):
            local = xyz + [index * 20, 0, 0]
            if index == 2:
                local[-1] += [0, 0, 50]
            markers = [dict(code=c, x_3d=x, y_3d=y, z_3d=z, valid_3d=True)
                       for c, (x, y, z) in enumerate(local)]
            frame = FrameData(index, f's{index}', markers=markers, is_offline=True)
            ok, message, _ = wf._chain_stitcher.add_frame(frame, detect_markers=False)
            self.assertTrue(ok, message)
        ok, message, _, after = wf.optimize_global()
        self.assertTrue(ok, message)
        self.assertLess(after, 1e-7)
        involving_outlier = [pair for pair in wf._marker_constraints() if 's2' in pair[:2]]
        self.assertEqual(len(involving_outlier), 2)
        self.assertTrue(all(len(pair[2]) == 7 for pair in involving_outlier))


if __name__ == '__main__':
    unittest.main(verbosity=2)
