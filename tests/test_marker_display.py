"""Shared renderer conversion keeps detection truth and measured coordinates."""

import _bootstrap  # Configure project and sibling-test imports.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ui_common.industrial_scene.marker_display import classify_markers, GREEN, RED, YELLOW
from ui_common.industrial_scene.marker_inspector import MarkerImage
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


class MarkerDisplayTests(unittest.TestCase):
    def test_all_preview_presentations_share_interaction_and_marker_geometry(self):
        from ui_common.image_preview import AspectRatioLabel
        app = QApplication.instance() or QApplication([])
        source = QImage(240, 175, QImage.Format_RGB32)
        source.fill(QColor('black'))
        marker = dict(code=7, x_2d=100, y_2d=85, marker_type='unencoded_circle',
                      ellipse_2d=[16, 28, 90], valid_3d=False)
        reference = MarkerImage()
        preview = AspectRatioLabel()
        self.assertIs(type(preview).wheelEvent, type(reference).wheelEvent)
        for view in (reference, preview):
            view.resize(240, 175)
            view.set_image(source, [marker])
            view.zoom = 2
            view.pan = QPointF(10, 2.5)
            view.show()
        app.processEvents()
        self.assertEqual(reference.grab().toImage(), preview.grab().toImage())
        preview.set_markers([dict(marker, x=100/240, y=85/175)])
        self.assertEqual(reference.grab().toImage(), preview.grab().toImage())
        preview.clear_image()
        self.assertEqual(preview.zoom, 1)
        self.assertTrue(preview.image.isNull())
        self.assertFalse(preview.display.rows)
        for view in (reference, preview):
            view.close()

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

    def test_circle_outline_tracks_image_edges_with_fixed_stroke_and_center(self):
        app = QApplication.instance() or QApplication([])
        view = MarkerImage()
        view.resize(240, 175)
        view.image = QImage(240, 175, QImage.Format_RGB32)
        view.image.fill(QColor('black'))
        view.display = classify_markers([
            dict(code=7, x_2d=100, y_2d=85, marker_type='unencoded_circle',
                 ellipse_2d=[16, 28, 90], valid_3d=False),
        ])
        view.show()
        app.processEvents()

        def assert_outline(center_x, center_y, zoom):
            rendered = view.grab().toImage()
            edge_x = center_x - 14 * zoom
            for x, y in ((edge_x, center_y), (center_x, center_y + 8 * zoom)):
                pixel = rendered.pixelColor(x, y)
                self.assertGreater(pixel.greenF(), 0.85)
                self.assertLess(pixel.redF(), 0.35)
            self.assertEqual(rendered.pixelColor(center_x, center_y), QColor(YELLOW))
            for offset in (-3, 3):
                self.assertEqual(rendered.pixelColor(edge_x + offset, center_y), QColor('black'))
            self.assertEqual(rendered.pixelColor(center_x - 3, center_y), QColor('black'))

        assert_outline(100, 85, 1)
        view.zoom = 2
        view.pan = QPointF(10, 2.5)
        view.update()
        assert_outline(90, 85, 2)
        view.close()


if __name__ == '__main__':
    unittest.main()
