"""SDK depth ownership and optional DB persistence without physical cameras."""

import _bootstrap  # Configure project and sibling-test imports.
import unittest
import numpy as np
from test_frame_database import FrameDatabaseTests
from core.camera_manager import SingleCameraController, CameraManager


class DepthTests(unittest.TestCase):
    setUp = FrameDatabaseTests.setUp
    frame = FrameDatabaseTests.frame
    def test_depth_db_roundtrip(self):
        frame = self.frame()
        frame.depth_np = np.array([[.3, np.nan], [0., .8]], dtype=np.float32)
        uid = self.db.ingest(frame)
        frame.depth_np[:] = 1
        loaded, _ = self.db.load_frame(uid)
        np.testing.assert_allclose(loaded.load_depth_map(), [[.3, np.nan], [0., .8]])
        old, _ = self.db.load_frame(self.db.ingest(self.frame()))
        self.assertIsNone(old.load_depth_map())
        from core.frame_database import FrameDatabase
        reopened = FrameDatabase('multi_cam')
        reopened.open_project(self.db.directory / 'index.json')
        restored, _ = reopened.load_frame(uid)
        np.testing.assert_allclose(restored.load_depth_map(), loaded.load_depth_map())

    def test_frame_save_load_depth(self):
        from core.frame_data import FrameData
        frame = self.frame()
        frame.depth_np = np.array([[0., np.nan], [.1, .7]], dtype=np.float32)
        directory = frame.save(str(self.root))
        restored = FrameData.load(directory)
        np.testing.assert_equal(restored.load_depth_map(), frame.depth_np)
        self.assertEqual(restored.load_depth_map().dtype, np.float32)

    def test_capture_copies_depth_and_clears_after_failure(self):
        from unittest.mock import Mock
        depth = np.array([[.2, .5]], dtype=np.float32)
        cam = SingleCameraController('cam0')
        cam.is_connected = True
        cam.camera_type = 'X1'
        cam.camera = Mock()
        cam.camera.GetImage.return_value = MockImage()
        cam.camera.GetDepthMap.return_value = depth
        manager = CameraManager()
        manager._cameras = {'cam0': cam}
        frame = manager.capture('cam0')
        self.assertIsNotNone(frame)
        depth[:] = 9
        np.testing.assert_allclose(frame.depth_np, [[.2, .5]])
        cam.camera.GetDepthMap.side_effect = RuntimeError('unsupported')
        second = manager.capture('cam0')
        self.assertIsNotNone(second)
        self.assertIsNone(second.depth_np)


class MockImage:
    def __array__(self, dtype=None, copy=None):
        return np.zeros((1, 2), dtype=np.uint8)

    def Clone(self):
        return self


if __name__ == '__main__':
    unittest.main()
