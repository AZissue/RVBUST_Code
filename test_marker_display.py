"""Shared renderer conversion keeps detection truth and measured coordinates."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from ui_common.industrial_scene.marker_display import classify_markers, GREEN, RED


class MarkerDisplayTests(unittest.TestCase):
    def test_cloud_points_preserve_coordinates_colors_and_duplicate_codes(self):
        def marker(code, z=30, **extra):
            return dict(code=code, x_2d=10, y_2d=20, x_3d=1, y_3d=2,
                        z_3d=z, world=[100, 200, 300], **extra)

        markers = [marker(1), marker(2, valid_3d=False), marker(None),
                   marker(3, z=float('nan')), marker(4), marker(4, z=40)]
        display = classify_markers(markers, [marker(1)])
        self.assertEqual(display.cloud_points(), [
            (1, ((1., 2., 30.), RED)),
            (4, ((1., 2., 30.), GREEN)),
            (4, ((1., 2., 40.), GREEN)),
        ])
        self.assertEqual(markers[0]['world'], [100, 200, 300])
        self.assertEqual(markers[0]['z_3d'], 30)
        self.assertEqual(classify_markers([]).cloud_points(), [])


if __name__ == '__main__':
    unittest.main()
