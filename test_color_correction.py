"""Offline colour estimation: known gains, material contrast and bounded sampling."""
import sys
from pathlib import Path
import unittest
from dataclasses import replace
import numpy as np

sys.path.insert(0, str(Path(__file__).parent/'src'))
from core.postprocess.session import CloudLayer
from core.postprocess.color_correction import ColorParameters, NoColorCorrection, unify_colors, correct_color_layers


def scene(gray=False):
    x, y = np.meshgrid(np.linspace(0, 100, 101), np.linspace(0, 20, 21))
    points = np.c_[x.ravel(), y.ravel(), .2*np.sin(x.ravel())]
    material = np.where(y.ravel() < 10, .24, .4)
    colors = np.repeat(material[:, None], 3, axis=1)
    if not gray:
        colors *= [1., .8, .65]
    t = x.ravel()/100
    field = (.7+.6*t)[:, None] if gray else np.c_[.7+.6*t, 1.15-.3*t, .8+.4*t]
    return points, colors, colors*field


def overlapping(gray=False):
    rng = np.random.default_rng(18)
    xyz = rng.uniform(0, 100, (3000, 3))
    rgb = rng.uniform(.16, .45, (3000, 3))
    if gray:
        rgb[:] = rgb.mean(axis=1, keepdims=True)
    gain = np.array([1.4]*3 if gray else [1.4, .8, 1.2])
    return xyz, rgb, rgb*gain, gain


class ColorTests(unittest.TestCase):
    def test_aggressive_modes_and_prevoxel_pipeline(self):
        x, y = np.meshgrid(np.arange(40.), np.arange(20.))
        base = np.c_[x.ravel(), y.ravel(), np.zeros(x.size)]
        points = np.repeat(base, 2, axis=0)
        colors = np.repeat(np.tile([.2, .38], len(base))[:, None], 3, axis=1)
        layer = CloudLayer('seam', points, colors, origins=(('input', 7),))
        gaps = []
        for mode in ('balanced', 'aggressive', 'spatial'):
            try:
                result, _ = correct_color_layers([layer], params=ColorParameters(
                    algorithm=mode, strength=1, seam_strength=1, max_gain=2, scale=12))
            except NoColorCorrection:
                self.assertEqual(mode, 'balanced')
                result = [layer]
            gaps.append(np.median(abs(result[0].colors[::2]-result[0].colors[1::2])))
            self.assertEqual(result[0].origins, layer.origins)
            np.testing.assert_array_equal(result[0].points, points)
        self.assertLess(gaps[1], gaps[0]*.5)
        self.assertLess(gaps[2], gaps[0]*.5)
        # Voxel centroids and averaged colors are the exact correction inputs.
        from core.postprocess.processing import voxel_downsample
        p, true, observed = scene(True)
        layer = CloudLayer('shoe', p, observed, origins=(('shoe', 2),))
        params = ColorParameters(voxel_size=2, algorithm='spatial', scale=15)
        result, reports = correct_color_layers([layer], params=params)
        xyz, rgb = voxel_downsample(p, observed, 2)
        expected, _ = unify_colors([CloudLayer('voxel', xyz, rgb)], params=params)
        np.testing.assert_array_equal(result[0].points, xyz)
        np.testing.assert_array_equal(result[0].colors, expected[0])
        self.assertLess(len(xyz), len(p))
        self.assertEqual(reports[0]['input_points'], len(p))
        self.assertEqual(reports[0]['output_points'], len(xyz))
        np.testing.assert_array_equal(layer.colors, observed)
        for params in (ColorParameters(algorithm='unknown'), ColorParameters(voxel_size=-1)):
            with self.assertRaises(ValueError):
                correct_color_layers([layer], params=params)

    def test_local_seam_blends_coincident_exposures_preserves_black_white(self):
        x, y = np.meshgrid(np.arange(40.), np.arange(20.))
        base = np.c_[x.ravel(), y.ravel(), np.zeros(x.size)]
        points = np.repeat(base, 2, axis=0)
        values = np.tile([.30, .39], len(base))
        values[points[:, 1] < 3] = .005
        values[points[:, 1] > 17] = .995
        colors = np.repeat(values[:, None], 3, axis=1)
        params = ColorParameters(scale=12, strength=1, max_gain=2)
        layer = CloudLayer('overlapping exposures', points, colors)
        with self.assertRaises(NoColorCorrection):
            unify_colors([layer], params=replace(params, seam_strength=0))
        old = [colors]
        new, _ = unify_colors([layer], params=params)
        middle = (base[:, 1] > 5) & (base[:, 1] < 15)
        gap = lambda c: np.median(abs(c[::2, 0][middle]-c[1::2, 0][middle]))
        self.assertLess(gap(new[0]), gap(old[0])*.7)
        # Range gating does not mix the black and white material into the seam.
        for selection in (points[:, 1] < 3, points[:, 1] > 17):
            np.testing.assert_array_equal(new[0][selection], old[0][selection])
        np.testing.assert_array_equal(layer.colors, colors)
        np.testing.assert_array_equal(new[0][:, 0], new[0][:, 2])

    def test_overlap_gray_robust_gain_strength_and_reference(self):
        points, rgb, target, gain = overlapping(True)
        target[::35] = .9  # minority colour outliers must not determine gain
        layers = [CloudLayer('ref', points, rgb), CloudLayer('target', points, target)]
        before = layers[1].colors.copy()
        full, reports = unify_colors(layers, params=ColorParameters(strength=1, max_gain=2))
        np.testing.assert_allclose(reports[1]['estimated_gain'], 1/gain, rtol=.01)
        np.testing.assert_array_equal(full[0], rgb)
        self.assertGreater(reports[1]['matches'], 2500)
        good = np.arange(len(points)) % 35 != 0
        self.assertLess(np.median(abs(full[1][good]-rgb[good])), 1e-10)
        np.testing.assert_array_equal(full[1][:, 0], full[1][:, 1])
        half, _ = unify_colors(layers, params=ColorParameters(strength=.5, max_gain=2))
        self.assertLess(np.median(abs(half[1][good]-rgb[good])), np.median(abs(before[good]-rgb[good])))
        np.testing.assert_array_equal(layers[1].colors, before)
        np.testing.assert_array_equal(layers[1].points, points)

    def test_rgb_overlap_reference_choice_and_unreliable_skip(self):
        points, rgb, target, gain = overlapping()
        layers = [CloudLayer('reference', points, rgb), CloudLayer('target', points, target),
                  CloudLayer('remote', points+1000, target)]
        result, report = unify_colors(layers, params=ColorParameters(strength=1, max_gain=2))
        np.testing.assert_allclose(result[1], rgb, atol=1e-12)
        np.testing.assert_allclose(report[1]['estimated_gain'], 1/gain)
        self.assertEqual(report[2]['status'], '跳过')
        self.assertIn('双向重叠不足', report[2]['reason'])
        np.testing.assert_array_equal(result[2], target)
        reverse, _ = unify_colors(layers[:2], reference=1, params=ColorParameters(strength=1, max_gain=2))
        np.testing.assert_array_equal(reverse[1], target)
        np.testing.assert_allclose(reverse[0], target)

    def test_rgb_chroma_range_and_distance_edge_validation(self):
        t = np.linspace(.2, .4, 300)
        points = np.c_[np.arange(300)*10, np.zeros((300, 2))]
        rgb = np.c_[t, .6-t, np.full(300, .3)]  # constant mean, real RGB variation
        gain = np.array([1.2, .8, 1.1])
        result, _ = unify_colors([CloudLayer('ref', points, rgb), CloudLayer('target', points, rgb*gain)],
                                 params=ColorParameters(strength=1, max_gain=2))
        np.testing.assert_allclose(result[1], rgb)
        with self.assertRaisesRegex(ValueError, '阈值边缘'):
            unify_colors([CloudLayer('ref', points, rgb), CloudLayer('target', points+[.9,0,0], rgb*gain)],
                         params=ColorParameters(overlap_distance=1))

    def test_no_overlap_distance_one_way_and_low_dynamic_reject(self):
        points, rgb, target, _ = overlapping()
        ref = CloudLayer('ref', points, rgb)
        for xyz, colors, text in ((points+1000, target, '重叠不足'),
                (points+.001, target, '重叠不足'),
                (np.repeat(points[:1], len(points), axis=0), target, '重叠不足'),
                (points, np.full_like(rgb, .3), '动态范围')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, text):
                unify_colors([ref, CloudLayer('target', xyz, colors)],
                             params=ColorParameters(overlap_distance=.0001))

    def test_single_rgb_and_gray_low_frequency_preserves_material_and_geometry(self):
        for gray in (True, False):
            points, true, observed = scene(gray)
            layer = CloudLayer('single', points, observed)
            params = ColorParameters(scale=15, strength=1, max_gain=1.5)
            output, reports = unify_colors([layer], params=params)
            corrected = output[0]
            before = np.mean(abs(observed-true))
            after = np.mean(abs(corrected-true))
            self.assertLess(after, before*.75, (gray, before, after))
            low = true[:, 0] < .3
            contrast = np.median(corrected[~low, 0])-np.median(corrected[low, 0])
            self.assertGreater(contrast, .12)
            self.assertGreater(np.unique(corrected[:, 0]).size, 100)
            self.assertTrue(np.isfinite(corrected).all())
            self.assertTrue(((corrected >= 0) & (corrected <= 1)).all())
            self.assertEqual(reports[0]['clipped_fraction'], 0)
            if gray:
                np.testing.assert_array_equal(corrected[:, 0], corrected[:, 2])
            np.testing.assert_array_equal(layer.points, points)
            np.testing.assert_array_equal(layer.colors, observed)

    def test_parameters_have_effect_and_sampling_is_bounded_deterministic(self):
        points, _, observed = scene()
        layers = [CloudLayer('one', points, observed)]
        base = ColorParameters(scale=15, strength=.7, sample_limit=1000, chunk_size=111)
        first, report = unify_colors(layers, params=base)
        second, _ = unify_colors(layers, params=base)
        np.testing.assert_array_equal(first[0], second[0])
        self.assertLessEqual(report[0]['samples'], 1000)
        self.assertEqual(first[0].shape, observed.shape)
        for options in (dict(strength=0), dict(max_gain=1)):
            with self.assertRaisesRegex(ValueError, '参数为0|无可应用校正'):
                unify_colors(layers, params=replace(base, **options))
        wide, _ = unify_colors(layers, params=replace(base, scale=40))
        self.assertFalse(np.allclose(wide, first))
        ratio = first[0]/observed
        self.assertLessEqual(ratio.max(), base.max_gain+1e-12)
        self.assertGreaterEqual(ratio.min(), 1/base.max_gain-1e-12)

    def test_large_input_deterministic_all_points_and_saturation_protection(self):
        points, _, observed = scene()
        points, observed = np.tile(points, (25, 1)), np.tile(observed, (25, 1))
        layer = CloudLayer('large', points, observed)
        params = ColorParameters(scale=15, sample_limit=2000, chunk_size=1024)
        first, report = unify_colors([layer], params=params)
        second, _ = unify_colors([layer], params=params)
        self.assertGreater(len(points), 50000)
        self.assertLessEqual(report[0]['samples'], 2000)
        self.assertEqual(first[0].shape, observed.shape)
        np.testing.assert_array_equal(first[0], second[0])
        # Saturated highlights cannot be made into plausible original colours.
        xyz, rgb, _, _ = overlapping()
        target = rgb.copy()
        target[::10] = .95
        with self.assertRaisesRegex(ValueError, '高光'):
            unify_colors([CloudLayer('ref', xyz, rgb*1.4), CloudLayer('target', xyz, target)],
                         params=ColorParameters(strength=1, max_gain=2))

    def test_highlights_adapt_and_diagnostics_and_constant_noop(self):
        x, y = np.meshgrid(np.linspace(0, 400, 201), np.linspace(0, 40, 21))
        points = np.c_[x.ravel(), y.ravel(), np.zeros(x.size)]
        values = .85*np.where(points[:, 0] < 200, .62, 1.)
        layer = CloudLayer('white', points, np.repeat(values[:, None], 3, axis=1))
        output, reports = unify_colors([layer], params=ColorParameters(strength=1, max_gain=2))
        row = reports[0]
        self.assertGreater(row['requested_clipped_fraction'], .01)
        self.assertLess(row['adaptive_scale'], 1)
        self.assertGreaterEqual(row['adaptive_scale'], .2)
        self.assertLessEqual(row['clipped_fraction'], .01)
        self.assertTrue(row['material_warning'])
        self.assertGreater(row['changed_gt5_fraction'], .1)
        self.assertGreater(row['changed_gt10_fraction'], .1)
        np.testing.assert_array_equal(output[0][:, 0], output[0][:, 2])
        self.assertTrue(np.isfinite(output[0]).all())
        with self.assertRaisesRegex(NoColorCorrection, '无可应用校正') as caught:
            unify_colors([CloudLayer('unchanged', points, np.full_like(points, .3))])
        self.assertEqual(caught.exception.reports[0]['changed_fraction'], 0)

    def test_disconnected_materials_keep_local_anchor_and_reduce_seam(self):
        x, y = np.meshgrid(np.linspace(0, 400, 201), np.linspace(0, 40, 21))
        part = np.c_[x.ravel(), y.ravel(), np.zeros(x.size)]
        points = np.vstack([part, part+[0, 140, 0]])
        true = np.r_[np.full(len(part), .55), np.full(len(part), .18)]
        observed = true*np.where(points[:, 0] < 200, .72, 1.)
        layer = CloudLayer('two materials', points, np.repeat(observed[:, None], 3, axis=1))
        left, right, bright = points[:, 0] < 100, points[:, 0] > 300, points[:, 1] < 100
        seam = lambda c: abs(np.median(c[left & bright])-np.median(c[right & bright]))
        contrast = lambda c: np.median(c[left & bright])-np.median(c[left & ~bright])
        for strength in (.6, 1.):
            out, rows = unify_colors([layer], params=ColorParameters(strength=strength))
            values = out[0][:, 0]
            self.assertEqual(rows[0]['components'], 2)
            self.assertGreaterEqual(1-seam(values)/seam(observed), .4)
            self.assertGreaterEqual(contrast(values)/contrast(observed), .55)

    def test_no_color_mixed_sparse_boundaries_and_invalid_parameters(self):
        points, rgb, target, _ = overlapping()
        layers = [CloudLayer('ref', points, rgb), CloudLayer('target', points, target)]
        for inputs in ([CloudLayer('none', points)], [layers[0], CloudLayer('none', points)]):
            with self.assertRaisesRegex(ValueError, '无色'):
                unify_colors(inputs)
        with self.assertRaisesRegex(ValueError, '样本不足'):
            unify_colors([CloudLayer('sparse', points[:2], rgb[:2])])
        boundaries = rgb.copy(); boundaries[:10] = 0; boundaries[10:20] = 1
        with self.assertRaisesRegex(NoColorCorrection, '无可应用校正') as caught:
            unify_colors([CloudLayer('a', points, boundaries), CloudLayer('b', points, boundaries)])
        self.assertEqual(caught.exception.reports[1]['changed_fraction'], 0)
        for kwargs in (dict(scale=0), dict(strength=-1), dict(strength=2), dict(max_gain=3),
                       dict(overlap_distance=float('nan')), dict(sample_limit=3), dict(chunk_size=0)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                unify_colors(layers, params=ColorParameters(**kwargs))


if __name__ == '__main__':
    unittest.main()
