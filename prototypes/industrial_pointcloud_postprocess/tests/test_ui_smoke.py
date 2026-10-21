"""Offscreen UI smoke test; direct unittest-style script, no camera hardware."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))


def main():
    from PySide6.QtWidgets import QApplication
    from industrial_pointcloud_postprocess.app.window import PostProcessWorkbench
    from industrial_pointcloud_postprocess.core.processing import ortho_project, point_in_polygon
    from industrial_pointcloud_postprocess.core.session import read_cloud, write_cloud
    app = QApplication.instance() or QApplication([])
    win = PostProcessWorkbench(load_demo=True)
    win.resize(1440, 900)
    win.show()
    app.processEvents()

    layer = win.session.layers[0]
    total = len(layer.points)
    assert total > 0, 'demo layer empty'
    print(f'[OK] demo layer loaded: {total:,} points, backend={win.canvas.backend_name}')

    canvas = win.canvas
    params = dict(center=canvas.center.copy(), rotation_matrix=canvas.rotation.matrix.copy(),
                  extent=canvas.extent, zoom=canvas.zoom, pan=canvas.pan.copy(),
                  width=canvas.width(), height=canvas.height())
    assert params['width'] > 50 and params['height'] > 50, 'canvas has no size'
    xy, _ = ortho_project(layer.points, **params)
    xmin, xmax = xy[:, 0].min(), xy[:, 0].max()
    ymin, ymax = xy[:, 1].min(), xy[:, 1].max()
    mid = (xmin + xmax) / 2
    polygon = [(xmin - 5, ymin - 5), (mid, ymin - 5), (mid, ymax + 5), (xmin - 5, ymax + 5)]

    assert win.apply_polygon_crop(0, polygon), 'polygon crop rejected'
    cropped = win.session.layers[0]
    assert 0 < len(cropped.points) < total, 'crop did not reduce point count'
    xy2, _ = ortho_project(cropped.points, **params)
    assert point_in_polygon(xy2, np.asarray(polygon)).all(), 'kept points outside polygon'
    assert cropped.name == layer.name and '多边形裁剪' in cropped.source
    print(f'[OK] polygon crop keep-inside: {total:,} -> {len(cropped.points):,} points')

    before = len(cropped.points)
    assert win.apply_voxel_downsample(0, 5.0), 'voxel downsample rejected'
    voxel = win.session.layers[0]
    assert 0 < len(voxel.points) < before, 'voxel downsample did not reduce points'
    print(f'[OK] voxel downsample: {before:,} -> {len(voxel.points):,} points')

    before = len(voxel.points)
    assert win.apply_random_downsample(0, 0.5), 'random downsample rejected'
    sampled = win.session.layers[0]
    assert len(sampled.points) == max(1, round(before * 0.5)), 'random downsample count wrong'
    print(f'[OK] random downsample: {before:,} -> {len(sampled.points):,} points')

    assert win.apply_polygon_crop(0, [(0, 0), (10, 10)]) is False, 'polygon with <3 vertices accepted'

    win.undo()
    assert len(win.session.layers[0].points) == len(voxel.points), 'undo 1 failed'
    win.undo()
    assert len(win.session.layers[0].points) == len(cropped.points), 'undo 2 failed'
    win.undo()
    assert len(win.session.layers[0].points) == total, 'undo 3 failed'
    print('[OK] undo restored all three edit steps')

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'merged.ply'
        count = write_cloud(path, win.session.layers)
        back = read_cloud(path)
        assert count == total and len(back.points) == total, 'PLY roundtrip mismatch'
    print(f'[OK] PLY export/read roundtrip: {total:,} points')

    extra = np.array([[1., 2., 3.], [4., 5., 6.], [7., 8., 9.]])
    win.load_layer_from_arrays('附加 A', extra)
    win.load_layer_from_arrays('附加 B', extra * 2)
    assert [layer.name for layer in win.session.layers] == ['演示点云 01', '附加 A', '附加 B']
    assert not win.session.can_undo, 'undo stack should be empty before recycle test'
    assert win.remove_layer_indices([1, 2]), 'remove_layer_indices rejected'
    assert len(win.session.layers) == 1, 'layers not removed'
    assert len(win.session.removed) == 1 and sum(len(b) for b in win.session.removed) == 2
    assert not win.session.can_undo, 'removal must not pollute the edit undo stack'
    print('[OK] recycle bin: removed 2 layers, undo stack untouched')
    assert win.restore_last_removal(), 'restore_last_removal rejected'
    assert [layer.name for layer in win.session.layers] == ['演示点云 01', '附加 A', '附加 B'], \
        'restore order or indices wrong'
    assert not win.session.removed
    assert not win.restore_last_removal(), 'empty recycle bin restore should fail'
    print('[OK] recycle bin: restored last removal at original indices and order')

    win.shutdown()
    win.close()
    app.processEvents()
    print('[OK] ui smoke test passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
