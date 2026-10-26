"""Bounded search ranking and cancellation, without camera initialization."""
import sys
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.marker_detector import MarkerDetector


class CircleSearchTests(unittest.TestCase):
    def test_integer_candidates_rank_stable_codes_over_transient_count(self):
        calls = []
        def detect(detector, image):
            params = tuple(detector.get_params())
            calls.append(params)
            count = 3 if params == (10, 3, 5) else 1
            if params == (12, 3, 5):
                count = 10 if image[0, 0, 0] == 200 else 0
            return [dict(code=i, x=10.+i*4, y=20.) for i in range(count)]
        with patch.object(MarkerDetector, 'detect', detect):
            result = MarkerDetector.search_params(np.full((30, 30, 3), 200, np.uint8), [8, 2.4, 3.4])
        self.assertEqual(result['circle'], [10, 3, 5])
        self.assertEqual(result['stable_count'], 3)
        self.assertLessEqual(result['evaluated'], 21)
        self.assertTrue(all(all(value == int(value) for value in params) for params in calls))

    def test_empty_or_inconsistent_centers_and_cancellation_do_not_suggest(self):
        image = np.full((30, 30, 3), 200, np.uint8)
        with patch.object(MarkerDetector, 'detect', return_value=[]):
            with self.assertRaisesRegex(ValueError, '未稳定检出'):
                MarkerDetector.search_params(image, [8, 2, 3])
        def shifted(detector, view):
            return [dict(code=1, x=float(view[0, 0, 0]), y=5)]
        with patch.object(MarkerDetector, 'detect', shifted):
            with self.assertRaisesRegex(ValueError, '未稳定检出'):
                MarkerDetector.search_params(image, [8, 2, 3])
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(ValueError, '已取消'):
            MarkerDetector.search_params(image, [8, 2, 3], cancelled=event)

    def test_offline_parameter_storage_without_sdk(self):
        detector = MarkerDetector()
        detector._coded_marker_type = None
        detector.set_params(10, 3., 5.)
        self.assertEqual(detector.get_params(), [10, 3., 5.])
        with self.assertRaises(ValueError):
            detector.set_params(10, 5, 3)
        self.assertEqual(detector.get_params(), [10, 3., 5.])


if __name__ == '__main__':
    unittest.main()
