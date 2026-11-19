"""The matching and workpiece regions must gate the same original pixels as the overlay."""
import unittest
from dataclasses import replace

import numpy as np

from core.feature_masks import WorkpieceMaskSettings, build_feature_mask, load_mask_settings


class WorkpieceMaskTests(unittest.TestCase):
    def test_two_boxes_and_bright_dark_threshold_preserve_sensor_pixels(self):
        image = np.full((96, 128, 3), 20, dtype=np.uint8)
        image[30:60, 50:90] = 180
        original = image.copy()
        matching = (.25, .125, .875, .875)
        workpiece = (.375, .25, .8125, .75)
        settings = WorkpieceMaskSettings(enabled=True, threshold=100)
        result = build_feature_mask(image, matching, workpiece, settings)
        self.assertEqual(result.box, (48, 24, 104, 72))
        self.assertEqual(int(result.mask.sum()), 30*40)
        self.assertTrue(result.mask[40, 65])
        self.assertFalse(result.mask[25, 50])
        self.assertFalse(result.mask[40, 110])
        dark = build_feature_mask(image, matching, workpiece, replace(settings, polarity='dark'))
        self.assertFalse(dark.mask[40, 65])
        self.assertTrue(dark.mask[25, 50])
        auto = build_feature_mask(image, matching, workpiece, replace(settings, threshold=-1))
        np.testing.assert_array_equal(auto.mask, result.mask)
        np.testing.assert_array_equal(image, original)

    def test_empty_intersection_is_rejected_and_defaults_are_backward_compatible(self):
        image = np.zeros((96, 128, 3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, '没有重叠'):
            build_feature_mask(image, (0, 0, .25, .5), (.5, .5, 1, 1), WorkpieceMaskSettings())
        self.assertEqual(load_mask_settings({}), WorkpieceMaskSettings())
        for invalid in ({'enabled': 1}, {'threshold': 256}, {'polarity': 'red'}):
            with self.assertRaises(ValueError):
                load_mask_settings(invalid)
