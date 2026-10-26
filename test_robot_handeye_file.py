"""Formal robot hand-eye matrix file compatibility and safety tests."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.robot_handeye import handeye_file


class RobotHandEyeFileTests(unittest.TestCase):
    def test_formal_file_roundtrip_is_exact_and_unverified(self):
        matrix = np.eye(4)
        matrix[:3, 3] = [20, -10, 120]
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'handeye.json')
            ok, message = handeye_file.write_matrix_file(
                path, matrix, eye_in_hand=True, unit='mm', source=handeye_file.SOURCE_TOOL,
                validated=True, verification={'state': 'VERIFIED', 'validated': True})
            self.assertTrue(ok, message)
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            self.assertNotIn('prototype', data['source'])
            ok, message, result = handeye_file.read_matrix_file(path)
            self.assertTrue(ok, message)
            np.testing.assert_array_equal(result.T_handeye_mm, matrix)
            self.assertFalse(result.validated)

    def test_unit_conflict_and_non_rigid_matrix_are_rejected(self):
        matrix = np.eye(4)
        matrix[:3, 3] = [20, -10, 120]
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'handeye.json')
            self.assertTrue(handeye_file.write_matrix_file(
                path, matrix, eye_in_hand=True, unit='mm', source=handeye_file.SOURCE_TOOL)[0])
            self.assertFalse(handeye_file.read_matrix_file(path, unit_override='m')[0])
            matrix[0, 0] = 2
            self.assertFalse(handeye_file.write_matrix_file(
                path, matrix, eye_in_hand=True, unit='mm', source=handeye_file.SOURCE_TOOL)[0])


if __name__ == '__main__':
    unittest.main()
