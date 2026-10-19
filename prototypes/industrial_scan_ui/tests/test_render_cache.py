"""Portable CPU/LOD contract tests; no OpenGL context or hardware required."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from industrial_scan_ui.core.render_cache import (
    RenderPolicy, FrameRenderCache, FrameSource, PACK_DTYPE,
    allocate_counts, progressive_indices,
)


class RenderCacheTests(unittest.TestCase):
    def source(self, count, offset=0):
        pts = np.arange(count*3, dtype=np.float64).reshape(-1, 3) + offset
        return FrameSource(pts, None)

    def test_progressive_prefix_has_no_duplicates_and_covers_acquisition(self):
        for size in (1, 16, 31, 1000):
            idx = progressive_indices(size, size)
            np.testing.assert_array_equal(np.sort(idx), np.arange(size))
        prefix = progressive_indices(5_000_000, 500)
        self.assertGreater(np.ptp(prefix), 4_900_000)

    def test_budget_is_global_and_not_multiplied_by_frame_count(self):
        for sizes in ([5_000_000]*8, [1, 100, 200], [1000]*100):
            counts = allocate_counts(sizes, 500_000)
            self.assertEqual(sum(counts), min(sum(sizes), 500_000))
            self.assertTrue(all(0 <= c <= n for c, n in zip(counts, sizes)))

    def test_append_reuses_existing_pack_and_camera_lod_has_no_build(self):
        cache, policy = FrameRenderCache(), RenderPolicy(1000, 100)
        first, second = self.source(1000), self.source(1000, 100)
        scene1 = cache.prepare([first], policy)
        scene2 = cache.prepare([first, second], policy)
        self.assertIs(scene1.frames[0].packed, scene2.frames[0].packed)
        self.assertEqual(scene2.builds, 1)
        self.assertEqual(sum(scene2.draw_counts(False, policy)), 1000)
        self.assertEqual(sum(scene2.draw_counts(True, policy)), 100)
        self.assertEqual(scene2.builds, 1)
        scene3 = cache.prepare([first, second], policy)
        self.assertEqual(scene3.builds, 0)

    def test_steady_state_memory_bound_and_cache_removal(self):
        cache, policy = FrameRenderCache(), RenderPolicy(1000, 100)
        sources = []
        for i in range(20):
            sources.append(self.source(1000, i))
            scene = cache.prepare(sources, policy)
            self.assertLessEqual(scene.stored_points, 2*policy.static_points)
            self.assertLessEqual(sum(scene.counts), policy.static_points)
        scene = cache.prepare([], policy)
        self.assertEqual(scene.frames, ())
        self.assertEqual(cache._frames, {})

    def test_display_packing_preserves_source_precision_and_originals(self):
        pts = np.array([[1e9+.001, 1e9+.002, 1e9+.003],
                        [1e9+.010, 1e9+.020, 1e9+.030]])
        colors = np.array([[1., .5, 0.], [0., .2, 1.]])
        original, original_colors = pts.copy(), colors.copy()
        source = FrameSource(pts, colors)
        scene = FrameRenderCache().prepare([source], RenderPolicy(10, 1))
        packed = scene.frames[0]
        self.assertEqual(PACK_DTYPE.itemsize, 16)
        self.assertFalse(packed.packed.flags.writeable)
        reconstructed = packed.packed['position'].astype(float) + packed.origin
        idx = progressive_indices(2, 2)
        np.testing.assert_allclose(reconstructed, pts[idx], rtol=0, atol=1e-6)
        np.testing.assert_array_equal(pts, original)
        np.testing.assert_array_equal(colors, original_colors)

    def test_small_frame_full_display_and_policy_upgrade(self):
        source = self.source(900)
        cache = FrameRenderCache()
        scene = cache.prepare([source], RenderPolicy(100, 10))
        self.assertEqual(scene.counts, (100,))
        scene = cache.prepare([source], RenderPolicy(1000, 100))
        self.assertEqual(scene.counts, (900,))
        self.assertEqual(scene.builds, 1)

    def test_explicit_revision_invalidates_changed_frame(self):
        source = self.source(100)
        cache, policy = FrameRenderCache(), RenderPolicy(100, 10)
        first = cache.prepare([source], policy)
        source.points[:] += 10  # No prepare is active; revision declares the change.
        changed = FrameSource(source.points, source.colors, revision=1)
        second = cache.prepare([changed], policy)
        self.assertEqual(second.builds, 1)
        self.assertIsNot(first.frames[0].packed, second.frames[0].packed)
        self.assertGreater(second.bounds[0, 0], first.bounds[0, 0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
